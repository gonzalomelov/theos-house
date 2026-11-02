"""Muse decides the log: one call reads the message, the log and the conversation and returns the log operations.

The guards in loop.py decided what the parent "said" from word lists and could throw away Muse's right values or miss
new phrasings (issue #77, four blind sets of 45 scored 8, 8, 5 and 11 wrong log states). Here the brain sees what a
careful parent sees, the log as it stands with ids, the open sleep, the last messages with their times, and returns
the operations as data. The agent only does what code is sure about: it turns ounces into ml at 30 ml an ounce, puts
a clock time on the latest such moment that is not in the future, refuses a value no real entry can have, and builds
the confirmation from the log diff. With verify on, a second call checks the proposed operations against the message
and the log and can keep them, correct them or drop them.
"""
import datetime
import json
import re

from . import brain as brain_mod
from . import rules
from .memory import parse_time

LOG_HOURS = 30
HISTORY = 12
HHMM = re.compile(r"^\s*(\d{1,2})[:.h](\d{2})\s*$")
EDIT_FIELDS = ("amount_ml", "amount_oz", "method", "type", "duration_min", "wet", "solid", "color", "text", "start", "end",
               "at")
COLORS = {"yellow": "yellow", "green": "green", "brown": "brown", "black": "black", "amarillo": "yellow",
          "amarilla": "yellow", "mostaza": "yellow", "verde": "green", "marron": "brown", "marrón": "brown",
          "negro": "black", "negra": "black", "mustard": "yellow"}
KINDS = ("feeding", "diaper", "sleep", "bath", "note")
LANG_NAMES = {"es": "Rioplatense Spanish with voseo (Uruguay: mamadera, never biberón)", "en": "English"}

