"""Muse Spark Open's eyes and ears: one still frame or one short clip, one strict JSON answer (issues #30 and #14).

Muse Spark Open on Baseten takes images and audio next to text. This client sends exactly one image (a JPEG made
in memory from a camera frame) or one audio clip (a WAV made in memory from the cry samples) with a prompt and a
JSON schema, and returns the parsed answer with the tokens, the price and the seconds it took.

Nothing is written to disk. The frame or clip goes only to the configured brain host (inference.baseten.co), which
is the one call allowed to leave the house. Spend is computed from the tokens the call reports, at the brain's price.

Audio, measured with real calls on Oct 29 2026 (results/audio-truth): Muse hears speech in an audio part. It wrote
down made-up words and random digits it could not guess, in Spanish and English, and prompt_tokens grows with the
clip's length (about 13 tokens a second) while usage.prompt_tokens_details.audio_tokens always reads 0, so that field
says nothing about hearing. Two things make it answer "no audio" anyway: a system message, and a prompt that offers
"if no audio reaches you" as a way out. So an audio question goes as one user message, the instruction first, then an
input_audio part. Muse does not hear sounds that are not speech: beeps, a cry, a dog or a doorbell all get "I cannot
hear audio" or a guess. heard() and canary() guard that: an audio answer counts only if Muse says it heard sound, and
the beep canary must be counted right before a sound guess is trusted.
"""
import base64
import io
import json
import math
import os
import time
import urllib.parse
import wave

import numpy as np

from .agent.brain import BrainError, post_json, without_thinking

DEFAULTS = {
    "model": "meta-models/muse-spark-open-1026",
    "base_url": "https://inference.baseten.co/v1",
    "key_env": "BASETEN_API_KEY",
    "reasoning_effort": "low",
    "max_tokens": 4000,
    "timeout_s": 60,
    "price_in_per_mtok": 1.25,
    "price_out_per_mtok": 4.25,
}


def jpeg_data_url(frame, quality=85):
    """A BGR numpy frame as a JPEG data URL, made in memory."""
    import cv2
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("could not encode the frame")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def wav_bytes(samples, rate=16000):
    """Mono float samples in -1..1 as 16-bit WAV bytes, made in memory."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def beeps(count, rate=16000, tone_hz=1000, beep_s=0.25, gap_s=0.35):
    """A clip with an exact number of beeps, the canary for the audio path."""
    samples = []
    for _ in range(count):
        samples += [0.5 * math.sin(2 * math.pi * tone_hz * i / rate) for i in range(int(beep_s * rate))]
        samples += [0.0] * int(gap_s * rate)
    return wav_bytes(samples, rate)


CANARY_SYSTEM = "You listen to a short sound recording from a home baby monitor."
CANARY_TEXT = ("This recording is a test tone that beeps a few times. Count the beeps. Set heard_sound true when you "
               "hear the tone.")


class MuseSenses:
    def __init__(self, config=None, post=post_json, clock=time.monotonic):
        self.cfg = {**DEFAULTS, **(config or {})}
        self.url = self.cfg["base_url"].rstrip("/") + "/chat/completions"
        self.destination = urllib.parse.urlparse(self.url).hostname
        self.post, self.clock = post, clock
        self.spent_usd, self.calls = 0.0, 0

    def _headers(self):
        key = os.environ.get(self.cfg["key_env"])
        if not key:
            raise BrainError(f"muse senses: {self.cfg['key_env']} is not set")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def body(self, system, text, schema, image_url=None, audio_wav=None):
        if audio_wav is not None:
            # Audio: one user message, the instruction first, then the clip. A system message makes Muse say it heard
            # nothing, so the system text leads the instruction instead.
            content = [{"type": "text", "text": f"{system}\n\n{text}"},
                       {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio_wav).decode(), "format": "wav"}}]
            messages = [{"role": "user", "content": content}]
        else:
            # An image first, then the question: the order Baseten's vision guide uses.
            content = ([{"type": "image_url", "image_url": {"url": image_url}}] if image_url else []) + [{"type": "text", "text": text}]
            messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        body = {"model": self.cfg["model"], "max_tokens": self.cfg["max_tokens"], "messages": messages,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "answer", "strict": True, "schema": schema}}}
        if self.cfg.get("reasoning_effort"):
            body["reasoning_effort"] = self.cfg["reasoning_effort"]
        return body

    def ask(self, system, text, schema, image_url=None, audio_wav=None):
        """{"answer": dict, "usage": {...}, "usd": float, "seconds": float, "host": str}. Raises BrainError."""
        started = self.clock()
        reply = self.post(self.url, self._headers(), self.body(system, text, schema, image_url, audio_wav),
                          self.cfg["timeout_s"])
        seconds = round(self.clock() - started, 3)
        choice = (reply.get("choices") or [{}])[0]
        raw = without_thinking((choice.get("message") or {}).get("content"))
        usage = reply.get("usage") or {}
        tokens_in, tokens_out = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        usd = (tokens_in * self.cfg["price_in_per_mtok"] + tokens_out * self.cfg["price_out_per_mtok"]) / 1_000_000
        self.spent_usd += usd
        self.calls += 1
        if not raw:
            raise BrainError(f"muse senses: empty answer (finish_reason {choice.get('finish_reason')})")
        try:
            answer = json.loads(raw)
        except json.JSONDecodeError as error:
            raise BrainError(f"muse senses: answer is not JSON: {raw[:120]}") from error
        if not isinstance(answer, dict):
            raise BrainError("muse senses: answer is not a JSON object")
        return {"answer": answer, "seconds": seconds, "usd": round(usd, 6), "host": self.destination,
                "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out,
                          "audio_tokens": (usage.get("prompt_tokens_details") or {}).get("audio_tokens", 0),
                          "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}}

    def canary(self, count=3):
        """True when Muse hears a clip of known beeps and counts them right. Audio guesses are trusted only then."""
        schema = {"type": "object", "additionalProperties": False, "required": ["heard_sound", "beeps"],
                  "properties": {"heard_sound": {"type": "boolean"}, "beeps": {"type": "integer"}}}
        try:
            got = self.ask(CANARY_SYSTEM, CANARY_TEXT, schema, audio_wav=beeps(count))
        except BrainError:
            return False
        return bool(got["answer"].get("heard_sound")) and got["answer"].get("beeps") == count
