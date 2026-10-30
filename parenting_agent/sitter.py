"""Sitter handover (issue #16): one message briefs a grandparent or a sitter, a time-boxed guest role, a summary after.

When a parent says "my mom is watching him tonight from 19:00 to 23:00", the brain calls sitter_handover. The brief
is built from the baby log and the rhythm, never guessed: the last feed and how much, the next feed expected, the
usual evening sleep, the last diaper, anything unusual today, where things are and how to reach the parents. The
last two come from a short family notes file the parents control (config/family-notes.example.json shows the shape).
Only its "handover" block is read, the rest of the file never reaches the brief or the guest.

The draft goes to the parent first, on the parent's channel. Nothing goes to the sitter on the agent's word:
send_handover_to_sitter is never on the allowed list, so each send waits for the parent's yes, and in this build
there is no sitter adapter at all unless one is passed in (the tests pass a fake).

During the window the sitter is a guest with fewer tools: log a feed, log a diaper, ask for today's totals, read the
handover again, the time. No house actions, no settings, no memory, no private notes. Health questions never reach
the brain: the guest gets a fixed answer pointing to the parents and the pediatrician. When the window ends the
parents get a short summary of what happened.

Add "parenting_agent.sitter:SitterHandover" to the agent config plugins, settings under "sitter":
    {"family_notes": "data/family-notes.json", "parent_channel": "telegram", "poll_s": 30}
The log is read the way the daily rhythm reads it (the "rhythm" block: Baby Buddy or the simulated-week fixture).
"""
import datetime
import json
import os
import re
import threading
from pathlib import Path

from . import cry_reason
from .agent import rules
from .agent.plugins import Plugin
from .agent.tools import Tool, Tools, schema
from .rhythm import patterns
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .rhythm.engine import make_log
from .rhythm.log import ordered, parse, when

EXAMPLE_NOTES = Path(__file__).resolve().parent.parent / "config" / "family-notes.example.json"
DEFAULTS = {"family_notes": "data/family-notes.json", "parent_channel": "telegram", "poll_s": 30}
SEND_TOOL = "send_handover_to_sitter"
GUEST_TOOLS = ("log_feed", "log_diaper", "baby_summary", "handover_brief", "current_time")
PRONOUNS = {"he": ("he", "his", "him"), "she": ("she", "her", "her"), "they": ("they", "their", "them")}
WAKE_NOTE = re.compile(r"wake-up handled by", re.IGNORECASE)
# Stricter than the rhythm's guard for what a sitter reads: no medicine, no doses, no treatment, ever.
DOSAGE_RE = re.compile(r"\b(dose\w*|dosage|mg|medicine\w*|medication\w*|drops|syrup|paracetamol|ibuprofen|acetaminophen|"
                       r"tylenol|antibiotic\w*|treat\w*|cream|ointment|vitamin\w*)\b", re.IGNORECASE)
HEALTH_LINE = ("For anything about {his} health, call us first. If you cannot reach us, call {pediatrician}. "
               "In an emergency call {emergency}.")
GUEST_HEALTH_REPLY = ("I can't help with health questions. Please call the parents now. If you cannot reach them, "
                      "call the pediatrician. In an emergency call {emergency}.")
GUEST_SYSTEM = """You help {sitter}, who is looking after {baby} from {start} to {end}. {sitter} is not a tech user:
answer in one or two short plain sentences.
- Log feeds with log_feed and diapers with log_diaper, then confirm in a few words.
- Answer simple questions from baby_summary or handover_brief. Never guess times or amounts.
- Never give medical advice, a diagnosis, a dose or a treatment. For anything about health, say to call the parents,
  then the pediatrician.
- You cannot change settings, act on the house or read anything beyond the handover.
"""


def safe_line(text):
    """True when a line has no advice, no health judgment and nothing about medicine or doses."""
    return patterns.no_advice(text) and cry_reason.no_medical(text) and DOSAGE_RE.search(text) is None


def _hm(minutes):
    h, m = divmod(round(minutes), 60)
    if not h:
        return f"{m} min"
    return f"{h} h" if not m else f"{h} h {m:02d} min"


