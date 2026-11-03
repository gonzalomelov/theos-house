"""Red flags and medical questions, in code and outside Muse, so nothing Muse is told can talk its way past them.

A parent's message passes through gate() before Muse sees it. An emergency or a newborn red flag gets the fixed line from
agent/rules.py, to both parents, and Muse is not called. A question asking for advice gets the fixed no-advice line.
Every message Muse writes passes through outbound(): a dose, a drug or a diagnosis is refused, and Muse is told why.
It also passes through unbacked(): how the night went, or an amount in ml, must come from the log or from a parent's words.
"""
import re

from ..agent import danger, final_guard, rules
from .settings import BASE_URL, MODEL

SCREEN = {"provider": "openai_compatible", "model": MODEL, "base_url": BASE_URL, "key_env": "BASETEN_API_KEY"}
ADVICE_OUT = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:mg|mcg|ug|gotas|drops)\b|\b(paracetamol|ibuprofen\w*|acetaminophen|tylenol|motrin|advil|"
                        r"calpol|nurofen|simethicone|simeticona|gripe water|antibi[oó]tic\w*|antibiotics?|dosis|dose|dosage|"
                        r"diagn[oó]stic\w*|diagnos\w*)\b", re.I)
# What Muse added on its own in the morning messages (Nov 3): the log holds events, never how the night felt.
HOW_IT_WENT = re.compile(r"\b(durmi[oó]\s+(?:\w+\s+)?(?:bien|tranquil\w*|genial|b[aá]rbaro|de corrido|toda la noche)|durmieron\s+(?:\w+\s+)?bien|descans[oó]\s+bien|"
                         r"noche\s+(?:\w+\s+)?(?:tranquila|buena|linda|b[aá]rbara|bien|sin\s+\w+)|(?:buena|linda|tranquila)\s+noche|"
                         r"sin\s+(?:problemas|sobresaltos|novedad\w*|complicaciones)|todo\s+(?:bien|tranquilo)|"
                         r"slept\s+(?:\w+\s+)?(?:well|through|fine)|(?:quiet|calm|good|easy|peaceful)\s+night|night\s+went\s+\w+)\b", re.I)
MILLILITERS = re.compile(r"\b(\d+)\s?(?:ml|mililitros|milliliters|cc)\b", re.I)
# A danger in a film or a book is not one at home, unless the words are also about this baby.
FICTION = re.compile(r"\b(movie|film|tv show|series|novel|book|story|documentary|episode|in the news|pel[ií]cula|peli|serie|novela|libro|cuento|historia|documental|cap[ií]tulo|noticiero)\b", re.I)
THIS_BABY = re.compile(r"\b(theo|my|our|mi|nuestro|the baby|baby is|el beb[eé]|he|his|him|[eé]l)\b", re.I)
# Claims that only hold for a while. The warmer turns itself off, and a long gap between feeds is never fine.
WARM_CLAIM = re.compile(r"\b(bottle|mamadera|biber[oó]n)\b[^.!?]{0,40}\b(warm|ready|caliente|tibia|lista|pronta)\b|\b(warm|caliente|tibia|lista|pronta)\b[^.!?]{0,40}\b(bottle|mamadera|biber[oó]n)\b", re.I)
REASSURE = re.compile(r"sleep when you can|get some rest|rest up|beside you|all good|no worries|due soon|al lado tuyo|dorm[ií] tranquil\w*|descans[aá]\b|tranquil[oa]\b|todo bien|sin problema|le toca pronto", re.I)
HOT_ROOM, COLD_ROOM = 28.0, 14.0
FEED_GAP_H, STALE_LOG_H = 8, 48
# The ladder: each step is said once, from code, and from BOTH_FROM up it reaches both parents, day or night.
GAP_STEPS, BOTH_FROM = (8, 12, 18, 24, 36), 18
GAP_LINES = {"en": ("The log shows no feed for {h} hours. Did feeds go unlogged? If he truly hasn't eaten, call your pediatrician.",
                    "The log shows no feed for {h} hours, which is long for a newborn. If feeds didn't go unlogged, call your pediatrician now.",
                    "No feed in the log for {h} hours. If he truly hasn't eaten, call your pediatrician or emergency services now. Please check on him and log what he had."),
             "es": ("El registro no tiene tomas hace {h} horas. ¿Quedaron tomas sin registrar? Si de verdad no comió, llamá a su pediatra.",
                    "El registro no tiene tomas hace {h} horas, y es mucho para un recién nacido. Si no quedaron tomas sin registrar, llamá a su pediatra ahora.",
                    "No hay tomas en el registro hace {h} horas. Si de verdad no comió, llamá ahora a su pediatra o a emergencias. Fijate cómo está y anotá lo que tomó.")}
