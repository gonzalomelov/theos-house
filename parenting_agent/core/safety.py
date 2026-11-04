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
THIS_BABY = re.compile(r"\btheo\b|\b(?:my|our|mi|nuestr[oa])\s+(?:baby|son|boy|kid|child|newborn|beb[eé]|hijo|nene|gur[ií])\b", re.I)
# "He isn't breathing, we were watching a film" is about this baby. "In the film he isn't breathing" is not.
HE_NOW = re.compile(r"\b(?:he|the baby|el beb[eé]|[eé]l)(?:'s|\s+(?:is|isn'?t|won'?t|can'?t|stopped|just|est[aá]|no|se))\b", re.I)
IN_STORY = re.compile(r"\b(?:in|en)\s+(?:the|a|this|that|my|la|el|una|un|esta|este|mi)\s+(?:\w+\s+)?(?:" + FICTION.pattern[3:-3] + r")\b|\b(?:movie|film|novel|book|series|story|pel[ií]cula|peli|serie|novela|libro|cuento)\s+(?:where|about|donde|en la que|sobre)\b", re.I)
# A baby who isn't this one: made up, named something else, or someone else's.
OTHER_BABY = re.compile(r"\b(?:fictional|fictitious|imaginary|made[- ]up|hypothetical(?:ly)?|ficticio\w*|imaginari\w*|inventad\w*|hipot[eé]tic\w*)\b"
                        r"|\b(?:baby|beb[eé]|newborn|reci[eé]n nacido|nene|nena)\s+(?:named|called|llamad[oa]|que se llama)\b"
                        r"|\b(?!ceci|gonza|our\b)\w+'s\s+(?:baby|son|kid|child|newborn)\b|\b(?:another|other|someone else'?s)\s+(?:baby|kid|child|newborn)\b"
                        r"|\b(?:beb[eé]|hij[oa]|nene|nena)\s+de\s+(?:mi|mis|la|el|una|un|nuestr\w+)\s+\w+|\botr[oa]\s+(?:beb[eé]|nene|nena)\b", re.I)
# A fever in someone else isn't Theo's. "Is my mom's cough a problem" doesn't call a newborn's red flag, and a life in danger still does.
SOMEONE_ELSE = re.compile(r"\b(?:my|our|mi|nuestr[oa]|la|el)\s+(?:mom|mum|mother|dad|father|wife|husband|partner|sister|brother|grandma|grandmother|grandpa|grandfather|friend|neighbou?r|dog|cat|boss|aunt|uncle|nanny|mother-in-law|father-in-law|"
                          r"mam[aá]|madre|pap[aá]|padre|esposa|esposo|mujer|marido|herman[oa]|abuel[oa]|amig[oa]|vecin[oa]|perr[oa]|gat[oa]|jefe|jefa|suegr[oa]|t[ií][oa]|ni[ñn]era)\b|\bgrandma\b|\babuela\b"
                          r"|\b(?:ceci|gonza)\s+(?:has|had|got|is|tiene|ten[ií]a|est[aá])\b"
                          r"|\b(?:i have|i got|i'?ve got|i'?m running|tengo|estoy con)\s+(?:a\s+|mucha\s+|\d\d(?:[.,]\d)?\s+(?:de\s+)?)?(?:fever|fiebre)\b", re.I)