def load_notes(path):
    """The family notes file's handover block only. No path: the example with placeholders (tests, the demo). A path
    that does not exist yet: no placeholders at all, so a real brief never shows a made-up phone number."""
    if path and not Path(os.path.expanduser(path)).exists():
        return {"baby_name": "Theo", "pronoun": "he", "where": [], "contacts": [], "pediatrician": {}, "emergency": "911"}
    path = Path(os.path.expanduser(path)) if path else EXAMPLE_NOTES
    data = json.loads(path.read_text())
    handover = data.get("handover") or {}
    return {"baby_name": data.get("baby_name") or "the baby", "pronoun": data.get("pronoun") or "he",
            "where": list(handover.get("where_things_are") or []), "contacts": list(handover.get("contacts") or []),
            "pediatrician": handover.get("pediatrician") or {}, "emergency": handover.get("emergency") or "911"}


def resolve_window(start, end, now, tz):
    """Start and end as aware datetimes. "19:00" means today in the family's time zone, an end before the start is the next day."""
    def at(value):
        value = str(value).strip()
        if re.fullmatch(r"\d{1,2}[:.]\d{2}", value):
            h, m = (int(x) for x in re.split(r"[:.]", value))
            return now.astimezone(tz).replace(hour=h, minute=m, second=0, microsecond=0)
        moment = parse(value)
        return moment if moment.tzinfo else moment.replace(tzinfo=tz)
    a, b = at(start), at(end)
    if b <= a:
        b += datetime.timedelta(days=1)
    return a, b


def _feed_words(e):
    method, amount = (e.get("method") or "").lower(), e.get("amount")
    minutes = round((parse(e["end"]) - parse(e["start"])).total_seconds() / 60) if e.get("end") else None
    if "breast" in method and "bottle" not in method:
        side = {"left breast": "left side", "right breast": "right side", "both breasts": "both sides"}.get(method, "")
        words = "breastfed" + (f" ({side})" if side else "") + (f", {minutes} min" if minutes else "")
    else:
        milk = "breast milk" if (e.get("type") or "") == "breast milk" else "formula"
        words = f"bottle of {milk}" + (f", {amount:g} ml" if amount else "")
    return words


def usual_evening_sleep(entries, start, end, tz):
    """Median start of the first sleep that began inside the window's hours on earlier days, and its usual length."""
    first = {}
    s_min = start.astimezone(tz).hour * 60 + start.astimezone(tz).minute
    span = (end - start).total_seconds() / 60
    today = start.astimezone(tz).date()
    for e in ordered(entries):
        if e["kind"] != "sleep" or not e.get("end"):
            continue
        t = when(e).astimezone(tz)
        offset = (t.hour * 60 + t.minute - s_min) % (24 * 60)
        day = (t - datetime.timedelta(minutes=offset)).date()
        if offset < span and day < today and day not in first:
            first[day] = (offset, (parse(e["end"]) - parse(e["start"])).total_seconds() / 60)
    if len(first) < 3:
        return None
    offsets = sorted(o for o, _ in first.values())
    lengths = sorted(length for _, length in first.values())
    mid = len(offsets) // 2
    at = start.astimezone(tz) + datetime.timedelta(minutes=offsets[mid])
    return {"at": at, "length_min": lengths[mid], "days": len(first)}


def facts(entries, now, start, end, tz):
    """Everything the brief says, computed from the log up to now. Each fact carries the entries it came from."""
    past = ordered(entries, now)
    local = now.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    feeds = [e for e in past if e["kind"] == "feeding"]
    changes = [e for e in past if e["kind"] == "change"]
    today_feeds = [e for e in feeds if when(e) >= midnight]
    out = {"now": local, "refs": []}
    if feeds:
        last = feeds[-1]
        out["last_feed"] = {"at": when(last).astimezone(tz), "words": _feed_words(last), "amount_ml": last.get("amount"),
                            "method": last.get("method")}
        out["refs"].append(last["ref"])
    out["today"] = {"feeds": len(today_feeds), "bottle_ml": round(sum(float(e.get("amount") or 0) for e in today_feeds))}
    nxt = patterns.next_feed(past, now)
    if nxt:
        out["next_feed"] = {"at": nxt["at"].astimezone(tz), "gap_min": nxt["gap_min"]}
        out["refs"] += nxt["computed_from"]
    if changes:
        last = changes[-1]
        kind = "wet and dirty" if last.get("wet") and last.get("solid") else "dirty" if last.get("solid") else "wet"
        out["last_diaper"] = {"at": when(last).astimezone(tz), "kind": kind}
        dirty = [c for c in changes if c.get("solid")]
        if dirty:
            out["last_dirty"] = when(dirty[-1]).astimezone(tz)
        out["refs"].append(last["ref"])
    asleep = [e for e in past if e["kind"] == "sleep" and (not e.get("end") or parse(e["end"]) > now)]
    if asleep:
        out["asleep_since"] = when(asleep[-1]).astimezone(tz)
    evening = usual_evening_sleep(past, start, end, tz)
    if evening:
        out["usual_sleep"] = evening
    notes = [e for e in past if e["kind"] == "note" and when(e) >= midnight and not WAKE_NOTE.search(e.get("note") or "")]
    out["today_notes"] = [(when(e).astimezone(tz), (e.get("note") or "").replace("[simulated]", "").strip()) for e in notes]
    yesterday = (local - datetime.timedelta(days=1)).date()
    out["unusual"] = [n["text"] for n in patterns.unusual_notes(past, tz) if n["day"] == yesterday]
    return out