# "Not an emergency" counts, unless the words name a sign nobody can wave away.
DENIED = re.compile(r"\b(not an emergency|no emergency|nothing urgent|not urgent|no es (?:una )?(?:emergencia|urgencia)|no es urgente|nada urgente)\b", re.I)
VITAL = re.compile(r"not breathing|stop\w* breathing|can'?t breathe|no respira|dej[oó] de respirar|\bblue\b|\bazul|\bmorad|unresponsive|no reacciona|no responde|seizure|convuls", re.I)
# Words on a label or a shelf, not about a baby now (Nov 3, a toy label and a thermometer on sale both called 911).
ERRANDS = re.compile(r"\bchoking hazards?\b|\bpeligro de asfixia\b|\bfever (?:thermometers?|reducers?)\b|\bterm[oó]metros? para (?:la )?fiebre\b", re.I)
STOPPED = re.compile(r"\bstops? breathing\b|\bdeja de respirar\b", re.I)
CLAUSE = re.compile(r"[.!?;\n]+|\b(?:also|adem[aá]s|tambi[eé]n)\b|,\s*y\s+|,?\s+y\s+(?=agreg|anot|compr|pon|prend|apag)|,?\s+and\s+(?=add|log|buy|turn|put|remind|tell)", re.I)
# A parent who is scared or worn out, with no danger sign named, needs the log and a human line, not the 911 line.
SCARED = re.compile(r"\b(?:i'?m|i am|im)\s+(?:so |really |very )?(?:scared|worried|frightened|anxious|nervous|panicking)\b|\btengo miedo\b|\bestoy\s+(?:muy |re )?(?:asustad[ao]|preocupad[ao]|nervios[ao])\b|\bme (?:asust\w+|preocupa)\b", re.I)
WORN_OUT = re.compile(r"\b(?:i'?m|i am|im)\s+(?:so |really |very )?(?:exhausted|tired|wrecked|done)\b|\bdoing (?:this|it) (?:all )?wrong\b|\bcan'?t do this\b|\bagotad[ao]\b|\bno doy m[aá]s\b|\bestoy muert[ao]\b|\blo estoy haciendo mal\b", re.I)
LOG_QUESTION = re.compile(r"\b(?:did|really|when|how long|how many|has he)\b[^.!?]{0,50}\b(?:eat|ate|eaten|fed|feed|feeds|bottle)\b[^.!]{0,40}\?|\b(?:de verdad|realmente|cu[aá]ndo|hace cu[aá]nto|cu[aá]ntas?)\b[^.!?]{0,50}\b(?:comi[oó]|tom[oó]|tomas?|mamadera)\b[^.!]{0,40}\?", re.I)
DANGER_SIGN = re.compile(r"breath|respir|\bblue\b|azul|morad|\blimp\b|floppy|blando|won'?t wake|not waking|wake up|no (?:se )?despierta|unrespons|no reacciona|no responde|seizure|convuls|vomit|sangr|blood|fever|fiebre|\bhot\b|caliente|\bpale\b|p[aá]lid|rash|chok|ahog|won'?t eat|refus|no quiere|rechaz|weird|strange|not right|\boff\b|raro|\bmal\b(?! hecho)|sleepy|letarg|callad|\bquiet\b|\bfell\b|se cay|golpe|\bhit\b|inconsolable|no para de llorar|dolor|\bpain\b", re.I)
# How far a room can't move in a few minutes.
SENSOR_JUMP = {"humidity": 30.0, "temperature": 10.0}
JUMP_MINUTES = 10
# What a message can't promise or say. The end time of the warmer is when it switches off, not when a bottle is ready.
PROMISE = re.compile(r"\bi'?ll (?:remind|ping|wake|message|text|check in|let you know|tell you)\b|\b(?:te|les) (?:aviso|avisar[eé]|recuerdo|escribo|despierto)\b|\bvoy a (?:avisar|recordar|escribir)\w*", re.I)
READY_AT = re.compile(r"\b(?:ready|warm)\s+(?:by|at|around)\s+\d|\b(?:lista|pronta|tibia|caliente)\s+(?:a las|para las|a eso de)\s+\d", re.I)
JARGON = re.compile(r"\brota\b|\bper the\b|\bas per\b|\bper (?:ceci|gonza)\b|\bdoes that (?:still )?stand\b|\bsince 22:00\b|\bdesde las 22\b", re.I)


def amounts(entries):
    """Every ml amount in the log, and the running totals from the newest feed back, so "180 ml in all" can be true."""
    feeds = [e["details"]["amount_ml"] for e in entries if isinstance((e.get("details") or {}).get("amount_ml"), (int, float))]
    known, total = set(), 0
    for amount in reversed(feeds):
        total += amount
        known |= {int(amount), int(total)}
    return known


def unbacked(text, entries, heard=""):
    """Why a message can't go out because it says what nobody knows, or None. entries is a callable, so the log is read only
    when a message makes such a claim. heard is the parent's own words: repeating them is fine."""
    text, heard = text or "", heard or ""
    claim = HOW_IT_WENT.search(text)
    if claim and claim.group(0).lower() not in heard.lower():
        return f'Refused, nothing was sent: the log does not say "{claim.group(0)}". Say only what the log shows.'
    said = {int(n) for n in MILLILITERS.findall(text)} - {int(n) for n in re.findall(r"\d+", heard)}
    if said:
        missing = said - amounts(entries())
        if missing:
            return f"Refused, nothing was sent: the log has no {min(missing)} ml. Say only what the log shows."
    return None


