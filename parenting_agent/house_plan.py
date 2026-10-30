"""The daily house plan (issue #29, with the white noise from #32): vacuum, shopping list and dinner around the baby.

Everything is decided from the baby log the way the daily rhythm reads it, and every house write goes through
HouseWriter, which only knows the writes the action policy allows (docs/home-assistant-inventory.md):

| Write | When |
|---|---|
| vacuum pause and return to base | alone: a nap starts, the baby is asleep, or a predicted nap is about to start |
| vacuum start, room clean | alone only when nobody is home or the baby is out, otherwise the parent is asked. Never when the run would land in a predicted nap window, not even after a yes |
| todo.shopping_list add and remove | alone: diapers, wipes or formula about to run out |
| Cookidoo, the Thermomix | never. The meal plan is a draft and a message, see parenting_agent/meals.py |

Predicted nap windows chain forward from the last wake-up with the baby's usual awake time and usual sleep length over
the last two days, day and night apart. The daily vacuum run takes the longest awake stretch of the day (the quietest
awake time: the most room before the next nap, ties go to the one nearest quiet_at) and moves when the prediction
moves. White noise goes on before each
predicted nap and at bedtime through WhiteNoisePlan, with the 50 dB cap at the crib that white_noise.py keeps in code.

Without live: true (and a Home Assistant token) every write is a dry run: a house_dry event with the exact request.
"""
import datetime
import os
import re
import threading
import urllib.error

from . import meals
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .house import HomeAssistant
from .rhythm import patterns
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .rhythm.engine import make_log
from .rhythm.log import ordered, parse, when
from .sleep_forecast import _median, as_of, sleep_windows, usual  # noqa: F401, re-exported
from .white_noise import CRIB_CAP_DB, SimulatedWhiteNoise, WhiteNoisePlan, crib_db

VACUUM = "vacuum.xiaomi_ov71gl_0681_robot_cleaner"
SHOPPING = "todo.shopping_list"
CLEAN_AREA_FEATURE = 16384
# The only writes this module can make. Anything else raises before a request is built.
ALLOWED_WRITES = {
    "vacuum.pause": VACUUM, "vacuum.return_to_base": VACUUM, "vacuum.start": VACUUM, "vacuum.clean_area": VACUUM,
    "todo.add_item": SHOPPING, "todo.remove_item": SHOPPING,
}
NEVER = re.compile(r"thermomix|cookidoo", re.IGNORECASE)
CLEANING = ("cleaning", "returning")

# Phrases to a Home Assistant area id, for "clean under the high chair" and messes logged in the baby log.
ROOMS = (
    (re.compile(r"high ?chair|dining|table", re.I), "dining_room"),
    (re.compile(r"kitchen|stove|fridge", re.I), "kitchen"),
    (re.compile(r"living|sofa|couch|play ?mat", re.I), "living_room"),
    (re.compile(r"bedroom|bed\b|crib|nursery", re.I), "bedroom"),
    (re.compile(r"study|desk|office", re.I), "study"),
    (re.compile(r"bath", re.I), "bathroom"),
)
MESS_RE = re.compile(r"\b(mess|messy|spill\w*|spit[- ]?up|crumbs?|food on the floor)\b", re.I)
STOCK_RE = re.compile(r"\bstock:?\s*(diapers|wipes|formula)\s+(\d+)", re.I)
# What every reply about a device action says while house.live is false: it was written down, nothing moved.
DRY_WRITE = "only written down, house.live is off (dry run), nothing moved in the house"
DRY_NOTE = "Dry run: house.live is off, so this was only written down and nothing moved in the house."
DEVICE_WORDS = re.compile(r"\b(vacuum|aspiradora|lights?|lamps?|luz|luces|white noise|ruido blanco|speakers?|echo|"
                          r"warmer|tv|doorbell|timbre)\b", re.I)
DONE_WORDS = re.compile(r"\b(start(ed|ing)?|running|runs|paused|stopped|docked|dimmed|turned|switched|is on|are on|"
                        r"sent|done|arranc\w*|prend\w*|apagu\w*|paus\w*|encend\w*)\b", re.I)
