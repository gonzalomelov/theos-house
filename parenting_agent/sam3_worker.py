"""SAM 3.1 confirm worker: Meta's open weights on this machine, one frame in, one verdict out.

Runs in its own Python (the one with torch and the sam3 package, see docs/sam3-local.md), started by
parenting_agent.sam3_local. It speaks a tiny protocol on stdin and stdout so the skill process needs no torch:
  start: one JSON line {"ready": true, ...} or {"blocked": "reason"}
  each request: 4-byte big-endian length, then that many bytes of JPEG
  each reply: one JSON line {"verdict": "on"|"off"|"unknown", "seconds": float, "rings": [...]}
  a request whose length has the top bit set (MASKS) also gets "hands" and "baby": PNG masks in base64, for the
  lift check's SAM 3.1 regions (parenting_agent/lift.py)
A hand is on the baby when at least ring_min of the ring of pixels around the hand mask is baby. Hands smaller
than min_hand_area of the frame are dropped, so the baby's own hand never counts. Frames stay in memory.
"""
import base64
import json
import os
import struct
import sys
import time
from pathlib import Path

MASKS = 1 << 31
DEFAULTS = {
    "checkpoints": [{"repo": "facebook/sam3.1", "file": "sam3.1_multiplex.pt"}, {"repo": "facebook/sam3", "file": "sam3.pt"}],
    "device": "mps", "confidence": 0.4, "hand_word": "hand", "baby_word": "baby",
    "ring_px": 6, "ring_min": 0.35, "min_hand_area": 0.012, "max_missing_share": 0.01,
}


def ring_state(hand_masks, baby, cfg):
    import cv2
    import numpy as np
    pixels = baby.shape[0] * baby.shape[1]
    kernel = np.ones((2 * cfg["ring_px"] + 1,) * 2, np.uint8)
    rings = []
    for mask in hand_masks:
        if mask.sum() / pixels < cfg["min_hand_area"]:
            continue
        hand = mask & ~baby
        ring = cv2.dilate(hand.astype(np.uint8), kernel).astype(bool) & ~hand
        rings.append(round(float((ring & baby).sum() / max(ring.sum(), 1)), 3))
    if not baby.any():
        return "unknown", rings
    return ("on" if any(r >= cfg["ring_min"] for r in rings) else "off"), rings


class Sam3:
    def __init__(self, cfg):
        import torch
        from huggingface_hub import hf_hub_download
        from sam3.model.sam3_image_processor import Sam3Processor
        from sam3.model_builder import build_sam3_image_model
        self.cfg = cfg
        device = cfg["device"]
        if device == "mps" and not torch.backends.mps.is_available():
            device = "cpu"
        tried = []
        for source in cfg["checkpoints"]:
            try:
                path = hf_hub_download(repo_id=source["repo"], filename=source["file"])
            except Exception as error:  # gated repo, no token, offline: try the next checkpoint
                tried.append(f"{source['repo']}: {type(error).__name__}")
                continue
            model = build_sam3_image_model(device="cpu", load_from_HF=False, checkpoint_path=None)
            ckpt = torch.load(path, map_location="cpu", weights_only=True)
            ckpt = ckpt["model"] if isinstance(ckpt.get("model"), dict) else ckpt
            missing, _ = model.load_state_dict({k.replace("detector.", ""): v for k, v in ckpt.items() if "detector" in k}, strict=False)
            model.eval()
            share = len(missing) / max(len(model.state_dict()), 1)
            if share <= cfg["max_missing_share"]:
                self.source = {"repo": source["repo"], "device": device, "missing_share": round(share, 4)}
                self.processor = Sam3Processor(model.to(device), device=device, confidence_threshold=cfg["confidence"])
                return
            tried.append(f"{source['repo']}: {len(missing)} detector keys missing")
        raise RuntimeError("no SAM 3 checkpoint loaded: " + " | ".join(tried))

    def judge(self, jpeg, with_masks=False):
        import cv2
        import numpy as np
        from PIL import Image
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        started = time.monotonic()
        state = self.processor.set_image(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        masks = {}
        for word in (self.cfg["hand_word"], self.cfg["baby_word"]):
            masks[word] = self.processor.set_text_prompt(word, state)["masks"][:, 0].cpu().numpy()
        babies = masks[self.cfg["baby_word"]]
        baby = babies.any(axis=0) if len(babies) else np.zeros(frame.shape[:2], bool)
        hands = list(masks[self.cfg["hand_word"]])
        verdict, rings = ring_state(hands, baby, self.cfg)
        reply = {"verdict": verdict, "seconds": round(time.monotonic() - started, 3), "rings": rings}
        if with_masks:
            png = lambda mask: base64.b64encode(cv2.imencode(".png", mask.astype(np.uint8) * 255)[1].tobytes()).decode()
            pixels = baby.shape[0] * baby.shape[1]
            reply["hands"] = [png(m) for m in hands if m.sum() / pixels >= self.cfg["min_hand_area"]]
            reply["baby"] = png(baby)
        return reply


def main():
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
        size = struct.unpack(">I", header)[0]
        jpeg = read(size & ~MASKS)
        try:
            reply = sam.judge(jpeg, with_masks=bool(size & MASKS))
        except Exception as error:  # one bad frame never kills the worker
            reply = {"verdict": "unknown", "error": str(error)[:200]}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).with_name("sam3_stubs")))
    raise SystemExit(main())
