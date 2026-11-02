"""Muse Spark Open listens to a cry: a guess at the reason from the sound, never medical (issue #14).

PANNs stays the fast local reflex that hears "a baby is crying". On a cry, only the first few seconds of that cry
(clip_s, 5 s by default) go to Muse Spark Open on Baseten as one WAV made in memory, with a schema that asks for the
likely reason in the categories cry_reason.py uses (hungry, tired, diaper, comfort) and a confidence. The clip is
dropped right after the call. Nothing else leaves the house: no room audio, no other sounds, no recording.

The guess is framed as a guess from the sound alone. It never names pain, illness or any medical cause, and it is
a second opinion next to the log: one added sentence, it does not change the log's ranking.

Audio path guard, measured with real calls on Oct 29 2026 (results/audio-truth): Muse hears speech in an audio part
but not other sounds. It wrote down made-up words and random digits it could not guess, and it answered "I cannot
hear audio" or guessed for beeps, cries, a dog and a doorbell. So before any cry clip is sent, the canary (a synthetic
beep clip, not house audio) must be counted right, and an answer counts only if Muse says it heard a baby crying.
While the canary fails, no cry audio is sent at all and the log-based reason stands alone.
"""
import time

from .agent.brain import BrainError
from .cry_reason import REASONS, no_medical
from .muse_senses import wav_bytes

DEFAULTS = {"enabled": False, "clip_s": 5.0, "canary_every_s": 6 * 3600, "min_confidence": 0.5}

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["heard_sound", "sound", "reason_guess", "confidence"],
    "properties": {
        "heard_sound": {"type": "boolean"},
        "sound": {"type": "string", "enum": ["baby_crying", "other_sound", "silence"]},
        "reason_guess": {"type": "string", "enum": [*REASONS, "cannot_tell"]},
        "confidence": {"type": "number"},
    },
}

SYSTEM = (
    "You listen to a few seconds of sound from the baby monitor in the nursery. You make a guess, not a diagnosis. "
    "You never give medical advice and never name pain, illness or any medical cause.")

TEXT = (
    "This recording is the sound in the nursery right now. Set heard_sound true when you hear it. Is this a baby crying? If it is, guess the most likely everyday reason from the sound alone: hungry (rhythmic, "
    "building, often with sucking or rooting sounds between cries), tired (whiny, on and off, with yawns or rubbing), "
    "diaper (fussy, uncomfortable, squirming), or comfort (wants to be held). Answer cannot_tell when the sound does "
    "not point to one. Give your confidence from 0 to 1.")


class CryEars:
    """Muse's guess for one cry clip, behind the audio canary."""

    def __init__(self, senses, config=None, clock=time.monotonic):
        self.senses, self.clock = senses, clock
        self.cfg = {**DEFAULTS, **(config or {})}
        self.canary_ok, self.canary_at = None, None

    def audio_works(self):
        now = self.clock()
        if self.canary_at is None or now - self.canary_at >= self.cfg["canary_every_s"]:
            self.canary_ok, self.canary_at = self.senses.canary(), now
        return self.canary_ok

    def guess(self, samples, rate=16000):
        """{"reason": ..., "confidence": ..., "heard": bool, ...} or {"skipped": why}. The clip is never kept."""
        if not self.cfg["enabled"]:
            return {"skipped": "muse audio is off in the config"}
        if not self.audio_works():
            return {"skipped": "the audio canary failed, Muse does not hear audio on this endpoint, no clip was sent"}
        clip = samples[:int(self.cfg["clip_s"] * rate)]
        try:
            got = self.senses.ask(SYSTEM, TEXT, SCHEMA, audio_wav=wav_bytes(clip, rate))
        except BrainError as error:
            return {"skipped": f"muse error: {str(error)[:120]}"}
        finally:
            del clip
        return read(got)


def read(got):
    answer = got["answer"]
    heard = answer.get("heard_sound") is True and answer.get("sound") == "baby_crying"
    reason = answer.get("reason_guess") if answer.get("reason_guess") in REASONS else None
    confidence = answer.get("confidence")
    confidence = max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) else 0.0
    return {"heard": heard, "sound": answer.get("sound"), "reason": reason if heard else None,
            "confidence": round(confidence, 2) if heard else 0.0, "seconds": got["seconds"], "usd": got["usd"],
            "usage": got["usage"], "host": got["host"]}


def blend(result, guess, min_confidence=DEFAULTS["min_confidence"]):
    """The log-based result with Muse's sound guess added as one plain sentence. The log's ranking stays as it is:
    the sound guess is a second opinion the parent hears, not a vote, until it is measured on labeled cries."""
    if not guess or not guess.get("reason") or guess["confidence"] < min_confidence:
        return result
    word = "a diaper" if guess["reason"] == "diaper" else guess["reason"]
    text = result["text"] + f" From the sound alone, a guess: {word}."
    if not no_medical(text):
        return result
    out = {**result, "text": text, "sound_guess": {k: guess[k] for k in ("reason", "confidence")}}
    if result.get("text_es"):
        word_es = {"hungry": "hambre", "tired": "sueño", "diaper": "el pañal"}.get(guess["reason"], guess["reason"])
        out["text_es"] = result["text_es"] + f" Solo por el sonido, una pista: {word_es}."
        if not no_medical(out["text_es"]):
            return result
    return out