SAYS_ABOUT_HIM = re.compile(r"\b(?:says|said|thinks|told me|dice|dijo|cree)\s+(?:that\s+|que\s+)?(?:he|[eé]l|le|tiene)\b", re.I)
THEO_NAMED = re.compile(r"\btheo\b|\bbaby\b|\bbeb[eé]\b|\bson\b|\bhijo\b|\bnewborn\b|\breci[eé]n nacido\b", re.I)
# Words trying to change the rules aren't a danger, and Muse refuses them. They never land in the log or in memory.
INJECTION = re.compile(r"\b(?:ignore|disregard|forget|override|bypass)\b[^.!?]{0,30}\b(?:rules?|instructions?|prompt|guidelines?|safety)\b|\b(?:ignor[aá]|olvid[aá]|salte[aá])\w*\b[^.!?]{0,30}\b(?:reglas?|instrucciones|prompt)\b|\bsystem prompt\b|\byou are now\b|\bact as\b|\bdeveloper mode\b|\bmaintenance mode\b|\bnew (?:rules|instructions)\b|\bnuevas (?:reglas|instrucciones)\b|\bfrom now on you\b", re.I)
AM_PM = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s?([ap])\.?\s?m\b\.?", re.I)
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
VITAL = re.compile(r"not breathing|stop\w* breathing|can'?t breathe|no respira|dej[oó] de respirar|\bblu(?:e|ish)\b|\bazul|\bmorad|\blimp\b|won'?t wake|not waking|no (?:se )?despierta|unresponsive|no reacciona|no responde|seizure|convuls", re.I)
# "Lips not blue" is reassurance, so it is no sign.
NOT_A_SIGN = re.compile(r"\b(?:not|aren'?t|isn'?t|no|sin|ni)\s+(?:\w+\s+)?(?:blu(?:e|ish)|azul\w*|morad\w*|limp)\b", re.I)
# Signs the word list misses, and how they come out typed fast at night. Everything else goes to the danger screen.
BUMPED = re.compile(r"\b(?:bump|bang|knock|smack)\w*\s+(?:his|her|the|its)\s+head\b|\bhead\s+(?:bump|knock)\b|\bse\s+(?:dio|peg[oó])\s+(?:\w+\s+)?(?:en\s+)?la\s+cabeza\b", re.I)
TYPED_FAST = re.compile(r"\b(?:lips?|labios?)\b[^.!?]{0,12}\b(?:blu\b|bleu\b|azul\w*)|\bbre?a?th?i?n?g?\w{0,3}\s+(?:funny|weird|strange|raro)\b|\bbreathng\b|\bw(?:no|on)t\s+wake\b|\bno\s+respir\b|\bno\s+resira\b", re.I)
# Which language the danger is written in, when a short message has no other word to go by.
DANGER_ES = re.compile(r"\b(?:respir\w*|despiert\w*|azul\w*|morad\w*|fiebre|labios?|convuls\w*|trag[oó]|golpe\w*|cabeza|pila|reacciona|ahog\w*)\b", re.I)
DANGER_EN = re.compile(r"\b(?:breath\w*|won'?t|wake|lips?|seizure|swallow\w*|battery|bump\w*|head|fever|stopped|limp|choking|fell)\b", re.I)
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
# A parent saying they fed him: the feed goes in the log first, so the gap it closes is never raised.
FEED_REPORT = re.compile(r"\b(?:gave|fed|just fed|nursed|drank|ate)\b|\bbottle (?:at|of)\b|\ble di\b|\btom[oó]\b|\bcomi[oó]\b|\bmamadera (?:a las|de)\b|\b\d+\s?ml\b", re.I)
# What the agent can't keep: the home decides these, not a promise in a chat.
# The agent can't see him. Only a person can go and look.
CANT_SEE = re.compile(r"\b(?:checking|i'?ll check|i will check|going to check|let me check|looking in) (?:on|in on) (?:him|theo)\b|\bvoy a (?:ver|revisar|chequear)(?:lo)?\s+(?:a theo|c[oó]mo est[aá])\b|\b(?:lo )?(?:estoy|sigo) (?:mirando|chequeando|revisando)\b", re.I)
CANT_KEEP = re.compile(r"\bi (?:won'?t|will not) (?:message|text|wake|bother|tell|write)\b|\bno (?:te|le|les) (?:escribo|aviso|molesto|despierto|voy a (?:escribir|avisar|molestar|despertar))\b|\bi'?ll (?:alert|tell|wake|message|text) (?:you )?both\b|\b(?:les )?aviso a (?:los |ustedes )?dos\b|\bdespierto a los dos\b", re.I)
WRONG_NUMBER = re.compile(r"\b(?:112|999|000)\b")
# What the rest of a message has to ask for, once the gate answered the worrying part. "He's 3 weeks old" isn't an errand.
ERRAND = re.compile(r"\b(?:add|log|buy|turn|put|remind|tell|write|note|shopping)\b|\bagreg|\banot|\bcompr|\bpon[eé]\b|\bprend|\bapag|\brecord|\bavis|\bdecile\b|\blista\b", re.I)
ALARM_TOLD = re.compile(r"emergenc|\b911\b|alarm|fever|fiebre|urgent|pediatr|call|llam|wrote|escribi|respir|breath|anoche|last night|esta madrugada", re.I)
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
    text = text or ""
    if rules.looks_spanish(text) or DANGER_ES.search(text):
        return "es"
    return "en" if rules.ENGLISH.search(text) or DANGER_EN.search(text) else default


def about_a_story(text):
    """A film, a book, a made-up baby or someone else's: not an alarm in this home. Muse answers, and anything about Theo in the same words still fires."""
    text = text or ""
    if THIS_BABY.search(text):
        return False
    if OTHER_BABY.search(text):
        return True
    return bool(FICTION.search(text)) and (bool(IN_STORY.search(text)) or not HE_NOW.search(text))


