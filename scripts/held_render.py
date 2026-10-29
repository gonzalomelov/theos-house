"""Render the held object set (issue #6): hands holding a diaper, a wipe or a bottle above the baby, and touches.

    python scripts/held_render.py --synthetic ~/Engineering/gonza/meta-hackathon-2026-synthetic --out held-dev --splits dev
    python scripts/held_render.py --synthetic ... --out held-blind --splits test --seed 1030

The same method as scripts/hover_render.py, on the same generated changing-table stretches where the hands rest on
the baby (a generated baby, never a real child). Every moment holds a drawn object in the hand from its first frame:
a diaper (a white pad with a blue waistband), a wipe (a thin pale sheet) or a bottle (a capsule with a cap), drawn
over the lower part of the hand so it hides some of the hand's landmarks, the way a grip does. Kinds:
  hold-touch   the hand keeps resting on the baby with the object in it (a hand on the baby holding a wipe).
               Label touch: the voice must stay silent. This is the false alarm set.
  hold-hover   at cue_s the hand and the object lift lift_cm (3 to 15 cm) over 0.25 to 0.45 s and stay there.
               Label hover: the voice must say "hand" within 2.5 s of the cue.
  hold-arrive  at cue_s the hands leave the view, and gap_s (0.5 to 0.9 s) later they come back already lifted
               lift_cm above the baby with the object, and stay there. This is the hero miss: a parent reaching
               for a fresh diaper. Label hover.
"both" puts one object between both hands and lifts both. "one" gives the object to one hand and lifts both hands
(the other empty), so no hand stays on the baby. The lifted hand and object grow by D / (D - lift) about the head's
centre of perspective (D = 45 cm), cast a shadow on the baby, and the baby under them is inpainted from around.
Clips, sheets, moments.json and labels.json go to <synthetic>/hover/<out>, never into git.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hover_render import CAMERA_CM, FPS, LENGTH_S, SHADOW_PX_PER_CM, SOURCES, Hands, ping_pong, read, sheet, write  # noqa: E402

OBJECTS = ("diaper", "wipe", "bottle")


def hand_boxes(masks):
    boxes = []
    for mask in masks:
        ys, xs = np.nonzero(mask)
        if len(xs):
            boxes.append((xs.min(), ys.min(), xs.max(), ys.max()))
    return boxes


def draw_object(frame, boxes, kind, hands):
    """The object drawn in the hand, over its lower part. Returns the frame and the object's mask."""
    out, mask = frame.copy(), np.zeros(frame.shape[:2], np.uint8)
    if not boxes:
        return out, mask
    if hands == "both" and len(boxes) > 1:
        x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    else:
        x1, y1, x2, y2 = boxes[0]
    w, h = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2, y1 + 0.62 * h
    if kind == "diaper":
        size = (max(w * 0.95, 70), max(h * 0.55, 50))
        colour, band = (245, 245, 240), (215, 170, 120)
    elif kind == "wipe":
        size = (max(w * 0.8, 60), max(h * 0.45, 45))
        colour, band = (232, 238, 236), None
    else:
        size = (max(w * 0.35, 30), max(h * 0.8, 70))
        colour, band = (236, 228, 222), (180, 120, 230)
    box = ((cx, cy), size, 8.0)
    corners = cv2.boxPoints(box).astype(np.int32)
    cv2.fillConvexPoly(mask, corners, 255)
    if kind == "bottle":
        cv2.ellipse(mask, (int(cx), int(cy - size[1] / 2)), (int(size[0] / 2), int(size[0] / 2)), 0, 0, 360, 255, -1)
    layer = out.copy()
    layer[mask > 0] = colour
    if band is not None:
        stripe = np.zeros_like(mask)
        top = int(cy - size[1] / 2) if kind == "diaper" else int(cy - size[1] / 2 - size[0] / 2)
        cv2.rectangle(stripe, (int(cx - size[0] / 2), top), (int(cx + size[0] / 2), top + int(size[1] * 0.18)), 255, -1)
        layer[(stripe > 0) & (mask > 0)] = band
    shade = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), 1.5)[..., None]
    out = (out * (1 - shade) + layer * shade).astype(np.uint8)
    noise = np.random.default_rng(int(cx * 7 + cy)).normal(0, 6, out.shape)  # texture, so the object has features
    out = np.where(mask[..., None] > 0, (out + noise).clip(0, 255), out).astype(np.uint8)
    return out, mask


def lifted(frame, held, union, lift_cm, centre, shift=(0.0, 0.0)):
    """held (hand plus object) lifted lift_cm above where it rests, over the frame with the rest inpainted."""
    h, w = frame.shape[:2]
    grown = cv2.dilate(union, np.ones((9, 9), np.uint8))
    clean = cv2.inpaint(frame, grown, 5, cv2.INPAINT_TELEA)
    if lift_cm is None:
        return clean
    scale = CAMERA_CM / (CAMERA_CM - lift_cm)
    area = union.astype(np.float32) / 255
    off = SHADOW_PX_PER_CM * lift_cm
    shadow = cv2.warpAffine(cv2.GaussianBlur(area, (0, 0), 3 + lift_cm), np.float32([[1, 0, off * 0.6], [0, 1, off]]), (w, h))
    out = clean.astype(np.float32) * (1 - 0.45 * shadow[..., None])
    zoom = cv2.getRotationMatrix2D(centre, 0, scale)
    zoom[:, 2] += shift
    raised = cv2.warpAffine(held, zoom, (w, h)).astype(np.float32)
    alpha = cv2.GaussianBlur(cv2.warpAffine(area, zoom, (w, h)), (0, 0), 2)[..., None]
    return (out * (1 - alpha) + raised * alpha).clip(0, 255).astype(np.uint8)


