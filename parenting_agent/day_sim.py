"""A full simulated day of the day engine with the house in dry run (issues #9 and #29).

The log is the simulated week (tests/fixtures/simweek.json) plus a few scripted notes: supply stock, tummy times on the
days before, where he is, a walk. The day is Sat Oct 24, the morning after the hard night of Fri Oct 23 (4 wake-ups).
The house starts as the real house was read on Oct 29 (results/house-day/house-start.json) and then follows a script of
what the people in it do: a TV turned on, the vacuum started by hand in the Xiaomi app, the doorbell, someone in the
kitchen. Every engine write is a dry run that SimHouse mirrors, so the timeline shows the house changing. Nothing
reaches Home Assistant: the writer has no client.
"""
import copy
import datetime
import json
from pathlib import Path

from . import meals
from .bus import Bus
from .day_engine import ECHO_ANNOUNCE, ECHO_DND, PUSH, TVS, VACUUM, DayEngine, DayWriter, empty_house
from .rhythm.log import FixtureLog, parse
from .white_noise import CRIB_CAP_DB, SimulatedWhiteNoise

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/simweek.json"
RECIPES = ROOT / "tests/fixtures/fast_recipes.json"
HOUSE_START = ROOT / "results/house-day/house-start.json"
TZ = datetime.timezone(datetime.timedelta(hours=-3))
DAY = datetime.datetime(2026, 10, 24, 6, 0, tzinfo=TZ)
LIVING_TV, BEDROOM_TV = list(TVS)


def at(day_offset, h, m=0):
    return DAY.replace(hour=0) + datetime.timedelta(days=day_offset, hours=h, minutes=m)


def note(t, text):
    return {"kind": "note", "time": t.isoformat(), "note": f"[simulated] {text}", "ref": f"note@{t.isoformat()}",
            "tags": ["day-engine-sim"]}


def day_entries():
    """The simulated week plus the scripted notes the routines read."""
    entries = FixtureLog(FIXTURE).entries()
    notes = [note(at(-2, 7, 0), "Stock: diapers 36"), note(at(-2, 7, 1), "Stock: formula 480"),
             note(at(-2, 7, 2), "Stock: wipes 200")]
    for d, (h, m) in ((-3, (14, 30)), (-2, (14, 40)), (-1, (14, 35)), (-3, (8, 35)), (-2, (8, 45)), (-1, (8, 40))):
        notes.append(note(at(d, h, m), "Tummy time on the play mat"))
    notes.append(note(at(0, 13, 56), "Feeding in the bedroom"))
    return entries + notes


CALENDAR = [{"start": at(0, 11, 30), "summary": "Newborn photos at home"},
            {"start": at(0, 16, 0), "summary": "Grandma visits"}]


class SimHouse:
    """The house state the engine reads, changed by the script and by mirrored dry-run writes."""

    def __init__(self, start=None):
        self.state = empty_house()
        if start:
            self.state["vacuum"] = start["vacuum"]
            self.state["tvs"] = copy.deepcopy(start["tvs"])
            self.state["echo_dnd"] = start["echo_dnd"]
            self.state["kitchen_temp_c"] = start["kitchen_temp_c"]
            self.state["presence"] = dict(start["presence"])
            self.state["weather"] = dict(start["weather_today"])
            self.state["shopping"] = list(start["shopping"])
        self.state["calendar"] = list(CALENDAR)
        self.state["freezer"] = ["Cooked Pascualina", "Cooked Torta de Pollo", "Broccoli"]
        self.pushes, self.spoken = [], []

    def apply(self, service, entity, data):
        s = self.state
        if service == "vacuum.pause":
            s["vacuum"] = "paused"
        elif service == "vacuum.return_to_base":
            s["vacuum"] = "returning"
        elif service == "vacuum.start":
            s["vacuum"] = "cleaning"
            if not s.get("vacuum_left_min"):
                s["vacuum_left_min"] = 31
        elif service == "media_player.volume_mute":
            s["tvs"][entity]["muted"] = data["is_volume_muted"]
        elif entity == ECHO_DND:
            s["echo_dnd"] = service == "switch.turn_on"
        elif service == PUSH:
            self.pushes.append(data)
        elif entity == ECHO_ANNOUNCE:
            self.spoken.append(data["message"])
        elif service == "todo.add_item":
            s["shopping"].append(data["item"])

    def minute(self):
        """One minute passes for the vacuum."""
        s = self.state
        if s["vacuum"] == "cleaning":
            s["vacuum_left_min"] = (s["vacuum_left_min"] or 31) - 1
            if s["vacuum_left_min"] <= 0:
                s["vacuum"], s["vacuum_left_min"] = "docked", None
        elif s["vacuum"] == "returning":
            s["vacuum"] = "docked"


