"""Daily baby laundry (issue #111): the washer's cycle from a power plug, "move it to the dryer", clean bodysuits.

The washer hangs on a power-monitoring plug. The plug is not bought yet, so it is a VirtualPowerPlug (dry,
virtual_devices.py) that the simulation feeds. With "source": "home_assistant" the watts are read, read only, from
the plug's power sensor in Home Assistant instead.

- Cycle: running once the power stays at or above start_w for start_min, finished once it stays under idle_w for
  end_min. A wash pauses with the drum still between turns, so end_min is longer than those pauses. A cycle shorter
  than min_cycle_min is a blip (the door lock, a rinse started by hand) and is dropped.
- Pushes: when a cycle starts, one push asks whether it is a baby load (mark_baby_load). When it finishes, one push
  "move it to the dryer". At remind_at, one push a day when no baby load ran that day.
- Clean bodysuits: a simple count. It starts from the stock the parents set (set_clean_bodysuits), and goes down by
  daily_use each day plus one for each log entry that dirties one: a diaper change or a note that mentions a blowout
  or a leak, a note about spit-up, a note that says the bodysuit or outfit was changed. When a baby load finishes,
  everything dirty is clean again. The parents correct it by saying how many are clean, which resets the count there.

Pushes go to Gonza's iPhone through house_tools (dry while house.live is false) and every step is a "laundry"
event. Add "parenting_agent.laundry:Laundry" to the agent plugins after the house tools, settings under "laundry".
"""
import datetime
import os
import re
import threading

from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .night_feed import find_plugin
from .rhythm import patterns
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .rhythm.engine import make_log
from .virtual_devices import SHOPPING, VirtualPowerPlug

DEFAULTS = {"source": "virtual", "power_entity": "sensor.washer_plug_power", "start_w": 8.0, "start_min": 1,
            "idle_w": 3.0, "end_min": 6, "min_cycle_min": 15, "remind_at": "19:00", "stock": 12, "daily_use": 1,
            "low": 3, "poll_s": 30}
DIRTY_RE = re.compile(r"\b(blow\s?-?out|leak\w*|spit\s?-?up|spat up|spit|bodysuit|onesie|outfit)\b", re.IGNORECASE)


class Washer:
    """The cycle state machine on power readings. feed() returns "started", "finished", "blip" or None."""

    def __init__(self, s):
        self.s = s
        self.state, self.started, self.above_since, self.below_since, self.ended = "idle", None, None, None, None

    def feed(self, watts, now):
        if self.state == "idle":
            if watts >= self.s["start_w"]:
                self.above_since = self.above_since or now
                if now - self.above_since >= datetime.timedelta(minutes=self.s["start_min"]):
                    self.state, self.started, self.below_since = "running", self.above_since, None
                    return "started"
            else:
                self.above_since = None
            return None
        if watts < self.s["idle_w"]:
            self.below_since = self.below_since or now
            if now - self.below_since >= datetime.timedelta(minutes=self.s["end_min"]):
                self.ended = ended = self.below_since
                length = ended - self.started
                self.state, self.above_since, self.below_since = "idle", None, None
                return "finished" if length >= datetime.timedelta(minutes=self.s["min_cycle_min"]) else "blip"
        else:
            self.below_since = None
        return None


def dirtied(row):
    """True when a log row says a bodysuit got dirty: a blowout, a leak, spit-up or a change of clothes."""
    text = " ".join(str(row.get(k) or "") for k in ("note", "notes", "text"))
    return bool(DIRTY_RE.search(text))