def _feed_words_es(last):
    """The last feed in Spanish, from the facts' last_feed (method, amount and the English words)."""
    method, amount = (last.get("method") or "").lower(), last.get("amount_ml")
    if "breast" in method and "bottle" not in method:
        side = {"left breast": "lado izquierdo", "right breast": "lado derecho", "both breasts": "los dos lados"}.get(method, "")
        return "teta" + (f" ({side})" if side else "")
    milk = "leche materna" if "breast milk" in (last.get("words") or "") else "fórmula"
    return f"mamadera de {milk}" + (f", {amount:g} ml" if amount else "")


def brief_es(f, sitter, start, end, notes):
    """The same handover in Spanish (Uruguay), from the same facts."""
    name, hhmm, dropped = notes["baby_name"], patterns.hhmm, []

    def keep(lines, text):
        if safe_line(text):
            lines.append("- " + text)
        else:
            dropped.append(text)

    food, sleep, diapers, where, reach = [], [], [], [], []
    if "last_feed" in f:
        keep(food, f"Última toma a las {hhmm(f['last_feed']['at'])}, {_feed_words_es(f['last_feed'])}.")
    else:
        keep(food, "Todavía no hay tomas anotadas hoy.")
    if "next_feed" in f:
        keep(food, f"La próxima toma se espera cerca de las {hhmm(f['next_feed']['at'])}. Viene comiendo cada "
                   f"{_hm(f['next_feed']['gap_min'])} más o menos.")
    keep(food, f"Hoy van {f['today']['feeds']} tomas" + (f", {f['today']['bottle_ml']} ml de mamadera."
                                                         if f["today"]["bottle_ml"] else "."))
    if "asleep_since" in f:
        keep(sleep, f"Está dormido desde las {hhmm(f['asleep_since'])}.")
    if "last_diaper" in f:
        kind = {"wet and dirty": "mojado y con caca", "dirty": "con caca", "wet": "mojado"}[f["last_diaper"]["kind"]]
        keep(diapers, f"Último pañal a las {hhmm(f['last_diaper']['at'])}, {kind}.")
    for line in notes["where"]:
        keep(where, line.rstrip(".") + ".")
    for c in notes["contacts"]:
        keep(reach, f"{c.get('name', 'Padres')}: {c.get('phone', 'sin número')}.")
    ped = notes["pediatrician"]
    pediatra = f"a {ped.get('name') or 'la pediatra'} al {ped['phone']}" if ped.get("phone") else "a la pediatra"
    parts = [f"Hola {sitter}, gracias por cuidar a {name} de {hhmm(start)} a {hhmm(end)}."]
    for title, lines in (("Comida", food), ("Sueño", sleep), ("Pañales", diapers), ("Dónde están las cosas", where),
                         ("Cómo ubicarnos", reach)):
        if lines:
            parts.append(title + "\n" + "\n".join(lines))
    parts.append("Salud\n- Por cualquier cosa de su salud, llamanos primero. Si no nos ubicás, llamá " + pediatra
                 + f". En una emergencia llamá al {notes['emergency']}.")
    return {"text": "\n\n".join(parts), "dropped": dropped, "facts": f, "computed_from": f["refs"]}


