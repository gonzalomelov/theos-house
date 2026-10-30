"""Muse runs the house (issue #116): Muse Spark Open plans the next hours, plain code checks the plan and arms the
fixed routines.

When: at bedtime, at the morning wake-up, after a night feed is logged, and before each predicted nap. And again,
at once, when something unusual happens: a sleep 40 minutes longer than usual, a parent asking to sleep, a dog alert,
a visitor. Muse gets the log, the rhythm prediction, the night rota, the house state (read only) and the weather, and
answers in a strict JSON schema (plan_schema): which routines to arm and when, who is on duty, what to tell each
parent, and one sentence of why.

Muse never touches a device. The schema has no device field at all: it names routines, and validate() checks every
item against the clock, the routine list and the safety gate (a floor clean never overlaps a predicted sleep, a bottle
pre-warm only at night, a door or white noise window has a length limit) before apply() hands the windows to the
deterministic routines in day_engine.py and night_feed.py. Those routines keep their own checks at run time: nap mode
always pauses the vacuum when a sleep starts, the floor clean re-checks that he is awake and out of the room, the
warmer has its hard auto off, the white noise its 50 dB cap.

When Muse is slow, errors, runs out of budget or returns a plan that fails validation, the plan is dropped and the
fixed routines run exactly as before. Every fallback is a "house_brain_fallback" event. Every plan, accepted or not,
is a "house_plan" event, so the event log holds the whole night.

Texts: what Muse writes to a parent passes the no-advice guard or is dropped. The morning explanation on the Echo also
passes a speaker filter (plain letters, short, no codes), and Muse writes it from the house's own events, never from a
parent's free text, so an injected message cannot reach the speaker.
"""
import datetime
import json
import os
import re
import threading
import time
import urllib.parse

from .agent import rules
from .agent.brain import BrainError, post_json, without_thinking
from .agent.plugins import Plugin
from .house_plan import as_of, sleep_windows, usual
from .rhythm import patterns
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .rhythm.engine import make_log
from .rhythm.log import ordered, parse, when

MUSE = {"model": "meta-models/muse-spark-open-1026", "base_url": "https://inference.baseten.co/v1",
        "key_env": "BASETEN_API_KEY", "reasoning_effort": "low", "max_tokens": 6000, "timeout_s": 60,
        "price_in_per_mtok": 1.25, "price_out_per_mtok": 4.25}
DEFAULTS = {"bedtime": "20:30", "explain_at": "07:30", "pre_nap_min": 15, "horizon_h": 12, "long_sleep_min": 40,
            "budget_usd": 0.5, "min_gap_min": 10, "parents": ["Parent A", "Parent B"], "utc_offset_h": -3,
            "run_min": 31, "margin_min": 10, "poll_s": 60, "dog_every_min": 30, "muse": {},
            # on_duty_on_request: Muse names the parent on duty only after a parent asked to sleep in the last 12 h.
            # Otherwise the rota stays fixed: in the replay of six nights Muse named the wrong parent 1 time in 21 and
            # 22 prepares, the rota never does (results/muse-house). "on_duty" would give Muse the rota always.
            "parts": ["floor_clean", "bottle_prewarm", "door_quiet", "white_noise_boost", "on_duty_on_request"],
            "tell": ["tonight", "replan", "morning_explain"]}  # what reaches Telegram, the rest stays in the event log
ROUTINES = ("floor_clean", "bottle_prewarm", "door_quiet", "white_noise_boost")
ALWAYS_ON = ("nap_mode", "door", "supplies", "morning_brief")  # safety and daily routines no plan can switch off
MAX_WINDOW_MIN = {"floor_clean": 180, "door_quiet": 240, "white_noise_boost": 60}
# How many windows one plan may arm, and the total minutes for the door: twelve boosts or a doorbell silent for 12 h
# passed the per-window caps in round 4.
MAX_WINDOWS = {"bottle_prewarm": 4, "floor_clean": 2, "door_quiet": 2, "white_noise_boost": 4}
MAX_TOTAL_MIN = {"door_quiet": 240, "white_noise_boost": 120}
EXHAUSTED_RE = re.compile(r"\b(exhausted|let me sleep|need (?:to|some) sleep|so tired|wiped out|agotad[oa]|"
                          r"d[eé]jame dormir|muert[oa] de sue[nñ]o)\b", re.IGNORECASE)
VISITOR_RE = re.compile(r"\b(visit\w*|coming over|guests?|arriv\w*|visita\w*|vienen?)\b", re.IGNORECASE)
DOG_LABELS = ("dog", "bark", "dog_bark", "barking")
SPEAKER_TEXT = re.compile(r"^[A-Za-z0-9 ,.:'()-]+$")
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

