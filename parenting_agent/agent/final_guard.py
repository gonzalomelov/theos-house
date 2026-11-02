"""The last step before any text reaches a parent: no machinery, and the parent's own language.

Every path that can carry the brain's words to a parent ends here: the agent's answers (agent/loop.py Agent.say, so the
family agent, the families bot and the demo), the chat channels' sends (channels/messaging.py, which also carries the
pushes) and the glasses (glasses.py replies and cards). Muse sometimes writes its own machinery into an answer:
"finish reason length", "not a JSON object", a tool or event name, its own name, "Parent A" for a rota label, or an
English sentence to a Spanish parent. The guard drops each sentence that holds one, keeps the rest, and says what it
dropped and why, so the event log shows every removal.

What it never touches: the words a parent said that the reply quotes («...» and "..."), and the red flag lines (the
callers skip a reply flagged as an emergency). When nothing is left it answers a short line in the parent's language
asking them to say it again, so a parent never gets an empty message or the machinery.
"""
import re
from dataclasses import dataclass, field

from . import rules

# The agent's machinery: the brain's own words about itself, model and provider names, tool, event and entity names,
# JSON and error text. Union of what the end-to-end day scorer (e2e/score.py) and the glasses cards look for.
INTERNAL = re.compile(
    r"finish[_ ]?reason|reason length|not a JSON|\bJSON\b|invalid answer|\bTraceback\b|\bexception\b|\berror:|"
    r"\bHTTP \d{3}\b|<\||(?-i:(?<=\w[ :=])None\b|\bnull\b)|\btool[_ ]?calls?\b|\[observation from|\bschema\b|\bfallback\b|"
    r"\bfixed routines?\b|\bcomputed from\b|\bplan armed\b|\bsystem prompt\b|\bstanding rules?\b|"
    r"\bhouse\.live\b|\b(?:switch|light|media_player|todo|notify|vacuum|sensor|binary_sensor|input_boolean|script|"
    r"automation|climate|camera|calendar)\.[a-z0-9_]+\b|"
    r"(?<![\w/.@-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b(?![\w/@-]|\.\w)",
    re.I)
# Model and provider names. The public demo names Muse Spark Open on purpose (its page says which model answered), so it
# lets them through, nothing else does.
MODELS = re.compile(r"\bMuse(?: Spark(?: Open)?)?\b|\bClaude\b|\bHaiku\b|\bAnthropic\b|\bBaseten\b|\bOpenAI\b|"
                    r"\bGPT-?\d|\bSAM ?3(?:\.1)?\b|\bMediaPipe\b|\bPANNs\b|\bPerception Encoder\b|\bpe-a-frame\b", re.I)
ROTA = re.compile(r"\bParent [AB]\b")
# The agent's own report of the tools it ran: "Nothing was sent. I only did this: start changing table." (live on the
# lens, Oct 31). Dropped up to the end of its sentence, before sentences are split on the colon.
TOOL_REPORT = re.compile(r"\b(?:I\s+)?(?:only|just)\s+did(?:\s+(?:this|these|that))?\s*:[^.!?\n]*[.!?]?|"
                         r"\b(?:Solo|Sólo|Nada más)\s+hice(?:\s+esto)?\s*:[^.!?\n]*[.!?]?|"
                         r"\b(?:Tools?|Actions?) (?:run|ran|called|used)\s*:[^.!?\n]*[.!?]?", re.I)
JSONISH = re.compile(r"```.*?```|\{\s*\"[^\"]+\"\s*:.*?\}|\[\s*\{.*?\}\s*\]", re.S)
QUOTED = re.compile(r"«[^»]*»|\"[^\"\n]*\"|“[^”\n]*”")
SENTENCE = re.compile(r"(?<=[.!?:;])\s+")
FALLBACK = {"es": "Perdón, no me salió bien la respuesta. ¿Me lo decís de nuevo?",
            "en": "Sorry, that answer did not come out right. Can you say it again?"}


@dataclass
class Guarded:
    text: str
    removed: list = field(default_factory=list)  # [{"why": ..., "text": ...}]
    fallback: bool = False

    @property
    def changed(self):
        return bool(self.removed) or self.fallback


def wrong_language(sentence, lang):
    """True when a sentence is in the other language: English to a Spanish parent, Spanish to an English one. Checked
    with the parent's quoted words left out, and only on sentences of three words or more."""
    body = QUOTED.sub(" ", sentence)
    if len(re.findall(r"[^\W\d_]+", body)) < 3:
        return False
    english_words = len(rules.ENGLISH.findall(body))
    if lang == "es":
        return not rules.looks_spanish(body) and english_words >= 2
    if lang == "en":
        return rules.looks_spanish(body) and english_words < 2
    return False


