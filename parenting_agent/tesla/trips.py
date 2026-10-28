"""Trips with the baby in the Tesla (issue #31): cabin ready, car naps, the Child Left Alone Detection check.

- Cabin ready. "We leave in 15" (the brain calls cabin_ready) or a calendar trip with the baby coming up (the plug-in's
  own tick) becomes a proposal with a target picked from the outside temperature in weather.forecast_home. Nothing
  reaches the car until the parent says yes: precondition_car is never on the allowed list. The seat under the car
  seat is set to off, never heated.
- Car naps. The plug-in follows the shift state. When a drive on a trip with the baby ends, it asks whether the baby
  slept and proposes that span as a sleep entry. Only the parent's yes logs it: log_car_nap is never on the allowed list.
- Child Left Alone Detection. Its status goes into every cabin-ready proposal and into car_status. The simulated car
  has a flag. tesla_fleet has no entity for it, so the real car shows unknown until one is configured. Tesla added it
  in software 2025.14.12 for some models only. Nothing here claims the 2027 Model 3 has it.

Add "parenting_agent.tesla.trips:CarTrips" to the agent config plugins, and cabin_ready and car_status to the allowed
tools. Settings live under "car" (see car.DEFAULTS and DEFAULTS below, docs/tesla.md for the Nov 5 switch).
"""
import datetime
import re
import threading

from ..agent.plugins import Plugin
from ..agent.tools import Tool, schema
from .car import Car

DEFAULTS = {"parent_channel": "telegram", "lead_min": 15, "trip_calendar": None,
            "baby_trip_words": ["baby", "pediatrician", "daycare"], "nap_min_drive_min": 10, "drive_end_park_min": 3,
            "baby_trip_window_min": 120, "poll_s": 60}
ASK_FIRST = ("precondition_car", "log_car_nap")
CLAD_NOTE = "Tesla added it in software 2025.14.12 on some models only, so check that this car has it."


def cabin_target(outside_c):
    """A comfortable cabin for the trip: warmer when it is cold out, cooler when it is hot, 21 C otherwise."""
    if outside_c is None:
        return 21.0
    if outside_c < 12:
        return 22.0
    if outside_c > 26:
        return 20.0
    return 21.0


def is_parked(shift):
    return shift in (None, "p", "unknown", "unavailable")


class DriveTracker:
    """Turns shift state readings into drives. A drive ends once the car has been parked for park_min minutes,
    so a short stop in P (a pickup) does not split it. The drive's end is the first parked reading."""

    def __init__(self, park_min=3):
        self.park = datetime.timedelta(minutes=park_min)
        self.start = self.parked_since = None

    def update(self, at, shift):
        if not is_parked(shift):
            if self.start is None:
                self.start = at
            self.parked_since = None
            return None
        if self.start is None:
            return None
        if self.parked_since is None:
            self.parked_since = at
        if at - self.parked_since >= self.park:
            drive = {"start": self.start, "end": self.parked_since}
            self.start = self.parked_since = None
            return drive
        return None


def drives(rows, park_min=3):
    """Every finished drive in a recorded sample (rows with t and shift_state)."""
    tracker, found = DriveTracker(park_min), []
    for row in rows:
        drive = tracker.update(datetime.datetime.fromisoformat(row["t"]), row.get("shift_state"))
        if drive:
            found.append(drive)
    return found


def _hm(moment):
    return moment.strftime("%H:%M")


def clad_sentence(status):
    if status["status"] == "on":
        return f"Child Left Alone Detection is on ({status['source']})."
    if status["status"] == "off":
        return f"Child Left Alone Detection is off ({status['source']}). If this car has it, turn it on in the car. {CLAD_NOTE}"
    return f"Child Left Alone Detection is not reported by the car yet. {CLAD_NOTE}"


def event_start(event):
    start = event.get("start")
    if isinstance(start, dict):
        start = start.get("dateTime") or start.get("date")
    moment = datetime.datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.astimezone()


