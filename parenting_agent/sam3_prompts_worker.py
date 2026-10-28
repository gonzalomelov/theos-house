"""SAM 3.1 masks worker: one frame and a list of text prompts in, the masks for each prompt out.

Runs in the Python that has torch and the sam3 package, like sam3_worker.py, and loads the weights the same way.
Protocol on stdin and stdout:
  start: one JSON line {"ready": true, ...} or {"blocked": "reason"}
  each request: 4-byte big-endian length + JSON {"prompts": [...]}, then 4-byte big-endian length + JPEG bytes
  each reply: one JSON line {"seconds": float, "found": {prompt: [{"score", "box", "mask"}]}}
mask is a PNG of the instance mask, base64. Frames and masks stay in memory and on the local pipe.
"""
import base64
import json
import os
import struct
import sys
import time
from pathlib import Path

MAX_INSTANCES = 6


def masks_for(sam, jpeg, prompts):
    import contextlib

    import cv2
    import numpy as np
    import torch
    from PIL import Image
    frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    started = time.monotonic()
    # half precision on the Mac GPU: about 0.2 s faster per frame, same scores to two decimals on the dev clips
    half = torch.autocast("mps", dtype=torch.float16) if sam.source.get("device") == "mps" else contextlib.nullcontext()
    with half:
        state = sam.processor.set_image(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        return _prompts(sam, state, prompts, started)


def _prompts(sam, state, prompts, started):
    import cv2
    import numpy as np
    found = {}
    for prompt in prompts:
        out = sam.processor.set_text_prompt(prompt, state)
        masks = out["masks"][:, 0].cpu().numpy()
        scores = out["scores"].float().cpu().numpy()
        boxes = out["boxes"].float().cpu().numpy()
        items = []
        for i in np.argsort(-scores)[:MAX_INSTANCES]:
            ok, png = cv2.imencode(".png", masks[i].astype(np.uint8) * 255)
            items.append({"score": round(float(scores[i]), 3), "box": [round(float(v), 1) for v in boxes[i]],
                          "mask": base64.b64encode(png.tobytes()).decode() if ok else ""})
        found[prompt] = items
    return {"seconds": round(time.monotonic() - started, 3), "found": found}


def main():
    from sam3_worker import DEFAULTS, Sam3
    cfg = {**DEFAULTS, **json.loads(os.environ.get("SAM3_CONFIG", "{}"))}
    out = sys.stdout
    try:
        sam = Sam3(cfg)
    except Exception as error:
        out.write(json.dumps({"blocked": str(error)[:300]}) + "\n")
        out.flush()
        return 1
    out.write(json.dumps({"ready": True, **sam.source}) + "\n")
    out.flush()
    read = sys.stdin.buffer.read
    while True:
        header = read(4)
        if len(header) < 4:
            return 0
        request = json.loads(read(struct.unpack(">I", header)[0]))
        header = read(4)
        if len(header) < 4:
            return 0
        jpeg = read(struct.unpack(">I", header)[0])
        try:
            reply = masks_for(sam, jpeg, request.get("prompts", []))
        except Exception as error:  # one bad frame never kills the worker
            reply = {"seconds": 0, "found": {}, "error": str(error)[:200]}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).with_name("sam3_stubs")))
    raise SystemExit(main())
