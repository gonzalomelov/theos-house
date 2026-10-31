"""BEFORE BASELINE ONLY, never imported by parenting_agent: the PANNs listener the Ear used until Oct 31 2026.

PANNs CNN14 is not a Meta model, so the agent no longer calls it at runtime. Offline scripts import this to reproduce
the before numbers (scripts/meta_hearing_eval.py, scripts/sounds_muse_eval.py) and the Oct 30 cry reason head
(scripts/cry_reason_train.py). Groups and thresholds are unchanged from meta-hackathon-2026 issue #2 (prior work, Oct 23).
"""
import json
import os
import struct
import subprocess
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PYTHON = Path.home() / "Engineering/gonza/sam3-native/venv/bin/python"
MODELS = Path.home() / "Engineering/gonza/parenting-agent/.models/panns"
WORKER = Path(__file__).with_name("panns_worker.py")
EMBED = 0x80000000

GROUPS = {
    "cry": ["Baby cry, infant cry", "Crying, sobbing", "Whimper"],
    "dog": ["Dog", "Bark", "Bow-wow", "Yip", "Howl", "Growling", "Whimper (dog)", "Canidae, dogs, wolves",
            "Domestic animals, pets"],
    "doorbell": ["Doorbell", "Ding-dong", "Ding", "Chime", "Bell", "Buzzer"],
    "splash": ["Splash, splatter", "Bathtub (filling or washing)", "Water", "Water tap, faucet", "Pour", "Liquid",
               "Fill (with liquid)", "Sink (filling or washing)", "Drip", "Stream"],
}
THRESHOLDS = {"cry": 0.05, "dog": 0.6, "doorbell": 0.1, "splash": 0.2}


class PannsListener:
    """Scores 2 s windows in the PANNs worker, same protocol the Ear's listener has."""

    name = "panns"

    def __init__(self, config=None):
        config = config or {}
        python = Path(os.path.expanduser(config.get("python") or DEFAULT_PYTHON))
        model_dir = Path(os.path.expanduser(config.get("model_dir") or os.environ.get("PANNS_DIR") or MODELS))
        if not (model_dir / "Cnn14_16k.pth").is_file():
            raise RuntimeError(f"no PANNs weights in {model_dir}, run scripts/fetch-panns.sh")
        env = {**os.environ, "HEARING_CONFIG": json.dumps({"model_dir": str(model_dir), "groups": GROUPS})}
        self.process = subprocess.Popen([str(python), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=env)
        hello = json.loads(self.process.stdout.readline() or b'{"blocked": "worker exited"}')
        if "blocked" in hello:
            self.process.kill()
            raise RuntimeError(f"panns: {hello['blocked']}")
        self.info = hello

    def score(self, samples):
        data = np.ascontiguousarray(samples, np.float32).tobytes()
        self.process.stdin.write(struct.pack(">I", len(data)) + data)
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline() or b'{"scores": {}}')

    def embed(self, samples):
        """CNN14's 2048 number embedding of a clip, the input of the Oct 30 cry reason head."""
        data = np.ascontiguousarray(samples, np.float32).tobytes()
        self.process.stdin.write(struct.pack(">I", len(data) | EMBED) + data)
        self.process.stdin.flush()
        reply = json.loads(self.process.stdout.readline() or b'{}')
        if "embedding" not in reply:
            raise RuntimeError(f"panns: no embedding, {reply.get('error', 'worker gave none')}")
        return np.asarray(reply["embedding"], np.float32)

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)
