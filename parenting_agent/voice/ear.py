"""The ear: Muse Spark Open hears a voice note as audio input and writes down what was said.

One call to the OpenAI-compatible endpoint on Baseten with an input_audio part. Checked with real calls on
Oct 28 2026: WAV and MP3 are accepted, OGG is refused with HTTP 400, so voice notes are converted to WAV first.
Checked again on Oct 29 2026 (results/audio-truth): Muse wrote down made-up words and random digits it could not
guess, and the prompt tokens grow with the note's length. usage.prompt_tokens_details.audio_tokens reads 0 even then,
so it is not a sign of hearing. The example values in the prompt match no test note.

Muse sometimes answers as if no audio came with the message ("No tengo acceso al audio", "I don't have access to
audio files") to a request that works the other times: 2 of 20 notes in the first full run on Oct 28. Such an answer is never
taken as the parent's words: the ear asks again, up to 3 times in all.
"""
import base64
import os
import re
import time
import urllib.parse

from ..agent.brain import BrainError, post_json

MODEL = "meta-models/muse-spark-open-1026"
BASE_URL = "https://inference.baseten.co/v1"
PROMPT = ("This is a voice note from a parent to their baby care assistant, in Spanish (often rioplatense, from "
          "Uruguay or Argentina) or English. Write down exactly what the parent said, in the language they spoke, "
          "with numbers as digits (35 ml, a las 11). Reply with the words only: no quotes, no translation, no comment. "
          "If there is no speech, reply with nothing.")


ABOUT_AUDIO = re.compile(r"audio|transcri|grabaci|recording|archivo|file", re.I)
# Words a parent does not say to log a baby note, but Muse says when it answers about the audio instead.
ABOUT_TASK = re.compile(r"transcri|grabaci[oó]n|recording|archivo de audio|audio file|adjunt|attach|upload|"
                        r"envi[aá](me)? el audio|send (me )?the audio", re.I)
CANNOT = re.compile(r"can.?t|cannot|don.?t have|unable|not able|no tengo|no puedo|no se pudo|no pude|necesit|need|sin acceso", re.I)


def refused(text):
    """True when Muse answered about the audio instead of writing it down."""
    return bool(ABOUT_TASK.search(text) or (ABOUT_AUDIO.search(text) and CANNOT.search(text))) or len(text) > 600


class Ear:
    name = "muse"

    def __init__(self, model=MODEL, base_url=BASE_URL, key_env="BASETEN_API_KEY", reasoning_effort="low",
                 max_tokens=1500, timeout=60, attempts=3):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.key_env, self.model, self.reasoning_effort = key_env, model, reasoning_effort
        self.max_tokens, self.timeout = max_tokens, timeout
        self.destination = urllib.parse.urlparse(self.url).hostname
        self.usage = None
        self.attempts = attempts
        self.tries = 0
        self.calls = []

    def hear(self, wav):
        """The words in a WAV voice note, or "" when there is no speech. Raises BrainError when Muse fails."""
        self.usage = None
        key = os.environ.get(self.key_env)
        if not key:
            raise BrainError(f"ear: {self.key_env} is not set")
        audio = {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}
        body = {"model": self.model, "max_tokens": self.max_tokens, "reasoning_effort": self.reasoning_effort,
                "messages": [{"role": "user", "content": [{"type": "text", "text": PROMPT}, audio]}]}
        started = time.monotonic()
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.calls = []
        text = ""
        for self.tries in range(1, self.attempts + 1):
            reply = post_json(self.url, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, body, self.timeout)
            usage = reply.get("usage") or {}
            self.usage["input_tokens"] += usage.get("prompt_tokens", 0)
            self.usage["output_tokens"] += usage.get("completion_tokens", 0)
            message = ((reply.get("choices") or [{}])[0]).get("message") or {}
            text = clean(message.get("content") or "")
            self.calls.append({"prompt_tokens": usage.get("prompt_tokens"),
                               "audio_tokens": (usage.get("prompt_tokens_details") or {}).get("audio_tokens"),
                               "completion_tokens": usage.get("completion_tokens"), "answer": text[:200],
                               "taken": bool(text and not refused(text))})
            if text and not refused(text):
                break
            text = ""
        self.seconds = round(time.monotonic() - started, 3)
        return text


def clean(text):
    text = text.strip()
    for prefix in ("Transcription:", "Transcripción:", "Transcript:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    return text.strip().strip('"“”«»').strip()