def brief(entries, now, sitter, start, end, tz, notes, lang="en"):
    """The handover text and what was left out. Lines that fail safe_line are dropped and reported to the parent."""
    if lang == "es":
        return brief_es(facts(entries, now, start, end, tz), sitter, start, end, notes)
    he, his, him = PRONOUNS.get(notes["pronoun"], PRONOUNS["he"])
    f = facts(entries, now, start, end, tz)
    name, hhmm = notes["baby_name"], patterns.hhmm
    dropped = []

    def keep(lines, text):
        if safe_line(text):
            lines.append("- " + text)
        else:
            dropped.append(text)

    food, sleep, diapers, today, where, reach = [], [], [], [], [], []
    if "last_feed" in f:
        keep(food, f"Last feed at {hhmm(f['last_feed']['at'])}, {f['last_feed']['words']}.")
    else:
        keep(food, "No feed in the log yet today.")
    if "next_feed" in f:
        keep(food, f"Next feed expected around {hhmm(f['next_feed']['at'])}. {he.capitalize()} has been eating about "
                   f"every {_hm(f['next_feed']['gap_min'])}.")
    keep(food, f"Today so far: {f['today']['feeds']} feeds" + (f", {f['today']['bottle_ml']} ml from bottles."
                                                                if f["today"]["bottle_ml"] else "."))
    if "asleep_since" in f:
        keep(sleep, f"{he.capitalize()} has been asleep since {hhmm(f['asleep_since'])}.")
    if "usual_sleep" in f:
        keep(sleep, f"In the evening {he} usually falls asleep around {hhmm(f['usual_sleep']['at'])} and sleeps about "
                    f"{_hm(f['usual_sleep']['length_min'])}.")
    if "last_diaper" in f:
        text = f"Last diaper at {hhmm(f['last_diaper']['at'])}, {f['last_diaper']['kind']}."
        if "last_dirty" in f and f["last_diaper"]["kind"] == "wet":
            text += f" Last dirty one at {hhmm(f['last_dirty'])}."
        keep(diapers, text)
    for at, note in f["today_notes"]:
        keep(today, f"{note} at {hhmm(at)}.")
    for note in f["unusual"]:
        keep(today, "Yesterday, " + note.split(": ", 1)[-1])
    for line in notes["where"]:
        keep(where, line.rstrip(".") + ".")
    for c in notes["contacts"]:
        keep(reach, f"{c.get('name', 'Parent')}: {c.get('phone', 'number missing')}.")
    ped = notes["pediatrician"]
    pediatrician = f"{ped.get('name') or 'the pediatrician'} on {ped['phone']}" if ped.get("phone") else "the pediatrician"
    parts = [f"Hi {sitter}, thank you for looking after {name} from {hhmm(start)} to {hhmm(end)}."]
    for title, lines in (("Food", food), ("Sleep", sleep), ("Diapers", diapers), ("Today", today),
                         ("Where things are", where), ("How to reach us", reach)):
        if lines:
            parts.append(title + "\n" + "\n".join(lines))
    parts.append("Health\n- " + HEALTH_LINE.format(his=his, pediatrician=pediatrician, emergency=notes["emergency"]))
    return {"text": "\n\n".join(parts), "dropped": dropped, "facts": f, "computed_from": f["refs"]}


class GuestTools(Tools):
    """The guest's tools. Anything else is refused outright, never queued for a yes the guest could give."""

    def run(self, name, arguments):
        if name not in GUEST_TOOLS or name not in self.items:
            return "denied", f"{name} is not available to a guest"
        return super().run(name, arguments)


