"""Rules the fake brain uses offline: turn a parent's note into a log event, answer from a summary, refuse health questions.

The real brain (Claude now, Muse Spark Open later) does this from the tool descriptions. These rules let
the tests check the whole path to Baby Buddy and back with no network, and give the fake brain the same
behaviour the system prompt asks of the real one.
"""
import datetime
import re

ML = re.compile(r"(\d+(?:\.\d+)?)\s*ml", re.I)
MINUTES = re.compile(r"(\d+)\s*(?:min|minutes)", re.I)
SPAN = re.compile(r"from\s+(\d{1,2})[:.](\d{2})\s+(?:to|until)\s+(\d{1,2})[:.](\d{2})", re.I)
MEDICAL = re.compile(r"\b(fever|temperature|medicine|medication|dose|dosage|paracetamol|ibuprofen|rash|vomit|sick|"
                     r"diagnos|should i give|is it normal|cough|infection|antibiotic)", re.I)
QUESTION_START = re.compile(r"^(when|how|what|did|has|have|is|was)\b", re.I)

# Spanish note words to the English ones parse_note knows, so "mamadera 120 ml" or "pañal sucio" read as notes too.
NOTE_WORDS_ES = [
    (r"pa[ñn]al(es)?", "diaper"), (r"sucio|caca", "dirty"), (r"mojado|pis|pich[ií]", "wet"),
    (r"se ba[ñn][oó]|ba[ñn]o|ba[ñn]ad[oa]", "bath"), (r"se durmi[oó]|dormid[oa]|se qued[oó] dormid[oa]", "fell asleep"),
    (r"se despert[oó]|despiert[oa]", "woke"), (r"teta|pecho", "breast"), (r"izquierd[oa]", "left"),
    (r"derech[oa]", "right"), (r"mamadera|biber[oó]n", "bottle"), (r"tom[oó]|comi[oó]", "drank"),
    (r"cu[aá]nto", "how much"), (r"cu[aá]ndo", "when"), (r"cu[aá]ntos|cu[aá]ntas", "how many"),
]
SPANISH = re.compile(r"[ñáéíóú¿¡]|\b(se|le|la|el|de|del|un|una|y|con|ya|reci[eé]n|hoy)\b", re.I)
# A reply that says something went into the log. "Noted" and "OK" are not claims, so small talk is never one.
CLAIMS_LOGGED = re.compile(r"\b(logged|recorded|added (it )?to the log|anot[eé]|anotad[oa]s?|registr[eé]|registrad[oa]s?)\b", re.I)

REFUSAL = ("I can't give medical advice. Please call your pediatrician about that. "
           "I can log what you see so you have it ready for the call.")


def is_medical(text):
    return bool(MEDICAL.search(text))


def is_question(text):
    return "?" in text or bool(QUESTION_START.search(text.strip()))


def today_at(hour, minute):
    return datetime.datetime.now().astimezone().replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat(timespec="seconds")


def parse_note(text):
    """(kind, details) for a parent's note, or None when it is not about the baby's day."""
    low = text.lower()
    if "diaper" in low or "nappy" in low or "poop" in low or "pee" in low:
        solid = any(w in low for w in ("dirty", "poop", "solid", "messy"))
        wet = "wet" in low or "pee" in low or not solid
        return "diaper", {"wet": wet, "solid": solid}
    if "bath" in low:
        return "bath", {"text": text}
    if "asleep" in low or "fell asleep" in low or "went down" in low:
        return "sleep", {"action": "start"}
    if "woke" in low or "awake" in low:
        return "sleep", {"action": "end"}
    span = SPAN.search(text)
    if span and ("nap" in low or "slept" in low or "sleep" in low):
        h1, m1, h2, m2 = (int(g) for g in span.groups())
        return "sleep", {"start": today_at(h1, m1), "end": today_at(h2, m2)}
    amount, minutes = ML.search(text), MINUTES.search(text)
    if "breast" in low or amount or "bottle" in low or "fed" in low or "drank" in low:
        details = {}
        if amount:
            details["amount_ml"] = float(amount.group(1))
        if "both breast" in low:
            details["method"] = "both breasts"
        elif "left" in low:
            details["method"] = "left breast"
        elif "right" in low:
            details["method"] = "right breast"
        else:
            details["method"] = "bottle"
        details["type"] = "breast milk" if ("breast" in low) else "formula"
        if minutes:
            details["duration_min"] = int(minutes.group(1))
        return "feeding", details
    if any(w in low for w in ("smiled", "rolled", "laughed", "first time", "milestone")):
        return "note", {"text": text}
    return None


def note_to_english(text):
    out = text
    for pattern, word in NOTE_WORDS_ES:
        out = re.sub(rf"\b(?:{pattern})\b", word, out, flags=re.I)
    return out


def log_kind(text):
    """The kind of log entry a parent's message reports (feeding, diaper, sleep, bath, note), in English or Spanish.
    None for questions, health questions and anything that is not a note about the baby."""
    english = note_to_english(text)
    if is_question(text) or is_question(english) or is_medical(text):
        return None
    parsed = parse_note(text) or parse_note(english)
    return parsed[0] if parsed else None


def is_log_request(text):
    return log_kind(text) is not None


def claims_logged(text):
    return bool(CLAIMS_LOGGED.search(text or ""))


def looks_spanish(text):
    return note_to_english(text) != text or bool(SPANISH.search(text))


def answer(question, summary):
    """A short answer to a parent's question from baby_summary, or None when the rules do not know the question."""
    q = question.lower()
    feeds, diapers, sleep, baths = summary["feedings"], summary["diapers"], summary["sleep"], summary["baths"]
    if "dirty" in q or "poop" in q:
        if "how many" in q:
            return f"{diapers['dirty']} dirty diapers today."
        return f"The last dirty diaper was at {diapers['last_dirty_at']}." if diapers["last_dirty_at"] else "No dirty diaper in the log yet."
    if "wet" in q:
        return f"{diapers['wet']} wet diapers today."
    if "diaper" in q:
        return f"{diapers['count']} diapers today, {diapers['wet']} wet and {diapers['dirty']} dirty."
    if "bath" in q:
        return f"The last bath was at {baths['last_at']} on {baths['last_date']}." if baths["last_at"] else "No bath in the log yet."
    if "sleep" in q or "nap" in q or "slept" in q:
        if "how long" in q or "how much" in q:
            return f"{sleep['total_min']} minutes of sleep today."
        return f"The last sleep ended at {sleep['last_end_at']}." if sleep["last_end_at"] else "No sleep in the log yet."
    if "last bottle" in q or "last feed" in q and "how much" in q:
        return f"The last feed was {feeds['last_amount_ml']:g} ml at {feeds['last_at']}." if feeds["last_amount_ml"] else "No feed amount in the log."
    if "how many" in q and ("feed" in q or "bottle" in q):
        return f"{feeds['count']} feeds today."
    if "how much" in q or "drank" in q or "drunk" in q or "drink" in q:
        return f"{feeds['total_ml']} ml today over {feeds['count']} feeds."
    if "eat" in q or "fed" in q or "feed" in q:
        return f"The last feed was at {feeds['last_at']}." if feeds["last_at"] else "No feed in the log yet."
    return None
