"""The first-month book: Muse writes a page for each day from the baby log and what it remembers, and code checks every number on
the page against that day's log. A page that claims a number the log doesn't have is replaced by a plain line from code. Illustrations
are not made here: no API for Muse's image model is open to this project, so they were made ahead of time in Meta's Muse app.
"""
import json
import re
from collections import defaultdict

from ..agent.memory import parse_time

MONTH_DAYS = 31
RULES = """You write pages of a family's keepsake book about their newborn Theo's first month, for his parents Gonza and Ceci.
Write one short warm page for each day you are given, in {language}, two sentences at most, three on a day with moments, in the voice of the family's home looking back.
Use only what the day's facts say, and any note given for it. Most pages use one fact or none, and no two pages sound alike. A day's "moments" really happened and each one must be on its page, in your words: who took the night, the recipe, the car seat. A frightening moment is named as one, with the words the parent wrote, and you never say how it ended unless the facts do. Use the "totals" of each day as they are. The home watches and remembers: it never holds or touches anyone. Don't invent events, feelings of the baby, weather or visitors. Numbers can only be those in the facts.
No medical or health judgments, and never say how he is doing or whether something is normal. Theo's parents are Gonza and Ceci, use no other names and no surnames.
Answer with JSON only: {{"title": "...", "pages": [{{"day": "YYYY-MM-DD", "text": "..."}}]}}"""
LANGUAGES = {"en": "English", "es": "Spanish"}
WORDS = {"en": (("feed", "feeds"), ("diaper", "diapers"), "{ml} ml in all", "Nothing went in the log this day."),
         "es": (("toma", "tomas"), ("pañal", "pañales"), "{ml} ml en total", "Este día no se anotó nada.")}
TOTALS = {"en": "In this session: {line}", "es": "En esta sesión: {line}"}
ALARM_WORD = {"en": ("alarm", "alarms"), "es": ("alarma", "alarmas")}
ALARM_NOTE = re.compile(r'^Alarm at (\d\d:\d\d), (.+?): "(.*)"$')
ALARM_LINE = {"en": 'A frightening moment: at {at} {who} wrote "{words}", and both parents were told.', "es": 'Un momento de miedo: a las {at} {who} escribió "{words}", y se les avisó a los dos.'}
TITLE = {"en": "Theo's first days", "es": "Los primeros días de Theo"}
FORBIDDEN = re.compile(r"\b(healthy|sano|normal|fever|fiebre|doctor|pediatr\w*)\b", re.I)
SAID_SCARED = re.compile(r"scar|fright|alarm|fear|worr|miedo|asust|alarma|susto|preocup", re.I)


def alarms_of(entries, lang):
    """The alarms the log holds, in the words that raised them. A night with one never goes missing from the book."""
    found = []
    for entry in entries:
        note = ALARM_NOTE.match(str((entry.get("details") or {}).get("text", ""))) if entry["kind"] == "note" else None
        if note:
            found.append({"day": parse_time(entry["ts"]).date().isoformat(), "kind": "alarm", "words": note.group(3),
                          "text": ALARM_LINE[lang].format(at=note.group(1), who=note.group(2).capitalize(), words=note.group(3))})
    return found


def days_of(entries, limit=MONTH_DAYS, moments=()):
    """The log, day by day: what happened and nothing else, with the moments that aren't in it. Only the last days fit in a book made now."""
    days = defaultdict(lambda: {"feeds": 0, "ml": 0, "diapers": 0, "sleeps": 0})
    for moment in moments:
        days[moment["day"]]
    for entry in entries:
        day = days[parse_time(entry["ts"]).date().isoformat()]
        if entry["kind"] == "feeding":
            day["feeds"] += 1
            day["ml"] += int(entry["details"].get("amount_ml") or 0)
        elif entry["kind"] == "diaper":
            day["diapers"] += 1
        elif entry["kind"] == "sleep":
            day["sleeps"] += 1
    return [{"day": day, **days[day], "moments": [m for m in moments if m["day"] == day]} for day in sorted(days)][-limit:]