class GuestSession:
    """A time-boxed guest role for one sitter, from start to end. Records what happened for the parents' summary."""

    def __init__(self, bus, baby_log, brain, sitter, start, end, brief_text, emergency="911", baby="the baby", clock=None,
                 max_steps=4):
        self.bus, self.baby_log, self.brain, self.sitter = bus, baby_log, brain, sitter
        self.start, self.end, self.brief_text, self.emergency, self.baby = start, end, brief_text, emergency, baby
        self.clock = clock or (lambda: datetime.datetime.now(start.tzinfo))
        self.max_steps = max_steps
        self.logged, self.questions, self.health_questions, self.denied = [], 0, [], []
        self.closed = False
        self.tools = self._tools()

    def active(self, now=None):
        now = now or self.clock()
        return not self.closed and self.start <= now < self.end

    def _check(self):
        if not self.active():
            raise RuntimeError("the handover window is not open")

    def _log(self, kind, details):
        self._check()
        entry = self.baby_log.add(kind, details)
        self.logged.append({"kind": kind, "details": details})
        self.bus.publish("guest_logged", sitter=self.sitter, kind=kind)
        return entry

    def _feed(self, amount_ml=None, method="bottle", type="formula"):
        details = {"method": method, "type": type}
        if amount_ml is not None:
            details["amount_ml"] = float(amount_ml)
        return self._log("feeding", details)

    def _diaper(self, wet=True, solid=False):
        return self._log("diaper", {"wet": bool(wet), "solid": bool(solid)})

    def _tools(self):
        tools = GuestTools(GUEST_TOOLS)
        tools.add(Tool("log_feed", "Log a feed the sitter gave. amount_ml for a bottle, method bottle, left breast, right "
                       "breast or both breasts, type formula or breast milk.",
                       schema({"amount_ml": {"type": "number"}, "method": {"type": "string"}, "type": {"type": "string"}}),
                       self._feed))
        tools.add(Tool("log_diaper", "Log a diaper change. wet true or false, solid true for a dirty diaper.",
                       schema({"wet": {"type": "boolean"}, "solid": {"type": "boolean"}}), self._diaper))
        tools.add(Tool("baby_summary", "Today's totals and last times from the baby log: feeds, diapers, sleep.", schema({}),
                       lambda: (self._check(), self.baby_log.summary())[1]))
        tools.add(Tool("handover_brief", "The handover the parents approved: feeds, sleep, where things are, how to reach them.",
                       schema({}), lambda: (self._check(), self.brief_text)[1]))
        tools.add(Tool("current_time", "The current local time.", schema({}),
                       lambda: self.clock().isoformat(timespec="minutes")))
        return tools

    def ask(self, text):
        """The guest's message, answered from the guest tools only. Returns the reply text."""
        self.bus.publish("guest_message", sitter=self.sitter, chars=len(text))
        if not self.active():
            return self._reply("The handover time has ended. Please ask the parents directly.")
        self.questions += 1
        if rules.is_medical(text) or not cry_reason.no_medical(text):
            self.health_questions.append(text)
            self.bus.publish("guest_health_question", sitter=self.sitter)
            return self._reply(GUEST_HEALTH_REPLY.format(emergency=self.emergency))
        system = GUEST_SYSTEM.format(sitter=self.sitter, baby=self.baby, start=patterns.hhmm(self.start),
                                     end=patterns.hhmm(self.end))
        transcript = [{"role": "user", "text": text}]
        for _ in range(self.max_steps):
            reply = self.brain.step(system, transcript, self.tools.specs())
            if not reply.tool_calls:
                return self._reply(reply.text or "OK.")
            transcript.append({"role": "assistant", "text": reply.text, "tool_calls": reply.tool_calls})
            for call in reply.tool_calls:
                status, result = self.tools.run(call["name"], call["arguments"])
                if status == "denied":
                    self.denied.append(call["name"])
                    self.bus.publish("guest_denied", sitter=self.sitter, name=call["name"])
                self.bus.publish("tool", name=call["name"], status=status, guest=True)
                transcript.append({"role": "tool", "id": call["id"], "name": call["name"], "result": result})
        return self._reply("Sorry, I could not do that. Please ask the parents.")

    def _reply(self, text):
        self.bus.publish("guest_reply", sitter=self.sitter, text=text)
        return text

    def summary(self):
        feeds = [e for e in self.logged if e["kind"] == "feeding"]
        diapers = [e for e in self.logged if e["kind"] == "diaper"]
        ml = round(sum(e["details"].get("amount_ml") or 0 for e in feeds))
        wet = sum(1 for d in diapers if d["details"]["wet"] and not d["details"]["solid"])
        dirty = sum(1 for d in diapers if d["details"]["solid"])
        span = f"{patterns.hhmm(self.start)} to {patterns.hhmm(self.end)}"
        parts = [f"{self.sitter} looked after {self.baby} from {span}."]
        feed_text = f"{len(feeds)} feed{'s' if len(feeds) != 1 else ''}" + (f" ({ml} ml)" if ml else "")
        parts.append(f"Logged: {feed_text}, {len(diapers)} diaper{'s' if len(diapers) != 1 else ''}"
                     + (f" ({wet} wet, {dirty} dirty)" if diapers else "") + ".")
        seen = self.window_log()
        if seen is not None and (seen["feeds"] > len(feeds) or seen["diapers"] > len(diapers)):
            parts.append(f"The log for those hours, whoever wrote it: {seen['feeds']} feed{'s' if seen['feeds'] != 1 else ''}"
                         + (f" ({seen['ml']} ml)" if seen["ml"] else "")
                         + f", {seen['diapers']} diaper{'s' if seen['diapers'] != 1 else ''}.")
        parts.append(f"{self.sitter} asked {self.questions} question{'s' if self.questions != 1 else ''}.")
        if self.health_questions:
            quoted = ", ".join(f'"{q[:80]}"' for q in self.health_questions)
            parts.append(f"Health questions, I told {self.sitter} to call you: {quoted}.")
        if self.denied:
            parts.append(f"Refused for the guest: {', '.join(sorted(set(self.denied)))}.")
        return " ".join(parts)

    def window_log(self):
        """What the log holds for the window, whoever wrote it: the sitter here, a parent in the family chat."""
        try:
            rows = self.baby_log.entries(since=self.start.isoformat(timespec="seconds"), limit=100)
        except Exception:  # noqa: BLE001 a log that cannot be read leaves the summary to what the guest logged
            return None
        rows = [r for r in rows if parse(r["ts"]) <= self.end]
        feeds = [r for r in rows if r["kind"] == "feeding"]
        diapers = [r for r in rows if r["kind"] == "diaper"]
        ml = round(sum(float(r["details"].get("amount_ml") or 0) for r in feeds))
        return {"feeds": len(feeds), "ml": ml, "diapers": len(diapers)}

    def summary_es(self):
        span = f"{patterns.hhmm(self.start)} a {patterns.hhmm(self.end)}"
        seen = self.window_log()
        parts = [f"{self.sitter} cuidó a {self.baby} de {span}."]
        if seen is not None:
            parts.append(f"En el registro de esas horas: {seen['feeds']} toma{'s' if seen['feeds'] != 1 else ''}"
                         + (f" ({seen['ml']} ml)" if seen["ml"] else "")
                         + f", {seen['diapers']} pañal{'es' if seen['diapers'] != 1 else ''}.")
        if self.logged:
            parts.append(f"{self.sitter} anotó {len(self.logged)} por acá.")
        if self.health_questions:
            parts.append(f"Preguntó {len(self.health_questions)} cosa(s) de salud: le dije que los llame a ustedes.")
        return " ".join(parts)

    def close(self):
        self.closed = True
        text = self.summary()
        self.bus.publish("sitter_summary", sitter=self.sitter, text=text, logged=len(self.logged),
                         questions=self.questions, health_questions=len(self.health_questions))
        return text