def why_internal(sentence, models_ok=False):
    body = QUOTED.sub(" ", sentence)
    found = INTERNAL.search(body) or (None if models_ok else MODELS.search(body))
    return f"internal: {found.group(0)}" if found else None


def why_of(sentence, lang, allowed=(), models_ok=False):
    """Why a sentence must not reach the parent, or None. allowed are names that look like rota labels on purpose."""
    why = why_internal(sentence, models_ok)
    if why is None and any(m.group(0) not in allowed for m in ROTA.finditer(QUOTED.sub(" ", sentence))):
        why = "internal: rota label"
    if why is None and wrong_language(sentence, lang):
        why = f"not in {'Spanish' if lang == 'es' else 'English'}"
    return why


def guard(text, lang=None, names=None, models_ok=False):
    """The text with every internal or wrong-language sentence removed. lang is "es", "en" or None (language left as it
    is). names maps rota labels to what this parent reads ({"Parent A": "Gonza"}): a label with no name is internal."""
    original = str(text or "")
    removed = []
    for label, name in (names or {}).items():
        original = re.sub(rf"\b{re.escape(label)}\b", name, original)
    allowed = set((names or {}).values())  # the demo's simulated parents are named "Parent A" on purpose

    def drop_json(match):
        removed.append({"why": "internal: JSON or code", "text": match.group(0)[:200]})
        return " "
    def drop_tools(match):
        removed.append({"why": "internal: tool report", "text": match.group(0)[:200]})
        return " "
    body = TOOL_REPORT.sub(drop_tools, JSONISH.sub(drop_json, original))
    lines = []
    for line in body.split("\n"):
        pieces = [[sentence.strip(), why_of(sentence, lang, allowed, models_ok)] for sentence in SENTENCE.split(line)
                  if sentence.strip()]
        for here, after in zip(pieces, pieces[1:]):
            if here[1] is None and here[0].endswith(":") and after[1] is not None:
                here[1] = "the label of a removed line"  # "La casa de noche:" with nothing after it
        removed += [{"why": why, "text": piece[:300]} for piece, why in pieces if why]
        kept = [piece for piece, why in pieces if not why]
        if kept or not line.strip():
            lines.append(" ".join(kept))
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not removed:
        return Guarded(original)
    if not re.search(r"[^\W_]", out):
        fallback_lang = lang or ("es" if rules.looks_spanish(original) else "en")
        return Guarded(FALLBACK[fallback_lang], removed, fallback=True)
    return Guarded(out, removed)


DECIMAL_HOURS = re.compile(r"\b(\d{1,2})[.,](\d{1,2})\s*(?:h|hs|hrs?|hours?|horas?)\b", re.I)


def plain_hours(text):
    """"1.1 h" or "12,3 horas" in any reply reads "1 h 6 min" or "12 h 18 min" (blind round b7)."""
    def words(match):
        minutes = round(float(f"{match.group(1)}.{match.group(2)}") * 60)
        h, m = divmod(minutes, 60)
        return (f"{h} h {m} min" if m else f"{h} h") if h else f"{m} min"
    return DECIMAL_HOURS.sub(words, text) if isinstance(text, str) else text


SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def no_repeats(text):
    """A sentence said twice, or a cut one said again in full, is said once (blind round b7: a reply cut off mid-sentence
    and then repeated)."""
    if not isinstance(text, str) or not text:
        return text
    parts = SENTENCE_END.split(text.strip())
    cut = False
    for i, part in enumerate(parts):
        again = part.find(part[:24], 1) if len(part) >= 48 and "\n" not in part else -1
        if again > 0:
            parts[i], cut = part[again:], True  # "se dur Le di la teta... se durmió.": the cut start, then the whole one
    key = [re.sub(r"\W+", " ", p).strip().lower() for p in parts]
    kept = [p for i, p in enumerate(parts)
            if key[i] and key[i] not in key[:i] and not any(k != key[i] and k.startswith(key[i]) and len(key[i]) >= 20
                                                             for k in key[i + 1:])]
    return " ".join(kept) if cut or len(kept) < len(parts) else text


def apply(text, lang=None, bus=None, where="", names=None, log_text=True, models_ok=False, **about):
    """guard() and, when it changed anything, one "final_guard" event on the bus saying what it removed and why.
    log_text=False keeps only the reasons and sizes (the families bot never logs a family's words)."""
    text = no_repeats(plain_hours(text))
    result = guard(text, lang, names, models_ok)
    if result.changed and bus is not None:
        removed = result.removed if log_text else [{"why": r["why"], "chars": len(r["text"])} for r in result.removed]
        bus.publish("final_guard", where=where, lang=lang, removed=removed, fallback=result.fallback,
                    **({"sent": result.text} if log_text else {}), **about)
    return result.text