SYSTEM = """You plan the house of a family with a newborn for the next hours. Plain code checks your plan and runs
the devices. You never control a device: you only arm routines by name, with times.

Routines you can arm (all times are HH:MM local, between now and plan_until, nothing later):
- floor_clean: a window [start, end] in which the robot vacuum may clean the living room floor. The run takes {run}
  minutes plus a {margin} minute margin, so end - start must be at least {window} minutes. The window must not
  overlap any predicted sleep (predicted_sleeps) and must be in the day (07:00 to 21:00). Finishing before the usual
  tummy time on the floor is the goal. The vacuum only starts while the log places him out of the house or in a room
  that is not the living room within the last 2 hours (floor_clean_gate), and a parent confirms. The routine checks
  that gate itself at run time, minute by minute inside your window, so a window can be armed before the gate is met.
  Arm none when there is no safe window.
- bottle_prewarm: start = the minute the bottle warmer (water only) and a dim study light go on before a night feed.
  Night only (21:00 to 06:59), at most 4, at least 60 minutes apart. The warmer turns itself off after 30 minutes.
- door_quiet: a window in which the doorbell goes to a silent phone push instead of the kitchen speaker, for example
  around a visitor arriving close to a nap. At most 2 windows and 4 hours in all.
- white_noise_boost: a window of at most 60 minutes in which the white noise goes up to its capped level, for example
  while a dog barks during a sleep. At most 4 windows and 120 minutes in all.
Nap mode, the door, the supplies list and the morning brief always run, you cannot switch them off.
Every window needs a real start and end (bottle_prewarm a start). An empty list means the routine is not armed.
Your answer replaces current_plan whole: list again every window from current_plan you want to keep, nothing carries
over by itself. The summary describes only what is in the lists.

on_duty: the parent who gets the night pushes. The night rota (next_by_rota) is the default. Change it only for a
reason in the log, for example a parent asking to sleep.

messages: what to tell each parent, short, plain facts and times. Never give advice or a health opinion: do not use
the words should, must, try, recommend, consider, need to, normal, worry, doctor, sick, fever, medicine.

summary: one sentence, the plan and why. It never names a parent on duty other than on_duty, and never holds a code,
a phone number or an address. why_changed: when what_happened is not empty, one sentence on what changed
and why, else "". Answer with the JSON only."""

EXPLAIN_SYSTEM = """You tell a family with a newborn, in plain words, what their house did overnight and why. You get
the house's own event list. State facts and times only. Never give advice or a health opinion: do not use the words
should, must, try, recommend, consider, need to, normal, worry, doctor, sick, fever, medicine.
telegram: at most 4 short sentences. echo: at most 2 short sentences for the kitchen speaker, plain letters and
numbers only. Answer with the JSON only."""


def plan_schema(parents):
    """The plan Muse must return. The routines come first, so Muse decides the windows before it describes them, and
    each routine has its own list in the same shape as current_plan in the prompt."""
    window = {"type": "object", "additionalProperties": False, "required": ["start", "end", "why"],
              "properties": {"start": {"type": "string", "description": "HH:MM"},
                             "end": {"type": "string", "description": "HH:MM"}, "why": {"type": "string"}}}
    moment = {"type": "object", "additionalProperties": False, "required": ["start", "why"],
              "properties": {"start": {"type": "string", "description": "HH:MM"}, "why": {"type": "string"}}}
    message = {"type": "object", "additionalProperties": False, "required": ["to", "text"],
               "properties": {"to": {"type": "string", "enum": list(parents) + ["both"]}, "text": {"type": "string"}}}
    props = {"on_duty": {"type": "string", "enum": list(parents)},
             "floor_clean": {"type": "array", "items": window}, "bottle_prewarm": {"type": "array", "items": moment},
             "door_quiet": {"type": "array", "items": window}, "white_noise_boost": {"type": "array", "items": window},
             "messages": {"type": "array", "items": message}, "summary": {"type": "string"},
             "why_changed": {"type": "string"}}
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


EXPLAIN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["telegram", "echo"],
                  "properties": {"telegram": {"type": "string"}, "echo": {"type": "string"}}}


class MuseAnswerError(BrainError):
    def __init__(self, message, meta):
        super().__init__(message)
        self.meta = meta


