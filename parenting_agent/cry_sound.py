"""The cry reason from the sound: the head and the wording, kept for the record (issues #161 and the Oct 31 Meta swap).

On Oct 30 a small softmax head (5 x 2048 weights in parenting_agent/assets/cry_reason_head.json) was trained on PANNs
CNN14 embeddings of the Donate-a-Cry corpus (ODbL 1.0, contents DbCL 1.0) to read a cry as hungry, tired, discomfort,
burping or belly_pain. It was at chance on its held-out test (balanced accuracy 0.19, chance 0.20,
results/cry-reason/README.md), so no class was ever said. On Oct 31 PANNs left the runtime because it is not a Meta
model, and the head went with it: the agent never computes an embedding. The cry reason the parent hears comes from
the baby log alone (cry_reason.py).

What stays here:
- Head: fit, load and probs, used offline by scripts/cry_reason_train.py to reproduce the Oct 30 result.
- combine: how any sound guess would be blended with the log reason, used by house_sounds.py for the guess the
  plug-in gets (Muse's opt-in guess goes through cry_muse.blend first). The log's reason stays first. A class is said
  only when the guess says it may be ("speak"). belly_pain is never said as pain: it becomes "check on him now", and
  with a red flag in the baby log of the last 24 h the fixed call-the-doctor line from agent/rules.py follows.
"""
import datetime
import json
from pathlib import Path

import numpy as np

from .agent import rules
from .cry_reason import no_medical
from .rhythm.log import ordered, when

HEAD = Path(__file__).with_name("assets") / "cry_reason_head.json"
CLASSES = ("hungry", "tired", "discomfort", "burping", "belly_pain")
# What each tag becomes for the parent, and the log reason (cry_reason.REASONS) it agrees with.
WORDS = {"hungry": "hungry", "tired": "tired", "discomfort": "uncomfortable, a diaper or too warm or cold",
         "burping": "a burp", "belly_pain": None}
AGREES = {"hungry": "hungry", "tired": "tired", "discomfort": "diaper"}
CHECK_NOW = "The cry sounds like ones parents tagged as hard crying. Check on {p} now."
# The same lines in Spanish (es-UY), for a parent who reads Spanish. Never pain, never a diagnosis.
WORDS_ES = {"hungry": "hambre", "tired": "sueño", "discomfort": "incomodidad, el pañal o calor o frío",
            "burping": "un provechito", "belly_pain": None}
CHECK_NOW_ES = "El llanto suena como los que otros padres marcaron como llanto fuerte. Fijate cómo está ahora."
AGREES_ES = "El sonido coincide."
GUESS_ES = "Solo por el sonido, una pista: {word}."


def softmax(z):
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


class Head:
    """Standardize, then a linear layer and a softmax. Trained by scripts/cry_reason_train.py."""

    def __init__(self, mean, std, weights, bias, classes=CLASSES, meta=None):
        self.mean, self.std = np.asarray(mean, np.float32), np.asarray(std, np.float32)
        self.w, self.b = np.asarray(weights, np.float32), np.asarray(bias, np.float32)
        self.classes, self.meta = tuple(classes), meta or {}

    def probs(self, x):
        x = (np.atleast_2d(x) - self.mean) / self.std
        return softmax(x @ self.w + self.b)

    @classmethod
    def fit(cls, x, y, l2=0.1, balanced=True, steps=600, lr=0.05, classes=CLASSES):
        """Softmax regression by full batch Adam, with an L2 penalty and optional class weights. y holds class indexes."""
        x, y = np.asarray(x, np.float32), np.asarray(y)
        mean, std = x.mean(axis=0), x.std(axis=0) + 1e-3
        z = (x - mean) / std
        k = len(classes)
        onehot = np.eye(k, dtype=np.float32)[y]
        counts = np.bincount(y, minlength=k).astype(np.float32)
        weight = (len(y) / (k * np.maximum(counts, 1)))[y] if balanced else np.ones(len(y), np.float32)
        weight = weight / weight.sum()
        w, b = np.zeros((z.shape[1], k), np.float32), np.zeros(k, np.float32)
        state = [np.zeros_like(w), np.zeros_like(w), np.zeros_like(b), np.zeros_like(b)]
        for step in range(1, steps + 1):
            p = softmax(z @ w + b)
            g = (p - onehot) * weight[:, None]
            gw, gb = z.T @ g + l2 * w / len(y), g.sum(axis=0)
            for i, (grad, param) in enumerate(((gw, w), (gb, b))):
                m, v = state[2 * i], state[2 * i + 1]
                m[:] = 0.9 * m + 0.1 * grad
                v[:] = 0.999 * v + 0.001 * grad ** 2
                param -= lr * (m / (1 - 0.9 ** step)) / (np.sqrt(v / (1 - 0.999 ** step)) + 1e-8)
        return cls(mean, std, w, b, classes)

    def to_json(self, meta):
        r = lambda a: np.round(np.asarray(a, np.float64), 5).tolist()  # noqa: E731
        return {"meta": meta, "classes": list(self.classes), "mean": r(self.mean), "std": r(self.std),
                "weights": r(self.w), "bias": r(self.b)}

    @classmethod
    def load(cls, path=None):
        data = json.loads(Path(path or HEAD).read_text())
        return cls(data["mean"], data["std"], data["weights"], data["bias"], data["classes"], data.get("meta"))


def red_flag_in_log(entries, now, hours=24):
    """The newborn red flag kind ("fever" or "red_flag") or "emergency" in a note or a field note of the last hours."""
    since = now - datetime.timedelta(hours=hours)
    for entry in reversed(ordered(entries, now)):
        if when(entry) < since:
            break
        text = " ".join(str(entry.get(k) or "") for k in ("note", "notes"))
        if not text.strip():
            continue
        if rules.is_emergency(text):
            return "emergency"
        kind = rules.newborn_red_flag(text)
        if kind:
            return kind
    return None


def combine(result, guess, entries, now, pronoun="he"):
    """The log-based result (cry_reason.explain) with the sound guess as one more signal. The log's ranking stays."""
    if not guess or "label" not in guess:
        return result
    label = guess["label"]
    out = {**result, "sound": {k: guess[k] for k in ("label", "confidence", "speak")}}
    if label == "belly_pain" and guess["speak"]:
        flag = red_flag_in_log(entries, now)
        line = rules.EMERGENCY_REPLY["en"] if flag == "emergency" else (
            rules.URGENT_REPLY[flag]["en"] if flag else None)
        text = CHECK_NOW.format(p="him" if pronoun == "he" else "her" if pronoun == "she" else "them")
        text += " " + result["text"]
        if line:
            text += " " + line
        out.update(text=text, check_now=True, safety_line=bool(line))
        if result.get("text_es"):
            line_es = rules.EMERGENCY_REPLY["es"] if flag == "emergency" else (
                rules.URGENT_REPLY[flag]["es"] if flag else None)
            out["text_es"] = " ".join(t for t in (CHECK_NOW_ES, result["text_es"], line_es) if t)
        return out
    if not guess["speak"] or WORDS.get(label) is None:
        return out
    agrees = AGREES.get(label) == result["top"] and result.get("likely")
    if agrees:
        text = result["text"] + " The sound agrees."
    else:
        text = result["text"] + f" From the sound alone, a guess: {WORDS[label]}."
    text_es = result["text_es"] + " " + (AGREES_ES if agrees else GUESS_ES.format(word=WORDS_ES[label])) \
        if result.get("text_es") else None
    if no_medical(text) and (text_es is None or no_medical(text_es)):
        out["text"] = text
        if text_es is not None:
            out["text_es"] = text_es
    return out
