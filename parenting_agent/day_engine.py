"""The day engine (issues #9 and #29): the whole house runs around the baby's day, from the log and the house state.

| Routine | Kind | Fires when | What it does |
|---|---|---|---|
| nap_mode | skill | a sleep starts or ends in the log | vacuum paused and docked, TVs muted, Echo on do not disturb, door becomes a silent push, white noise on. All back when he wakes, the vacuum resumes if it was mid-run and the rest fits before the next predicted nap. At night a short wake-up keeps the house quiet |
| door | skill | a doorbell sound or a person at the door | silent push while nap mode is on, the Echo says one fixed line otherwise |
| floor_clean | schedule | before a predicted tummy time | vacuum only when he is out or awake in another room and the run ends before the next predicted nap. Waits for Gonza's yes until floor_clean_alone is set |
| morning_brief | schedule | morning_at (07:30) | night summary, who was up, appointments, Cookidoo dinner, weather, supplies running low. Telegram text at once, the Echo when he is awake and someone is in the kitchen |
| supplies | schedule | every tick | diapers, wipes and formula from the log, onto the shopping list and to both parents once, three days before they run out. Live on the family agent since Oct 30 (shopping_list_add), never twice on the list |
| parents_meals | schedule | the morning after a hard night | quick Thermomix recipes from Cookidoo (read only) for the next quiet window, logistics only |

Every house write goes through DayWriter, which knows a fixed set of writes and refuses everything else, the never list
included. Every write is a dry run, a house_dry event with the exact request, except the ones the live gate allows
(house_live.py, house.live_actions): since Oct 30 on the family agent that is nap mode's vacuum pause and return to
base when a sleep starts, never a start or a resume, and adding a supply that runs low or an item a parent asks for to
the shopping list (add_to_shopping_list), never removing one. Nothing in this module calls Home Assistant on its own:
HouseReader reads states, the writer is the only door out.
"""
import datetime
import os
import re
import statistics
import threading
import urllib.error

from . import baby_phase, meals
from .agent import rules
from .agent.rules import FEVER_HOLD, fever_today
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .house import HomeAssistant, never_reason
from .house_live import SLEEP_START, gate_for
from .house_plan import DRY_WRITE, SUPPLY_NAMES, add_dry_guard, as_of, baby_out, in_window, sleep_windows, supplies
from .rhythm import patterns
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .rhythm.engine import make_log
from .rhythm.log import ordered, parse, when
from .white_noise import SimulatedWhiteNoise

VACUUM = "vacuum.xiaomi_ov71gl_0681_robot_cleaner"
TVS = {"media_player.lg_webos_tv_oled55b3psa": "living room TV", "media_player.43_crystal_uhd_un43u8000fgxpr": "bedroom TV"}
ECHO_DND = "switch.gonza_s_echo_dot_do_not_disturb"
ECHO_ANNOUNCE = "notify.gonza_s_echo_dot_announce"
ECHO_MOTION = "binary_sensor.gonza_s_echo_dot_motion"
KITCHEN_TEMP = "sensor.gonza_s_echo_dot_temperature"
PUSH = "notify.mobile_app_gonzas_iphone"
SHOPPING = "todo.shopping_list"
DOOR_SENSORS = ("binary_sensor.barbecue_tapo_c200_barbacue_person_detection_2",)
LIVING_PERSON = "binary_sensor.tapo_c200_sofa_onvif_person_detection"
WEATHER = "weather.forecast_home"
MEAL_PLAN = "calendar.cookidoo_meal_plan"

# The only writes the engine makes: service to the entities it may target. None is a service without a target.
ALLOWED_WRITES = {
    "vacuum.pause": {VACUUM}, "vacuum.return_to_base": {VACUUM}, "vacuum.start": {VACUUM},
    "media_player.volume_mute": set(TVS),
    "switch.turn_on": {ECHO_DND}, "switch.turn_off": {ECHO_DND},
    "notify.send_message": {ECHO_ANNOUNCE},
    PUSH: {None},
    "todo.add_item": {SHOPPING},
}
NEVER = re.compile(r"thermomix|cookidoo", re.IGNORECASE)
DOOR_LINE = "Someone is at the door."
TUMMY_RE = re.compile(r"\btummy[- ]?time\b|\bfloor time\b|\bplay ?mat\b", re.IGNORECASE)
UNSURE_WHERE = "where he is is not in the log"
ROOM_RE = re.compile(r"\b(?:in|to|into) the (bedroom|nursery|kitchen|living room|study|dining room)\b", re.IGNORECASE)
SKY = {"sunny": "sunny", "clear-night": "clear", "partlycloudy": "partly cloudy", "cloudy": "cloudy", "rainy": "rain",
       "pouring": "heavy rain", "fog": "fog", "windy": "windy", "windy-variant": "windy", "lightning-rainy": "storms",
       "lightning": "storms", "snowy": "snow", "snowy-rainy": "sleet", "hail": "hail"}

DEFAULTS = {
    "utc_offset_h": -3, "parents": ["Parent A", "Parent B"],
    "run_min": 31, "margin_min": 10, "resume_alone": True,
    "floor_room": "living room", "floor_lead_min": 5, "floor_window_min": 25, "floor_alone": False,
    "tummy_days": 3, "morning_at": "07:30", "echo_until": "10:30", "echo_motion_min": 10,
    "supplies": {"diapers": None, "wipes": None, "formula": None}, "wipes_per_change": 3, "low_days": 3.0,
    "bad_night": {}, "fast_max_min": 30, "quiet_min_extra": 10, "day_end": "21:00", "poll_s": 60,
    # The binary sensors that count as someone at the door. The family agent sets [] so
    # a camera person detection is not a doorbell.
    "door_sensors": list(DOOR_SENSORS),
}
ROUTINES = {
    "nap_mode": "skill", "door": "skill", "floor_clean": "schedule", "morning_brief": "schedule",
    "supplies": "schedule", "parents_meals": "schedule",
}


