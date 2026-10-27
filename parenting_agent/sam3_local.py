"""SAM 3.1 confirm on this machine, for skill config confirm.provider sam3_local.

The skill process starts the worker (parenting_agent/sam3_worker.py) in the Python that has torch and the
sam3 package, given by confirm.python or SAM3_PYTHON (default ~/Engineering/gonza/sam3-native/venv).
The worker loads the weights once, then answers one frame at a time. Frames go through a local pipe and never
leave the machine. If the worker cannot start, build() raises confirm.Unavailable before the routine begins.
"""
import json
import os
import struct
import subprocess
import threading
from pathlib import Path

from .confirm import Unavailable

DEFAULT_PYTHON = Path.home() / "Engineering/gonza/sam3-native/venv/bin/python"
WORKER = Path(__file__).with_name("sam3_worker.py")
KEYS = ("device", "confidence", "hand_word", "baby_word", "ring_px", "ring_min", "min_hand_area")


class Sam3Local:
    name = "sam3_local"

    def __init__(self, config):
        python = Path(os.path.expanduser(config.get("python") or os.environ.get("SAM3_PYTHON") or DEFAULT_PYTHON))
        if not python.is_file():
            raise Unavailable(f"sam3_local: no Python with SAM 3 at {python}")
        token = Path.home() / ".cache/huggingface/token"
        env = {**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1", "SAM3_INIT_DEVICE": config.get("device", "mps"),
               "SAM3_CONFIG": json.dumps({k: config[k] for k in KEYS if k in config})}
        if token.is_file():
            env.setdefault("HF_TOKEN_PATH", str(token))
        self.process = subprocess.Popen([str(python), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=env)
        hello = json.loads(self.process.stdout.readline() or b'{"blocked": "worker exited"}')
        if "blocked" in hello:
            self.process.kill()
            raise Unavailable(f"sam3_local: {hello['blocked']}")
        self.source = hello
        self.lock = threading.Lock()

    def judge(self, frame_bgr):
        import cv2
        ok, jpeg = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return "unsure"
        data = jpeg.tobytes()
        with self.lock:
            self.process.stdin.write(struct.pack(">I", len(data)) + data)
            self.process.stdin.flush()
            reply = json.loads(self.process.stdout.readline() or b'{"verdict": "unknown"}')
        self.last = reply
        return {"on": "on", "off": "off"}.get(reply.get("verdict"), "unsure")

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)


def build(config):
    return Sam3Local(config)
