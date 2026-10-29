"""Screens what the ear wrote down before the agent echoes it or acts on it.

Muse is asked to write down a voice note, but it sometimes answers the question it heard instead (round 2 red team:
"Para un bebé de 5 kilos la dosis de paracetamol es de 75 mg cada 6 horas, no hace falta ir al pediatra."). That text
is Muse's own advice, not the parent's words, so it is never shown as "what you said" and never handed to the agent.
The parent gets "No te entendí bien, ¿me lo repetís?" with the health line instead.

A real transcript can hold a dose too ("le di 2.5 ml de paracetamol"). It is handled, but never echoed: the reply
goes out without the heard words above it.

It lives apart from ear.py, so the ear's prompt and the screen change independently.
"""
import io
import re
import wave

from ..agent import rules

# Muse answering, not transcribing: it speaks to the parent, recommends, or reasons about weight and intervals.
SECOND_PERSON = re.compile(
    r"\b(you should|you can give|you could give|you need to|you may|i recommend|i would recommend|i suggest|it is "
    r"recommended|is recommended|do not need to|don'?t need to|there is no need|no need to|"
    r"deber[ií]as|deb[eé]s|ten[eé]s que|tienes que|pod[eé]s darle|puedes darle|pod[eé]s dar|te recomiendo|le recomiendo|"
    r"se recomienda|recomendad[oa]|no hace falta|no es necesario|no necesit[aá]s|no necesitas|consult[aá] con|"
    r"lo ideal es|lo mejor es|lo normal es|es normal que)\b", re.I)
ADVICE_SHAPE = re.compile(
    r"\b(para un beb[eé] de \d+|for a baby (of|weighing) \d+|\d+\s*(mg|ml)\s*(/|por|per)\s*(kg|kilo)|"
    r"cada \d+\s*(a \d+\s*)?horas|every \d+\s*(to \d+\s*)?hours|la dosis (es|recomendada|habitual|correcta)|"
    r"the (usual |right |correct |recommended )?dose (is|for))\b", re.I)
DOSE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(mg|ml|cc|gotas|drops|mcg|ui|iu)\b|\b(dosis|dose|dosage)\b", re.I)
# A parent says about 2 to 3 words a second. More text than the audio could hold was not heard, it was written.
CHARS_PER_SECOND = 25
SLACK_CHARS = 40

REPEAT = {"es": "No te entendí bien, ¿me lo repetís?", "en": "I did not catch that well, could you say it again?"}


def wav_seconds(wav):
    """The length of a WAV in seconds, or None when it is not a WAV this can read."""
    try:
        with wave.open(io.BytesIO(wav)) as audio:
            return audio.getnframes() / float(audio.getframerate())
    except (wave.Error, EOFError, ValueError, ZeroDivisionError, TypeError):
        return None


def has_dose(text):
    """A medicine with an amount or the word dose: never echoed as heard words."""
    return bool(rules.mentions_medicine(text) and DOSE.search(text or ""))


def answered(text, seconds=None):
    """The reason the ear's text is an answer and not a transcript, or None when it reads as the parent's words."""
    text = text or ""
    if SECOND_PERSON.search(text):
        return "second_person"
    if ADVICE_SHAPE.search(text):
        return "advice_shape"
    if has_dose(text) and not rules.GAVE.search(text):
        return "dose_not_given"
    if seconds is not None and len(text) > CHARS_PER_SECOND * seconds + SLACK_CHARS:
        return "too_long"
    return None


def screen(text, seconds=None):
    """("answer", reason) when the ear answered instead of writing down, ("no_echo", "dose") for a real transcript
    with a dose, ("ok", None) otherwise."""
    reason = answered(text, seconds)
    if reason:
        return "answer", reason
    if has_dose(text):
        return "no_echo", "dose"
    return "ok", None


def not_understood(lang):
    """What the parent gets instead of the ear's answer: ask again, and the health route."""
    lang = "es" if lang == "es" else "en"
    return f"{REPEAT[lang]} {rules.NO_ADVICE[lang]}"
