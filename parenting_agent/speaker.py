"""Speaker: plays the chime and the spoken prompt on this Mac and sends them to the head camera page.

On macOS the chime is a system sound through afplay. The prompt uses say, or Meta's MMS-TTS when voice="mms" or
PA_SPEAKER_VOICE=mms (parenting_agent/voice/tts.py, needs torch and transformers). Both play on the default output
device, so AirPods work when they are the output. Elsewhere, or with quiet=True, it only forwards events.
Playback never blocks the reflex loop: MMS speaks from a thread, and the first prompt is synthesized at start.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading

CHIME = "/System/Library/Sounds/Tink.aiff"
WARM = ("hand",)


class Speaker:
    def __init__(self, source=None, quiet=False, voice=None, lang="en"):
        self.source = source
        self.local = not quiet and sys.platform == "darwin" and shutil.which("say") is not None
        self.lang = lang
        self.mms = None
        if self.local and (voice or os.environ.get("PA_SPEAKER_VOICE")) == "mms":
            from .voice.tts import MmsVoice
            self.mms = MmsVoice()
            threading.Thread(target=self.warm, daemon=True).start()

    def warm(self):
        for text in WARM:
            self.mms.synth(text, self.lang)

    def say(self, text):
        """Speaks text on the default output. Returns at once."""
        if self.mms is None:
            subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        threading.Thread(target=self.play_mms, args=(text,), daemon=True).start()

    def play_mms(self, text):
        wav, _ = self.mms.synth(text, self.lang)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out:
            out.write(wav)
        try:
            subprocess.run(["afplay", out.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        finally:
            os.unlink(out.name)

    def on_event(self, event):
        if self.source is not None:
            self.source.push({"kind": event["kind"], "text": event.get("text")})
        if not self.local:
            return
        if event["kind"] == "chime":
            subprocess.Popen(["afplay", CHIME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif event["kind"] == "voice":
            self.say(event.get("text") or "hand")
