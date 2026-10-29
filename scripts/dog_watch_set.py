"""Builds the dog-near-baby test set (issue #109) outside git, from Wikimedia Commons photos labeled by hand.

Two kinds of item:
- photo: a Commons photo as it is, labeled near, far, no_baby (a dog and no baby) or no_dog (a baby and no dog).
- composite: a dog cut out of a dog photo and a baby cut out of a baby photo, pasted on a room photo at a gap set by
  construction. near is a gap from 0 (touching or a small overlap) to 0.3 baby sizes, far is 1.5 to 3.5 baby sizes.
  The cutouts come from SAM 3.1 masks, so composites favour SAM's own segmentation. Photos are the harder test.

The split is drawn once with a fixed seed, stratified by label and kind, and frozen: set.sha256 holds the hash of
every image and of labels.json. Hold the GPU lock (/tmp/pa-gpu.lock) while it runs, it loads SAM 3.1 for the cutouts.

    python scripts/dog_watch_set.py --data ~/Engineering/gonza/pa-local-data/dog-near-baby
"""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DOGS = "c158 c201 c209 c160 c176 c218 c014 c017 c148 c030 c004 c172".split()
BABIES = "c092 c094 c100 c280 c132 c022 c116 c119 c072 c075".split()
ROOMS = "c091 c101 c145 c146 c099 c124".split()
W, H = 1280, 720
SEED = 1029


def cutout(sam, image, word):
    found, _ = sam.masks(image, [word])
    items = [(s, m) for s, m in found.get(word, []) if s >= 0.6]
    if not items:
        return None
    score, mask = max(items, key=lambda x: x[0])
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return image[y0:y1, x0:x1].copy(), mask[y0:y1, x0:x1].copy()


def scaled(cut, size):
    rgb, mask = cut
    factor = size / np.sqrt(mask.sum())
    new = (max(2, int(rgb.shape[1] * factor)), max(2, int(rgb.shape[0] * factor)))
    return cv2.resize(rgb, new, interpolation=cv2.INTER_AREA), cv2.resize(mask.astype(np.uint8), new) > 0


def paste(canvas, cut, x, y):
    rgb, mask = cut
    h, w = mask.shape
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (3, 3), 0)[..., None]
    region = canvas[y:y + h, x:x + w]
    canvas[y:y + h, x:x + w] = (alpha * rgb + (1 - alpha) * region).astype(np.uint8)
    full = np.zeros(canvas.shape[:2], bool)
    full[y:y + h, x:x + w] = mask
    return full


def place_dog(rng, baby_full, dog, lo, hi, overlap_ok):
    """A top-left corner for the dog whose gap to the baby, in pixels, falls in [lo, hi]. Returns (x, y, gap)."""
    distance = cv2.distanceTransform((~baby_full).astype(np.uint8), cv2.DIST_L2, 5)
    h, w = dog[1].shape
    for _ in range(4000):
        x, y = rng.randrange(0, W - w), rng.randrange(0, H - h)
        dog_full = np.zeros((H, W), bool)
        dog_full[y:y + h, x:x + w] = dog[1]
        overlap = (dog_full & baby_full).sum() / max(dog_full.sum(), 1)
        gap = 0.0 if overlap > 0 else float(distance[dog_full].min())
        if overlap > (0.15 if overlap_ok else 0):
            continue
        if lo <= gap <= hi:
            return x, y, gap
    return None


def composites(sam, data, rng):
    src = data / "commons"
    dogs = [c for c in (cutout(sam, cv2.imread(str(src / f"{i}.jpg")), "dog") for i in DOGS) if c is not None]
    babies = [c for c in (cutout(sam, cv2.imread(str(src / f"{i}.jpg")), "baby") for i in BABIES) if c is not None]
    rooms = [cv2.resize(cv2.imread(str(src / f"{i}.jpg")), (W, H)) for i in ROOMS]
    out_dir = data / "composite"
    out_dir.mkdir(exist_ok=True)
    plan = [("near", 24), ("far", 24), ("no_baby", 8), ("no_dog", 8)]
    items, n = [], 0
    for label, count in plan:
        made = 0
        while made < count:
            canvas = rooms[rng.randrange(len(rooms))].copy()
            baby_size = rng.uniform(80, 140)
            baby = scaled(babies[rng.randrange(len(babies))], baby_size)
            dog = scaled(dogs[rng.randrange(len(dogs))], baby_size * rng.uniform(0.8, 1.4))
            item = {"kind": "composite", "label": label, "baby_size_px": round(baby_size, 1)}
            if label in ("near", "far", "no_dog"):
                bh, bw = baby[1].shape
                bx, by = rng.randrange(W // 6, W - W // 6 - bw), rng.randrange(H // 3, H - bh)
                baby_full = np.zeros((H, W), bool)
                baby_full[by:by + bh, bx:bx + bw] = baby[1]
            if label in ("near", "far"):
                lo, hi = (0, 0.3 * baby_size) if label == "near" else (1.5 * baby_size, 3.5 * baby_size)
                spot = place_dog(rng, baby_full, dog, lo, hi, overlap_ok=label == "near")
                if spot is None:
                    continue
                paste(canvas, baby, bx, by)
                paste(canvas, dog, spot[0], spot[1])
                item["gap_baby_sizes"] = round(spot[2] / baby_size, 3)
            elif label == "no_dog":
                paste(canvas, baby, bx, by)
            else:
                dh, dw = dog[1].shape
                paste(canvas, dog, rng.randrange(0, W - dw), rng.randrange(H // 4, H - dh))
            item["id"] = f"m{n:03d}"
            item["file"] = f"composite/{item['id']}.jpg"
            cv2.imwrite(str(data / item["file"]), canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])
            items.append(item)
            made += 1
            n += 1
    return items


def split(items, rng):
    groups = {}
    for item in items:
        groups.setdefault((item["kind"], item["label"]), []).append(item)
    for group in groups.values():
        rng.shuffle(group)
        for i, item in enumerate(group):
            item["split"] = "blind" if i % 2 == 0 else "dev"
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    args = parser.parse_args()
    data = Path(args.data).expanduser()
    rng = random.Random(SEED)
    photos = [{"id": p["id"], "file": f"commons/{p['id']}.jpg", "kind": "photo", "label": p["label"]}
              for p in json.loads((data / "meta/photo_labels.json").read_text())]
    from parenting_agent.carseat.sam3_masks import Sam3Masks
    sam = Sam3Masks({"confidence": 0.3})
    try:
        items = photos + composites(sam, data, rng)
    finally:
        sam.close()
    items = split(items, rng)
    (data / "labels.json").write_text(json.dumps(items, indent=1) + "\n")
    lines = [f"{hashlib.sha256((data / i['file']).read_bytes()).hexdigest()}  {i['file']}" for i in items]
    lines.append(f"{hashlib.sha256((data / 'labels.json').read_bytes()).hexdigest()}  labels.json")
    (data / "set.sha256").write_text("\n".join(lines) + "\n")
    counts = {}
    for i in items:
        key = f"{i['split']}/{i['kind']}/{i['label']}"
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps(dict(sorted(counts.items())), indent=1))


if __name__ == "__main__":
    main()
