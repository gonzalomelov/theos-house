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
QUESTION_START = re.compile(r"^(when|how|what|did|has|have|is|was|why|cu[aá]nd[oa]|cu[aá]nt[oa]s?|qu[eé]|a qu[eé]|c[oó]mo|"
                            r"d[oó]nde|por qu[eé]|para cu[aá]ndo)\b", re.I)
# Health words in Spanish, on top of the English ones in MEDICAL. A bottle the parent gives ("le doy la mamadera") is
# not one of them, only a question about what to give ("le puedo dar").
MEDICAL_ES = re.compile(r"\b(fiebre|temperatura|medicamento|medicina|remedio|dosis|paracetamol|ibuprofeno|sarpullido|"
                        r"erupci|v[oó]mit|enferm|diagn[oó]s|tos\b|infecci|antibi[oó]tic|es normal|le puedo dar|puedo darle|"
                        r"c[oó]lico|gotas para)", re.I)
# Red flags: an answer in no time, with no brain call, that says to call emergency services. Fussing and crying are
# not on the list, they get the likely reason from the log instead.
EMERGENCY = re.compile(
    r"\b(not breathing|stopped breathing|isn'?t breathing|can'?t breathe|cannot breathe|struggling to breathe|"
    r"(blue|purple|gr[ae]y) (lips|face)|lips (are |look |turned |turning )?(blue|purple|gr[ae]y)|turn(ed|ing|s)? (blue|purple)|"
    r"limp|floppy|chok(e|es|ed|ing)|won'?t wake|wont wake|can'?t wake|cannot wake|not waking|unresponsive|"
    r"fell (off|from|down|out of)|had a fall|dropped (him|her|the baby)|hit (his|her|the|its) head|head injury|seizure|convuls\w*|"
    r"no respira|dej[oó] de respirar|le cuesta respirar|no puede respirar|morad[oa]s?|labios azules|se puso azul|"
    r"se (est[aá] )?ahog\w*|atragant\w*|no se despierta|no reacciona|no responde|"
    r"se (me )?cay[oó](?! (el|la) (chupete|mamadera|biber[oó]n|tete|juguete))|"
    r"se golpe[oó]|golpe en la cabeza|convulsi\w*)", re.I)
# Health and feeding-safety talk. Never a log request, so the not-logged check never answers it with "send it again".
HEALTH = re.compile(r"\b(can i|could i|should i|is it ok|is it safe|safe to|puedo|debo|deber[ií]a|es seguro|"
                    r"cereal|honey|miel|water|agua|not (pooped|peed|eaten)|hasn'?t (pooped|peed|eaten)|"
                    r"no (hizo|ha hecho) (caca|pis)|in \d+ days|\d+ d[ií]as sin|hace \d+ d[ií]as)\b", re.I)
# A message that corrects or removes an entry already in the log.
EDIT = re.compile(r"\b(perd[oó]n|correg\w*|corrij\w*|cambi[aá](la|lo)?|borr[aá](la|lo)?|elimin[aá](la|lo)?|sac[aá](la|lo)|"
                  r"me equivoqu[eé]|no eran?|eran? \d+ no|fue de \d+|fue \d+|(dos|2) veces|sin querer|duplicad\w*|repetid\w*|"
                  r"(it|that) was \d+|was \d+ not|not \d+|delete|remove|undo|wrong|mistake|sent (it )?twice|twice by|"
                  r"correct (it|that)|fix (it|that)|change (it|that))\b", re.I)
# The parent's answer to "did you send it twice or were there two bottles?"
DOUBLE_ONCE = re.compile(r"(dos|2) veces|sin querer|repet|duplic|una sola|era una|fue una|la misma|me equivoqu|error|"
                         r"twice|by mistake|same (one|bottle)|just one|only one|\bonce\b", re.I)
DOUBLE_TWO = re.compile(r"(dos|2) mamaderas|fueron (dos|2)|son (dos|2)|\botra\b|segunda|two bottles|another|second|"
                        r"there were two|were two|both", re.I)
