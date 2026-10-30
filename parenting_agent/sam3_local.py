"""SAM 3.1 confirm on this machine, for skill config confirm.provider sam3_local.

The skill process starts the worker (parenting_agent/sam3_worker.py) in the Python that has torch and the
sam3 package, given by confirm.python or SAM3_PYTHON (default ~/Engineering/gonza/sam3-native/venv).
The worker loads the weights once, then answers one frame at a time. Frames go through a local pipe and never
leave the machine. If the worker cannot start, build() raises confirm.Unavailable before the routine begins.

One worker serves the whole agent. live() is the worker that is running, so another check (the dog watch on the
glasses frames) asks it for prompt masks instead of loading a second SAM 3.1 on the GPU. Requests take turns on its lock.
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
MASKS, HELD, PROMPTS = 1 << 31, 1 << 30, 1 << 29  # same flags as sam3_worker
KEYS = ("device", "confidence", "hand_word", "baby_word", "ring_px", "ring_min", "min_hand_area", "autocast", "held_words", "held_touch_px", "held_mask_words", "batch_prompts", "worn_share", "held_min_hand_area")


_LIVE = []
_LIVE_LOCK = threading.Lock()


def live():
    """The SAM 3.1 worker running in this process, or None while none is loaded."""
    with _LIVE_LOCK:
        running = [worker for worker in _LIVE if worker.process.poll() is None]
    return running[-1] if running else None


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
        self.codec = config.get("frame_codec", "jpg")
        self.held_objects = []
        with _LIVE_LOCK:
            _LIVE.append(self)

    def _ask(self, frame_bgr, flag=0, prefix=b""):
        import cv2
        # PNG keeps the frame as the camera gave it: a JPEG at quality 90 can halve a partly hidden hand's SAM 3.1 mask
        ok, jpeg = (cv2.imencode(".png", frame_bgr) if self.codec == "png"
                    else cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90]))
        if not ok:
            return {"verdict": "unknown"}
        data = prefix + jpeg.tobytes()
        with self.lock:
            self.process.stdin.write(struct.pack(">I", len(data) | flag) + data)
            self.process.stdin.flush()
            return json.loads(self.process.stdout.readline() or b'{"verdict": "unknown"}')

    def judge(self, frame_bgr):
        reply = self.last = self._ask(frame_bgr)
        return {"on": "on", "off": "off"}.get(reply.get("verdict"), "unsure")

    def masks(self, frame_bgr, held=False):
        """SAM 3.1 hand masks (each at least min_hand_area of the frame) and the baby mask, as bool arrays.
        held draws each hand with the diaper, wipe or bottle it holds (held_mask_words)."""
        import base64
        import cv2
        import numpy as np
        reply = self._ask(frame_bgr, MASKS | (HELD if held else 0))
        if held:
            self.held_objects = list(reply.get("held_objects", []))
        decode = lambda text: cv2.imdecode(np.frombuffer(base64.b64decode(text), np.uint8), cv2.IMREAD_GRAYSCALE) > 0
        baby = decode(reply["baby"]) if reply.get("baby") else None
        return [decode(h) for h in reply.get("hands", [])], baby

    def prompt_masks(self, frame_bgr, prompts):
        """{prompt: [(score, bool mask)]} and the seconds SAM 3.1 took, the same answer as carseat.sam3_masks.Sam3Masks,
        from this worker."""
        import base64
        import cv2
        import numpy as np
        request = json.dumps({"prompts": list(prompts)}).encode()
        reply = self._ask(frame_bgr, PROMPTS, struct.pack(">I", len(request)) + request)
        out = {}
        for prompt, items in reply.get("found", {}).items():
            decoded = []
            for item in items:
                mask = cv2.imdecode(np.frombuffer(base64.b64decode(item["mask"]), np.uint8), cv2.IMREAD_GRAYSCALE) if item.get("mask") else None
                if mask is not None:
                    decoded.append((item["score"], mask > 127))
            out[prompt] = decoded
        return out, reply.get("seconds", 0.0)

    def close(self):
        with _LIVE_LOCK:
            if self in _LIVE:
                _LIVE.remove(self)
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)


def build(config):
    return Sam3Local(config)
