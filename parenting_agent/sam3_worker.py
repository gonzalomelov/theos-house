"""SAM 3.1 confirm worker: Meta's open weights on this machine, one frame in, one verdict out.

Runs in its own Python (the one with torch and the sam3 package, see docs/sam3-local.md), started by
parenting_agent.sam3_local. It speaks a tiny protocol on stdin and stdout so the skill process needs no torch:
  start: one JSON line {"ready": true, ...} or {"blocked": "reason"}
  each request: 4-byte big-endian length, then that many bytes of JPEG
  each reply: one JSON line {"verdict": "on"|"off"|"unknown", "seconds": float, "rings": [...]}
  a request whose length has the top bit set (MASKS) also gets "hands" and "baby": PNG masks in base64, for the
  lift check's SAM 3.1 regions (parenting_agent/lift.py)
  a request with the next bit set too (HELD) also prompts the held_mask_words and draws each hand with what it holds,
  for a hand the reflex lost behind a diaper, a wipe or a bottle (results/hover/held), and names them in "held_objects"
  a request with the PROMPTS bit set carries 4-byte length + JSON {"prompts": [...]} before the image and gets the
  masks for each prompt, the reply of sam3_prompts_worker.py, so the dog watch on the glasses shares this one process
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
HELD = 1 << 30
PROMPTS = 1 << 29
DEFAULTS = {
    "checkpoints": [{"repo": "facebook/sam3.1", "file": "sam3.1_multiplex.pt"}, {"repo": "facebook/sam3", "file": "sam3.pt"}],
    "device": "mps", "confidence": 0.4, "hand_word": "hand", "baby_word": "baby",
    "ring_px": 6, "ring_min": 0.35, "min_hand_area": 0.012, "max_missing_share": 0.01, "autocast": None,
    "held_words": [], "held_touch_px": 4, "batch_prompts": True, "worn_share": 0.5, "held_min_hand_area": 0.004, "held_mask_words": ["diaper", "wipe", "bottle"],
}


def ring_state(hand_masks, baby, cfg):
    """How much of a thin band around each hand lies on the baby. Any hand over ring_min reads as on."""
    import cv2
    import numpy as np
    side = 2 * cfg["ring_px"] + 1
    grow = cv2.getStructuringElement(cv2.MORPH_RECT, (side, side))
    smallest = cfg["min_hand_area"] * baby.size
    shares = []
    for mask in filter(lambda m: m.sum() >= smallest, hand_masks):
        outside_baby = mask & ~baby
        band = cv2.dilate(outside_baby.astype(np.uint8), grow) > 0
        band &= ~outside_baby
        shares.append(round(float(np.count_nonzero(band & baby) / max(np.count_nonzero(band), 1)), 3))
    if not baby.any():
        return "unknown", shares
    return ("on" if shares and max(shares) >= cfg["ring_min"] else "off"), shares


def holding(hands, objects, cfg, baby=None):
    """Each hand with the held objects that touch it: a wipe or a diaper in the hand hides the hand's own contact edge,
    so the ring is drawn around the hand and what it holds (held_words, results/hover/held). An object that lies
    mostly inside the baby mask is worn, not held (the baby's own diaper), and is left out."""
    if baby is not None:
        objects = [o for o in objects if (o & baby).sum() <= cfg["worn_share"] * max(o.sum(), 1)]
    if not objects:
        return hands
    import cv2
    import numpy as np
    kernel = np.ones((2 * cfg["held_touch_px"] + 1,) * 2, np.uint8)
    grown = [cv2.dilate(h.astype(np.uint8), kernel).astype(bool) for h in hands]
    out = [h.copy() for h in hands]
    for obj in objects:
        touching = [i for i, g in enumerate(grown) if (g & obj).any()]
        for i in touching:
            out[i] |= obj & ~hands[i]
    return out


def held_objects(hands, masks, cfg, baby=None):
    """The words of the held objects that touch a hand, the way holding() draws them: what the HUD names as held."""
    import cv2
    import numpy as np
    kernel = np.ones((2 * cfg["held_touch_px"] + 1,) * 2, np.uint8)
    grown = [cv2.dilate(h.astype(np.uint8), kernel).astype(bool) for h in hands]
    found = []
    for word, objects in masks.items():
        for obj in objects:
            if baby is not None and (obj & baby).sum() > cfg["worn_share"] * max(obj.sum(), 1):
                continue
            if any((g & obj).any() for g in grown) and word not in found:
                found.append(word)
    return found


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
            saved = torch.load(path, map_location="cpu", weights_only=True)
            weights = saved["model"] if isinstance(saved.get("model"), dict) else saved
            detector_only = {name.replace("detector.", ""): value for name, value in weights.items() if "detector" in name}
            missing, _ = model.load_state_dict(detector_only, strict=False)
            model.eval()
            share = len(missing) / max(len(model.state_dict()), 1)
            if share <= cfg["max_missing_share"]:
                self.source = {"repo": source["repo"], "device": device, "missing_share": round(share, 4)}
                self.processor = Sam3Processor(model.to(device), device=device, confidence_threshold=cfg["confidence"])
                return
            tried.append(f"{source['repo']}: {len(missing)} detector keys missing")
        raise RuntimeError("no SAM 3 checkpoint loaded: " + " | ".join(tried))

    def judge(self, jpeg, with_masks=False, held=False):
        """autocast "float16" runs the model in half precision on MPS: 1.73 to 1.56 s median, same verdicts (results/held)."""
        import contextlib
        import torch
        dtype = self.cfg.get("autocast")
        context = torch.autocast(self.source["device"], dtype=getattr(torch, dtype)) if dtype else contextlib.nullcontext()
        with context:
            return self._judge(jpeg, with_masks, held)

    def _prompts(self, state, words):
        """Every word's masks from one decoder pass: the words share the image and go through as a batch of queries.
        The same masks as one set_text_prompt per word, in less time: 5 words 0.82 s against 1.79 s on the M3 Max
        (results/hover/held). batch_prompts false keeps one pass per word."""
        import torch
        from torch.nn.functional import interpolate
        p = self.processor
        if not self.cfg.get("batch_prompts", True) or len(words) == 1:
            return {w: p.set_text_prompt(w, state)["masks"][:, 0].cpu().numpy() for w in words}
        from sam3.model.data_misc import FindStage
        n, device = len(words), p.device
        with torch.inference_mode():
            state["backbone_out"].update(p.model.backbone.forward_text(list(words), device=device))
            find = FindStage(img_ids=torch.zeros(n, device=device, dtype=torch.long),
                             text_ids=torch.arange(n, device=device, dtype=torch.long), input_boxes=None,
                             input_boxes_mask=None, input_boxes_label=None, input_points=None, input_points_mask=None)
            out = p.model.forward_grounding(backbone_out=state["backbone_out"], find_input=find,
                                            geometric_prompt=p.model._get_dummy_prompt(n), find_target=None)
            probs = (out["pred_logits"].sigmoid() * out["presence_logit_dec"].sigmoid().unsqueeze(1)).squeeze(-1)
            found = {}
            for i, word in enumerate(words):
                masks = out["pred_masks"][i][probs[i] > p.confidence_threshold]
                masks = interpolate(masks.unsqueeze(1).float(), (state["original_height"], state["original_width"]),
                                    mode="bilinear", align_corners=False).sigmoid() > 0.5
                found[word] = masks[:, 0].cpu().numpy()
        return found

    def warm(self):
        """The first batched pass of each size is slow on MPS (about 2 s): run them once at start."""
        import cv2
        import numpy as np
        blank = cv2.imencode(".jpg", np.full((360, 640, 3), 128, np.uint8))[1].tobytes()
        self.judge(blank)
        self.judge(blank, with_masks=True, held=True)

    def _judge(self, jpeg, with_masks=False, held=False):
        import cv2
        import numpy as np
        from PIL import Image
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        started = time.monotonic()
        state = self.processor.set_image(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        extra = list(self.cfg["held_mask_words"] if held else self.cfg["held_words"])
        masks = self._prompts(state, [self.cfg["hand_word"], self.cfg["baby_word"], *extra])
        babies = masks[self.cfg["baby_word"]]
        baby = babies.any(axis=0) if len(babies) else np.zeros(frame.shape[:2], bool)
        hands = list(masks[self.cfg["hand_word"]])
        min_area = self.cfg["min_hand_area"]
        if held:  # the parent's hand, mostly hidden by what it holds: smaller, and never the baby's own hand
            hands = [h for h in hands if (h & baby).sum() < self.cfg["worn_share"] * max(h.sum(), 1)]
            min_area = self.cfg["held_min_hand_area"]
        objects = held_objects(hands, {w: masks[w] for w in extra}, self.cfg, baby) if held else None
        hands = holding(hands, [m for w in extra for m in masks[w]], self.cfg, baby)
        verdict, rings = ring_state(hands, baby, self.cfg)
        reply = {"verdict": verdict, "seconds": round(time.monotonic() - started, 3), "rings": rings}
        if objects is not None:
            reply["held_objects"] = objects
        if with_masks:
            png = lambda mask: base64.b64encode(cv2.imencode(".png", mask.astype(np.uint8) * 255)[1].tobytes()).decode()
            pixels = baby.shape[0] * baby.shape[1]
            reply["hands"] = [png(m) for m in hands if m.sum() / pixels >= min_area]
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
    try:
        sam.warm()
    except Exception as error:  # a cold first pass is slower, never fatal
        sam.source["warm_error"] = str(error)[:200]
    out.write(json.dumps({"ready": True, **sam.source}) + "\n")
    out.flush()
    read = sys.stdin.buffer.read
    while True:
        header = read(4)
        if len(header) < 4:
            return 0
        size = struct.unpack(">I", header)[0]
        jpeg = read(size & ~(MASKS | HELD | PROMPTS))
        try:
            if size & PROMPTS:
                from sam3_prompts_worker import masks_for
                length = struct.unpack(">I", jpeg[:4])[0]
                prompts = json.loads(jpeg[4:4 + length]).get("prompts", [])
                reply = masks_for(sam, jpeg[4 + length:], prompts)
            else:
                reply = sam.judge(jpeg, with_masks=bool(size & MASKS), held=bool(size & HELD))
        except Exception as error:  # one bad frame never kills the worker
            reply = {"verdict": "unknown", "error": str(error)[:200]}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).with_name("sam3_stubs")))
    raise SystemExit(main())
