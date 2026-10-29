"""One interface for the ears and the voice, in process (the Mac) or through the voice service (the Vostro).

Config block "voice" in the agent config:
    {"service": "local" or "http://voice:8800" or "none", "ear": {"model": ..., "key_env": "BASETEN_API_KEY"},
     "reply_with_voice": true}
"local" runs ffmpeg and MMS-TTS in this process. A URL reaches the voice service directly, never through the
egress proxy. "none" turns voice notes off: they get a short "please type it" answer.
"""
import json
import threading
import urllib.error
import urllib.request

from ..agent import rules
from ..agent.brain import BrainError
from . import audio, words
from . import screen
from .ear import Ear

# A spoken answer is the first sentences only: the text has the rest. On the Vostro CPU a sentence takes about 10 s.
MAX_SPOKEN_SENTENCES = 3


class VoiceError(Exception):
    pass


def lang_of(text):
    return "es" if rules.looks_spanish(text) else "en"


class LocalVoice:
    def __init__(self):
        from .tts import MmsVoice
        self.tts = MmsVoice()

    def to_wav(self, data):
        try:
            return audio.to_wav(data)
        except audio.AudioError as error:
            raise VoiceError(str(error)) from None

    def speak(self, text, lang, fmt="ogg"):
        try:
            wav, _ = self.tts.synth(text, lang)
            return wav if fmt == "wav" else audio.to_ogg_opus(wav)
        except (audio.AudioError, ValueError) as error:
            raise VoiceError(str(error)) from None


class RemoteVoice:
    """The voice service on the internal network. No proxy: the egress proxy would refuse it anyway."""

    def __init__(self, url, timeout=120):
        self.url, self.timeout = url.rstrip("/"), timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self, path, body, kind):
        request = urllib.request.Request(self.url + path, data=body, headers={"Content-Type": kind}, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise VoiceError(f"voice service {path} HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise VoiceError(f"voice service {path} failed: {type(error).__name__}") from None

    def to_wav(self, data):
        return self.post("/wav", data, "application/octet-stream")

    def speak(self, text, lang, fmt="ogg"):
        return self.post("/speak", json.dumps({"text": text, "lang": lang, "format": fmt}).encode(), "application/json")


class Voice:
    """Hears a voice note with Muse and speaks a reply with MMS-TTS."""

    def __init__(self, backend, ear, reply_with_voice=True):
        self.backend, self.ear, self.reply_with_voice = backend, ear, reply_with_voice
        self.seconds = None

    def hear(self, data):
        """The words in a voice note. Raises VoiceError when it could not be converted or heard. seconds keeps the
        note's length, so the screen can tell a transcript from an answer too long for the audio."""
        wav = self.backend.to_wav(data)
        self.seconds = screen.wav_seconds(wav)
        try:
            return self.ear.hear(wav)
        except BrainError as error:
            raise VoiceError(f"ear: {str(error)[:150]}") from None

    def speak(self, text, lang=None, fmt="ogg"):
        short = " ".join(words.sentences(text)[:MAX_SPOKEN_SENTENCES]) or text
        return self.backend.speak(short, lang or lang_of(text), fmt)


def in_background(work, *args):
    """Speaking takes seconds on a CPU, so a voice reply never holds up the agent or the next message."""
    thread = threading.Thread(target=work, args=args, name="voice-reply", daemon=True)
    thread.start()
    return thread


def build(config):
    """A Voice from the agent's "voice" block, or None when voice notes are off."""
    config = config or {}
    service = config.get("service", "none")
    if service == "none":
        return None
    backend = LocalVoice() if service == "local" else RemoteVoice(service)
    return Voice(backend, Ear(**config.get("ear", {})), config.get("reply_with_voice", True))
