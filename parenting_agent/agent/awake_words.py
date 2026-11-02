"""What a parent's message says about the baby waking, shared by the night feed and the rules (the demo and families
images carry no night_feed.py, blind round b7 broke on that import)."""
import re

BABY_EN = r"(?:theo|he|the baby|baby|the little one)"
EN_AWAKE = re.compile(r"\b" + BABY_EN + r"(?:'s|’s| is| has| just| now| already)*\s*(?:up|awake|woken|woke|waking|crying|cries|cried|"
                      r"fussing|fussy|stirring|hungry)\b", re.I)
# Spanish leaves the subject out: "se despertó" is him (or a named someone), "me desperté" is the speaker. Only third
# person forms count.
ES_AWAKE = re.compile(r"\b(?:se\s+(?:est[áa]\s+)?(?:despert[óo]|despierta|despertando|levant[óo]|levanta|levantando)|"
                      r"est[áa]\s+(?:despierto|despertando|llorando|inquieto|molesto)|llor(?:a|ó|ando)|"
                      r"despert[óo]|tiene hambre)\b", re.I)
FEED_RE = re.compile(r"\b(feeding|starting (a |the )?(bottle|feed)|making (a |the )?bottle|nursing)\b|"
                     r"\b(?:d[áa]ndo(?:le)?|le doy|preparando|calentando)\s+(?:la |el |una )?(?:mamadera|biber[óo]n|teta|"
                     r"pecho|leche)\b|\bdando de mamar\b|\bempezando (?:la |una )?toma\b", re.I)
NOT_RE = re.compile(r"\b(not|n't|still asleep|sleeping|no|todav[íi]a duerme|sigue durmiendo|dormido|durmiendo)\b", re.I)
BABY_WORD = re.compile(r"\b(theo|baby|bebé|bebe|nene)\b", re.I)
# Someone else as the subject: the dog, the cat, the speaker in English, or a person named in the config.
OTHER_RE = re.compile(r"\b(dog|dogs|puppy|perro|perra|perrito|cat|gato|gata)\b", re.I)
I_EN = re.compile(r"\b(I|I'm|I’m|we|we're)\b")
QUESTION_RE = re.compile(r"[?¿]|^\s*(when|what|how|is|was|did|does|should|can|will|cu[áa]ndo|qu[ée]|c[óo]mo)\b", re.I)


def awake_message(text, others=()):
    """What a parent's message says about the baby: "awake", "feed" (a feed is starting) or None (a question, a
    "not up yet", the speaker or the dog waking, anything else). others are names that are not the baby, the parents
    from the people block: "Ceci se levantó" is not him."""
    text = (text or "").strip()
    if not text or QUESTION_RE.search(text) or NOT_RE.search(text):
        return None
    named = any(re.search(rf"\b{re.escape(name)}\b", text, re.I) for name in others if name)
    if (OTHER_RE.search(text) or named) and not BABY_WORD.search(text):
        return None
    if FEED_RE.search(text):
        return "feed"
    if EN_AWAKE.search(text):
        return "awake"
    if ES_AWAKE.search(text) and not I_EN.search(text):
        return "awake"
    return None