def about_someone_else(text):
    text = text or ""
    return bool(SOMEONE_ELSE.search(text)) and not THEO_NAMED.search(text) and not SAYS_ABOUT_HIM.search(text)


def injected(text):
    return bool(INJECTION.search(text or ""))


SIGN_MAX = 160
SIGN_WORDS = re.compile(DANGER_SIGN.pattern + r"|fever|fiebre|\b3[89](?:[.,]\d)?\b|\b40(?:[.,]\d)?\b|gasping|choking|ahog", re.I)


def sign_of(text):
    """The words that raised the alarm, kept whole: the sentence with the danger in it, without the rest of the message. It is what the other parent,
    the log and the morning check quote, so an instruction in the same message goes no further."""
    parts = [p.strip(" ,\n") for p in re.split(r"[.!?;\n]+", text or "") if p.strip() and not INJECTION.search(p)]
    worst = [p for p in parts if VITAL.search(p) or rules.EMERGENCY.search(p)] or [p for p in parts if SIGN_WORDS.search(p)]
    words = ". ".join(worst or parts[:1])
    if len(words) <= SIGN_MAX:
        return words
    found = VITAL.search(words) or rules.EMERGENCY.search(words) or SIGN_WORDS.search(words)  # a long run-on keeps the part with the danger, not its start
    start = max(0, found.start() - SIGN_MAX // 2) if found else 0
    start = words.find(" ", start) + 1 if start else 0
    return words[start:start + SIGN_MAX].strip(" ,")


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
    return f'{str(sender).capitalize()} {words}: "{sign_of(text)}"\n{line}'


def just_worry(text):
    """Fear, tiredness or a question the log can answer, with no danger sign named. Muse reads the log and answers."""
    text = text or ""
    return bool(SCARED.search(text) or WORN_OUT.search(text) or LOG_QUESTION.search(text)) and not DANGER_SIGN.search(text)


def writes_as_someone_else(parent, text):
    """Why a message reads wrong to the one getting it: "does Ceci take it back?", written to Ceci. Their name opening the line is fine."""
    found = re.search(rf"\b{re.escape(str(parent))}\b", text or "", re.I)
    if found and found.start() > 3:
        return f"Refused, nothing was sent: this goes to {parent}, so write to them as you, not about {str(parent).capitalize()}. Say what you need from them."
    return None


def reports_feed(text):
    return bool(FEED_REPORT.search(text or "")) and "?" not in (text or "")


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
    lang = lang_of(text, lang or "es")
    if about_a_story(text):  # a dose Muse might write is still refused on the way out
        return None
    signs = NOT_A_SIGN.sub(" ", text or "")
    if DENIED.search(text or ""):
        if not VITAL.search(signs):
            return None
        return "emergency", rules.EMERGENCY_REPLY[lang]  # a sign named outranks the words around it, with or without the model
    text = ERRANDS.sub(" ", text or "")
    if rules.is_emergency(text) or rules.spoken_emergency(text) or BUMPED.search(text) or TYPED_FAST.search(text) or (STOPPED.search(text) and not FICTION.search(text)):
        return "emergency", rules.EMERGENCY_REPLY[lang]
    if just_worry(text):
        return None
    if about_someone_else(text):  # not about Theo: Muse answers, and a dose is still refused
        return ("medical", rules.NO_ADVICE[lang]) if rules.asks_dose(text) else None
    if injected(text):  # the screen reads only what isn't an order to it, and only if it says something about him
        text = ". ".join(p for p in re.split(r"[.!?;\n]+", text) if not INJECTION.search(p) and (DANGER_SIGN.search(p) or THEO_NAMED.search(p)))
        if not text:
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
    return " ".join(p + "." for p in parts if len(parts) > 1 and ERRAND.search(p) and not gate(p, _NO_SCREEN))


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


def clock24(found):
    hour = int(found.group(1)) % 12 + (12 if found.group(3).lower() == "p" else 0)
    return f"{hour:02d}:{found.group(2) or '00'}"


def plain(text):
    """Muse writes long dashes, and nobody in this house texts with them. Times read one way, on the 24 hour clock."""
    return AM_PM.sub(clock24, re.sub(r"\s*[\u2014\u2013]\s*", ", ", text or ""))


def outbound(text, lang="es"):
    """(text to send, why it was refused). The final guard drops machinery, a dose or a drug refuses the whole message."""
    if ADVICE_OUT.search(text or ""):
        return None, "Refused, nothing was sent: never a dose, a drug or a diagnosis. Say what you saw or did instead."
    return final_guard.apply(plain(text), lang=lang), None