NUMBER_WORDS = {w: str(i) for i, w in enumerate("one two three four five six seven eight nine ten eleven twelve".split(), 1)} | \
    {w: str(i) for i, w in enumerate("una dos tres cuatro cinco seis siete ocho nueve diez once doce".split(), 1)} | {"un": "1", "uno": "1"}


def counted(n, forms):
    return f"{n} {forms[0] if n == 1 else forms[1]}"


def plain_line(day, lang):
    feed, diaper, ml, empty = WORDS[lang]
    if not day["feeds"] and not day["diapers"]:
        return empty
    return ", ".join([counted(day["feeds"], feed), *([ml.format(ml=day["ml"])] if day["ml"] else []), counted(day["diapers"], diaper)]) + "."


def plain_page(day, lang):
    lines = [m["text"] for m in day.get("moments", [])]
    return " ".join([*lines, plain_line(day, lang)]) if lines and (day["feeds"] or day["diapers"]) else " ".join(lines) or plain_line(day, lang)


def totals_line(days, lang):
    feed, diaper, ml, _ = WORDS[lang]
    alarms = sum(1 for day in days for m in day["moments"] if m["kind"] == "alarm")
    parts = [counted(sum(d["feeds"] for d in days), feed), ml.format(ml=sum(d["ml"] for d in days)), counted(sum(d["diapers"] for d in days), diaper), *([counted(alarms, ALARM_WORD[lang])] if alarms else [])]
    return TOTALS[lang].format(line=", ".join(parts)) + "."


def left_out(text, day):
    """The moments of this day a page doesn't name."""
    low = text.lower()
    missing = []
    for moment in day.get("moments", []):
        kept = moment.get("words", "").lower() in low and bool(moment.get("words")) or (moment["kind"] == "alarm" and SAID_SCARED.search(low)) or \
            (moment["kind"] != "alarm" and any(w.lower() in low for w in moment.get("names", ())))
        if not kept:
            missing.append(moment["text"])
    return missing


def page_is_true(text, day):
    """Numbers on the page must be numbers of that day, and the page keeps away from health and surnames."""
    said = " ".join(m["text"] for m in day.get("moments", []))
    allowed = {str(n) for n in (day["feeds"], day["ml"], day["diapers"], day["sleeps"])} | set(re.findall(r"\d+", day["day"])) | set(re.findall(r"\d+", said))
    words = [NUMBER_WORDS[w] for w in re.findall(r"\w+", text.lower()) if w in NUMBER_WORDS and w not in ("one", "una", "un", "uno")]  # "one" is rarely a count
    return not any(w.lower() not in said.lower() for w in FORBIDDEN.findall(text)) and all(n in allowed for n in re.findall(r"\d+", text) + words)


def clean_json(text):
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


async def write(model, entries, notes="", lang="en", moments=()):
    """A book from this log and what happened around it. Returns the title, the session's totals and one page per day, each saying whether Muse's words stood,
    code wrote the line, or code added what Muse left out."""
    days = days_of(entries, moments=[*alarms_of(entries, lang), *moments])
    if not days:
        return {"title": TITLE[lang], "pages": [], "totals": ""}
    prompt = [("system", RULES.format(language=LANGUAGES[lang])),
              ("user", json.dumps({"days": [{**d, "moments": [m["text"] for m in d["moments"]]} for d in days], "notes_from_the_home": notes}, ensure_ascii=False))]
    try:
        answer = clean_json((await model.ainvoke(prompt)).content)
        written = {page.get("day"): str(page.get("text", "")).strip() for page in answer.get("pages", [])}
        title = str(answer.get("title") or TITLE[lang])[:80]
    except (ValueError, AttributeError, TypeError):
        written, title = {}, TITLE[lang]
    pages = []
    for day in days:
        text = written.get(day["day"], "")
        kept = bool(text) and page_is_true(text, day)
        missing = left_out(text, day) if kept else []
        kinds = [m["kind"] for m in day["moments"]]
        pages.append({"day": day["day"], "text": " ".join([text, *missing]) if kept else plain_page(day, lang), "by": ("both" if missing else "muse") if kept else "code",
                      "art": next((k for k in ("alarm", "recipe", "coach") if k in kinds), None)})
    return {"title": title if page_is_true(title, days[0]) else TITLE[lang], "pages": pages, "totals": totals_line(days, lang)}