class Laundry(Plugin):
    name = "laundry"

    def __init__(self, agent, config, log=None, clock=None, plug=None, reader=None):
        super().__init__(agent, config)
        self.s = {**DEFAULTS, **(config.get("laundry") or {})}
        self.rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self._log = log
        self.plug = plug or VirtualPowerPlug(self.s["power_entity"], SHOPPING["washer"])
        self.reader = reader
        self.washer = Washer(self.s)
        self.cycles = []  # {"start", "end", "baby"}
        self.base = {"count": int(self.s["stock"]), "at": self.clock(), "why": "stock"}
        self.reminded = set()
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        agent.tools.add(Tool("laundry_status", "The washer (idle or running), today's loads, whether a baby load ran "
                             "today, and how many clean bodysuits are left. Changes nothing. Use it when the parent says \"laundry status\" "
                             "or asks about the washer or clean bodysuits.", schema({}), self.status_text))
        agent.tools.add(Tool("mark_baby_load", "Mark the washer's current load, or the last one today, as the baby's "
                             "laundry. Use it when the parent says \"baby load\" or that the load is the baby's.", schema({}),
                             self.mark_baby_load))
        agent.tools.add(Tool("set_clean_bodysuits", "Set how many clean bodysuits there are, when the parent says the "
                             "count is wrong.", schema({"count": {"type": "integer", "minimum": 0, "maximum": 60}}, ["count"]),
                             self.set_clean_bodysuits))

    @property
    def log(self):
        if self._log is None:
            self._log = make_log(self.rhythm, os.environ)
        return self._log

    def start(self):
        threading.Thread(target=self.run, name="laundry", daemon=True).start()

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.stopped.is_set():
            now = self.clock()
            try:
                watts = self.read_watts()
                if watts is not None:
                    self.reading(watts, now)
                self.tick(now)
            except Exception as error:  # a bad read must not stop the agent
                self.agent.bus.publish("laundry_error", error=str(error)[:300])
            self.stopped.wait(self.s["poll_s"])

    def read_watts(self):
        if self.s["source"] == "home_assistant":
            house = find_plugin(self.agent, "house")
            client = self.reader or getattr(house, "client", None)
            if client is None:
                return None
            state = client.state(self.s["power_entity"])
            try:
                return float(state)
            except (TypeError, ValueError):
                return None
        return self.plug.read()

    def event(self, step, now, **fields):
        return self.agent.bus.publish("laundry", step=step, at=now.astimezone(self.tz).isoformat(timespec="seconds"), **fields)

    def push(self, text, now):
        self.event("push", now, text=text)
        house = find_plugin(self.agent, "house")
        if house is None:
            return self.agent.bus.publish("notify", text=text, source="laundry")
        return house.push_gonza(text=text, title="Laundry")

    # The washer

    def reading(self, watts, now):
        with self.lock:
            self.plug.feed(watts, now)
            change = self.washer.feed(watts, now)
            if change == "started":
                self.cycles.append({"start": self.washer.started, "end": None, "baby": False})
                self.event("started", now, since=patterns.hhmm(self.washer.started.astimezone(self.tz)))
                self.push("Washer started. If it is the baby's laundry, say \"baby load\".", now)
            elif change in ("finished", "blip"):
                cycle = self.cycles[-1]
                cycle["end"] = self.washer.ended
                minutes = round((cycle["end"] - cycle["start"]).total_seconds() / 60)
                if change == "blip":
                    self.cycles.pop()
                    self.event("blip", now, minutes=minutes)
                else:
                    self.event("finished", now, minutes=minutes, baby=cycle["baby"])
                    self.push(f"Washer done after {minutes} min: move the laundry to the dryer.", now)
                    if cycle["baby"]:
                        self.reset_clean(cycle["end"], "baby load washed")
            return change

    def today(self, now):
        day = now.astimezone(self.tz).date()
        return [c for c in self.cycles if c["start"].astimezone(self.tz).date() == day]

    def mark_baby_load(self):
        with self.lock:
            now = self.clock()
            cycles = self.today(now)
            if not cycles:
                return "mark_baby_load: no washer load today yet, nothing marked"
            cycle = cycles[-1]
            cycle["baby"] = True
            self.event("baby_load", now, start=patterns.hhmm(cycle["start"].astimezone(self.tz)))
            if cycle["end"] is not None:
                self.reset_clean(cycle["end"], "baby load washed")
                return f"mark_baby_load: the load from {patterns.hhmm(cycle['start'].astimezone(self.tz))} is the baby's, bodysuits counted clean again"
            return "mark_baby_load: the running load is the baby's, bodysuits count clean again when it finishes"

    # Bodysuits

    def reset_clean(self, at, why):
        self.base = {"count": int(self.s["stock"]), "at": at, "why": why}
        self.event("bodysuits_reset", at, count=self.base["count"], reason=why)

    def set_clean_bodysuits(self, count):
        with self.lock:
            now = self.clock()
            self.base = {"count": max(0, int(count)), "at": now, "why": "the parents' count"}
            self.event("bodysuits_set", now, count=self.base["count"])
            return f"set_clean_bodysuits: {self.base['count']} clean bodysuits from now"

    def clean_bodysuits(self, now):
        """The count, and the log rows that took one each since the last reset or correction."""
        since = self.base["at"]
        rows = [r for r in patterns.ordered(self.log.entries(), now) if patterns.when(r) > since and dirtied(r)]
        days = (now.astimezone(self.tz).date() - since.astimezone(self.tz).date()).days
        used = len(rows) + days * int(self.s["daily_use"])
        return {"count": max(0, self.base["count"] - used), "from": [r.get("ref") for r in rows], "days": days,
                "base": self.base["count"], "why": self.base["why"]}

    # The daily reminder

    def tick(self, now):
        with self.lock:
            local = now.astimezone(self.tz)
            h, m = map(int, self.s["remind_at"].split(":"))
            if local < local.replace(hour=h, minute=m, second=0, microsecond=0) or local.date() in self.reminded:
                return None
            self.reminded.add(local.date())
            if any(c["baby"] for c in self.today(now)):
                self.event("reminder_skipped", now, reason="a baby load ran today")
                return None
            clean = self.clean_bodysuits(now)
            text = f"No baby load today yet. About {clean['count']} clean bodysuits left."
            self.event("reminder", now, clean=clean["count"])
            self.push(text, now)
            return text

    def status_text(self):
        now = self.clock()
        cycles = self.today(now)
        clean = self.clean_bodysuits(now)
        loads = ", ".join(f"{patterns.hhmm(c['start'].astimezone(self.tz))}{' baby' if c['baby'] else ''}"
                          f"{'' if c['end'] else ' running'}" for c in cycles) or "none"
        low = " That is low." if clean["count"] <= self.s["low"] else ""
        return (f"Washer {self.washer.state}. Loads today: {loads}. Baby load today: "
                f"{'yes' if any(c['baby'] for c in cycles) else 'no'}. Clean bodysuits: about {clean['count']}.{low}")