def empty_house():
    """The house the engine sees when nothing is read: everything off and unknown."""
    return {"vacuum": "docked", "vacuum_left_min": None, "tvs": {e: {"on": False, "muted": False} for e in TVS},
            "echo_dnd": False, "echo_motion_at": None, "kitchen_temp_c": None, "presence": {}, "door": [],
            "living_person": False, "weather": None, "calendar": [], "meal_plan": [], "shopping": [], "freezer": []}


class DayWriter:
    """The only door to Home Assistant writes. Dry run publishes the exact request and sends nothing. A mirror (the
    simulated house) can follow dry writes so a simulation shows the house changing. A live gate (house_live.py) lets
    the few writes listed in house.live_actions run for real, nap mode's vacuum pause and return to base today."""

    def __init__(self, bus, client=None, live=False, mirror=None, gate=None):
        self.bus, self.client, self.mirror, self.gate = bus, client, mirror, gate
        self.live = live is True and client is not None

    def request(self, service, entity_id, data=None):
        reason = never_reason(entity_id)
        if reason:
            raise PermissionError(f"{service} on {entity_id}: {reason} is never controlled")
        if NEVER.search(service) or NEVER.search(entity_id or ""):
            raise PermissionError(f"{service} on {entity_id}: the Thermomix and Cookidoo are never written")
        if entity_id not in ALLOWED_WRITES.get(service, ()):
            raise PermissionError(f"{service} on {entity_id} is not a day engine write")
        domain, name = service.split(".", 1)
        body = {**({"entity_id": entity_id} if entity_id else {}), **(data or {})}
        return {"method": "POST", "path": f"/api/services/{domain}/{name}", "body": body}

    def call(self, routine, service, entity_id, data=None, reason="", at=None, signal=None):
        req = self.request(service, entity_id, data)
        if not self.live and self.gate is not None:
            event = self.gate.write(routine, service, entity_id, data, reason, signal,
                                    datetime.datetime.fromisoformat(at) if at else None)
            if event is not None:
                return event
        if not self.live:
            event = self.bus.publish("house_dry", routine=routine, action=service, entity=entity_id, request=req,
                                     reason=reason, at=at)
            if self.mirror is not None:
                self.mirror.apply(service, entity_id, data)
            return event
        try:
            self.client.service(service, entity_id, data)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            return self.bus.publish("house_error", routine=routine, action=service, entity=entity_id, error=str(error)[:200])
        return self.bus.publish("house_done", routine=routine, action=service, entity=entity_id, reason=reason, at=at)


def shopping_said(event, item):
    """What a parent reads about one shopping list add, true to what happened: real, already there, dry or failed."""
    status = event.get("status") if event.get("kind") == "house_live" else event.get("kind")
    if status in ("ran", "house_done"):
        return f"{item} added to the shopping list for real."
    if status == "already_listed":
        return f"{item} is already on the shopping list, nothing added."
    if status in ("error", "unavailable", "house_error"):
        return f"{item} was not added: the shopping list could not be reached."
    return f"{item} only written down for the shopping list (dry run), nothing was added."


SUPPLY_ES = {"diapers": "Pañales", "wipes": "Toallitas", "formula": "Fórmula"}
DAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def shopping_said_es(event, item):
    status = event.get("status") if event.get("kind") == "house_live" else event.get("kind")
    if status in ("ran", "house_done"):
        return f"{item}: agregado a la lista de compras de verdad."
    if status == "already_listed":
        return f"{item} ya está en la lista de compras, no se agregó nada."
    if status in ("error", "unavailable", "house_error"):
        return f"{item} no se agregó: no se pudo llegar a la lista de compras."
    return f"{item}: solo anotado para la lista de compras (prueba en seco), no se agregó nada."


def asleep_now(entries, now):
    """The sleep entry going on at now, or None."""
    for e in reversed(ordered(entries, now)):
        if e["kind"] == "sleep" and when(e) <= now and (not e.get("end") or now < parse(e["end"])):
            return e
    return None


def baby_room(entries, now, hours=2):
    """The room the latest log note puts him in ("feeding in the bedroom"), if it is recent, else None."""
    room = None
    for e in ordered(entries, now):
        if e["kind"] == "note" and now - when(e) <= datetime.timedelta(hours=hours):
            match = ROOM_RE.search(e.get("note") or "")
            if match:
                room = match.group(1).lower()
    return room


def tummy_times(entries, now, tz, days=3):
    """Today's predicted floor times: the usual minute of day of tummy time notes on the last days, clustered."""
    today = now.astimezone(tz).date()
    minutes = sorted(
        when(e).astimezone(tz).hour * 60 + when(e).astimezone(tz).minute
        for e in ordered(entries, now)
        if e["kind"] == "note" and TUMMY_RE.search(e.get("note") or "")
        and 1 <= (today - when(e).astimezone(tz).date()).days <= days)
    clusters = []
    for m in minutes:
        if clusters and m - clusters[-1][-1] <= 45:
            clusters[-1].append(m)
        else:
            clusters.append([m])
    midnight = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return [midnight + datetime.timedelta(minutes=round(statistics.median(c))) for c in clusters if len(c) >= 2]