def script(t):
    """What the people in the house do at minute t: (description, change)."""
    return {
        at(0, 8, 15): ("Someone turns on the living room TV", lambda s: s["tvs"][LIVING_TV].update(on=True, muted=False)),
        at(0, 8, 45): ("Someone starts the vacuum by hand in the Xiaomi app",
                       lambda s: s.update(vacuum="cleaning", vacuum_left_min=31)),
        at(0, 8, 20): ("Someone moves in the kitchen (Echo motion)", lambda s: s.update(echo_motion_at=t)),
        at(0, 10, 20): ("The doorbell rings and the outdoor camera sees a person",
                        lambda s: s["door"].extend([{"source": "doorbell", "at": t.isoformat()},
                                                    {"source": "person_detection", "at": t.isoformat()}])),
        at(0, 12, 0): ("Someone turns off the living room TV", lambda s: s["tvs"][LIVING_TV].update(on=False, muted=False)),
        at(0, 12, 40): ("Someone turns on the bedroom TV mid-nap", lambda s: s["tvs"][BEDROOM_TV].update(on=True, muted=False)),
        at(0, 14, 30): ("Someone turns off the bedroom TV", lambda s: s["tvs"][BEDROOM_TV].update(on=False, muted=False)),
        at(0, 16, 35): ("A courier rings the doorbell while he is awake",
                        lambda s: s["door"].append({"source": "doorbell", "at": t.isoformat()})),
        at(0, 20, 30): ("Someone turns on the living room TV", lambda s: s["tvs"][LIVING_TV].update(on=True, muted=False)),
        at(0, 23, 0): ("Someone turns off the living room TV", lambda s: s["tvs"][LIVING_TV].update(on=False, muted=False)),
    }.get(t)


def asleep(entries, t):
    return any(e["kind"] == "sleep" and parse(e["start"]) <= t < parse(e["end"]) for e in entries if e.get("end"))


