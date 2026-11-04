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
Write one short warm page for each day you are given, in {language}, two sentences at most, in the voice of the family's home looking back.
Use only what the day's facts say, and any note given for it. Most pages use one fact or none, and no two pages sound alike. The home watches and remembers: it never holds or touches anyone. Don't invent events, feelings of the baby, weather or visitors. Numbers can only be those in the facts.
No medical or health judgments, and never say how he is doing or whether something is normal. Theo's parents are Gonza and Ceci, use no other names and no surnames.
Answer with JSON only: {{"title": "...", "pages": [{{"day": "YYYY-MM-DD", "text": "..."}}]}}"""
LANGUAGES = {"en": "English", "es": "Spanish"}
PLAIN = {"en": "{feeds} feeds, {ml} ml in all, {diapers} diapers.", "es": "{feeds} tomas, {ml} ml en total, {diapers} pañales."}
TITLE = {"en": "Theo's first days", "es": "Los primeros días de Theo"}
FORBIDDEN = re.compile(r"\b(healthy|sano|normal|fever|fiebre|doctor|pediatr\w*)\b", re.I)


def days_of(entries, limit=MONTH_DAYS):
    """The log, day by day: what happened and nothing else. Only the last days fit in a book made now."""
    days = defaultdict(lambda: {"feeds": 0, "ml": 0, "diapers": 0, "sleeps": 0})
    for entry in entries:
        day = days[parse_time(entry["ts"]).date().isoformat()]
        if entry["kind"] == "feeding":
            day["feeds"] += 1
            day["ml"] += int(entry["details"].get("amount_ml") or 0)
        elif entry["kind"] == "diaper":
            day["diapers"] += 1
        elif entry["kind"] == "sleep":
            day["sleeps"] += 1
    return [{"day": day, **days[day]} for day in sorted(days)][-limit:]


NUMBER_WORDS = {w: str(i) for i, w in enumerate("one two three four five six seven eight nine ten eleven twelve".split(), 1)} | \
    {w: str(i) for i, w in enumerate("una dos tres cuatro cinco seis siete ocho nueve diez once doce".split(), 1)} | {"un": "1", "uno": "1"}


def plain_page(day, lang):
    return PLAIN[lang].format(**day)


def page_is_true(text, day):
    """Numbers on the page must be numbers of that day, and the page keeps away from health and surnames."""
    allowed = {str(n) for n in (day["feeds"], day["ml"], day["diapers"], day["sleeps"])} | set(re.findall(r"\d+", day["day"]))
    words = [NUMBER_WORDS[w] for w in re.findall(r"\w+", text.lower()) if w in NUMBER_WORDS and w not in ("one", "una", "un", "uno")]  # "one" is rarely a count
    return not FORBIDDEN.search(text) and all(n in allowed for n in re.findall(r"\d+", text) + words)


def clean_json(text):
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


async def write(model, entries, notes="", lang="en"):
    """A book from this log. Returns the title and one page per day, each saying whether Muse's words stood or code wrote the line."""
    days = days_of(entries)
    if not days:
        return {"title": TITLE[lang], "pages": []}
    prompt = [("system", RULES.format(language=LANGUAGES[lang])),
              ("user", json.dumps({"days": days, "notes_from_the_home": notes}, ensure_ascii=False))]
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
        pages.append({"day": day["day"], "text": text if kept else plain_page(day, lang), "by": "muse" if kept else "code"})
    return {"title": title if page_is_true(title, days[0]) else TITLE[lang], "pages": pages}
