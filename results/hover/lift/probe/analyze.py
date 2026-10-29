"""Hand to baby depth gap per frame. usage: analyze.py <depthdir> [sign]  sign=+1 when depth grows with distance"""
import json, sys
from pathlib import Path
import numpy as np, cv2
FR, MK, DD = Path("frames"), Path("masks"), Path(sys.argv[1])
SIGN = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
RING = int(sys.argv[3]) if len(sys.argv) > 3 else 10
def k(n): return np.ones((2*n+1, 2*n+1), np.uint8)
rows = []
for row in json.loads((FR / "index.json").read_text()):
    stem = row["file"][:-4]
    m = np.load(MK / f"{stem}.npz"); d = np.load(DD / f"{stem}.npy") * SIGN
    H, W = d.shape; px = H * W
    baby = m["baby"].any(0) if len(m["baby"]) else np.zeros((H, W), bool)
    hands = [h for h in m["hand"] if h.sum() / px >= 0.012]
    allh = np.zeros((H, W), bool)
    for h in hands: allh |= h
    near_baby = cv2.dilate(baby.astype(np.uint8), k(12)).astype(bool)
    gaps = []
    for h in hands:
        over = h & near_baby
        if over.sum() < 50: continue
        ring = cv2.dilate(over.astype(np.uint8), k(RING)).astype(bool) & ~allh & baby
        if ring.sum() < 30: continue
        gaps.append(float(np.median(d[ring]) - np.median(d[over])))
    rows.append({**row, "gaps": gaps, "gap": min(gaps) if gaps else None})
json.dump(rows, open(DD.name + f"-gaps-r{RING}.json", "w"), indent=0)
def show(split):
    for lab in ("touch", "hover"):
        for kk in (0, 1, 2, 3):
            v = [r["gap"] for r in rows if r["split"] == split and r["label"] == lab and r["k"] == kk and r["gap"] is not None]
            miss = sum(1 for r in rows if r["split"] == split and r["label"] == lab and r["k"] == kk and r["gap"] is None)
            if v: print(split, lab, kk, "n", len(v), "none", miss, "pct10/50/90", np.round(np.percentile(v, [10, 50, 90]), 4))
for s in ("dev", "test"): show(s)