def render(clip, masks, kind, obj, hands, cue_s, lift_cm, ramp_s, gap_s, centre):
    frames = []
    for i, (frame, hand_list) in enumerate(zip(clip, masks)):
        boxes = hand_boxes(hand_list)
        held, obj_mask = draw_object(frame, boxes, obj, hands)
        union = obj_mask.copy()
        for m in hand_list:
            union = np.maximum(union, m)
        t = i / FPS
        if kind == "hold-touch" or t < cue_s:
            frames.append(held)
        elif kind == "hold-hover":
            frames.append(lifted(frame, held, union, lift_cm * min(1.0, (t - cue_s) / ramp_s), centre))
        elif t < cue_s + gap_s:
            frames.append(lifted(frame, held, union, None, centre))
        else:
            frames.append(lifted(frame, held, union, lift_cm, centre))
    return frames


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic", type=Path, required=True)
    parser.add_argument("--out", required=True, help="folder under <synthetic>/hover")
    parser.add_argument("--splits", required=True)
    parser.add_argument("--seed", type=int, default=1031)
    parser.add_argument("--hovers-per-tag", type=int, default=4)
    parser.add_argument("--arrivals-per-tag", type=int, default=2)
    parser.add_argument("--touches-per-tag", type=int, default=3)
    args = parser.parse_args(argv)
    root = args.synthetic.expanduser()
    out = root / "hover" / args.out
    (out / "sheets").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    hands_finder = Hands()
    moments = []
    splits = args.splits.split(",")
    for source_id, file, scene, split, start_s, end_s in SOURCES:
        if split not in splits or scene != "changing_table":
            continue
        base = read(root / file, start_s, end_s)
        for mirrored in (False, True):
            frames = [cv2.flip(f, 1) for f in base] if mirrored else base
            tag = f"{source_id}{'-m' if mirrored else ''}"
            h, w = frames[0].shape[:2]
            plan = ([("hold-touch", k) for k in range(args.touches_per_tag)] + [("hold-hover", k) for k in range(args.hovers_per_tag)]
                    + [("hold-arrive", k) for k in range(args.arrivals_per_tag)])
            for kind, k in plan:
                count = {"hold-touch": args.touches_per_tag, "hold-hover": args.hovers_per_tag, "hold-arrive": args.arrivals_per_tag}[kind]
                edges = np.linspace(3.0, 15.0, count + 1)
                obj = OBJECTS[(k + len(moments)) % 3] if kind != "hold-touch" else ("wipe", "diaper", "bottle")[k % 3]
                both = "both" if (k % 2 == 0) else "one"
                phase = int(rng.integers(len(frames)))
                cue_s = round(float(rng.uniform(2.2, 2.8)), 2)
                lift_cm = round(float(rng.uniform(edges[k], edges[k + 1])), 2) if kind != "hold-touch" else 0.0
                ramp_s = round(float(rng.uniform(0.25, 0.45)), 2)
                gap_s = round(float(rng.uniform(0.5, 0.9)), 2)
                centre = (w / 2 + float(rng.uniform(-40, 40)), h / 2 + float(rng.uniform(-40, 40)))
                clip = ping_pong(frames, LENGTH_S, phase)
                hands_finder.last = []
                masks = [list(hands_finder.masks(f)) for f in clip]
                rendered = render(clip, masks, kind, obj, both, cue_s, lift_cm, ramp_s, gap_s, centre)
                moment = f"{tag}-{kind}-{obj}-{both}-s{k}"
                write(rendered, out / f"{moment}.mp4")
                sheet(rendered, out / "sheets" / f"{moment}.jpg", cue_s)
                moments.append({"id": moment, "source": source_id, "file": file, "scene": scene, "split": split,
                                "mirrored": mirrored, "seed": args.seed, "held": kind, "object": obj, "hands": both,
                                "kind": "touch" if kind == "hold-touch" else "hover", "lift_cm": lift_cm, "phase": phase,
                                "cue_s": cue_s, "ramp_s": ramp_s if kind == "hold-hover" else None,
                                "gap_s": gap_s if kind == "hold-arrive" else None,
                                "centre_px": [round(c, 1) for c in centre], "origin": "rendered"})
                print(moment, flush=True)
    (out / "moments.json").write_text(json.dumps({"camera_cm": CAMERA_CM, "fps": FPS, "moments": moments}, indent=2) + "\n")
    (out / "labels.json").write_text(json.dumps({"labelled_by": "construction", "moments": [
        {**m, "label": m["kind"], "split": "test" if m["split"] == "test" else "dev"} for m in moments]}, indent=2) + "\n")
    print(f"{len(moments)} moments in {out}")


if __name__ == "__main__":
    main()