class CarTrips(Plugin):
    name = "tesla"

    def __init__(self, agent, config, car=None, clock=None):
        super().__init__(agent, config)
        self.cfg = {**DEFAULTS, **config.get("car", {})}
        self.car = car or Car(config.get("car", {}), agent.bus)
        self.clock = clock or (lambda: datetime.datetime.now().astimezone())
        self.tracker = DriveTracker(self.cfg["drive_end_park_min"])
        self.baby_trip_at = None
        self.proposed_events = set()
        self.stopped = threading.Event()
        self.thread = None
        for name in ASK_FIRST:
            if name in agent.tools.allowed:
                agent.tools.allowed.discard(name)
                agent.bus.publish("car_warning", error=f"{name} removed from the allowed list, it always waits for a yes")
        agent.tools.add(Tool(
            "cabin_ready", "When a parent says they will leave with the baby soon (for example \"we leave in 15\"), get the "
            f"car ready. leave_in_min is minutes from now, or leave_at is HH:MM. It proposes warming or cooling the "
            f"{self.car.label} and the parent is asked for a yes before anything reaches the car. Say its result to the "
            "parent and do not call precondition_car yourself.",
            schema({"leave_in_min": {"type": "number"}, "leave_at": {"type": "string"}}), self.cabin_ready))
        agent.tools.add(Tool(
            "precondition_car", "Warm or cool the car to target_c. Always waits for the parent's yes.",
            schema({"target_c": {"type": "number"}}, ["target_c"]), self.precondition))
        agent.tools.add(Tool(
            "log_car_nap", "Log a nap the baby took in the car, start and end ISO times. Always waits for the parent's yes.",
            schema({"start": {"type": "string"}, "end": {"type": "string"}}, ["start", "end"]), self.log_car_nap))
        agent.tools.add(Tool(
            "car_status", f"The {self.car.label}: where it is, cabin and outside temperature, climate, battery, "
            "and whether Child Left Alone Detection is on.", schema({}), self.status))

    # Cabin ready

    def plan(self, leave_at):
        snap = self.car.read()
        target = cabin_target(snap["outside_c"])
        inside = snap["inside_c"]
        verb = "warm" if inside is None or inside < target - 1 else "cool" if inside > target + 1 else "hold"
        return {"leave_at": leave_at, "target_c": target, "inside_c": inside, "outside_c": snap["outside_c"],
                "verb": verb, "clad": snap["child_left_alone"]}

    def proposal_text(self, plan, why):
        def c(value):
            return "unknown" if value is None else f"{value:g} C"
        action = {"warm": "Warm", "cool": "Cool", "hold": "Hold"}[plan["verb"]]
        return (f"{why} The {self.car.label} is {c(plan['inside_c'])} inside and it is {c(plan['outside_c'])} outside. "
                f"{action} the cabin to {plan['target_c']:g} C now, ready by {_hm(plan['leave_at'])}? "
                f"The seat under the car seat stays off. {clad_sentence(plan['clad'])} Say yes to start.")

    def leave_time(self, leave_in_min=None, leave_at=None):
        now = self.clock()
        if leave_at:
            if re.fullmatch(r"\d{1,2}[:.]\d{2}", str(leave_at).strip()):
                h, m = (int(x) for x in re.split(r"[:.]", str(leave_at).strip()))
                moment = now.replace(hour=h, minute=m, second=0, microsecond=0)
                return moment if moment >= now else moment + datetime.timedelta(days=1)
            return event_start({"start": leave_at})
        return now + datetime.timedelta(minutes=float(leave_in_min if leave_in_min is not None else self.cfg["lead_min"]))

    def cabin_ready(self, leave_in_min=None, leave_at=None):
        """The brain's tool. Proposes, never sends: returns the proposal for the brain to say."""
        plan = self.plan(self.leave_time(leave_in_min, leave_at))
        why = (f"Leaving in {float(leave_in_min):g} min with the baby." if leave_in_min is not None and not leave_at
               else f"Leaving at {_hm(plan['leave_at'])} with the baby.")
        text = self.proposal_text(plan, why)
        self.agent.propose(self.cfg["parent_channel"], "precondition_car", {"target_c": plan["target_c"]})
        self.agent.bus.publish("car_proposal", proposal="cabin_ready", car=self.car.label, simulated=self.car.simulated,
                               target_c=plan["target_c"], leave_at=plan["leave_at"].isoformat(), source="parent")
        return text

    def precondition(self, target_c):
        """Runs only after the parent's yes. Returns a sentence, never raises (approved tools run outside error handling)."""
        try:
            done = self.car.precondition(target_c, keep_seat_off=self.car.cfg["car_seat"])
        except Exception as error:  # the parent hears it failed, the agent keeps running
            self.agent.bus.publish("car_error", action="precondition", error=str(error)[:200])
            return f"I could not reach the {self.car.label}."
        self.baby_trip_at = self.clock()
        self.agent.bus.publish("car_precondition", car=self.car.label, simulated=self.car.simulated,
                               target_c=done["target_c"], result=done["result"], approved_by_parent=True)
        if done["result"] == "dry":
            return f"Dry run, nothing sent to the {self.car.label} (live commands are off)."
        text = f"The {self.car.label} is heading to {done['target_c']:g} C."
        if done["seat_off"] == "failed":
            text = "Check the car seat's seat heater is off. " + text
        return text

    def calendar_trips(self, now):
        """Calendar entries with the baby that start within lead_min, not proposed yet."""
        entity = self.cfg["trip_calendar"]
        if not entity:
            return []
        lead = datetime.timedelta(minutes=self.cfg["lead_min"])
        events = self.car.calendar_events(entity, now, now + lead) or []
        words = [w.lower() for w in self.cfg["baby_trip_words"]]
        due = []
        for event in events:
            summary = event.get("summary") or ""
            start = event_start(event)
            key = (summary, start.isoformat())
            if key in self.proposed_events or not now <= start <= now + lead:
                continue
            if any(re.search(rf"\b{re.escape(w)}\b", summary.lower()) for w in words):
                due.append((summary, start, key))
        return due

    # Car naps

    def on_drive_end(self, drive):
        minutes = (drive["end"] - drive["start"]).total_seconds() / 60
        on_baby_trip = (self.baby_trip_at is not None
                        and drive["start"] - self.baby_trip_at <= datetime.timedelta(minutes=self.cfg["baby_trip_window_min"]))
        self.agent.bus.publish("car_drive", car=self.car.label, simulated=self.car.simulated, start=drive["start"].isoformat(),
                               end=drive["end"].isoformat(), minutes=round(minutes), baby_trip=on_baby_trip)
        if not on_baby_trip:
            return None
        self.baby_trip_at = None
        text = f"Parked ({self.car.label}). Check the back seat before you walk away."
        if minutes >= self.cfg["nap_min_drive_min"]:
            arguments = {"start": drive["start"].isoformat(timespec="minutes"), "end": drive["end"].isoformat(timespec="minutes")}
            text += (f" Did the baby sleep on the drive, {_hm(drive['start'])} to {_hm(drive['end'])}? "
                     "Say yes and I will log it as a nap. If the times were different, tell me.")
            self.agent.propose(self.cfg["parent_channel"], "log_car_nap", arguments)
            self.agent.bus.publish("car_proposal", proposal="car_nap", car=self.car.label, simulated=self.car.simulated,
                                   **arguments)
        self.agent.say(self.cfg["parent_channel"], text)
        return text

    def log_car_nap(self, start, end):
        """Runs only after the parent's yes."""
        try:
            entry = self.agent.baby_log.add("sleep", {"start": start, "end": end}, end)
        except Exception as error:  # the parent hears it failed, the agent keeps running
            self.agent.bus.publish("car_error", action="log_car_nap", error=str(error)[:200])
            return "I could not log that nap."
        self.agent.bus.publish("car_nap_logged", car=self.car.label, simulated=self.car.simulated, start=start, end=end,
                               entry_id=entry.get("id"), approved_by_parent=True)
        return f"Nap logged, {start[11:16]} to {end[11:16]}."

    # Status and the loop

    def status(self):
        snap = self.car.read()
        return {**snap, "child_left_alone_text": clad_sentence(snap["child_left_alone"])}

    def tick(self, now=None):
        """One poll: propose cabin ready for a calendar trip, follow the shift state for car naps."""
        now = now or self.clock()
        for summary, start, key in self.calendar_trips(now):
            self.proposed_events.add(key)
            plan = self.plan(start)
            self.agent.propose(self.cfg["parent_channel"], "precondition_car", {"target_c": plan["target_c"]},
                               self.proposal_text(plan, f"\"{summary}\" at {_hm(start)}."))
            self.agent.bus.publish("car_proposal", proposal="cabin_ready", car=self.car.label, simulated=self.car.simulated,
                                   target_c=plan["target_c"], leave_at=start.isoformat(), source="calendar")
        drive = self.tracker.update(now, self.car.shift_state())
        return self.on_drive_end(drive) if drive else None

    def start(self):
        self.thread = threading.Thread(target=self.run, name="tesla", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.tick()
            except Exception as error:  # a bad poll must not stop the agent
                self.agent.bus.publish("car_error", action="tick", error=str(error)[:300])
            self.stopped.wait(self.cfg["poll_s"])

    def stop(self):
        self.stopped.set()