def lang_of(text, default="es"):
    return "es" if rules.looks_spanish(text) else ("en" if rules.ENGLISH.search(text) else default)


def about_a_story(text):
    return bool(FICTION.search(text or "")) and not THIS_BABY.search(text or "")


def unsafe_room(payload):
    """The reading when a temperature event says Theo's room is far out of range, or None."""
    if "temperature" not in str(payload.get("entity_id", "")):
        return None
    try:
        value = float(payload.get("state"))
    except (TypeError, ValueError):
        return None
    return value if value >= HOT_ROOM or value <= COLD_ROOM else None


def because(sender, text, line, lang):
    """The fixed line for the other parent says who wrote and why, or it reads as an alarm from nowhere."""
    words = {"es": 'escribió', "en": "wrote"}[lang]
    return f'{str(sender).capitalize()} {words}: "{str(text)[:140]}"\n{line}'


def just_worry(text):
    """Fear, tiredness or a question the log can answer, with no danger sign named. Muse reads the log and answers."""
    text = text or ""
    return bool(SCARED.search(text) or WORN_OUT.search(text) or LOG_QUESTION.search(text)) and not DANGER_SIGN.search(text)


def worn_out(text):
    return bool(WORN_OUT.search(text or "")) and not DANGER_SIGN.search(text or "")


def brief(line):
    """The fixed urgent line, short, with its source last and on its own line, so it stays one tap and not a wall of text."""
    found = re.search(r"https?://\S+", line)
    if not found:
        return line
    words = re.sub(r"\s*(?:This is the public guidance|Es la gu[ií]a p[uú]blica)[^:]*:?\s*$", "", line[:found.start()]).rstrip()
    return f"{words}\n{found.group(0)}"


def gate(text, screen=None, lang=None):
    """(kind, line) for a message that must not reach Muse, or None. kind is emergency, urgent or medical."""
    lang = lang or lang_of(text)
    if about_a_story(text):  # a dose Muse might write is still refused on the way out
        return None
    if DENIED.search(text or "") and not VITAL.search(text or ""):
        return None
    text = ERRANDS.sub(" ", text or "")
    if rules.is_emergency(text) or rules.spoken_emergency(text) or (STOPPED.search(text) and not FICTION.search(text)):
        return "emergency", rules.EMERGENCY_REPLY[lang]
    if just_worry(text):
        return None
    urgent = rules.newborn_red_flag(text)
    if urgent:
        return "urgent", brief(rules.URGENT_REPLY[urgent][lang])
    if rules.asks_dose(text) or (rules.asks_advice(text) and (rules.is_medical(text) or rules.is_medical_es(text))):
        return "medical", rules.NO_ADVICE[lang]
    if (screen or danger.build(SCREEN)).screen(text)[0]:
        return "emergency", rules.EMERGENCY_REPLY[lang]
    return None


def rest_of(text):
    """The parts of a message the gate has no business with, for Muse. An alarm in one sentence never eats the errand in the next."""
    parts = [p.strip(" ,") for p in CLAUSE.split(text or "") if p and len(p.split()) >= 3]
    return " ".join(p + "." for p in parts if len(parts) > 1 and not gate(p, _NO_SCREEN))


class _NoScreen:
    def screen(self, text):
        return False, "words"


_NO_SCREEN = _NoScreen()


def gap_step(hours):
    """The highest step of the ladder this gap has reached, or None."""
    return max((s for s in GAP_STEPS if hours >= s), default=None)


def gap_line(hours, step, lang="es"):
    lines = GAP_LINES["en" if lang == "en" else "es"]
    return lines[0 if step < BOTH_FROM else 1 if step < 24 else 2].format(h=int(hours))


def sensor_jump(entity, value, before, minutes):
    """Why a reading can't be the room, or None: a room doesn't move this far this fast."""
    kind = next((k for k in SENSOR_JUMP if k in str(entity)), None)
    if kind and minutes <= JUMP_MINUTES and abs(value - before) >= SENSOR_JUMP[kind]:
        return f"This reading went from {before:g} to {value:g} in {minutes:.0f} minutes, which a room can't do. Suspect the sensor: say so to the parent on duty and don't move a device on it until another reading agrees."
    return None


def plain(text):
    """Muse writes long dashes, and nobody in this house texts with them."""
    return re.sub(r"\s*[\u2014\u2013]\s*", ", ", text or "")


def outbound(text, lang="es"):
    """(text to send, why it was refused). The final guard drops machinery, a dose or a drug refuses the whole message."""
    if ADVICE_OUT.search(text or ""):
        return None, "Refused, nothing was sent: never a dose, a drug or a diagnosis. Say what you saw or did instead."
    return final_guard.apply(plain(text), lang=lang), None
