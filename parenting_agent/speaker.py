"""Speaker: plays the chime and the spoken prompt on this Mac and sends them to the head camera page.

On macOS the chime is a system sound through afplay and the prompt uses say. Elsewhere, or with
quiet=True, it only forwards events. Playback never blocks the reflex loop.
"""
import shutil
import subprocess
import sys

CHIME = "/System/Library/Sounds/Tink.aiff"


class Speaker:
    def __init__(self, source=None, quiet=False):
        self.source = source
        self.local = not quiet and sys.platform == "darwin" and shutil.which("say") is not None

    def on_event(self, event):
        if self.source is not None:
            self.source.push({"kind": event["kind"], "text": event.get("text")})
        if not self.local:
            return
        if event["kind"] == "chime":
            subprocess.Popen(["afplay", CHIME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif event["kind"] == "voice":
            subprocess.Popen(["say", event.get("text") or "hand"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