OTHERS_DRY_NOTE = "Everything else was only written down (dry run), nothing else moved in the house."
LIVE_WORDS = re.compile(r"for real|\(live\)", re.I)
DRY_WORDS = re.compile(r"dry run|written down|simulated|simulad|nothing moved|not now|did not|didn't|no real|"
                       r"stays docked|waits? for|reply yes|\?", re.I)
# A note that puts him in a room of the house ("tummy time on the play mat in the living room"). A mess note such as
# "crumbs on the sofa" says where the mess is, not where he is.
AT_HOME_RE = re.compile(r"\b(?:in|to|into|on) the (bedroom|nursery|kitchen|living room|study|dining room|play ?mat|crib)\b",
                        re.I)
OUT_RE = re.compile(r"^(\[simulated\] )?(out with the baby|baby is out|went out with)", re.I)
BACK_RE = re.compile(r"^(\[simulated\] )?(back home|baby is back|we are back)", re.I)
SUPPLY_NAMES = {"diapers": "Diapers", "wipes": "Wipes", "formula": "Formula"}

DEFAULTS = {
    "live": False, "ha_url": "http://127.0.0.1:18123", "ha_token_env": "HA_MCP_TOKEN",
    "persons": ["person.gonza", "person.ceci"],
    "run_min": 31, "margin_min": 10, "settle_min": 10, "nap_lead_min": 5,
    "day_start": "08:00", "day_end": "19:00", "quiet_at": "10:30",
    "supplies": {"diapers": None, "wipes": None, "formula": None}, "wipes_per_change": 3, "low_days": 2.0,
    "bad_night": {}, "fast_max_min": 30, "recipes": "home-agents", "recipes_fixture": "tests/fixtures/fast_recipes.json",
    "morning_at": "07:30", "dinner_from": "17:30", "dinner_by": "21:00", "dinner_cook_min": 30,
    "white_noise": True, "poll_s": 60, "clean_area": None,
}


def in_window(t0, t1, windows):
    """The first predicted window that [t0, t1) overlaps, or None."""
    for w in windows:
        if t0 < w["end"] and w["start"] < t1:
            return w
    return None


def room_for(text):
    for pattern, area in ROOMS:
        if pattern.search(text or ""):
            return area
    return None


# An "out with the baby" note counts for this long. A note from the morning never says he is out all afternoon.
OUT_MAX = datetime.timedelta(hours=2)


def baby_out(entries, now, max_age=OUT_MAX):
    """True only when the latest presence note says the baby is out and is at most max_age old. A later "back home"
    note or a later note that puts him in a room of the house ("tummy time on the play mat") means he is home. With no
    recent note he is not taken as out: unsure is never out."""
    out_at = None
    for e in ordered(entries, now):
        if e["kind"] == "note":
            note = e.get("note") or ""
            if OUT_RE.search(note):
                out_at = when(e)
            elif BACK_RE.search(note) or AT_HOME_RE.search(note):
                out_at = None
    return out_at is not None and now - out_at <= max_age


def dry_reply(text, live=()):
    """While house.live is off, a reply that says a device started, paused or turned on also says what really
    happened. The brain can paraphrase a dry-run tool result into "I started the vacuum" (round 4 red team). live holds
    (device words, true sentence) for each device the live gate (house_live.py) wrote for real in the last hour: those
    get their true sentence, every other device in the reply gets the dry-run note."""
    if not (text and DEVICE_WORDS.search(text) and DONE_WORDS.search(text)) or DRY_WORDS.search(text) \
            or LIVE_WORDS.search(text):
        return text
    hits = [(words, sentence) for words, sentence in live if words.search(text)]
    if not hits:
        return f"{text.rstrip()} {DRY_NOTE}"
    rest = text
    for words, _ in hits:
        rest = words.sub("", rest)
    out = f"{text.rstrip()} {' '.join(sentence for _, sentence in hits)}"
    return f"{out} {OTHERS_DRY_NOTE}" if DEVICE_WORDS.search(rest) else out


def add_dry_guard(agent):
    """Adds the truthful reply guard once, however many house plug-ins load. It reads the agent's live gate at reply
    time, so a light or vacuum write that really ran is never called a dry run."""
    guards = getattr(agent, "reply_guards", None)
    if guards is None or getattr(agent, "_house_reply_guard", None) in guards:
        return

    def guard(text):
        gate = getattr(agent, "house_live", None)
        return dry_reply(text, gate.claims() if gate is not None else ())

    agent._house_reply_guard = guard
    guards.append(guard)