OPS_SYSTEM = """You keep a baby's log for tired parents on a chat. Each turn you get the log as it stands, the open
sleep, the last messages with their times and the parent's newest message. You decide what the newest message changes
in the log and you call log_ops exactly once with the operations and a short reply.

Operations (an empty list when the message changes nothing):
- {"op": "add", "kind": "feeding", "method": "bottle" | "left breast" | "right breast" | "both breasts" | "breast",
   "amount_ml": n or "amount_oz": n, "type": "formula" | "breast milk", "duration_min": n, "at": "HH:MM"}
- {"op": "add", "kind": "diaper", "wet": true|false, "solid": true|false, "color": "yellow" | "green" | "brown" |
   "black", "at": "HH:MM"}
- {"op": "add", "kind": "bath", "text": "...", "at": "HH:MM"}
- {"op": "add", "kind": "note", "text": "the parent's words", "at": "HH:MM"}
- {"op": "sleep_start", "at": "HH:MM"} when the baby fell asleep and is still asleep
- {"op": "sleep_end", "at": "HH:MM"} when the baby woke up and a sleep is open, it closes that sleep
- {"op": "add", "kind": "sleep", "start": "HH:MM", "end": "HH:MM"} for a sleep that is already over and was not open
- {"op": "edit", "id": n, "kind": the entry's kind as the log shows it, plus only the fields that change: amount_ml or
   amount_oz, method, type, duration_min, wet, solid, color, text, at (the entry's new clock time), start (a sleep's
   start), end (a sleep's end)}
- {"op": "delete", "id": n, "kind": the entry's kind}
- The open sleep, when there is one, has the id "open-sleep": {"op": "edit", "id": "open-sleep", "start": "HH:MM"}
  moves its start, {"op": "delete", "id": "open-sleep"} removes a sleep that never happened.

How to read the parent:
- Log only what the newest message says. Earlier messages were already handled and their entries are in the log.
- Never add a detail the parent did not say: no milk type, no side, no duration when not said. A bottle with no milk
  type named leaves type out. A breast feed is "breast" when no side was said.
- Keep every detail the parent did say, the log is all they have: the amount (also in words, "cien", "noventa",
  "sesenta y cinco"), the side, the minutes, the milk type, the stool colour. Expressed milk in a bottle is "breast
  milk": "leche materna", "la leche que me saqué", "leche de Ceci de la heladera", "pumped", "expressed", "breast milk".
  Formula is "formula": "fórmula", "leche de fórmula", "formula". A stool colour goes in color: amarilla, mostaza,
  amarillenta, "mustard" and "yellow" are yellow, verde, verdosa and "green" are green, marrón and "brown" are brown,
  negra and "black" are black. No colour said, no color.
- Amounts: give what the baby took. "prepare 120 y tomo la mitad" is 60, "prepare 110 y sobraron 20" is 90. Ounces go
  in amount_oz as said ("3 onzas y media" is amount_oz 3.5), the agent turns them into ml.
- Times: "at" is the clock time the parent named for the event, 24 hour HH:MM, the latest such time that is not after
  the newest message ("a las 12 y 40" sent at 00:50 is 00:40, "a la una menos diez" is 00:50 at night, "noon" is
  12:00). Leave "at" out when no time was named: the agent uses the message's time. For a feed with a start and an end
  time, "at" is the start and duration_min the minutes between them. For a breast feed on both sides, add the minutes.
- Only what happened is logged. A plan or something about to happen ("ahora le voy a dar 90", "le va a dar la teta",
  "about to give him a bottle", "going to feed him") changes nothing: answer in one short line and log it when the
  parent says it happened.
- A sleep: "se durmio" is sleep_start. "se desperto", "arriba", "woke up" is sleep_end at the time named, or leave "at"
  out for now. "hace 10 min q esta despierta" is the end 10 minutes before the message. A nap told after it ended,
  with no open sleep ("durmio 40 min, recien se desperto"), is an added sleep with its start and end. If a sleep is
  already open, a repeated "se durmio" changes nothing, and so does "sigue dormido", "still asleep" or "se movió pero
  sigue durmiendo": nothing changed. "Se despertó llorando" and "woke up crying" are a wake-up, sleep_end. A message
  that tells a sequence is every step in order: "se despertó a las 14 y a las 14:20 se volvió a dormir" is sleep_end
  at 14:00 then sleep_start at 14:20, "se durmió a las 10, se despertó 10:40 y ahora se volvió a dormir" with no open
  sleep is an added sleep from 10:00 to 10:40 then sleep_start now, "le di 60 y ahora se durmió" is the feed then
  sleep_start now, "durmió de 16:15 a 17:30" is an added sleep with exactly that start and end. A wake-up with no open
  sleep and no start said changes nothing: ask when the baby fell asleep.
- A short follow-up that adds or fixes a detail of the entry just logged ("y era formula", "como 14 min", "y pis
  tambien", "ah y tenía caca tb", "eran 4 onzas, no 3", "no perdón eran 60", "no, fue a las 9 y media", "era el
  izquierdo", "no era verde era amarilla", "era leche de Ceci no fórmula", "it was 90") is an edit of that entry, never
  a new entry. A correction of an earlier entry is an edit of it, found by its time and kind in the log ("el de las 4
  fueron 20 min no 10", "the 10pm one was left side", "el pañal de las 10 tenía caca también"). A wrong kind ("no era
  una toma, era un pañal con caca", "no se durmió, quise poner que tomó teta") is a delete of that entry and an add of
  the right one. "Borrá eso", "borrá la última", "delete the last one", "lo mandé sin querer", "al final no lo bañamos"
  is a delete of the entry the parent means, only that one ("borrá el último pañal" deletes the newest diaper). Never
  answer that the log cannot be changed: it can.
- The same report again a few minutes after it was logged (the same text, or the same feed with the same amount or
  minutes, also from the other parent: "Gonza le cambió el pañal, pis y caca" after "le cambié el pañal, tenía pis y
  caca") is usually one message sent twice or one event told by both parents: change nothing and ask in the reply
  whether it was sent twice or there were two. When the parent says the log holds one event twice ("lo mandé dos
  veces, es uno solo"), delete the newer copy. If the parent then says there were two, add the second at the time of the repeated message. If the parent
  says it was one, change nothing. Delete only when the parent asks to delete or the log really holds the entry twice.
- Notes are for something to keep: a symptom, a medicine given, a milestone, a vaccine, or whatever the parent asks to
  write down ("anota ..."). A moment shared, a mood, the weather or a chat with you is answered warmly and logged as
  nothing. A diaper the parent says was dry or not changed is nothing. A symptom told with a feed ("tomo 70 y vomito
  un poco") is two operations: the feed with what the baby took, and a note with the parent's words.
- A total or summary over a period ("solo tomo 20 ml desde la mañana", "300 ml en total hoy") is no new entry: change
  nothing and ask in the reply whether a feed is missing.
- A question is answered from the log and the numbers given, logged as nothing. For when the next feed is, answer with
  the rhythm line given.
- Never give medical advice, a diagnosis or a dose. Set "health": true when the newest message asks anything about
  the baby's health or body: whether a symptom, a colour, a poop, a sneeze or a behaviour is normal or ok, what it
  could be, what to do about it, a medicine, a dose, a tea or a remedy. The agent then answers that part with its own
  fixed line, so leave the reply empty. What the message reports is still logged.

The reply: one or two short plain sentences in {language}, with commas and periods, never an em dash. When there are operations, the agent itself confirms what
the log now holds, so your reply is only used for a question or the double-send question. When there are no
operations, never say you logged, saved, changed, corrected or deleted anything.
"""

