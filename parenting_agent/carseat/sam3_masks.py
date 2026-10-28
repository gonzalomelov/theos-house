"""Text prompts to masks with SAM 3.1 on this machine, for the car seat coach.

Starts parenting_agent/sam3_prompts_worker.py in the Python that has torch and sam3 (the same one the
changing-table confirm uses, see docs/sam3-local.md). Frames go through a local pipe and never leave the Mac.
"""
import base64
import json
import os
import struct
import subprocess
import threading
from pathlib import Path

from ..confirm import Unavailable
from ..sam3_local import DEFAULT_PYTHON

WORKER = Path(__file__).resolve().parent.parent / "sam3_prompts_worker.py"


class Sam3Masks:
    name = "sam3_masks"

    def __init__(self, config=None):
        config = config or {}
        python = Path(os.path.expanduser(config.get("python") or os.environ.get("SAM3_PYTHON") or DEFAULT_PYTHON))
        if not python.is_file():
            raise Unavailable(f"sam3_masks: no Python with SAM 3 at {python}")
        token = Path.home() / ".cache/huggingface/token"
        env = {**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1", "SAM3_INIT_DEVICE": config.get("device", "mps"),
               "SAM3_CONFIG": json.dumps({k: config[k] for k in ("device", "confidence") if k in config})}
        if token.is_file():
            env.setdefault("HF_TOKEN_PATH", str(token))
        self.process = subprocess.Popen([str(python), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=env)
        hello = json.loads(self.process.stdout.readline() or b'{"blocked": "worker exited"}')
        if "blocked" in hello:
            self.process.kill()
            raise Unavailable(f"sam3_masks: {hello['blocked']}")
        self.source = hello
        self.lock = threading.Lock()
        self._warm_up()

    def _warm_up(self):
        """One pass on a blank frame, so the first real step does not pay the GPU's first-call cost."""
        import numpy as np
        self.masks(np.zeros((480, 640, 3), np.uint8), ["strap"])

    def masks(self, frame_bgr, prompts):
        """{prompt: [(score, bool mask)]} for one frame, best score first, plus the seconds SAM took."""
        import cv2
        import numpy as np
        ok, jpeg = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return {}, 0.0
        request, data = json.dumps({"prompts": list(prompts)}).encode(), jpeg.tobytes()
        with self.lock:
            self.process.stdin.write(struct.pack(">I", len(request)) + request + struct.pack(">I", len(data)) + data)
            self.process.stdin.flush()
            reply = json.loads(self.process.stdout.readline() or b'{"found": {}}')
        out = {}
        for prompt, items in reply.get("found", {}).items():
            decoded = []
            for item in items:
                png = np.frombuffer(base64.b64decode(item["mask"]), np.uint8) if item.get("mask") else None
                mask = cv2.imdecode(png, cv2.IMREAD_GRAYSCALE) if png is not None else None
                if mask is not None:
                    decoded.append((item["score"], mask > 127))
            out[prompt] = decoded
        return out, reply.get("seconds", 0.0)

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)