def simulate_day(start=None, end=None, yes_after_min=2, house_start=None, entries=None, brain_factory=None, events=None,
                 script_fn=None):
    """Runs the day minute by minute. Returns the timeline rows, the bus and the checks.

    brain_factory(bus, engine, white_noise) returns a house brain (house_brain.HouseBrain) that ticks each minute
    before the engine, events maps a minute to bus events to publish then (kind, fields), script_fn replaces the
    scripted people."""
    start = start or DAY
    end = end or at(1, 7, 0)
    entries = entries if entries is not None else day_entries()
    events = events or {}
    script_fn = script_fn or script
    house = SimHouse(house_start if house_start is not None else json.loads(HOUSE_START.read_text()))
    bus = Bus()
    writer = DayWriter(bus, client=None, live=False, mirror=house)
    white = SimulatedWhiteNoise(bus)
    engine = DayEngine(bus, writer, {"utc_offset_h": -3, "supplies": {}}, meals.FixtureRecipes(RECIPES), white)
    clock = [start]
    bus.subscribe(lambda e: e.__setitem__("sim_at", clock[0].isoformat()))
    brain = brain_factory(bus, engine, white) if brain_factory else None
    rows, yes_at = [], {}
    stats = {"vacuum_cleaning_while_asleep_min": 0, "tv_unmuted_while_asleep_min": 0, "white_noise_max_db": 0.0,
             "echo_dnd_off_while_asleep_min": 0, "live_writes": 0}
    t = start
    while t < end:
        clock[0] = t
        scripted = script_fn(t)
        if scripted:
            scripted[1](house.state)
            rows.append({"at": t, "routine": "house", "what": scripted[0]})
        before = len(bus.history)
        for kind, fields in events.get(t, ()):
            bus.publish(kind, **fields)
            rows.append({"at": t, "routine": "house", "what": f"{kind} {fields.get('label', '')}".strip()})
        if brain is not None:
            brain.tick(entries, t, house.state)
        engine.tick(entries, t, house.state)
        house.state["door"] = []
        for event in list(bus.history)[before:]:
            if event["kind"] == "ask_parent":
                yes_at[t + datetime.timedelta(minutes=yes_after_min)] = event["action"]
            rows += describe(event, t)
        if t in yes_at:
            rows.append({"at": t, "routine": "floor_clean", "what": "Gonza replies yes"})
            before = len(bus.history)
            engine.approve(yes_at[t], entries, t, house.state)
            for event in list(bus.history)[before:]:
                rows += describe(event, t)
        sleeping = asleep(entries, t)
        if sleeping:
            stats["vacuum_cleaning_while_asleep_min"] += house.state["vacuum"] == "cleaning"
            stats["tv_unmuted_while_asleep_min"] += any(tv["on"] and not tv["muted"] for tv in house.state["tvs"].values())
            stats["echo_dnd_off_while_asleep_min"] += not house.state["echo_dnd"]
        house.minute()
        t += datetime.timedelta(minutes=1)
    stats["white_noise_max_db"] = max((e["crib_db"] for e in bus.history if e["kind"] == "white_noise"), default=0.0)
    stats["live_writes"] = sum(1 for e in bus.history if e["kind"] == "house_done")
    stats["dry_writes"] = sum(1 for e in bus.history if e["kind"] == "house_dry")
    stats["cap_db"] = CRIB_CAP_DB
    stats["sleeps_in_day"] = sum(1 for e in entries if e["kind"] == "sleep" and start <= parse(e["start"]) < end)
    return {"rows": rows, "bus": bus, "stats": stats, "house": house, "engine": engine, "entries": entries, "brain": brain}


def describe(event, t):
    kind = event["kind"]
    if kind == "house_plan":
        return [{"at": t, "routine": "house_brain", "what": f"Muse plan {'armed' if event['accepted'] else 'refused'} "
                 f"({event['trigger']})", "detail": event.get("plan") or {"errors": event.get("errors")}}]
    if kind == "house_brain_fallback":
        return [{"at": t, "routine": "house_brain", "what": "fallback to the fixed routines", "detail": event["reason"]}]
    if kind == "routine":
        detail = {k: v for k, v in event.items() if k not in ("kind", "t", "ts", "unix", "name", "trigger", "step", "at")}
        if event["name"] == "nap_mode" and event["step"] in ("on", "off"):
            return [{"at": t, "routine": "nap_mode", "what": event["step"],
                     "detail": f"{event['sleep']} {'started' if event['step'] == 'on' else 'ended'}, the house "
                               f"{'goes quiet' if event['step'] == 'on' else 'goes back'}"}]
        return [{"at": t, "routine": event["name"], "what": event["step"].replace("_", " "), "detail": detail}]
    if kind == "house_dry":
        body = {k: v for k, v in event["request"]["body"].items() if k != "entity_id"}
        target = event["entity"] or ""
        return [{"at": t, "routine": event["routine"], "what": f"dry run {event['action']} {target}".strip(),
                 "detail": {"data": body, "reason": event["reason"]}}]
    if kind == "white_noise":
        return [{"at": t, "routine": "nap_mode", "what": f"white noise {event['action']} (simulated device)",
                 "detail": {"crib_db": event["crib_db"], "reason": event["reason"]}}]
    if kind == "notify":
        return [{"at": t, "routine": event["routine"], "what": f"message to Gonza ({event['channel']})",
                 "detail": {"text": event["text"]}}]
    return []


def is_vacuum(row):
    return VACUUM in row["what"]