# The log's own tools, and remember (a baby's name), which the families bot has too. Any other tool the agent has (a
# reminder, the shopping list, the house) is the guarded loop's: a message that asks for one is handed off whole.
LOG_TOOLS = {"log_baby_event", "edit_baby_event", "delete_baby_event", "read_baby_log", "baby_summary", "current_time",
             "next_feed", "remember"}
HANDOFF = """
This assistant can also do other things, with tools that are not yours: {tools}. When the newest message asks for any
of them (a reminder, a list, an appointment, the house, the night rota, a fact to remember, the prep checklist, a
sitter handover), call log_ops with ops [{{"op": "handoff"}}] and an empty reply: the message then goes, whole, to the
assistant that runs those tools, and it also logs what the message reports. Never hand off a message that only logs,
corrects the log or asks about the log.
"""

LANG_RETRY = ("Your last reply was not in {language}. Call log_ops exactly once now with the same operations and the reply "
              "in {language}.")

RETRY = "Your last answer had no log_ops call. Call log_ops exactly once now, with the operations and the reply."

VERIFY_SYSTEM = """You check a baby log assistant's work before it is saved. You get the log as it stands, the open
sleep, the last messages with their times, the parent's newest message and the operations the assistant proposed.
Operations follow the same rules as the assistant's:
""" + OPS_SYSTEM.split("Operations (an empty list when the message changes nothing):", 1)[1].split("The reply:", 1)[0] + """
Check every operation against the newest message and the log: right kind, right entry for an edit or delete, every
value the parent said and nothing they did not say, the time, and no operation missing or extra. Call verdict exactly
once: ok true when the proposal is right, or ok false with the full corrected list of operations (an empty list when
the message should change nothing) and one short reason.
"""

OPS_TOOL = {"name": "log_ops", "description": "The log operations for the parent's newest message and a short reply.",
            "parameters": {"type": "object", "properties": {
                "ops": {"type": "array", "items": {"type": "object"}, "description": "operations, empty when nothing changes"},
                "reply": {"type": "string"},
                "health": {"type": "boolean", "description": "true when the newest message asks about the baby's health"}},
                "required": ["ops", "reply"]}}
VERDICT_TOOL = {"name": "verdict", "description": "Whether the proposed operations are right, or the corrected list.",
                "parameters": {"type": "object", "properties": {
                    "ok": {"type": "boolean"}, "ops": {"type": "array", "items": {"type": "object"}},
                    "reason": {"type": "string"}}, "required": ["ok"]}}


def _hm(ts, tz):
    return parse_time(ts, tz).strftime("%a %H:%M")


def entry_line(entry, tz):
    """One log entry as the brain reads it: id, day and time, kind and what it holds."""
    d = entry.get("details") or {}
    kind = entry.get("kind")
    parts = [f"#{entry.get('id')}", _hm(entry["ts"], tz), kind]
    if kind == "feeding":
        parts.append(str(d.get("method") or "bottle"))
        if d.get("amount_ml") is not None:
            parts.append(f"{float(d['amount_ml']):g} ml")
        if d.get("type") and d.get("type") != "unknown" and "breast" not in str(d.get("method")):
            parts.append(str(d["type"]))
        if d.get("duration_min"):
            parts.append(f"{d['duration_min']} min")
    elif kind == "diaper":
        parts.append(", ".join(w for w, on in (("wet", d.get("wet")), ("dirty", d.get("solid"))) if on) or "dry")
        if d.get("color"):
            parts.append(str(d["color"]))
    elif kind == "sleep":
        parts.append(f"from {_hm(d['start'], tz)} to {_hm(entry['ts'], tz)}" if d.get("start") else "")
    else:
        parts.append(json.dumps(str(d.get("text") or "")[:80], ensure_ascii=False))
    return " ".join(p for p in parts if p)