def nobody_home(states):
    """True only when every tracked person is known to be away. Unknown is never taken as away."""
    return bool(states) and all(s not in (None, "", "unknown", "unavailable", "home") for s in states.values())


def supplies(entries, now, tz, stock=None, wipes_per_change=3):
    """Per supply: what is left, use per day and when it runs out. Stock comes from the latest "Stock: diapers 40"
    note in the log, or the setting when there is none. Use is counted from the log after that."""
    seen = ordered(entries, now)
    out = {}
    for item in SUPPLY_NAMES:
        base, since, ref = (stock or {}).get(item), None, None
        for e in seen:
            match = STOCK_RE.search(e.get("note") or "") if e["kind"] == "note" else None
            if match and match.group(1).lower() == item:
                base, since, ref = int(match.group(2)), when(e), e["ref"]
        if base is None:
            continue

        def use(e):
            if item == "diapers":
                return 1 if e["kind"] == "change" else 0
            if item == "wipes":
                return wipes_per_change if e["kind"] == "change" else 0
            return (e.get("amount") or 0) if e["kind"] == "feeding" and e.get("type") == "formula" else 0

        used = sum(use(e) for e in seen if since is None or when(e) >= since)
        recent_from = now - datetime.timedelta(days=3)
        first = max(recent_from, since or when(seen[0])) if seen else now
        span_days = max((now - first).total_seconds() / 86400, 0.5)
        rate = sum(use(e) for e in seen if when(e) >= first) / span_days
        left = base - used
        runs_out = now + datetime.timedelta(days=left / rate) if rate > 0 and left > 0 else (now if left <= 0 else None)
        out[item] = {"left": left, "per_day": round(rate, 1), "runs_out": runs_out, "stock_since": since,
                     "days_left": round(left / rate, 2) if rate > 0 else None, "computed_from": [ref] if ref else []}
    return out


class HouseWriter:
    """The only door to Home Assistant writes. Dry run publishes the exact request and sends nothing."""

    def __init__(self, bus, client=None, live=False):
        self.bus, self.client, self.live = bus, client, bool(live and client is not None)

    def request(self, service, entity_id, data=None):
        if NEVER.search(service) or NEVER.search(entity_id):
            raise PermissionError(f"{service} on {entity_id}: the Thermomix and Cookidoo are never written")
        if ALLOWED_WRITES.get(service) != entity_id:
            raise PermissionError(f"{service} on {entity_id} is not an allowed house write")
        domain, name = service.split(".", 1)
        return {"method": "POST", "path": f"/api/services/{domain}/{name}", "body": {"entity_id": entity_id, **(data or {})}}

    def call(self, service, entity_id, data=None, reason=""):
        req = self.request(service, entity_id, data)
        if not self.live:
            return self.bus.publish("house_dry", action=service, entity=entity_id, request=req, reason=reason)
        response = self.client.service(service, entity_id, data)
        return self.bus.publish("house_done", action=service, entity=entity_id, reason=reason,
                                changed=len(response or []) if isinstance(response, list) else None)