class SitterHandover(Plugin):
    """Agent plug-in. Adds sitter_handover (allowed) and send_handover_to_sitter (always waits for the parent's yes)."""
    name = "sitter"

    def __init__(self, agent, config, log=None, clock=None, sitter_messenger=None, contacts=None):
        super().__init__(agent, config)
        self.cfg = {**DEFAULTS, **config.get("sitter", {})}
        people = getattr(agent, "people", None)
        self.lang = self.cfg.get("lang") or (people.family_lang() if people is not None else None) or "en"
        self.rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self._log = log
        # No real sitter adapter exists in this build. Tests pass a fake one with the sitter's chat id.
        self.sitter_messenger, self.contacts = sitter_messenger, dict(contacts or {})
        self.draft, self.session = None, None
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = None
        if SEND_TOOL in agent.tools.allowed:
            agent.tools.allowed.discard(SEND_TOOL)
            agent.bus.publish("sitter_warning", error=f"{SEND_TOOL} removed from the allowed list, it always waits for a yes")
        agent.tools.add(Tool(
            "sitter_handover", "When a parent says someone (a grandparent, a sitter) will look after the baby, write the "
            "handover for them from the log and the family notes. sitter is how the parent named them (Grandma, Ana), "
            "start and end are HH:MM or ISO times. The draft goes to the parent to check, never to the sitter.",
            schema({"sitter": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}},
                   ["sitter", "start", "end"]), self.prepare))
        agent.tools.add(Tool(
            SEND_TOOL, "Send the approved handover to the sitter. Only when the parent asks to send it. The parent is "
            "asked for a yes every time before it runs.", schema({}), self.send_to_sitter))

    @property
    def log(self):
        if self._log is None:
            self._log = make_log(self.rhythm, os.environ)
        return self._log

    def notes(self):
        return load_notes(self.cfg["family_notes"])

    def prepare(self, sitter, start, end):
        """Builds the draft, opens the guest window, sends the draft to the parent. Returns a short result for the brain."""
        now = self.clock()
        sitter = sitter.strip()
        sitter = sitter[:1].upper() + sitter[1:]  # a name in the brief, "Mom" or "Ana", however the brain wrote it
        a, b = resolve_window(start, end, now, self.tz)
        if b <= now:
            raise ValueError("that time window has already ended")
        notes = self.notes()
        made = brief(self.log.entries(), now, sitter, a, b, self.tz, notes, self.lang)
        asked_by = (getattr(self.agent, "current_event", None) or {}).get("person")
        with self.lock:
            self.draft = {"sitter": sitter, "start": a, "end": b, "asked_by": asked_by, **made}
            self.session = GuestSession(self.agent.bus, self.agent.baby_log, self.agent.brain, sitter, a, b, made["text"],
                                        notes["emergency"], notes["baby_name"], self.clock)
        if self.lang == "es":
            header = (f"Borrador del resumen para {sitter}, de {patterns.hhmm(a)} a {patterns.hhmm(b)}. No le mando "
                      f"nada a {sitter} si no me decís. Reenviáselo vos.")
            if made["dropped"]:
                header += f" Dejé afuera {len(made['dropped'])} línea(s) sobre salud o remedios: contáselo vos."
        else:
            header = (f"Draft handover for {sitter}, {patterns.hhmm(a)} to {patterns.hhmm(b)}. Nothing goes to {sitter} "
                      f"unless you say so.")
            if made["dropped"]:
                header += f" I left out {len(made['dropped'])} line(s) from the family notes about health or medicine, tell {sitter} yourself."
        self.agent.say(self.cfg["parent_channel"], header + "\n\n" + made["text"])
        self.agent.bus.publish("sitter_draft", sitter=sitter, start=a.isoformat(), end=b.isoformat(),
                               computed_from=made["computed_from"], dropped=len(made["dropped"]))
        return (f"Draft sent to the parent to check. Nothing was sent to {sitter}. The guest window is "
                f"{patterns.hhmm(a)} to {patterns.hhmm(b)}.")

    def send_to_sitter(self):
        """Runs only after the parent's yes (the tool is never on the allowed list). One send per yes.

        It returns a sentence instead of raising, because the agent runs approved tools outside its error handling.
        """
        with self.lock:
            draft = self.draft
        if draft is None:
            return "There is no handover draft yet."
        chat = self.contacts.get(draft["sitter"])
        if self.sitter_messenger is None or chat is None:
            self.agent.bus.publish("sitter_not_sent", sitter=draft["sitter"], reason="no sitter adapter in this build")
            return f"Sending to {draft['sitter']} is not switched on yet. Please forward the draft yourself."
        sent = self.sitter_messenger.send(chat, draft["text"])
        self.agent.bus.publish("sitter_sent", sitter=draft["sitter"], message_id=sent)
        return f"Sent to {draft['sitter']}."

    def start(self):
        self.thread = threading.Thread(target=self.run, name="sitter", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.tick(self.clock())
            except Exception as error:  # a bad tick must not stop the agent
                self.agent.bus.publish("sitter_error", error=str(error)[:300])
            self.stopped.wait(self.cfg["poll_s"])

    def tick(self, now):
        """Closes the window once it ends and tells the parents what happened. Returns the summary, or None."""
        with self.lock:
            session = self.session
            if session is None or session.closed or now < session.end:
                return None
            text = session.close()
        asked_by = (self.draft or {}).get("asked_by")
        if any(getattr(p, "name", "") == "family-push" for p in getattr(self.agent, "plugins", [])):
            texts = {"en": text, "es": session.summary_es()}
            self.agent.bus.publish("notify", text=text, texts=texts, source="sitter", routine="sitter_summary",
                                   **({"person": asked_by} if asked_by else {}))
        else:
            self.agent.say(self.cfg["parent_channel"], text)
        return text

    def stop(self):
        self.stopped.set()