class DayEngine:
    """Pure decisions on a clock: tick(entries, now, house) runs what is due and returns the events it made."""

    def __init__(self, bus, writer, settings=None, recipes=None, white_noise=None):
        self.bus, self.writer = bus, writer
        self.s = {**DEFAULTS, **(settings or {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.s["utc_offset_h"]))
        self.recipes = recipes
        self.white_noise = white_noise
        self.mode = None
        self.done = set()
        self.asks = {}
        self.added = set()
        self.facts = None
        self.echo_brief = None
        self.seen_door = set()
        self.floor_why = {}
        self.last_door = None
        # Set by the house brain (house_brain.py) from a checked Muse plan: {"floor_clean": [windows], "door_quiet":
        # [windows]}. None runs the fixed rules. A plan only moves when a routine may run, never its safety checks.
        self.plan = None
        self.cleaned = []  # when each floor clean started

    def _local(self, now, hhmm):
        h, m = map(int, hhmm.split(":"))
        return now.astimezone(self.tz).replace(hour=h, minute=m, second=0, microsecond=0)

    def _hm(self, t):
        return patterns.hhmm(t.astimezone(self.tz))

    def routine(self, name, step, now, **fields):
        return self.bus.publish("routine", name=name, trigger=ROUTINES[name], step=step, at=now.isoformat(), **fields)

    def notify(self, routine, text, now, channel="telegram", unchecked="", es=None, **fields):
        """A message for Gonza. The engine's own words pass the no-advice guard. unchecked holds words that come
        from his own calendar or Cookidoo, which are quoted as they are. es is the same message in Spanish: the family
        push sends each parent their own language."""
        if not patterns.no_advice(text):
            raise ValueError(f"day engine text failed the no-advice guard: {text[:80]}")
        if es is not None:
            fields["texts"] = {"en": text + unchecked, "es": es + unchecked}
        return self.bus.publish("notify", text=text + unchecked, channel=channel, source="day-engine",
                                routine=routine, at=now.isoformat(), **fields)

    def write(self, routine, service, entity, data=None, reason="", now=None, signal=None):
        return self.writer.call(routine, service, entity, data, reason, at=now.isoformat() if now else None, signal=signal)

    # Nap mode

    def nap_mode(self, entries, now, house):
        sleep = asleep_now(entries, now)
        local = now.astimezone(self.tz)
        if sleep is not None and self.mode is None:
            return self.enter(sleep, now, house)
        if sleep is not None and self.mode is not None:
            return self.keep_quiet(now, house)
        if sleep is None and self.mode is not None:
            if patterns.is_night(local) and self.mode["night"]:
                if ("night_hold", self.mode["since"]) not in self.done:
                    self.done.add(("night_hold", self.mode["since"]))
                    return [self.routine("nap_mode", "night_wake_stays_quiet", now,
                                         detail="a night wake-up, the house stays quiet until morning")]
                return []
            return self.leave(entries, now, house)
        return []

    def enter(self, sleep, now, house):
        start = when(sleep).astimezone(self.tz)
        kind = "nap" if 7 <= start.hour < 19 else "sleep"
        night = patterns.is_night(start) or start.hour >= 19
        why = f"{kind} started at {self._hm(start)}"
        saved = {"echo_dnd": house["echo_dnd"], "muted": [], "resume_min": None}
        out = [self.routine("nap_mode", "on", now, sleep=kind, since=start.isoformat())]
        state = house["vacuum"]
        if state == "cleaning":
            saved["resume_min"] = house.get("vacuum_left_min")
            out.append(self.write("nap_mode", "vacuum.pause", VACUUM, None, why, now, signal=SLEEP_START))
        if state in ("cleaning", "paused"):
            out.append(self.write("nap_mode", "vacuum.return_to_base", VACUUM, None, why, now, signal=SLEEP_START))
        for entity, tv in house["tvs"].items():
            if tv["on"] and not tv["muted"]:
                saved["muted"].append(entity)
                out.append(self.write("nap_mode", "media_player.volume_mute", entity, {"is_volume_muted": True}, why, now))
        if not house["echo_dnd"]:
            out.append(self.write("nap_mode", "switch.turn_on", ECHO_DND, None, why, now))
        if self.white_noise is not None and not self.white_noise.state["on"]:
            out.append(self.white_noise.on(why))
        self.mode = {"since": start, "kind": kind, "night": night, "saved": saved}
        return out

    def keep_quiet(self, now, house):
        """A TV someone turns on during the sleep is muted too, and unmuted with the others when he wakes."""
        out = []
        for entity, tv in house["tvs"].items():
            if tv["on"] and not tv["muted"] and entity not in self.mode["saved"]["muted"]:
                self.mode["saved"]["muted"].append(entity)
                out.append(self.write("nap_mode", "media_player.volume_mute", entity, {"is_volume_muted": True},
                                      f"{TVS[entity]} turned on while he sleeps", now))
        return out

    def leave(self, entries, now, house):
        saved = self.mode["saved"]
        why = f"he woke up, {self.mode['kind']} since {self._hm(self.mode['since'])}"
        out = [self.routine("nap_mode", "off", now, sleep=self.mode["kind"])]
        for entity in saved["muted"]:
            if house["tvs"][entity]["on"] and house["tvs"][entity]["muted"]:
                out.append(self.write("nap_mode", "media_player.volume_mute", entity, {"is_volume_muted": False}, why, now))
        if not saved["echo_dnd"] and house["echo_dnd"]:
            out.append(self.write("nap_mode", "switch.turn_off", ECHO_DND, None, why, now))
        if self.white_noise is not None and self.white_noise.state["on"]:
            out.append(self.white_noise.off(why))
        left = saved["resume_min"]
        self.mode = None
        if left:
            out += self.resume(entries, now, house, left)
        return out

    def resume(self, entries, now, house, left):
        windows = sleep_windows(entries, now, self.tz)
        end = now + datetime.timedelta(minutes=left + self.s["margin_min"])
        hit = in_window(now, end, windows)
        if hit or not self.s["resume_alone"]:
            why = (f"the rest of the run ({round(left)} min) would reach the {hit['kind']} around {self._hm(hit['start'])}"
                   if hit else "resuming waits for a yes")
            why_es = (f"el resto de la pasada ({round(left)} min) llegaría a la siesta prevista cerca de las "
                      f"{self._hm(hit['start'])}" if hit else "retomarla espera un sí")
            self.notify("nap_mode", f"The vacuum stays docked: {why}.", now, es=f"La aspiradora queda en su base: {why_es}.")
            return [self.routine("nap_mode", "vacuum_hold", now, why=why)]
        house["vacuum_left_min"] = left
        return [self.write("nap_mode", "vacuum.start", VACUUM, None,
                           f"resume the run the nap paused, {round(left)} min left, done before the next predicted sleep",
                           now)]

    # Door

    def door(self, now, house):
        out = []
        for event in house.get("door") or []:
            key = (event["source"], event["at"])
            if key in self.seen_door:
                continue
            self.seen_door.add(key)
            moment = parse(event["at"])
            if self.last_door is not None and abs((moment - self.last_door).total_seconds()) < 120:
                out.append(self.routine("door", "same_visit", now, source=event["source"]))
                continue
            self.last_door = moment
            what = "the doorbell rang" if event["source"] == "doorbell" else "a person at the door (camera)"
            quiet = next((w for w in (self.plan or {}).get("door_quiet") or [] if w["start"] <= now < w["end"]), None)
            if self.mode is None and quiet is not None:
                out.append(self.routine("door", "silent_push", now, source=event["source"], by="plan", why=quiet["why"]))
                out.append(self.write("door", PUSH, None,
                                      {"title": "Door", "message": f"{what.capitalize()} at {self._hm(now)}. The Echo "
                                       "stays quiet, the plan has the door on silent.",
                                       "data": {"push": {"interruption-level": "passive"}}},
                                      f"{what}, door quiet in the plan: {quiet['why']}"[:200], now))
            elif self.mode is not None:
                out.append(self.routine("door", "silent_push", now, source=event["source"]))
                out.append(self.write("door", PUSH, None,
                                      {"title": "Door", "message": f"{what.capitalize()} at {self._hm(now)}. He is asleep, "
                                       "the Echo stays quiet.", "data": {"push": {"interruption-level": "passive"}}},
                                      f"{what} during the {self.mode['kind']}", now))
            else:
                out.append(self.routine("door", "announce", now, source=event["source"]))
                out.append(self.write("door", "notify.send_message", ECHO_ANNOUNCE, {"message": DOOR_LINE}, what, now))
        return out

    # Floor clean

    def floor_slots(self, entries, now):
        """(key, floor time, earliest start, latest start): the plan's windows when a plan is armed, else the fixed
        window before each predicted tummy time."""
        run = datetime.timedelta(minutes=self.s["run_min"])
        if self.plan is not None and self.plan.get("floor_clean") is not None:
            return [(("floor", w["end"].isoformat()), w["end"], w["start"], w["end"] - run) for w in self.plan["floor_clean"]]
        slots = []
        for floor in tummy_times(entries, now, self.tz, self.s["tummy_days"]):
            latest = floor - run - datetime.timedelta(minutes=self.s["floor_lead_min"])
            slots.append((("floor", floor.isoformat()), floor, latest - datetime.timedelta(minutes=self.s["floor_window_min"]),
                          latest))
        return slots

    def floor_clean(self, entries, now, house):
        out = []
        run = datetime.timedelta(minutes=self.s["run_min"])
        for key, floor, earliest, latest in self.floor_slots(entries, now):
            if key in self.done:
                continue
            if now < earliest:
                continue
            ok, why = self.floor_ok(entries, now, house)
            if now > latest:
                self.done.add(key)
                self.asks.pop(key, None)
                out.append(self.routine("floor_clean", "hold", now, floor_at=floor.isoformat(),
                                        why=self.floor_why.get(key) or why or "no safe moment before floor time"))
                continue
            if not ok:
                self.floor_why[key] = why
                where_key = ("where", now.astimezone(self.tz).date())
                if why == UNSURE_WHERE and where_key not in self.done:
                    # Unsure where he is: ask, never assume he is out. Once a day: on Oct 30 the end-to-end day got the
                    # same question after every nap.
                    self.done.add(where_key)
                    out.append(self.notify("floor_clean", f"I could run the floor clean before {self._hm(floor)}, but "
                                           "the log does not say where he is in the last 2 hours, so the vacuum stays "
                                           "docked. Tell me where he is, or that he is out with you.", now,
                                           es=f"Podría pasar la aspiradora antes de las {self._hm(floor)}, pero el registro "
                                              "no dice dónde está en las últimas 2 horas, así que queda en su base. "
                                              "Decime dónde está, o si salió con ustedes."))
                continue
            if self.s["floor_alone"] is True:
                out += self.floor_start(key, floor, now, "alone")
            elif key not in self.asks:
                self.asks[key] = floor
                where = "he is out" if baby_out(entries, now) else f"he is awake in the {baby_room(entries, now)}"
                done = self._hm(now + run)
                out.append(self.bus.publish("ask_parent", action="floor_clean", key=list(key), at=now.isoformat(),
                                            floor_at=floor.isoformat()))
                out.append(self.routine("floor_clean", "ask", now, floor_at=floor.isoformat()))
                lead = (f"The plan has a floor clean window until {self._hm(floor)}." if self.plan and
                        self.plan.get("floor_clean") is not None else f"Tummy time is usually around {self._hm(floor)}.")
                where_es = "está afuera" if baby_out(entries, now) else "está despierto en otro cuarto"
                lead_es = (f"El plan tiene una ventana para aspirar hasta las {self._hm(floor)}." if self.plan and
                           self.plan.get("floor_clean") is not None else
                           f"El rato en el piso suele ser cerca de las {self._hm(floor)}.")
                out.append(self.notify("floor_clean", f"{lead} {where.capitalize()}, "
                                       f"I can run the vacuum now: {self.s['run_min']} min, done by {done}, before the next "
                                       "predicted nap. Reply yes to start it.", now, ask="floor_clean",
                                       es=f"{lead_es} {where_es.capitalize()}, puedo pasar la aspiradora ahora: "
                                          f"{self.s['run_min']} min, termina a las {done}, antes de la próxima siesta "
                                          "prevista. Respondé sí para empezar."))
        return out

    def floor_ok(self, entries, now, house):
        if fever_today(entries, now):
            return False, FEVER_HOLD
        windows = sleep_windows(entries, now, self.tz)
        if windows and windows[0].get("ongoing"):
            return False, "he is asleep"
        end = now + datetime.timedelta(minutes=self.s["run_min"] + self.s["margin_min"])
        hit = in_window(now, end, windows)
        if hit:
            return False, f"the run would reach the {hit['kind']} predicted around {self._hm(hit['start'])}"
        if house["vacuum"] != "docked":
            return False, f"the vacuum is {house['vacuum']}"
        # The room sensor and the latest room note come first: a stale "out with the baby" note never outweighs a
        # person in the living room or a newer note that puts him there (round 4 red team).
        room = baby_room(entries, now)
        if room == self.s["floor_room"] or house.get("living_person"):
            return False, f"he or someone is in the {self.s['floor_room']}"
        if baby_out(entries, now):
            return True, ""
        if room is None:
            return False, UNSURE_WHERE
        return True, ""

    def approve(self, action, entries, now, house):
        """Gonza's yes to a floor clean. Re-checked: a yes never starts a run that would reach a nap."""
        seen = as_of(entries, now)
        for key, floor in list(self.asks.items()):
            if key[0] != action.split("_")[0]:
                continue
            ok, why = self.floor_ok(seen, now, house)
            self.asks.pop(key)
            if not ok:
                self.done.add(key)
                return [self.routine("floor_clean", "yes_but_hold", now, why=why)]
            return self.floor_start(key, floor, now, "Gonza's yes")
        return []

    def floor_start(self, key, floor, now, by):
        self.done.add(key)
        self.cleaned.append(now)
        return [self.routine("floor_clean", "start", now, by=by, floor_at=floor.isoformat()),
                self.write("floor_clean", "vacuum.start", VACUUM, None,
                           f"floor clean before tummy time around {self._hm(floor)}, {by}", now)]

    # Morning brief

    def morning_brief(self, entries, now, house):
        out = []
        day = now.astimezone(self.tz).date()
        if ("brief", day) not in self.done and now >= self._local(now, self.s["morning_at"]):
            self.done.add(("brief", day))
            text, extra, echo = self.brief(entries, now, house)
            out.append(self.routine("morning_brief", "telegram", now))
            out.append(self.notify("morning_brief", text, now, unchecked=extra, facts=self.facts))
            self.echo_brief = {"day": day, "text": echo}
        if self.echo_brief and self.echo_brief["day"] == day:
            if now > self._local(now, self.s["echo_until"]):
                out.append(self.routine("morning_brief", "echo_skipped", now, why="nobody in the kitchen while he was awake"))
                self.echo_brief = None
            elif self.echo_ready(entries, now, house):
                out.append(self.routine("morning_brief", "echo", now))
                out.append(self.write("morning_brief", "notify.send_message", ECHO_ANNOUNCE,
                                      {"message": self.echo_brief["text"]}, "morning brief, someone is in the kitchen", now))
                self.echo_brief = None
        return out

    def echo_ready(self, entries, now, house):
        moved = house.get("echo_motion_at")
        recent = moved is not None and now - moved <= datetime.timedelta(minutes=self.s["echo_motion_min"])
        return recent and asleep_now(entries, now) is None and self.mode is None and not house["echo_dnd"]

    def brief(self, entries, now, house):
        """(telegram text, quoted calendar text, Echo text). The Echo text is numbers and fixed words only."""
        night = meals.last_night(entries, now, self.tz)
        summary_row = patterns.night_summary(entries, now, self.tz, self.s["parents"], aliases=self.s.get("aliases"))
        summary = summary_row["text"]
        weather = house.get("weather") or {}
        sky = SKY.get(weather.get("condition"))
        parts = [f"Good morning. {summary}"]
        if sky:
            parts.append(f"Weather: {sky}, {round(weather['templow'])} to {round(weather['temperature'])} C"
                         + (f", {weather['precipitation']:g} mm of rain." if weather.get("precipitation") else "."))
        if house.get("kitchen_temp_c") is not None:
            parts.append(f"Kitchen {house['kitchen_temp_c']:.0f} C.")
        low = [(item, row) for item, row in supplies(entries, now, self.tz, self.s["supplies"], self.s["wipes_per_change"]).items()
               if row["days_left"] is not None and row["days_left"] <= self.s["low_days"] + 1]
        if low:
            parts.append("Running low: " + ", ".join(f"{SUPPLY_NAMES[i]} (about {r['days_left']:.1f} days left)" for i, r in low) + ".")
        today = now.astimezone(self.tz).date()
        events = sorted((e for e in house.get("calendar") or [] if e["start"].astimezone(self.tz).date() == today),
                        key=lambda e: e["start"])
        meals_today = [e["summary"] for e in house.get("meal_plan") or [] if e.get("date") == today.isoformat()]
        parts.append(f"{len(events)} appointment{'s' if len(events) != 1 else ''} today" + (":" if events else "."))
        extra = ""
        if events:
            extra += " " + ", ".join(f"{self._hm(e['start'])} {e['summary'][:60]}" for e in events) + "."
        if meals_today:
            extra += " Cookidoo meal plan: " + ", ".join(m[:60] for m in meals_today) + "."
        text = " ".join(parts)
        # The same brief as facts, so the family push can write each parent one short morning message with only what
        # is theirs (channels/morning.py). The full text above stays in the event log.
        self.facts = {"night": {k: summary_row[k] for k in ("feeds", "longest_h", "wakeups")},
                      "weather": ({"sky": weather.get("condition"), "low": round(weather["templow"]),
                                   "high": round(weather["temperature"]), "rain_mm": weather.get("precipitation") or 0}
                                  if sky else None),
                      "low": [{"item": i, "days_left": r["days_left"]} for i, r in low],
                      "appointments": [f"{self._hm(e['start'])} {e['summary'][:60]}" for e in events],
                      "meals": [m[:60] for m in meals_today]}
        longest = patterns.hours_words(night["longest_h"]) if night["longest_h"] is not None else "unknown"
        echo = [f"Good morning. Last night he woke {night['wakeups']} times, longest sleep {longest}."]
        if sky:
            echo.append(f"Today {sky}, up to {round(weather['temperature'])} degrees.")
        echo.append(f"{len(events)} appointment{'s' if len(events) != 1 else ''} today"
                    + (f", the first at {self._hm(events[0]['start'])}." if events else "."))
        if low:
            echo.append("Running low: " + ", ".join(SUPPLY_NAMES[i] for i, _ in low) + ".")
        return text, extra, " ".join(echo)

    # Supplies

    def supplies(self, entries, now, house):
        out = []
        listed = {str(i).lower() for i in house.get("shopping") or []}
        for item, row in supplies(entries, now, self.tz, self.s["supplies"], self.s["wipes_per_change"]).items():
            key = (item, row["stock_since"])
            if key in self.added or row["days_left"] is None or row["days_left"] > self.s["low_days"]:
                continue
            self.added.add(key)
            name = SUPPLY_NAMES[item]
            if name.lower() in listed:
                out.append(self.routine("supplies", "already_listed", now, item=item))
                continue
            unit = " ml" if item == "formula" else ""
            runs = f"{row['runs_out'].astimezone(self.tz):%a} {self._hm(row['runs_out'])}" if row["runs_out"] else "soon"
            description = f"About {row['left']}{unit} left, {row['per_day']}{unit} a day, runs out around {runs}"
            out.append(self.routine("supplies", "low", now, item=item, left=row["left"], per_day=row["per_day"],
                                    computed_from=row["computed_from"]))
            written = self.write("supplies", "todo.add_item", SHOPPING, {"item": name, "description": description},
                                 f"{item} running low", now, signal="supplies_low")
            out.append(written)
            if written.get("status") != "already_listed":
                name_es = SUPPLY_ES[item]
                runs_es = (f"{DAYS_ES[row['runs_out'].astimezone(self.tz).weekday()]} {self._hm(row['runs_out'])}"
                           if row["runs_out"] else "pronto")
                description_es = (f"Quedan unos {row['left']}{unit}, se usan {row['per_day']}{unit} por día, se terminan "
                                  f"cerca del {runs_es}")
                out.append(self.notify("supplies", f"{shopping_said(written, name)} {description}.", now,
                                       es=f"{shopping_said_es(written, name_es)} {description_es}."))
            house.setdefault("shopping", []).append(name)
        return out

    def add_item(self, item, now, by=None):
        """A parent asked for an item on the shopping list. Live when shopping_list_add is listed, once per item."""
        return self.write("shopping", "todo.add_item", SHOPPING, {"item": item}, f"{by or 'a parent'} asked", now,
                          signal="parent_asked")

    # Parents' meals

    def parents_meals(self, entries, now, house):
        day = now.astimezone(self.tz).date()
        if ("meals", day) in self.done or now < self._local(now, self.s["morning_at"]) or self.recipes is None:
            return []
        self.done.add(("meals", day))
        night = meals.last_night(entries, now, self.tz)
        if not meals.is_bad(night, self.s["bad_night"]):
            return [self.routine("parents_meals", "not_needed", now, wakeups=night["wakeups"])]
        try:
            recipes = self.recipes.fast(self.s["fast_max_min"])[:2]
        except (RuntimeError, OSError, ValueError) as error:
            return [self.routine("parents_meals", "error", now, error=str(error)[:200])]
        if not recipes:
            return [self.routine("parents_meals", "no_recipes", now)]
        cook = max(r["total_time_seconds"] for r in recipes) / 60
        window = self.quiet_window(entries, now, cook + self.s["quiet_min_extra"])
        longest = patterns.hours_words(night["longest_h"]) if night["longest_h"] is not None else "unknown"
        when_text = (f"Next quiet window: his {window['kind']} around {self._hm(window['start'])} to {self._hm(window['end'])}."
                     if window else "No predicted quiet window long enough today.")
        names = ", ".join(f"{r['name']} ({round(r['total_time_seconds'] / 60)} min)" for r in recipes)
        cooked = [i for i in house.get("freezer") or [] if re.search(r"\bcooked\b", str(i), re.I)][:3]
        text = (f"Hard night: {night['wakeups']} wake-ups, longest sleep {longest}. {when_text} Quick Thermomix options "
                f"from Cookidoo:")
        event = self.routine("parents_meals", "suggest", now, wakeups=night["wakeups"], recipes=[r["name"] for r in recipes],
                             window=({k: window[k].isoformat() for k in ("start", "end")} if window else None))
        frozen = f" Already cooked in the freezer: {', '.join(str(i)[:40] for i in cooked)}." if cooked else ""
        return [event, self.notify("parents_meals", text, now, unchecked=f" {names}.{frozen} Nothing is written to "
                                   "Cookidoo, the Thermomix waits for your press of the dial.")]

    def quiet_window(self, entries, now, minutes):
        end_of_day = self._local(now, self.s["day_end"])
        for w in sleep_windows(entries, now, self.tz):
            if w.get("ongoing"):
                continue
            start = max(w["start"], now)
            if start >= end_of_day:
                break
            if (w["end"] - start).total_seconds() / 60 >= minutes and 7 <= start.astimezone(self.tz).hour < 21:
                return {**w, "start": start}
        return None

    # The tick

    def tick(self, entries, now, house):
        seen = as_of(entries, now)
        out = self.nap_mode(seen, now, house)
        out += self.door(now, house)
        out += self.floor_clean(seen, now, house)
        out += self.morning_brief(seen, now, house)
        out += self.supplies(seen, now, house)
        out += self.parents_meals(seen, now, house)
        if self.white_noise is not None:
            expired = self.white_noise.tick(now)
            if expired:
                out.append(expired)
        return out


class HouseReader:
    """Reads the house state the engine needs from Home Assistant. Reads only: GET states and calendars, and the
    todo.get_items and weather.get_forecasts read services that return data and change nothing."""

    def __init__(self, client, tz, run_min=31, door_sensors=DOOR_SENSORS):
        self.client, self.tz, self.run_min = client, tz, run_min
        self.door_sensors = tuple(door_sensors)
        # A person at the door counts when the sensor turns on, never while it stays on: the outdoor camera's
        # person sensor read "on" all through Oct 29, and a stuck sensor must not push every minute.
        self.door_was = {}

    def _safe(self, fn, default):
        try:
            return fn()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, AttributeError, TypeError):
            return default

    def read(self, now):
        c = self.client
        house = empty_house()
        house["vacuum"] = self._safe(lambda: c.state(VACUUM), "unknown")
        if house["vacuum"] == "cleaning":
            started = self._safe(lambda: parse(c.state("input_datetime.xiaomi_vacuum_run_start").replace(" ", "T") + "-03:00"), None)
            if started:
                house["vacuum_left_min"] = max(self.run_min - (now - started).total_seconds() / 60, 1)
        for entity in TVS:
            state = self._safe(lambda: c.state(entity), "unknown")
            muted = self._safe(lambda: bool(c.attributes(entity).get("is_volume_muted")), False)
            house["tvs"][entity] = {"on": state not in ("off", "unavailable", "unknown", "standby"), "muted": muted}
        house["echo_dnd"] = self._safe(lambda: c.state(ECHO_DND), "off") == "on"
        if self._safe(lambda: c.state(ECHO_MOTION), "off") == "on":
            house["echo_motion_at"] = now
        house["kitchen_temp_c"] = self._safe(lambda: float(c.state(KITCHEN_TEMP)), None)
        house["living_person"] = self._safe(lambda: c.state(LIVING_PERSON), "off") == "on"
        house["presence"] = {p: self._safe(lambda: c.state(p), "unknown") for p in ("person.gonza", "person.ceci")}
        for sensor in self.door_sensors:
            on = self._safe(lambda: c.state(sensor), "off") == "on"
            if on and self.door_was.get(sensor) is False:
                house["door"].append({"source": "person_detection", "at": now.replace(second=0, microsecond=0).isoformat()})
            self.door_was[sensor] = on
        forecast = self._safe(lambda: c.response("weather.get_forecasts", WEATHER, {"type": "daily"})
                              ["service_response"][WEATHER]["forecast"], [])
        house["weather"] = forecast[0] if forecast else None
        house["shopping"] = self._safe(lambda: [i["summary"] for i in c.response("todo.get_items", SHOPPING)
                                                ["service_response"][SHOPPING]["items"]], [])
        house["freezer"] = self._safe(lambda: [i["summary"] for i in c.response("todo.get_items", "todo.freezer")
                                               ["service_response"]["todo.freezer"]["items"]], [])
        day = now.astimezone(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        plan = self._safe(lambda: c.calendar_events(MEAL_PLAN, day, day + datetime.timedelta(days=1)), [])
        house["meal_plan"] = [{"date": e["start"].get("date"), "summary": e.get("summary", "")} for e in plan]
        return house


class DayEnginePlugin(Plugin):
    """Agent plug-in "parenting_agent.day_engine:DayEnginePlugin". Settings under "day_engine", the log from "rhythm",
    and the write switch is the same house.live as the house tools: off unless Gonza turns it on."""
    name = "day-engine"
    ASK_FIRST = ("floor_clean_yes",)

    def __init__(self, agent, config, client=None, log=None, clock=None):
        super().__init__(agent, config)
        self.s = {**DEFAULTS, **config.get("day_engine", {})}
        house_cfg = config.get("house") or {}
        self.rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.rhythm["utc_offset_h"]))
        token = os.environ.get(house_cfg.get("ha_token_env", "HA_MCP_TOKEN"))
        self.client = client if client is not None else (
            HomeAssistant(house_cfg.get("ha_url", "http://127.0.0.1:18123"), token) if token else None)
        self.reader = (HouseReader(self.client, self.tz, self.s["run_min"], self.s["door_sensors"])
                       if self.client is not None else None)
        self.born = baby_phase.born(config)
        self._log = log
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        recipes = meals.FixtureRecipes(self.s["recipes_fixture"]) if self.s.get("recipes_fixture") else (
            meals.HomeAgentsRecipes() if self.s.get("recipes") == "home-agents" else None)
        self.gate = gate_for(agent, config, self.client, self.clock)
        self.engine = DayEngine(agent.bus, DayWriter(agent.bus, self.client, house_cfg.get("live") is True, gate=self.gate),
                                {**self.s, "utc_offset_h": self.rhythm["utc_offset_h"]}, recipes,
                                SimulatedWhiteNoise(agent.bus))
        if not self.engine.writer.live:
            add_dry_guard(agent)
        people = getattr(agent, "people", None)
        if people:
            self.engine.s["aliases"] = {str(people.name(p)).lower(): people.label(p) for p in people.keys()
                                        if people.label(p)}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.door = []
        for name in self.ASK_FIRST:
            agent.tools.allowed.discard(name)
        agent.bus.subscribe(self.on_sound, kinds=["house_sound"])
        agent.tools.add(Tool("floor_clean_yes", "Start the floor clean the day engine asked about, after the parent said "
                             "yes. Refused when the run would reach a predicted nap.", schema({}), self.floor_yes))
        agent.tools.add(Tool("add_to_shopping_list", "Add one item to the family's shopping list in Home Assistant when a "
                             "parent asks, for example diapers or pañales. It checks the list first and never adds an "
                             "item twice. It cannot remove items.",
                             schema({"item": {"type": "string"}}, ["item"]), self.add_to_shopping_list))
        agent.tools.add(Tool("set_supply_stock", "When a parent says how many diapers or wipes, or how much formula (ml), "
                             "the family has at home now, for example 'tenemos 26 pañales'. The supplies routine counts "
                             "down from it and puts the item on the shopping list three days before it runs out.",
                             schema({"item": {"type": "string", "enum": list(SUPPLY_NAMES)},
                                     "count": {"type": "integer"}}, ["item", "count"]), self.set_stock))
        agent.tools.add(Tool("day_engine_status", "What the day engine is doing: nap mode, open questions. Changes nothing.",
                             schema({}), self.status))

    @property
    def log(self):
        if self._log is None:
            self._log = make_log(self.rhythm, os.environ)
        return self._log

    def house(self, now):
        house = self.reader.read(now) if self.reader is not None else empty_house()
        house["door"] += self.door
        return house

    def on_sound(self, event):
        if event.get("label") == "doorbell":
            self.door.append({"source": "doorbell", "at": self.clock().replace(microsecond=0).isoformat()})

    def floor_yes(self):
        now = self.clock()
        with self.lock:
            events = self.engine.approve("floor_clean", self.log.entries(), now, self.house(now))
        if not events:
            return "There is no floor clean waiting for a yes."
        if events[0].get("step") != "start":
            return f"Not now: {events[0].get('why')}."
        if self.engine.writer.live:
            return "Vacuum start sent for the floor clean."
        return f"Vacuum start for the floor clean {DRY_WRITE}."

    def add_to_shopping_list(self, item):
        item = " ".join(str(item or "").split())[:120]
        if not item:
            return "add_to_shopping_list: no item given, nothing added."
        if rules.holds_code(item):
            self.agent.bus.publish("house_live", status="refused", routine="shopping", service="todo.add_item",
                                   entity=SHOPPING, reason="a parent asked", why="holds a code or a number")
            return "add_to_shopping_list: refused, a code, a password or a long number never goes on a list."
        with self.lock:
            event = self.engine.add_item(item, self.clock())
        return shopping_said(event, item)

    def set_stock(self, item, count):
        """A "Stock: diapers 26" note in the baby log: the supplies routine reads the latest one (house_plan.STOCK_RE)."""
        if item not in SUPPLY_NAMES:
            return f"set_supply_stock: unknown item {item}, expected one of {', '.join(SUPPLY_NAMES)}."
        count = int(count)
        if not 0 <= count <= 5000:
            return "set_supply_stock: refused, the count must be between 0 and 5000."
        text = f"Stock: {item} {count}"
        try:
            since = (self.clock() - datetime.timedelta(hours=12)).isoformat(timespec="seconds")
            kept = [e for e in self.agent.baby_log.entries("note", since, 50)
                    if str((e.get("details") or {}).get("text", "")).strip().lower().startswith(f"stock: {item} ")]
        except Exception:  # noqa: BLE001 an unreadable log never blocks the write
            kept = []
        if kept and kept[-1]["details"]["text"].strip().lower() == text.lower():
            # The brain can call it again on a later message (Oct 30 end-to-end day: the 06:20 count again at 08:05).
            return f"Stock already kept: {item} {count}, nothing new written."
        entry = self.agent.baby_log.add("note", {"text": text})
        self.agent.bus.publish("supplies_stock", item=item, count=count, entry=entry.get("id"))
        return f"Stock kept: {item} {count}. I tell you both and add it to the shopping list three days before it runs out."

    def status(self):
        mode = self.engine.mode
        return {"nap_mode": bool(mode), "since": mode["since"].isoformat() if mode else None,
                "asks": [k[0] for k in self.engine.asks], "live": self.engine.writer.live,
                "live_actions": [n for n in self.gate.listed if self.gate.enabled(n)]}

    def start(self):
        self.thread = threading.Thread(target=self.run, name="day-engine", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                now = self.clock()
                with self.lock:
                    # Before the birth the log is a test child: the routines see an empty log (baby_phase.py).
                    self.engine.tick(self.log.entries() if self.born else [], now, self.house(now))
                    self.door = []
            except Exception as error:  # a bad read must not stop the agent
                self.agent.bus.publish("day_engine_error", error=str(error)[:300])
            self.stopped.wait(self.s["poll_s"])

    def stop(self):
        self.stopped.set()