class HousePlan:
    """Pure decisions on a clock: tick(entries, now, situation) does what is due and returns the events."""

    def __init__(self, bus, writer, settings=None, recipes=None, white_noise=None, read_state=None):
        self.bus, self.writer = bus, writer
        self.s = {**DEFAULTS, **(settings or {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.s.get("utc_offset_h", -3)))
        self.recipes = recipes
        self.white_noise = white_noise
        self.read_state = read_state or (lambda: "docked")
        self.done = set()
        self.slot = {}
        self.added = {}
        self.drafts = {}

    def _local(self, now, hhmm):
        h, m = map(int, hhmm.split(":"))
        return now.astimezone(self.tz).replace(hour=h, minute=m, second=0, microsecond=0)

    def _mins(self, key):
        return datetime.timedelta(minutes=self.s[key])

    def notify(self, text, **fields):
        if not patterns.no_advice(text):
            raise ValueError("house plan text failed the no-advice guard")
        return self.bus.publish("notify", text=text, source="house-plan", **fields)

    # Vacuum

    def run_fits(self, entries, now):
        """(fits, why): a run of run_min plus a margin must end before the next predicted sleep, and he is awake."""
        windows = sleep_windows(entries, now, self.tz)
        if windows and windows[0].get("ongoing"):
            return False, "he is asleep", windows
        end = now + self._mins("run_min") + self._mins("margin_min")
        hit = in_window(now, end, windows)
        if hit:
            return False, f"a {hit['kind']} is expected around {patterns.hhmm(hit['start'].astimezone(self.tz))}", windows
        return True, "", windows

    def start_vacuum(self, entries, now, situation, reason, area=None, approved=False):
        """Starts the vacuum (or a room clean) if the policy allows, asks the parent otherwise. Returns the event."""
        fits, why, windows = self.run_fits(entries, now)
        what = f"clean the {area.replace('_', ' ')}" if area else "run the vacuum"
        if not fits:
            return self.bus.publish("vacuum_hold", reason=reason, area=area, why=why, at=now.isoformat())
        alone = situation.get("nobody_home") or situation.get("baby_out")
        if area and self.s.get("clean_area") is False:
            self.notify(f"This vacuum cannot clean only the {area.replace('_', ' ')} yet: its rooms are not mapped to "
                        "Home Assistant areas. Reply yes to run the whole house instead.", ask="vacuum_start")
            return self.bus.publish("ask_parent", action="vacuum_start", area=None, reason=reason,
                                    why="clean_area not supported", at=now.isoformat())
        if not (alone or approved):
            nxt = windows[0]["start"].astimezone(self.tz) if windows else None
            until = f", done before the {windows[0]['kind']} around {patterns.hhmm(nxt)}" if nxt else ""
            event = self.bus.publish("ask_parent", action="vacuum_start", area=area, reason=reason, at=now.isoformat())
            self.notify(f"I can {what} now. It takes {self.s['run_min']} min{until}. Reply yes to start it.", ask="vacuum_start")
            return event
        if area:
            event = self.writer.call("vacuum.clean_area", VACUUM, {"cleaning_area_id": [area]}, reason)
        else:
            event = self.writer.call("vacuum.start", VACUUM, None, reason)
        self.bus.publish("vacuum_started", reason=reason, area=area, alone=bool(alone), approved=approved,
                         at=now.isoformat(), run_until=(now + self._mins("run_min")).isoformat())
        return event

    def dock_if_napping(self, entries, now):
        windows = sleep_windows(entries, now, self.tz)
        if not windows:
            return []
        first = windows[0]
        asleep = first.get("ongoing")
        soon = first["start"] <= now + self._mins("nap_lead_min")
        state = self.read_state()
        if state not in CLEANING + ("paused",) or not (asleep or soon):
            return []
        why = "he fell asleep" if asleep else f"a {first['kind']} is expected around {patterns.hhmm(first['start'].astimezone(self.tz))}"
        out = []
        if state == "cleaning":
            out.append(self.writer.call("vacuum.pause", VACUUM, None, why))
        if state != "returning":
            out.append(self.writer.call("vacuum.return_to_base", VACUUM, None, why))
        self.bus.publish("vacuum_docked", why=why, at=now.isoformat(), was=state)
        return out

    def plan_slot(self, entries, now):
        """The longest predicted awake stretch left in today's day hours, as (start, minutes), or None."""
        day_start, day_end = self._local(now, self.s["day_start"]), self._local(now, self.s["day_end"])
        windows = sleep_windows(entries, now, self.tz)
        need = self.s["run_min"] + self.s["margin_min"]
        quiet = self._local(now, self.s["quiet_at"])
        edges, best = [], None
        cursor = now if not (windows and windows[0].get("ongoing")) else windows[0]["end"]
        for w in windows:
            if w.get("ongoing"):
                continue
            edges.append((cursor, w["start"]))
            cursor = w["end"]
        for a, b in edges:
            start = a if a == now else a + self._mins("settle_min")
            start, stop = max(start, day_start), min(b, day_end)
            minutes = (stop - start).total_seconds() / 60
            if minutes >= need:
                # Longest first. Stretches within 5 min of each other count as equal, then the one nearest quiet_at.
                rank = (round(minutes / 5), -abs((start - quiet).total_seconds()))
                if best is None or rank > best[2]:
                    best = (start, round(minutes), rank)
        return best[:2] if best else None

    def daily_run(self, entries, now, situation):
        local = now.astimezone(self.tz)
        day = local.date()
        if ("daily", day) in self.done or not (self._local(now, self.s["day_start"]) <= now < self._local(now, self.s["day_end"])):
            return []
        planned = self.slot.get(day)
        best = self.plan_slot(entries, now)
        if planned is None or (now < planned and best and abs((best[0] - planned).total_seconds()) > 900):
            if best:
                self.slot[day] = best[0]
                self.bus.publish("vacuum_slot", day=day.isoformat(), at=best[0].isoformat(), minutes=best[1],
                                 moved=planned is not None)
            planned = self.slot.get(day)
        if planned is None or now < planned:
            return []
        fits, _, _ = self.run_fits(entries, now)
        if not fits:
            return []
        self.done.add(("daily", day))
        return [self.start_vacuum(entries, now, situation, "daily run at the quietest awake time")]

    def mess(self, entries, now, situation):
        out = []
        for e in ordered(entries, now):
            if e["kind"] == "note" and ("mess", e["ref"]) not in self.done and MESS_RE.search(e.get("note") or ""):
                if now - when(e) > datetime.timedelta(hours=2):
                    self.done.add(("mess", e["ref"]))
                    continue
                area = room_for(e["note"]) or "dining_room"
                event = self.start_vacuum(entries, now, situation, f"mess logged: {e['note'][:60]}", area=area)
                if event["kind"] != "vacuum_hold":
                    self.done.add(("mess", e["ref"]))
                    out.append(event)
        return out

    # Shopping list

    def shopping(self, entries, now):
        out = []
        for item, row in supplies(entries, now, self.tz, self.s["supplies"], self.s["wipes_per_change"]).items():
            key = (item, row["stock_since"])
            if key in self.added or row["days_left"] is None or row["days_left"] > self.s["low_days"]:
                continue
            self.added[key] = now
            runs = patterns.hhmm(row["runs_out"].astimezone(self.tz)) if row["runs_out"] else "soon"
            day = f"{row['runs_out'].astimezone(self.tz):%a} " if row["runs_out"] else ""
            unit = " ml" if item == "formula" else ""
            description = f"About {row['left']}{unit} left, {row['per_day']}{unit} a day, runs out around {day}{runs}"
            out.append(self.writer.call("todo.add_item", SHOPPING, {"item": SUPPLY_NAMES[item], "description": description},
                                        f"{item} running low"))
            self.bus.publish("supply_low", item=item, left=row["left"], per_day=row["per_day"], at=now.isoformat(),
                             runs_out=row["runs_out"].isoformat() if row["runs_out"] else None,
                             computed_from=row["computed_from"])
            self.notify(f"{SUPPLY_NAMES[item]} added to the shopping list. {description}.")
        return out

    # Meals and dinner

    def bad_night(self, entries, now):
        day = now.astimezone(self.tz).date()
        if ("meal", day) in self.done or now < self._local(now, self.s["morning_at"]) or self.recipes is None:
            return []
        self.done.add(("meal", day))
        night = meals.last_night(entries, now, self.tz)
        if not meals.is_bad(night, self.s["bad_night"]):
            return []
        try:
            recipes = self.recipes.fast(self.s["fast_max_min"])
        except (RuntimeError, OSError, ValueError) as error:
            return [self.bus.publish("meal_error", error=str(error)[:200])]
        plan = meals.draft(night, recipes, day)
        if plan is None:
            return []
        self.drafts[day] = plan
        event = self.bus.publish("meal_plan_draft", **plan)
        self.notify(plan["text"], draft="meal_plan")
        return [event]

    def dinner(self, entries, now):
        day = now.astimezone(self.tz).date()
        if ("dinner", day) in self.done or not (self._local(now, self.s["dinner_from"]) <= now < self._local(now, self.s["dinner_by"])):
            return []
        recipe = (self.drafts.get(day) or {}).get("recipes", [None])[0]
        cook = round(recipe["total_time_seconds"] / 60) if recipe else self.s["dinner_cook_min"]
        windows = sleep_windows(entries, now, self.tz)
        if windows and windows[0].get("ongoing"):
            return []
        nxt = windows[0]["start"] if windows else None
        if nxt and nxt < now + datetime.timedelta(minutes=cook + 5):
            return []
        self.done.add(("dinner", day))
        what = f"{recipe['name']} ({cook} min)" if recipe else f"dinner in the Thermomix ({cook} min)"
        until = f", until the {windows[0]['kind']} around {patterns.hhmm(nxt.astimezone(self.tz))}" if nxt else ""
        text = f"He is awake{until}. A good moment to start {what}. The Thermomix waits for your press of the dial."
        return [self.bus.publish("dinner_reminder", at=now.isoformat(), recipe=recipe["name"] if recipe else None,
                                 cook_min=cook, until=nxt.isoformat() if nxt else None), self.notify(text)]

    # White noise and the day

    def day_plan(self, entries, now):
        """Today's planned house actions from now: the vacuum slot, white noise before each sleep and at bedtime."""
        items = []
        slot = self.plan_slot(entries, now)
        if slot:
            items.append({"at": slot[0], "what": "vacuum", "detail": f"daily run, {self.s['run_min']} min, a {slot[1]} min awake stretch"})
        end_of_day = self._local(now, "23:59")
        if self.white_noise is not None:
            plan = self.white_noise
            lead = datetime.timedelta(minutes=plan.s["lead_min"])
            level = plan.device.comfort_level
            db = round(crib_db(level, plan.device.calibration), 1)
            for w in sleep_windows(entries, now, self.tz):
                if not w.get("ongoing") and w["start"] <= end_of_day:
                    items.append({"at": w["start"] - lead, "what": "white_noise_on", "level": level, "crib_db": db,
                                  "detail": f"{w['kind']} expected around {patterns.hhmm(w['start'].astimezone(self.tz))}, "
                                            f"timer {plan.s['timer_min']} min once asleep"})
            bedtime = self._local(now, plan.s["bedtime"])
            if bedtime >= now:
                items.append({"at": bedtime - lead, "what": "white_noise_on", "level": level, "crib_db": db,
                              "detail": f"bedtime at {plan.s['bedtime']}"})
        for item in items:
            assert item.get("crib_db", 0) <= CRIB_CAP_DB
        return sorted(items, key=lambda i: i["at"])

    def tick(self, entries, now, situation=None):
        situation = situation or {}
        seen = as_of(entries, now)
        situation = {**situation, "baby_out": situation.get("baby_out") or baby_out(seen, now)}
        out = self.dock_if_napping(seen, now)
        out += self.mess(seen, now, situation)
        out += self.daily_run(seen, now, situation)
        out += self.shopping(seen, now)
        out += self.bad_night(seen, now)
        out += self.dinner(seen, now)
        if self.white_noise is not None:
            out += self.white_noise.tick(seen, now)
        return out


def make_recipes(settings):
    if settings.get("recipes") == "fixture":
        return meals.FixtureRecipes(settings["recipes_fixture"])
    if settings.get("recipes") == "home-agents":
        return meals.HomeAgentsRecipes()
    return None


class HousePlanPlugin(Plugin):
    """Agent plug-in "parenting_agent.house_plan:HousePlanPlugin", settings under "house_plan", the log from "rhythm"."""
    name = "house-plan"

    def __init__(self, agent, config, client=None, log=None, clock=None):
        super().__init__(agent, config)
        self.s = {**DEFAULTS, **config.get("house_plan", {})}
        self.rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.rhythm["utc_offset_h"]))
        token = os.environ.get(self.s["ha_token_env"])
        self.client = client if client is not None else (HomeAssistant(self.s["ha_url"], token) if token else None)
        self._log = log
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        sounds = "parenting_agent.house_sounds:HouseSounds" in config.get("plugins", [])
        white = None
        if self.s["white_noise"]:
            # House sounds already drives the white noise when it is loaded. The day plan still shows its schedule.
            white = WhiteNoisePlan(SimulatedWhiteNoise(agent.bus if not sounds else _Quiet()),
                                   {"utc_offset_h": self.rhythm["utc_offset_h"], **config.get("house_sounds", {}).get("white_noise", {})})
        self.drives_white_noise = white is not None and not sounds
        self.plan = HousePlan(agent.bus, HouseWriter(agent.bus, self.client, self.s["live"]),
                              {**self.s, "utc_offset_h": self.rhythm["utc_offset_h"]}, make_recipes(self.s),
                              white if self.drives_white_noise else None, self.vacuum_state)
        self.day_white_noise = white
        if self.s["live"] is not True:
            add_dry_guard(agent)
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        agent.tools.add(Tool("vacuum_dock", "Pause the robot vacuum and send it back to its base, for example when the baby "
                             "falls asleep.", schema({}), self.dock))
        agent.tools.add(Tool("vacuum_start", "Start the robot vacuum, or clean one room when the parent names a place such as "
                             "'under the high chair'. Refused when a nap is expected before the run ends.",
                             schema({"place": {"type": "string", "description": "the room or spot the parent named, omit for the whole house"}}),
                             self.start_from_tool))
        agent.tools.add(Tool("house_plan_today", "Today's house plan: the vacuum slot and white noise times, from the baby's rhythm.",
                             schema({}), self.today))

    @property
    def log(self):
        if self._log is None:
            self._log = make_log(self.rhythm, os.environ)
        return self._log

    def vacuum_state(self):
        if self.client is None:
            return "docked"
        try:
            return self.client.state(VACUUM)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return "unknown"

    def situation(self):
        if self.client is None:
            return {"nobody_home": False}
        states = {}
        for person in self.s["persons"]:
            try:
                states[person] = self.client.state(person)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                states[person] = "unknown"
        return {"nobody_home": nobody_home(states), "presence": states}

    def dock(self):
        out = []
        state = self.vacuum_state()
        if state == "cleaning":
            out.append(self.plan.writer.call("vacuum.pause", VACUUM, None, "asked"))
        out.append(self.plan.writer.call("vacuum.return_to_base", VACUUM, None, "asked"))
        if not self.plan.writer.live:
            return f"Vacuum pause and return to base {DRY_WRITE}."
        return "Vacuum paused and sent to its base (live)."

    def start_from_tool(self, place=None):
        now = self.clock()
        area = room_for(place) if place else None
        if place and area is None:
            return f"I do not know which room {place!r} is in."
        event = self.plan.start_vacuum(as_of(self.log.entries(), now), now, self.situation(), f"asked: {place or 'whole house'}",
                                       area=area, approved=True)
        if event["kind"] == "vacuum_hold":
            return f"Not now: {event['why']}."
        what = f"clean of the {area.replace('_', ' ')}" if area else "start"
        if not self.plan.writer.live:
            return f"Vacuum {what} {DRY_WRITE}."
        return f"Vacuum {'cleaning the ' + area.replace('_', ' ') if area else 'started'} (live)."

    def today(self):
        now = self.clock()
        plan = HousePlan(_Quiet(), HouseWriter(_Quiet()), self.plan.s, None, self.day_white_noise)
        items = plan.day_plan(as_of(self.log.entries(), now), now)
        return [{"at": patterns.hhmm(i["at"].astimezone(self.tz)), **{k: v for k, v in i.items() if k != "at"}} for i in items]

    def start(self):
        if self.client is not None and self.s.get("clean_area") is None:
            try:
                features = self.client.attributes(VACUUM).get("supported_features") or 0
                self.plan.s["clean_area"] = bool(features & CLEAN_AREA_FEATURE)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                pass
        self.thread = threading.Thread(target=self.run, name="house-plan", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                with self.lock:
                    self.plan.tick(self.log.entries(), self.clock(), self.situation())
            except Exception as error:  # a bad read must not stop the agent
                self.agent.bus.publish("house_plan_error", error=str(error)[:300])
            self.stopped.wait(self.s["poll_s"])

    def stop(self):
        self.stopped.set()


class _Quiet:
    """A bus that keeps nothing, for the read-only day plan and for white noise another plug-in drives."""

    def publish(self, kind, **fields):
        return {"kind": kind, **fields}