def context(agent, request, now):
    """What a careful parent would look at: the log of the last hours, the open sleep, today's totals, the rhythm line
    and the conversation, then the newest message with its time."""
    tz = now.tzinfo
    since = (now - datetime.timedelta(hours=LOG_HOURS)).isoformat(timespec="seconds")
    entries = agent.baby_log.entries(None, since, 200)
    opened = agent.open_sleep()
    lines = [f"Now: {now.strftime('%a %Y-%m-%d %H:%M')}. Baby: {agent.baby_name() or 'the baby'}."]
    if opened:
        so_far = int((now - parse_time(opened, tz)).total_seconds() // 60)
        lines.append(f"Open sleep (id open-sleep): asleep since {_hm(opened, tz)}, {so_far // 60} h {so_far % 60:02d} min "
                     "so far.")
    else:
        lines.append("Open sleep: none.")
    lines.append(f"Log of the last {LOG_HOURS} hours, oldest first:")
    lines += [f"  {entry_line(e, tz)}" for e in entries] or ["  (empty)"]
    try:
        summary = agent.baby_log.summary(None, None)
        lines.append(f"Today ({now.strftime('%a %Y-%m-%d')}) since midnight: "
                     + json.dumps(summary, ensure_ascii=False, default=str))
        lines.append(f"Today's feeds by milk, counted by code: {milk_totals(entries, now)}.")
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_before = midnight - datetime.timedelta(days=1)
        yesterday = agent.baby_log.summary(day_before.isoformat(timespec="seconds"), midnight.isoformat(timespec="seconds"))
        lines.append(f"Yesterday ({day_before.strftime('%a %Y-%m-%d')}), its last entries are yesterday's own: "
                     + json.dumps(yesterday, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 a log without totals still gets its entries read
        pass
    if "next_feed" in agent.tools.items:
        status, text = agent.tools.run("next_feed", {})
        if status == "ran":
            lines.append(f"Rhythm line for the next feed: {text}")
    lines.append("Conversation, oldest first:")
    for m in agent.memory.recent_messages(HISTORY):
        who = "Parent" if m["role"] == "user" else "You"
        lines.append(f"  [{_hm(m['ts'], tz)}] {who}: {m['text']}")
    lines.append(f"Newest message from the parent, at {now.strftime('%H:%M')}: {request}")
    return "\n".join(lines)


def milk_totals(entries, now):
    """Today's bottles by milk type and the breast feeds, from the log: "how much formula today" is the formula only
    (held-out run-1 counted every bottle, 400 for 240)."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    groups = {}
    for e in entries:
        if e.get("kind") != "feeding" or parse_time(e["ts"], now.tzinfo) < midnight:
            continue
        d = e.get("details") or {}
        method = str(d.get("method") or "bottle")
        key = "breast feeds" if "breast" in method else f"bottles of {d.get('type') or 'unknown'}"
        count, ml = groups.get(key, (0, 0.0))
        groups[key] = (count + 1, ml + float(d.get("amount_ml") or 0))
    if not groups:
        return "none"
    return ", ".join(f"{key}: {count}" + (f", {ml:g} ml" if ml else "") for key, (count, ml) in sorted(groups.items()))


# A clock hour the parent said with no half of the day: "a las 2", "a la una y media", "a las 5 menos cuarto", "at 3".
HOUR_WORDS = {"una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
              "diez": 10, "once": 11, "doce": 12}
SAID_HOUR = re.compile(r"\b(?:a las?|las?|desde las?|hasta las?|de las?|tipo|at|around|by|from|until|till|de|a)\s+"
                       r"(\d{1,2}|" + "|".join(HOUR_WORDS) + r")(?!\d|[.,]\d|\s*(?:ml|cc|oz|onzas?|min\w*|h\b|hs|horas?|"
                       r"hours?|kg|g\b|%|veces|times|grados|degrees|°|dias|days))(\s+menos)?", re.I)
DAY_HALF = re.compile(r"\b(am|pm|a\.\s?m\.?|p\.\s?m\.?|mañana|manana|tarde|noche|madrugada|mediod[ií]a|medianoche|"
                      r"noon|midnight|morning|afternoon|evening|night|tonight|anoche|ayer|anteayer|yesterday|"
                      r"(1[3-9]|2[0-3])\s*[:.h]\s*\d{2}|(1[3-9]|2[0-3])\s*(hs|horas))\b", re.I)


def bare_hours(request):
    """The hours from 1 to 12 the parent said with no half of the day, as hour % 12, or an empty set when the message
    names a half of the day, a day, or a 24 hour time. "a las 5 menos cuarto" names 4 too, the hour Muse writes."""
    request = str(request or "")
    if DAY_HALF.search(request):
        return frozenset()
    hours = set()
    for match in SAID_HOUR.finditer(request):
        word = match.group(1).lower()
        hour = HOUR_WORDS.get(word) or int(word)
        if 1 <= hour <= 12:
            hours.add(hour % 12)
            if match.group(2):
                hours.add((hour - 1) % 12)
    return frozenset(hours)


def clock(value, now, hours=frozenset()):
    """A clock time HH:MM as the latest such moment not after now, or None when it is not a clock time. When the parent
    said that hour with no half of the day (hours from bare_hours), the latest of its two readings wins in code: round 4
    put "a las 2 le di pecho" said at 15:00 at 02:00 instead of 14:00."""
    match = HHMM.match(str(value or ""))
    if not match:
        try:
            moment = parse_time(value, now.tzinfo)
        except (TypeError, ValueError):
            return None
        match = HHMM.match(moment.strftime("%H:%M"))
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    readings = (hour % 12, hour % 12 + 12) if hour % 12 in hours else (hour,)
    return max(_latest(h, minute, now) for h in readings)


def _latest(hour, minute, now):
    moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment > now + datetime.timedelta(minutes=1):
        moment -= datetime.timedelta(days=1)
    return moment


def color(value):
    """A stool colour as the log keeps it (yellow, green, brown or black), or None."""
    return COLORS.get(str(value or "").strip().lower())


def amount(op):
    """The ml of an operation: amount_oz at 30 ml an ounce, as the bottle marks read, or amount_ml, rounded."""
    for name, factor in (("amount_oz", 30.0), ("amount_ml", 1.0)):
        value = op.get(name)
        if value is None or isinstance(value, bool):
            continue
        try:
            return float(round(float(value) * factor))
        except (TypeError, ValueError):
            return value
    return None


def to_call(op, now, hours=frozenset()):
    """One operation as a log tool call (name, arguments), or None when it is not an operation. hours are the bare clock
    hours the parent said, so each time lands on the latest of its two readings."""
    kind, name = op.get("kind"), op.get("op")
    at = clock(op.get("at"), now, hours) if op.get("at") else None
    ts = at.isoformat(timespec="seconds") if at else None
    if name == "sleep_start":
        return "log_baby_event", {"kind": "sleep", "details": {"action": "start"}, **({"ts": ts} if ts else {})}
    if name == "sleep_end":
        return "log_baby_event", {"kind": "sleep", "details": {"action": "end"}, **({"ts": ts} if ts else {})}
    if name == "add" and kind == "sleep":
        end = clock(op.get("end"), now, hours) if op.get("end") else now
        start = clock(op.get("start"), end, hours) if end is not None else None
        if start is None or end is None:
            return None
        if start >= end:
            start -= datetime.timedelta(days=1)
        return "log_baby_event", {"kind": "sleep", "details": {"start": start.isoformat(timespec="seconds"),
                                                               "end": end.isoformat(timespec="seconds")}}
    if name == "add" and kind in ("feeding", "diaper", "bath", "note"):
        if kind == "feeding":
            details = {"method": op.get("method") or "bottle"}
            ml = amount(op)
            if ml is not None:
                details["amount_ml"] = ml
            if op.get("type") in ("formula", "breast milk"):
                details["type"] = op["type"]
            if op.get("duration_min"):
                details["duration_min"] = op["duration_min"]
        elif kind == "diaper":
            details = {"wet": bool(op.get("wet")), "solid": bool(op.get("solid"))}
            if color(op.get("color")):
                details["color"] = color(op.get("color"))
        else:
            details = {"text": str(op.get("text") or "")}
        return "log_baby_event", {"kind": kind, "details": details, **({"ts": ts} if ts else {})}
    if name in ("edit", "delete") and op.get("id") is not None:
        which = {"id": op["id"], **({"kind": kind} if kind in KINDS and op["id"] != "open-sleep" else {})}
        if name == "delete":
            return "delete_baby_event", which
        # A correction moves an entry Muse can see in the log, so its own reading of the hour stands: "no, fue a las 9 y
        # media" at 22:00 may well mean the morning feed.
        at = clock(op.get("at"), now) if op.get("at") else None
        ts = at.isoformat(timespec="seconds") if at else None
        details = {k: op[k] for k in EDIT_FIELDS if k in op and k not in ("at", "amount_oz", "amount_ml", "start", "end",
                                                                             "color")}
        if "color" in op:
            details["color"] = color(op["color"]) or ""
        if "amount_oz" in op or "amount_ml" in op:
            details["amount_ml"] = amount(op)
        for field in ("start", "end"):
            if op.get(field):
                moment = clock(op[field], now)
                if moment is not None:
                    details[field] = moment.isoformat(timespec="seconds")
        return "edit_baby_event", {**which, "details": details, **({"ts": ts} if ts else {})}
    return None


def parse_reply(reply, tool):
    """The tool call's arguments, or a JSON object in the text, or None."""
    for call in reply.tool_calls:
        if call["name"] == tool and isinstance(call.get("arguments"), dict):
            return call["arguments"]
    text = reply.text or ""
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def usable(proposal):
    return isinstance(proposal, dict) and bool({"ops", "reply"} & set(proposal))


def call_brain(agent, system, text, tool):
    reply, seconds = brain_mod.timed(agent.brain, system, [{"role": "user", "text": text}], [tool])
    usage = reply.usage or {}
    agent.bus.publish("brain_call", provider=agent.brain.name, model=agent.brain.model,
                      destination=agent.brain.destination, seconds=seconds, tool_calls=len(reply.tool_calls),
                      input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                      reasoning_tokens=usage.get("reasoning_tokens"), usd=reply.usd, fallback=bool(reply.fallback))
    if reply.fallback:
        agent.bus.publish("brain_fallback", **reply.fallback)
        agent.brain_busy = True
    return reply


def observation_ops(agent, request, ops, now):
    """A health message that reports what the parent saw keeps it as a note in their words, and a feed told with it
    ("tomo 70 y vomito un poco") is logged, whatever Muse proposed: round 4 lost the 70 ml from the day total in 3 of 3
    runs. The feed is added only when Muse proposed none and the log has no such feed in the last 30 minutes."""
    ops = list(ops)
    if rules.SYMPTOM.search(request or "") and not any(op.get("op") == "add" and op.get("kind") == "note" for op in ops):
        ops.append({"op": "add", "kind": "note", "text": request})
    feed = rules.symptom_feed(request)
    if feed and not any(op.get("kind") == "feeding" or op.get("op") == "edit" for op in ops):
        since = (now - datetime.timedelta(minutes=30)).isoformat(timespec="seconds")
        try:
            near = agent.baby_log.entries("feeding", since, 20)
        except Exception:  # noqa: BLE001 a log that cannot be read is read as holding no such feed
            near = []
        twin = any(float((e.get("details") or {}).get("amount_ml") or 0) == float(feed.get("amount_ml") or -1) or
                   (feed.get("duration_min") and (e.get("details") or {}).get("duration_min") == feed["duration_min"])
                   for e in near)
        if not twin:
            agent.bus.publish("guard", status="symptom_feed_added")
            ops.insert(0, {"op": "add", "kind": "feeding", **feed})
    return ops


# Whether something about the baby is normal, ok or what to give: health questions in any words around them.
NORMAL_ASK = re.compile(r"\b(es normal|is (that|this|it) (normal|ok|okay|bad|fine)|normal\s*\?|(eso )?est[aá] bien\s*\?|"
                        r"qu[eé] le (doy|puedo dar)|le puedo dar|is (he|she) sick|est[aá] enfermit?[oa]|is it (ok|okay|safe) "
                        r"to (give|put)|should i (give|worry)|me preocupo|tengo que preocuparme|es grave|is it serious)(?!\w)",
                        re.I)


def asks_health(request):
    """True when the words alone ask a health question: a question about a symptom, a medicine or whether something is
    normal. Muse's "health" flag catches the rest by meaning."""
    request = request or ""
    return bool(NORMAL_ASK.search(request) or (rules.ADVICE.search(request) and (
        rules.is_medical(request) or rules.is_medical_es(request) or rules.SYMPTOM.search(request)
        or rules.MEDICINE.search(request))))


def other_tools(agent):
    """The agent's tools that are not the log's, as "name: first sentence", for the hand-off line."""
    out = []
    for name, tool in sorted(agent.tools.items.items()):
        if name in LOG_TOOLS:
            continue
        first = re.split(r"(?<=[.!?])\s", str(getattr(tool, "description", "") or "").strip(), 1)[0][:120]
        out.append(f"{name} ({first})" if first else name)
    return out


def stagger(ops, now):
    """Two or more feeds told in one message with no time ("le di 50 de leche materna y después otra de 30 de fórmula")
    end one after the other, the last one now: held-out run-1 had the second refused as overlapping the first."""
    feeds = [op for op in ops if op.get("op") == "add" and op.get("kind") == "feeding" and not op.get("at")]
    if len(feeds) < 2:
        return ops
    cursor = now
    for op in reversed(feeds):
        op["at"] = cursor.strftime("%H:%M")
        cursor -= datetime.timedelta(minutes=float(op.get("duration_min") or 15) + 1)
    return ops


AFTER_ALERT = ("[from the agent, not the parent] The fixed emergency line was already sent for this message, and the "
               "parent is calling for help. Return only the log operations for what the message reports happened (a "
               "feed, a diaper, a sleep) and a note with the parent's words about the sign. The reply is not used.")


def decide(agent, channel, request, verify=False, health=False, after_alert=False):
    """One parent message through the ops brain. Returns the reply text, which the caller says, or None when the brain
    answered no log operations at all, so the caller can take the guarded path. after_alert: the fixed safety line went
    out already, only what the message reports is logged, and the reply is the confirmation from the log or ""."""
    from .loop import BOUNDS_ASK, diff_text, log_diff, diff_empty, TEXTS  # loop imports this module lazily

    now = agent.now()
    lang = agent.lang(request)
    lang = lang if lang in LANG_NAMES else "en"
    seen = context(agent, request, now) + ("\n" + AFTER_ALERT if after_alert else "")
    system = OPS_SYSTEM.replace("{language}", LANG_NAMES[lang])
    others = [] if after_alert else other_tools(agent)
    if others:
        system += HANDOFF.format(tools="; ".join(others))
    proposal = parse_reply(call_brain(agent, system, seen, OPS_TOOL), "log_ops")
    if not usable(proposal) and agent.brain.name != "fake":
        # On the fifth blind set Muse once answered "un cuarto de hora de pecho" without a log_ops call, and the guarded
        # loop that took over lost the 15 minutes. Muse is asked once more before that.
        agent.bus.publish("guard", status="ops_retry")
        proposal = parse_reply(call_brain(agent, system, seen + "\n" + RETRY, OPS_TOOL), "log_ops")
    if not usable(proposal):
        agent.bus.publish("guard", status="no_log_ops")
        return None
    ops = [op for op in proposal.get("ops") or [] if isinstance(op, dict)]
    if others and any(op.get("op") == "handoff" for op in ops):
        agent.bus.publish("guard", status="ops_handoff")
        return None
    said = "" if after_alert else re.sub(r"\s*[—–]\s*", ", ", str(proposal.get("reply") or "")).strip()
    if said and not ops and rules.message_lang(said) not in (None, lang) and agent.brain.name != "fake":
        # Round 4: "No worries, I kept just the one at 03:45." in a Spanish chat at 3 AM. A reply in the wrong language
        # is asked for once more in the family's language, and never sent as it was.
        agent.bus.publish("guard", status="ops_wrong_language")
        again = parse_reply(call_brain(agent, system, seen + "\n" + LANG_RETRY.format(language=LANG_NAMES[lang]), OPS_TOOL),
                            "log_ops") or {}
        redo = re.sub(r"\s*[—–]\s*", ", ", str(again.get("reply") or "")).strip()
        if [op for op in again.get("ops") or [] if isinstance(op, dict)]:
            redo = ""  # a second answer that suddenly changes the log is not trusted for a reply-only turn
        said = redo if redo and rules.message_lang(redo) in (None, lang) else ""
    if verify:
        check = parse_reply(call_brain(agent, VERIFY_SYSTEM, seen + "\nProposed operations: "
                                       + json.dumps(ops, ensure_ascii=False), VERDICT_TOOL), "verdict") or {}
        if check.get("ok") is False and isinstance(check.get("ops"), list):
            agent.bus.publish("guard", status="verify_corrected", reason=str(check.get("reason") or "")[:200])
            ops = [op for op in check["ops"] if isinstance(op, dict)]
    if health:
        ops = observation_ops(agent, request, ops, now)
    # Held-out run-1 dev: "many babies strain when they poop" came from the ops reply to a health question. Muse's own
    # words never answer one: the fixed no-advice line does, whether Muse flagged it or the words say it.
    health_question = proposal.get("health") is True or asks_health(request)
    if health_question and not after_alert:
        agent.bus.publish("guard", status="ops_health_question")
        said = agent.no_advice(request)
    ops = stagger(ops, now)
    hours = bare_hours(request)
    calls = [c for c in (to_call(op, now, hours) for op in ops) if c is not None]
    for name, arguments in calls:
        kind = arguments.get("kind")
        if name == "edit_baby_event" and kind is None:
            kind = "feeding" if "amount_ml" in arguments.get("details", {}) else None
        bad = rules.out_of_bounds(kind, arguments.get("details"), arguments.get("ts"), now, parse_time)
        if bad:
            # A value no real entry can have is asked about, and nothing of this message is logged.
            agent.bus.publish("guard", status="out_of_bounds", field=bad[0], tool=name)
            if after_alert:
                return ""
            value = f"{float(bad[1]):g}" if bad[0] in ("amount_ml", "duration_min") else bad[1]
            return BOUNDS_ASK[lang][bad[0]].format(value=value)
    before = agent.log_state()
    for name, arguments in calls:
        status, result = agent.tools.run(name, arguments)
        agent.bus.publish("tool", name=name, status=status)
    diff = log_diff(before, agent.log_state())
    if after_alert:
        return "" if diff_empty(diff) else diff_text(diff, lang, agent.baby_name())
    # A safety line in Muse's reply is never dropped for the log confirmation, and a red flag never gets "tell me again".
    safety = rules.carries_safety_line(said)
    red_flag = rules.names_red_flag(request)
    if not diff_empty(diff):
        text = diff_text(diff, lang, agent.baby_name())
        if health and rules.asks_advice(request):
            text += " " + agent.no_advice(request)
        elif health:
            pass
        elif safety:
            agent.bus.publish("guard", status="safety_line_kept")
            text += " " + said
        elif health_question or ("?" in request and said and not rules.claims_done(said)):
            text += " " + said
        return text
    if calls:
        if safety:
            agent.bus.publish("guard", status="safety_line_kept")
            return said + " " + TEXTS[lang]["NOTHING_LOGGED"]
        if red_flag:
            return TEXTS[lang]["NOTHING_LOGGED"] + " " + agent.safety_line(request)
        if any(name in ("edit_baby_event", "delete_baby_event") for name, _ in calls):
            return TEXTS[lang]["NOT_CHANGED"]
        return TEXTS[lang]["NOT_IN_LOG"]
    if health:
        return agent.refusal(request)
    if red_flag and not safety and not said:
        return agent.safety_line(request)
    if health_question:
        return said
    return said or ("OK." if lang == "en" else "Dale.")