CRY = re.compile(r"\b(cry|crying|cries|cried|fussy|fussing|screaming|llor\w*|berrinche|molest[oa])\b", re.I)
SIDE_SAID = re.compile(r"izquierd|derech|ambos|los dos|las dos|left|right|both", re.I)
TYPE_SAID = {"formula": re.compile(r"f[oó]rmula|formula|leche de f", re.I),
             "breast milk": re.compile(r"leche materna|materna|extra[ií]da|sacada|breast ?milk|pumped|expressed", re.I)}
TIME_SAID = re.compile(r"\d{1,2}[:.h]\d{2}|\d{1,2}\s*(am|pm|hs?)\b|\ba las?\s+\d|\bat \d|\bhace\b|\bago\b|y media|y cuarto|"
                       r"menos cuarto|anoche|esta ma[ñn]ana|madrugada|this morning|last night|earlier|\bantes\b|from \d|"
                       r"de \d{1,2} a \d{1,2}|\bayer\b|yesterday|\bla de la", re.I)
MINUTES_SAID = re.compile(r"\d+\s*(min|minutos|minutes|mins)\b|\d+\s*m\b|media hora|half an hour", re.I)
COLOR_SAID = re.compile(r"amarill|verde|marr[oó]n|negr|roj|yellow|green|brown|black|red", re.I)

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

REFUSAL = ("I can't give medical advice. Please call your pediatrician about that. If it is urgent, call emergency "
           "services (911 in Uruguay, or your local emergency number). I can log what you see so you have it ready for the call.")
EMERGENCY_REPLY = {
    "en": "This may be an emergency. Call emergency services now: 911 in Uruguay, or your local emergency number.",
    "es": "Puede ser una emergencia. Llamá ya al 911 (emergencias en Uruguay) y contales lo que ves.",
}


def is_medical(text):
    return bool(MEDICAL.search(text))


def is_emergency(text):
    return bool(EMERGENCY.search(text or ""))


def is_medical_es(text):
    return bool(MEDICAL_ES.search(text or ""))


def is_health(text):
    """Any health, safety or emergency talk, in English or Spanish. Never treated as a note to log."""
    return is_medical(text) or is_medical_es(text) or is_emergency(text) or bool(HEALTH.search(text or ""))


def is_edit_request(text):
    return bool(EDIT.search(text or "")) and not is_health(text)


def double_answer(text):
    """"once" when the parent sent the same note twice by mistake, "two" when there were two, None when unclear."""
    if DOUBLE_ONCE.search(text or ""):
        return "once"
    if DOUBLE_TWO.search(text or ""):
        return "two"
    return None


def is_cry_question(text):
    return bool(CRY.search(text or "")) and not is_emergency(text)


def said_only(request, kind, details, ts=None):
    """The log call's details and time, without anything the parent did not say: no breast side, milk type, duration,
    amount, diaper color or time the brain made up. Returns (details, ts)."""
    details = dict(details or {}) if isinstance(details, dict) else {}
    request = request or ""
    timed = bool(TIME_SAID.search(request))
    if not timed:
        ts = None
        if kind != "sleep":
            for name in ("start", "end", "time"):
                details.pop(name, None)
    if kind == "feeding":
        method = str(details.get("method") or "")
        if "breast" in method.lower() and not SIDE_SAID.search(request):
            details["method"] = "breast"
        milk = details.get("type")
        if milk and not any(pattern.search(request) for pattern in TYPE_SAID.values()):
            details.pop("type", None)
        if details.get("duration_min") is not None and not MINUTES_SAID.search(request):
            details.pop("duration_min", None)
        if details.get("amount_ml") is not None and not re.search(r"\d", request):
            details.pop("amount_ml", None)
    if kind == "diaper" and details.get("color") and not COLOR_SAID.search(request):
        details.pop("color", None)
    return details, ts


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
    if is_question(text) or is_question(english) or is_health(text):
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