class MuseClient:
    """One strict JSON answer from Muse Spark Open, standard library only (the Vostro image has no numpy)."""

    def __init__(self, config=None, post=post_json, clock=time.monotonic):
        self.cfg = {**MUSE, **(config or {})}
        self.url = self.cfg["base_url"].rstrip("/") + "/chat/completions"
        self.host = urllib.parse.urlparse(self.url).hostname
        self.post, self.clock = post, clock

    def ask(self, system, text, schema, name="plan"):
        key = os.environ.get(self.cfg["key_env"])
        if not key:
            raise BrainError(f"house brain: {self.cfg['key_env']} is not set")
        body = {"model": self.cfg["model"], "max_tokens": self.cfg["max_tokens"],
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
                "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}
        if self.cfg.get("reasoning_effort"):
            body["reasoning_effort"] = self.cfg["reasoning_effort"]
        started = self.clock()
        reply = self.post(self.url, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, body,
                          self.cfg["timeout_s"])
        seconds = round(self.clock() - started, 3)
        usage = reply.get("usage") or {}
        tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        usd = (tin * self.cfg["price_in_per_mtok"] + tout * self.cfg["price_out_per_mtok"]) / 1_000_000
        choice = (reply.get("choices") or [{}])[0]
        raw = without_thinking((choice.get("message") or {}).get("content"))
        meta = {"seconds": seconds, "usd": round(usd, 6), "input_tokens": tin, "output_tokens": tout, "host": self.host,
                "model": self.cfg["model"]}
        try:
            answer = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            answer = None
        if not isinstance(answer, dict):
            raise MuseAnswerError(f"not a JSON object (finish_reason {choice.get('finish_reason')}): {str(raw)[:120]}", meta)
        return answer, meta


def local_hm(t, tz):
    return patterns.hhmm(t.astimezone(tz))


def absolute(hhmm, now, tz, horizon_h):
    """The moment at HH:MM nearest to now, today, yesterday or tomorrow. ValueError when it is not HH:MM or more than
    the horizon ahead."""
    match = HHMM.match(str(hhmm or "").strip())
    if not match:
        raise ValueError(f"{hhmm!r} is not HH:MM")
    local = now.astimezone(tz)
    today = local.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    moment = min((today + datetime.timedelta(days=d) for d in (-1, 0, 1)), key=lambda t: abs(t - local))
    if moment > local + datetime.timedelta(hours=horizon_h):
        raise ValueError(f"{hhmm} is more than {horizon_h} h ahead")
    return moment


def after(hhmm, start, tz):
    """The first moment at HH:MM after start (a window's end)."""
    match = HHMM.match(str(hhmm or "").strip())
    if not match:
        raise ValueError(f"{hhmm!r} is not HH:MM")
    moment = start.astimezone(tz).replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    return moment if moment > start else moment + datetime.timedelta(days=1)


def is_night_hour(t, tz):
    hour = t.astimezone(tz).hour
    return hour >= 21 or hour < 7


def clean_text(text, limit=280):
    return " ".join(str(text or "").split())[:limit]


def check_item(name, item, now, tz, s, windows):
    """(window, None) or (None, reason) for one routine item."""
    try:
        start = absolute(item.get("start"), now, tz, s["horizon_h"])
        end = None if name == "bottle_prewarm" else after(item.get("end"), start, tz)
    except ValueError as error:
        return None, f"{name}: {error}"
    window = {"start": start, "end": end, "why": clean_text(item.get("why"), 200)}
    if (end or start + datetime.timedelta(minutes=30)) <= now:
        return None, "expired"  # a window from the last plan that is over, left out
    if end is not None:
        if end - start > datetime.timedelta(minutes=MAX_WINDOW_MIN[name]):
            return None, f"{name}: longer than {MAX_WINDOW_MIN[name]} min"
    if name == "floor_clean":
        start = window["start"] = max(start, now.astimezone(tz).replace(second=0, microsecond=0))
        if end - start < datetime.timedelta(minutes=s["run_min"] + s["margin_min"]):
            return None, f"floor_clean {local_hm(start, tz)}-{local_hm(end, tz)}: shorter than the run and margin"
        if is_night_hour(start, tz) or is_night_hour(end - datetime.timedelta(minutes=1), tz):
            return None, f"floor_clean {local_hm(start, tz)}: not in the day"
        hit = next((w for w in windows if start < w["end"] and w["start"] < end), None)
        if hit:
            return None, (f"floor_clean {local_hm(start, tz)}-{local_hm(end, tz)} overlaps the predicted {hit['kind']} "
                          f"{local_hm(hit['start'], tz)}-{local_hm(hit['end'], tz)}")
    if name == "bottle_prewarm" and not is_night_hour(start, tz):
        return None, f"bottle_prewarm {local_hm(start, tz)}: not at night"
    return window, None


def validate(answer, now, tz, s, windows):
    """(plan, errors, refused, dropped).

    errors: the answer is not a plan (wrong shape, unknown parent). The whole plan is refused and every routine runs
    its fixed rule. refused: {routine: [reasons]} for items that fail the clock or the safety gate. That routine is
    None in the plan, so it runs its fixed rule, and the rest of the plan stands. An item with an empty start is Muse
    leaving the routine out, it goes to dropped. dropped also lists texts that failed the no-advice guard."""
    errors, refused, dropped = [], {}, []
    parents = list(s["parents"])
    if not isinstance(answer, dict):
        return None, ["not an object"], refused, dropped
    if answer.get("on_duty") not in parents:
        errors.append(f"on_duty {answer.get('on_duty')!r} is not a parent")
    plan = {}
    for name in ROUTINES:
        items = answer.get(name)
        if not isinstance(items, list):
            errors.append(f"{name} is not a list")
            continue
        plan[name] = []
        for item in items:
            item = item if isinstance(item, dict) else {}
            if not str(item.get("start") or "").strip():
                dropped.append({"to": name, "text": json.dumps(item)[:120], "why": "empty start, left out"})
                continue
            window, reason = check_item(name, item, now, tz, s, windows)
            if reason == "expired":
                dropped.append({"to": name, "text": json.dumps(item)[:120], "why": "over already, left out"})
            elif reason:
                refused.setdefault(name, []).append(reason)
            else:
                plan[name].append(window)
    if errors:
        return None, errors, refused, dropped
    warm = sorted(w["start"] for w in plan["bottle_prewarm"])
    if any(b - a < datetime.timedelta(minutes=60) for a, b in zip(warm, warm[1:])):
        refused.setdefault("bottle_prewarm", []).append("bottle pre-warms less than 60 min apart")
    for name, most in MAX_WINDOWS.items():
        if len(plan[name]) > most:
            refused.setdefault(name, []).append(f"more than {most} {name} windows")
    for name, most in MAX_TOTAL_MIN.items():
        total = sum((w["end"] - w["start"]).total_seconds() / 60 for w in plan[name])
        if total > most:
            refused.setdefault(name, []).append(f"{name} windows add up to {total:.0f} min, more than {most}")
    for name in refused:
        plan[name] = None
    messages = []
    for m in (answer.get("messages") or [])[:4]:
        m = m if isinstance(m, dict) else {}
        text, to = clean_text(m.get("text")), m.get("to")
        if to not in parents + ["both"] or not text:
            dropped.append({"to": to, "text": text, "why": "unknown recipient or empty"})
        elif not text_ok(text):
            dropped.append({"to": to, "text": text, "why": "failed the no-advice guard"})
        else:
            messages.append({"to": to, "text": text})
    texts = {"summary": clean_text(answer.get("summary"), 240), "why_changed": clean_text(answer.get("why_changed"), 240)}
    for field, text in list(texts.items()):
        if text and not text_ok(text):
            # The same check as every other outgoing text: no advice, no code, no contact detail.
            dropped.append({"to": field, "text": text, "why": "failed the no-advice or private-detail guard"})
            texts[field] = ""
    other = disagrees_on_duty(texts["summary"], answer["on_duty"], parents)
    if other:
        dropped.append({"to": "summary", "text": texts["summary"], "why": f"names {other} on duty, the plan says {answer['on_duty']}"})
        texts["summary"] = ""
    plan.update(on_duty=answer["on_duty"], messages=messages, **texts)
    return plan, [], refused, dropped


def text_ok(text):
    """No advice, no secret and no contact detail. Times like 08:15-09:14 are not a run of digits."""
    return patterns.no_advice(text) and not rules.personal_detail(re.sub(r"\b\d{1,2}:\d{2}\b", "T", text))


def disagrees_on_duty(summary, on_duty, parents):
    """The other parent a summary puts on duty, or None. The Telegram line names on_duty from the plan itself, so a
    summary that says "Parent B is on" while the plan says Parent A would make the plan say two things."""
    for other in parents:
        if other != on_duty and re.search(rf"\b{re.escape(other)}\b(?:'s)?\s+(?:is\s+|takes\s+|has\s+)?(?:on\b|on duty|"
                                           rf"the night|tonight's shift|up next|next)", summary or "", re.I):
            return other
    return None


def speaker_ok(text):
    return bool(text) and len(text) <= 300 and SPEAKER_TEXT.match(text) is not None and text_ok(text)


def plan_json(plan, tz):
    """A plan with local HH:MM times, for the event log and the next prompt."""
    if not plan:
        return None
    out = {k: v for k, v in plan.items() if k not in ROUTINES}
    for name in ROUTINES:
        out[name] = "fixed rule" if plan[name] is None else [
            {"start": local_hm(w["start"], tz), "end": local_hm(w["end"], tz) if w["end"] else "", "why": w["why"]}
            for w in plan[name]]
    return out


class HouseBrain:
    """Decides when to ask Muse, checks the answer, arms the routines, falls back. Pure on a clock: tick(entries, now,
    house) with a house dict as the day engine reads it, a callable that reads it only when Muse is asked, or None."""

    def __init__(self, bus, muse, settings=None, day_engine=None, night_feed=None, white_noise=None, say=None,
                 tell=None):
        self.bus, self.muse = bus, muse
        self.s = {**DEFAULTS, **(settings or {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.s["utc_offset_h"]))
        self.day_engine, self.night_feed, self.white_noise = day_engine, night_feed, white_noise
        self.say = say      # the Echo, a callable(text, now)
        self.tell = tell    # Telegram to Gonza, a callable(text, now)
        self.plan, self.done = None, set()
        self.stats = {"calls": 0, "usd": 0.0, "seconds": [], "fallbacks": 0, "accepted": 0, "by_trigger": {},
                      "fallback_reasons": []}
        self.last_call, self.last_feed, self.boosting, self.last_dog = None, None, None, None
        self.asked_to_sleep, self.asking_at = None, None  # when a parent last asked to sleep, when Muse is asked
        self.sounds, self.overnight = [], []
        bus.subscribe(self.on_event)

    # Events the brain reacts to or keeps for the morning

    KEEP = ("house_plan", "house_brain_fallback", "night_feed", "virtual_device", "house_dry", "white_noise", "house_call")

    def on_event(self, event):
        kind = event["kind"]
        if kind in ("house_sound", "sound") and str(event.get("label", "")).lower() in DOG_LABELS:
            self.sounds.append(event)
        if kind in self.KEEP:
            self.overnight.append({k: v for k, v in event.items() if k not in ("t", "ts", "unix", "request")})
            del self.overnight[:-300]

    # When to plan

    def triggers(self, seen, now):
        """[(trigger, what happened or None)] due at now, each once. Reads the log only, never the house."""
        out, local = [], now.astimezone(self.tz)
        sleeps = [e for e in seen if e["kind"] == "sleep"]
        current = sleeps[-1] if sleeps and (not sleeps[-1].get("end") or now < parse(sleeps[-1]["end"])) else None
        day = (local - datetime.timedelta(hours=12)).date()  # the evening a night belongs to
        bed = local.replace(hour=int(self.s["bedtime"][:2]), minute=int(self.s["bedtime"][3:]), second=0, microsecond=0)
        night_start = current is not None and when(current).astimezone(self.tz).hour >= 19
        evening = local.hour >= 18 and (local >= bed or night_start)
        if ("bedtime", day) not in self.done and (evening or local.hour < 5):
            self.done.add(("bedtime", day))
            out.append(("bedtime", None))
        ended = [e for e in sleeps if e.get("end") and parse(e["end"]) <= now]
        if ended and current is None:
            end = parse(ended[-1]["end"]).astimezone(self.tz)
            key = ("wake", ended[-1].get("end"))
            # Every wake-up in the day, and the morning one. A night wake-up is the night feed trigger below.
            if (not patterns.is_night(end) or 5 <= end.hour < 10) and now - end < datetime.timedelta(minutes=10) \
                    and key not in self.done:
                self.done.add(key)
                out.append(("wake_up", f"he woke up at {local_hm(end, self.tz)}"))
        feeds = patterns.feeds(seen, now)
        if feeds:
            ref = feeds[-1].get("ref") or when(feeds[-1]).isoformat()
            fresh = self.last_feed is not None and ref != self.last_feed
            self.last_feed = ref
            if fresh and patterns.is_night(when(feeds[-1]).astimezone(self.tz)) \
                    and now - when(feeds[-1]) < datetime.timedelta(hours=1):
                out.append(("night_wake", f"a night feed was logged at {local_hm(when(feeds[-1]), self.tz)}"))
        if current is None and ended:
            nxt = next((w for w in sleep_windows(seen, now, self.tz, horizon_h=2) if not w.get("ongoing")), None)
            key = ("pre_nap", ended[-1].get("end"))
            if nxt and nxt["kind"] == "nap" and key not in self.done \
                    and nxt["start"] - now <= datetime.timedelta(minutes=self.s["pre_nap_min"]):
                self.done.add(key)
                out.append(("before_nap", f"a nap is predicted around {local_hm(nxt['start'], self.tz)}"))
        return out + self.unusual(seen, now, current)

    def unusual(self, seen, now, current):
        out = []
        if current is not None:
            night = patterns.is_night(when(current).astimezone(self.tz))
            usual_min = usual(seen, now, self.tz)["sleep"][night]
            so_far = (now - when(current)).total_seconds() / 60
            key = ("long", current.get("ref") or current.get("start"))
            woke = any(when(f) > when(current) for f in patterns.feeds(seen, now))  # a feed since means he woke
            if not woke and so_far >= usual_min + self.s["long_sleep_min"] and key not in self.done:
                self.done.add(key)
                out.append(("adapt", f"he has slept {round(so_far)} min since {local_hm(when(current), self.tz)}, "
                                     f"{round(so_far - usual_min)} min longer than the usual {round(usual_min)} min"))
        for e in ordered(seen, now):
            if e["kind"] != "note" or now - when(e) > datetime.timedelta(minutes=30):
                continue
            key = ("note", e.get("ref") or e.get("time"))
            text = (e.get("note") or "").replace("[simulated] ", "")
            if key in self.done:
                continue
            if EXHAUSTED_RE.search(text):
                self.done.add(key)
                self.asked_to_sleep = when(e)
                out.append(("adapt", f"a parent wrote at {local_hm(when(e), self.tz)}: \"{clean_text(text, 160)}\""))
            elif VISITOR_RE.search(text):
                self.done.add(key)
                out.append(("adapt", f"a visitor note at {local_hm(when(e), self.tz)}: \"{clean_text(text, 160)}\""))
        if self.sounds:
            self.sounds = []
            if self.last_dog is None or now - self.last_dog >= datetime.timedelta(minutes=self.s["dog_every_min"]):
                self.last_dog = now
                where = "while he sleeps" if current is not None else "while he is awake"
                out.append(("adapt", f"the house microphone heard a dog barking at {local_hm(now, self.tz)}, {where}"))
        return out

    # The plan

    def context(self, seen, now, house, trigger, what):
        from .night_feed import predict
        tz = self.tz
        local = now.astimezone(tz)
        rows = []
        for e in ordered(seen, now):
            if now - when(e) > datetime.timedelta(hours=24):
                continue
            t = when(e).astimezone(tz)
            if e["kind"] == "sleep":
                end = f"-{local_hm(parse(e['end']), tz)}" if e.get("end") and parse(e["end"]) <= now else " (ongoing)"
                rows.append(f"{t:%a %H:%M}{end} sleep")
            elif e["kind"] == "feeding":
                amount = f" {e.get('amount')} ml" if e.get("amount") else ""
                rows.append(f"{t:%a %H:%M} feed {e.get('method') or ''}{amount}".rstrip())
            elif e["kind"] == "note":
                rows.append(f"{t:%a %H:%M} note: {clean_text((e.get('note') or '').replace('[simulated] ', ''), 120)}")
            elif e["kind"] == "change":
                rows.append(f"{t:%a %H:%M} diaper")
        u = usual(seen, now, tz)
        windows = sleep_windows(seen, now, tz, horizon_h=self.s["horizon_h"])
        nxt = predict(seen, now)
        handled = [w["parent"] for w in patterns.night_wakeups(seen, tz) if w["at"] < now]
        tummy = []
        if self.day_engine is not None:
            from .day_engine import tummy_times
            tummy = [local_hm(t, tz) for t in tummy_times(seen, now, tz)]
        floor = {}
        if self.day_engine is not None:
            from .day_engine import baby_room
            from .house_plan import baby_out
            floor = {"cleaned_today": any(c.astimezone(tz).date() == local.date() for c in self.day_engine.cleaned),
                     "he_is_out": bool(baby_out(seen, now)), "room_from_log_last_2h": baby_room(seen, now)}
        h = house or {}
        weather = h.get("weather") or {}
        noise = getattr(self.white_noise, "state", None)
        state = {"vacuum": h.get("vacuum"), "tvs_on": sum(1 for tv in (h.get("tvs") or {}).values() if tv.get("on")),
                 "echo_do_not_disturb": h.get("echo_dnd"), "someone_in_living_room": h.get("living_person"),
                 "kitchen_temp_c": h.get("kitchen_temp_c"),
                 "white_noise": {"on": noise["on"], "level": noise["level"]} if noise else None,
                 "bottle_warmer": getattr(getattr(self.night_feed, "warmer", None), "state", None)}
        calendar = [f"{local_hm(e['start'], tz)} {clean_text(e['summary'], 60)}" for e in h.get("calendar") or []
                    if e["start"].astimezone(tz).date() == local.date()]
        return {
            "now": f"{local:%a %H:%M}",
            "plan_until": f"{local + datetime.timedelta(hours=self.s['horizon_h']):%a %H:%M}",
            "trigger": trigger, "what_happened": what or "",
            "parents": self.s["parents"],
            "log_last_24h": rows[-60:],
            "usual_minutes": {"nap": round(u["sleep"][False]), "night_sleep": round(u["sleep"][True]),
                              "awake_day": round(u["awake"][False]), "awake_night": round(u["awake"][True])},
            "predicted_sleeps": [{"start": local_hm(w["start"], tz), "end": local_hm(w["end"], tz), "kind": w["kind"],
                                  "ongoing": bool(w.get("ongoing"))} for w in windows],
            "next_feed_predicted": local_hm(nxt["at"], tz) if nxt else None,
            "night_rota": {"wakeups_handled": {p: handled.count(p) for p in self.s["parents"]},
                           "next_by_rota": patterns.next_on_duty(handled, self.s["parents"])},
            "usual_tummy_times": tummy,
            "floor_clean_gate": floor,
            "house_read_only": state,
            "weather": {k: weather.get(k) for k in ("condition", "temperature", "templow", "precipitation")} if weather else None,
            "calendar_today": calendar,
            "current_plan": plan_json(self.plan, tz),
        }

    def system(self):
        run, margin = self.s["run_min"], self.s["margin_min"]
        return SYSTEM.format(run=run, margin=margin, window=run + margin)

    def ask(self, seen, now, house, trigger, what):
        self.asking_at = now
        self.stats["by_trigger"][trigger] = self.stats["by_trigger"].get(trigger, 0) + 1
        if self.stats["usd"] >= self.s["budget_usd"]:
            return self.fallback(trigger, what, now, f"budget of {self.s['budget_usd']} USD used", None)
        house = house() if callable(house) else house
        windows = sleep_windows(seen, now, self.tz, horizon_h=self.s["horizon_h"])
        ctx = self.context(seen, now, house, trigger, what)
        try:
            answer, meta = self.muse.ask(self.system(), json.dumps(ctx, default=str), plan_schema(self.s["parents"]))
        except MuseAnswerError as error:
            self.count(error.meta)
            return self.fallback(trigger, what, now, f"invalid answer: {error}", error.meta)
        except (BrainError, OSError, ValueError) as error:
            self.stats["calls"] += 1
            return self.fallback(trigger, what, now, f"Muse error: {str(error)[:200]}", None)
        self.count(meta)
        plan, errors, refused, dropped = validate(answer, now, self.tz, self.s, windows)
        if plan is None:
            self.bus.publish("house_plan", trigger=trigger, what=what, at=now.isoformat(), accepted=False, errors=errors,
                             answer=answer, muse=meta)
            return self.fallback(trigger, what, now, "plan refused: " + "; ".join(errors)[:300], meta)
        self.plan = plan
        self.stats["accepted"] += 1
        self.apply(plan)
        event = self.bus.publish("house_plan", trigger=trigger, what=what, at=now.isoformat(), accepted=True,
                                 plan=plan_json(plan, self.tz), refused=refused, dropped=dropped, muse=meta)
        if refused:
            self.stats["partial_fallbacks"] = self.stats.get("partial_fallbacks", 0) + 1
            self.stats["fallback_reasons"].append({"at": now.isoformat(), "trigger": trigger, "routines": sorted(refused),
                                                   "reason": "; ".join(r for rs in refused.values() for r in rs)[:300]})
            self.bus.publish("house_brain_fallback", trigger=trigger, what=what, at=now.isoformat(),
                             reason="; ".join(r for rs in refused.values() for r in rs)[:300], muse=meta,
                             routines=sorted(refused), scope="routine")
        self.announce(plan, trigger, now)
        return event

    def count(self, meta):
        self.stats["calls"] += 1
        self.stats["usd"] = round(self.stats["usd"] + meta["usd"], 6)
        self.stats["seconds"].append(meta["seconds"])

    def fallback(self, trigger, what, now, reason, meta):
        self.plan = None
        self.apply(None)
        self.stats["fallbacks"] += 1
        self.stats["fallback_reasons"].append({"at": now.isoformat(), "trigger": trigger, "reason": reason[:300]})
        return self.bus.publish("house_brain_fallback", trigger=trigger, what=what, at=now.isoformat(), reason=reason,
                                muse=meta, routines="fixed")

    def apply(self, plan):
        """Arms the fixed routines with the plan's windows, or puts them back on their own rules (plan None). Only the
        parts in settings "parts" take the plan, the others keep their fixed rule."""
        parts = set(self.s["parts"])
        request = self.asked_to_sleep is not None and self.asking_at is not None \
            and self.asking_at - self.asked_to_sleep < datetime.timedelta(hours=12)
        if "on_duty_on_request" in parts and request:
            parts.add("on_duty")
        take = lambda part, value: value if part in parts else None
        if self.day_engine is not None:
            self.day_engine.plan = None if plan is None else {"floor_clean": take("floor_clean", plan["floor_clean"]),
                                                              "door_quiet": take("door_quiet", plan["door_quiet"])}
        if self.night_feed is not None:
            warm = plan and plan["bottle_prewarm"]
            self.night_feed.plan = None if plan is None else {
                "prewarm": take("bottle_prewarm", None if warm is None else [w["start"] for w in warm]),
                "on_duty": take("on_duty", plan["on_duty"])}

    def announce(self, plan, trigger, now):
        """Tonight's plan at bedtime, the one-sentence why on a re-plan, and the plan's messages to the parents."""
        tz = self.tz
        if trigger == "bedtime":
            parts = [f"Tonight's plan. On duty: {plan['on_duty']}."]
            if plan["bottle_prewarm"]:
                parts.append("Bottle warmer and dim light at " + ", ".join(local_hm(w["start"], tz) for w in plan["bottle_prewarm"]) + ".")
            elif plan["bottle_prewarm"] is None:
                parts.append("Bottle warmer on the fixed rhythm rule, Muse's times did not pass the checks.")
            else:
                parts.append("No bottle pre-warm armed, a cry on the microphone still gets the house ready.")
            for name, label in (("door_quiet", "Door to silent push"), ("floor_clean", "Floor clean window"),
                                ("white_noise_boost", "White noise up")):
                for w in plan[name] or []:
                    parts.append(f"{label} {local_hm(w['start'], tz)} to {local_hm(w['end'], tz)}.")
            if plan["summary"]:
                parts.append(f"Why: {plan['summary']}")
            self.send("\n".join(parts), now, "tonight")
            if plan["why_changed"]:
                self.send(f"Plan changed: {plan['why_changed']}", now, "replan")
        elif trigger == "adapt" and plan["why_changed"]:
            self.send(f"Plan changed: {plan['why_changed']}", now, "replan")
        for m in plan["messages"]:
            self.send(f"For {m['to']}: {m['text']}" if m["to"] != "both" else m["text"], now, "plan_message", to=m["to"])

    def send(self, text, now, what, to="both"):
        if not patterns.no_advice(text):
            self.bus.publish("house_brain_refused", text=text[:200], reason="failed the no-advice guard")
            return None
        event = self.bus.publish("notify", text=text, channel="telegram", source="house-brain", routine=what, to=to,
                                 at=now.isoformat())
        if self.tell is not None and what in self.s["tell"]:
            self.tell(text, now)
        return event

    # White noise boost, run by the brain itself (the device keeps its cap)

    def boost(self, now):
        if self.white_noise is None or "white_noise_boost" not in self.s["parts"]:
            return None
        windows = (self.plan or {}).get("white_noise_boost") or []  # None, the fixed rule, is no boost
        active = next((w for w in windows if w["start"] <= now < w["end"]), None)
        state = self.white_noise.state
        if active and self.boosting is None and state["on"]:
            self.boosting = {"before": state["level"], "until": active["end"]}
            return self.white_noise.level(self.white_noise.max_level, f"Muse plan: {active['why'] or 'boost'}")
        if self.boosting is not None and (now >= self.boosting["until"] or not state["on"]):
            before, self.boosting = self.boosting["before"], None
            if state["on"]:
                return self.white_noise.level(before, "Muse plan: boost window over")
        return None

    # The morning

    def explain(self, now, force=False):
        """What the house did overnight and why: Muse writes it from the house's own events, plain code guards it."""
        day = now.astimezone(self.tz).date()
        if ("explain", day) in self.done and not force:
            return None
        self.done.add(("explain", day))
        since = now - datetime.timedelta(hours=12)
        events = [c for c in (compact(e) for e in self.overnight if (event_time(e) or now) >= since) if c][-80:]
        text, echo, meta, source = fixed_explanation(events), fixed_echo(events), None, "fixed"
        if self.stats["usd"] < self.s["budget_usd"]:
            try:
                answer, meta = self.muse.ask(EXPLAIN_SYSTEM, json.dumps({"now": f"{now.astimezone(self.tz):%a %H:%M}",
                                                                         "events": events}, default=str),
                                             EXPLAIN_SCHEMA, name="explain")
                self.count(meta)
                tg, ec = clean_text(answer.get("telegram"), 600), clean_text(answer.get("echo"), 300)
                if tg and text_ok(tg):
                    text, source = tg, "muse"
                if speaker_ok(ec):
                    echo = ec
            except (BrainError, OSError, ValueError) as error:
                if isinstance(error, MuseAnswerError):
                    self.count(error.meta)
                else:
                    self.stats["calls"] += 1
                self.stats["fallbacks"] += 1
                self.stats["fallback_reasons"].append({"at": now.isoformat(), "trigger": "explain", "reason": str(error)[:200]})
                self.bus.publish("house_brain_fallback", trigger="explain", at=now.isoformat(), reason=str(error)[:200],
                                 routines="fixed explanation")
        self.overnight = []
        event = self.bus.publish("house_explain", at=now.isoformat(), telegram=text, echo=echo, source=source, muse=meta,
                                 events=len(events))
        self.send(text, now, "morning_explain")
        if self.say is not None and speaker_ok(echo):
            self.say(echo, now)
        return event

    # The tick

    def tick(self, entries, now, house=None):
        seen = as_of(entries, now)
        out = []
        due = self.triggers(seen, now)
        adapts = [t for t in due if t[0] == "adapt"]
        planned = [t for t in due if t[0] != "adapt"]
        bedtime = any(t[0] == "bedtime" for t in planned)
        if adapts:
            # A bedtime that comes with something unusual is one call: tonight's plan, with the why.
            out.append(self.ask(seen, now, house, "bedtime" if bedtime else "adapt", "; ".join(t[1] for t in adapts)))
            self.last_call = now
        elif planned:
            trigger, what = planned[0]
            recent = self.last_call is not None and now - self.last_call < datetime.timedelta(minutes=self.s["min_gap_min"])
            if not recent or trigger == "bedtime":
                out.append(self.ask(seen, now, house, trigger, what))
                self.last_call = now
        local = now.astimezone(self.tz)
        explain_at = local.replace(hour=int(self.s["explain_at"][:2]), minute=int(self.s["explain_at"][3:]), second=0,
                                   microsecond=0)
        if explain_at <= local < explain_at + datetime.timedelta(hours=3):
            done = self.explain(now)
            if done:
                out.append(done)
        boosted = self.boost(now)
        if boosted:
            out.append(boosted)
        return out


def event_time(e):
    at = e.get("sim_at") or e.get("at")
    try:
        return parse(at) if at else None
    except (TypeError, ValueError):
        return None


def compact(e):
    """An event as a short line of facts for the morning prompt. Parent free text never goes in."""
    kind = e["kind"]
    at = e.get("sim_at") or e.get("at") or ""
    hm = at[11:16] if len(at) >= 16 else ""
    if kind == "house_plan":
        if not e.get("accepted"):
            return {"at": hm, "what": "Muse plan refused by the checks, fixed routines ran", "trigger": e.get("trigger")}
        p = e.get("plan") or {}
        lists = lambda name, fmt: p[name] if isinstance(p.get(name), str) else [fmt(w) for w in p.get(name) or []]
        return {"at": hm, "what": "Muse plan armed", "trigger": e.get("trigger"), "on_duty": p.get("on_duty"),
                "bottle_prewarm": lists("bottle_prewarm", lambda w: w["start"]),
                "floor_clean": lists("floor_clean", lambda w: f"{w['start']}-{w['end']}"),
                "door_quiet": lists("door_quiet", lambda w: f"{w['start']}-{w['end']}"),
                "white_noise_boost": lists("white_noise_boost", lambda w: f"{w['start']}-{w['end']}"),
                "why": p.get("why_changed") or p.get("summary")}
    if kind == "house_brain_fallback":
        return {"at": hm, "what": "Muse not used, fixed routines ran", "reason": str(e.get("reason"))[:120]}
    if kind == "night_feed":
        keep = {k: e.get(k) for k in ("trigger", "on_duty", "expected", "to", "logged", "feed_at", "minutes") if e.get(k)}
        return {"at": hm, "what": f"night feed {e.get('step')}", **keep}
    if kind == "virtual_device":
        return {"at": hm, "what": f"{e.get('device')} {e.get('action')}", "reason": str(e.get("reason"))[:80]}
    if kind == "house_dry":
        return {"at": hm, "what": f"{e.get('routine')}: {e.get('action')} {e.get('entity') or ''}".strip(),
                "reason": str(e.get("reason"))[:80]}
    if kind == "house_call":
        return {"at": hm, "what": f"{e.get('action')} ({e.get('status')})"}
    if kind == "white_noise":
        return {"at": hm, "what": f"white noise {e.get('action')}", "crib_db": e.get("crib_db")}
    return None


def fixed_explanation(events):
    feeds = sum(1 for e in events if e.get("what") == "night feed prepare")
    warm = sum(1 for e in events if e.get("what", "").startswith("bottle warmer on"))
    plans = sum(1 for e in events if e.get("what") == "Muse plan armed")
    falls = sum(1 for e in events if e.get("what", "").startswith(("Muse not used", "Muse plan refused")))
    s = lambda n: "" if n == 1 else "s"
    return (f"Overnight the house got ready for {feeds} night feed{s(feeds)}, the bottle warmer went on {warm} "
            f"time{s(warm)}. Muse armed {plans} plan{s(plans)}, the fixed routines ran {falls} time{s(falls)} instead.")


def fixed_echo(events):
    feeds = sum(1 for e in events if e.get("what") == "night feed prepare")
    return f"Good morning. The house got ready for {feeds} night feed{'' if feeds == 1 else 's'}."


class HouseBrainPlugin(Plugin):
    """Agent plug-in "parenting_agent.house_brain:HouseBrainPlugin", listed after the day engine and the night feed
    plug-ins it arms. Settings under "house_brain" (DEFAULTS, "muse" overrides the Muse client). Telegram goes only to
    the first chat id in TELEGRAM_CHAT_ID (Gonza), whoever a message is for. The Echo goes through the day engine's
    writer, so it is a dry run while house.live is false."""
    name = "house-brain"

    def __init__(self, agent, config, log=None, clock=None, muse=None):
        super().__init__(agent, config)
        self.rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.s = {**DEFAULTS, "parents": self.rhythm["parents"], "utc_offset_h": self.rhythm["utc_offset_h"],
                  **(config.get("house_brain") or {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.s["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self._log = log
        self.muse = muse or MuseClient(self.s.get("muse"))
        self.brain, self.day = None, None
        self.stopped = threading.Event()
        self.chat = next((c.strip() for c in os.environ.get(self.s.get("chat_ids_env", "TELEGRAM_CHAT_ID"), "").split(",")
                          if c.strip()), None)
        self.spent_day, self.spent_base = None, 0.0

    @property
    def log(self):
        if self._log is None:
            self._log = make_log(self.rhythm, os.environ)
        return self._log

    def wire(self):
        from .night_feed import find_plugin
        self.day = find_plugin(self.agent, "day-engine")
        feed = find_plugin(self.agent, "night-feed")
        engine = getattr(self.day, "engine", None)
        say = None
        if engine is not None:
            from .day_engine import ECHO_ANNOUNCE
            say = lambda text, now: engine.write("house_brain", "notify.send_message", ECHO_ANNOUNCE, {"message": text},
                                                 "Muse's morning explanation", now)
        self.brain = HouseBrain(self.agent.bus, self.muse, self.s, day_engine=engine, night_feed=feed,
                                white_noise=getattr(engine, "white_noise", None), say=say, tell=self.tell)
        return self.brain

    def tell(self, text, now):
        if self.chat:
            self.agent.bus.publish("reply", channel="telegram", chat_id=self.chat, text=text)

    def start(self):
        self.wire()
        threading.Thread(target=self.run, name="house-brain", daemon=True).start()

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.stopped.is_set():
            try:
                now = self.clock()
                today = now.astimezone(self.tz).date()
                if self.spent_day != today:  # the budget is per day
                    self.spent_day, self.spent_base = today, self.brain.stats["usd"]
                self.brain.s["budget_usd"] = self.spent_base + self.s["budget_usd"]
                house = (lambda: self.day.house(now)) if self.day is not None else None
                self.brain.tick(self.log.entries(), now, house)
            except Exception as error:  # a bad read or a bad answer must not stop the agent
                self.agent.bus.publish("house_brain_error", error=str(error)[:300])
            self.stopped.wait(self.s["poll_s"])
