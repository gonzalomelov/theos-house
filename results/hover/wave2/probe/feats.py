"""Offline SAM 3.1 mask signals on the seen set (old dev + old test), cached frames and masks at cue -0.5, +0.8, +1.5, +2.2 s."""
import json, sys, numpy as np, cv2
from collections import defaultdict
HD = sys.argv[1]; MIN_AREA = float(sys.argv[2])
idx = json.load(open(f"{HD}/frames/index.json")); by = defaultdict(dict); meta = {}
for r in idx: by[r["id"]][r["k"]] = r; meta[r["id"]] = r
K = lambda n: np.ones((2*n+1, 2*n+1), np.uint8)
dil = lambda m, n: cv2.dilate(m.astype(np.uint8), K(n)).astype(bool)
sift = cv2.SIFT_create(nfeatures=4000, contrastThreshold=0.01); bf = cv2.BFMatcher(cv2.NORM_L2)
def scale(g0, m0, g1, r1):
    k0, d0 = sift.detectAndCompute(g0, m0.astype(np.uint8)*255); k1, d1 = sift.detectAndCompute(g1, r1.astype(np.uint8)*255)
    if d0 is None or d1 is None or len(k0) < 8 or len(k1) < 8: return None
    ms = [a for a, b in bf.knnMatch(d0, d1, k=2) if a.distance < 0.8*b.distance]
    if len(ms) < 8: return None
    M, inl = cv2.estimateAffinePartial2D(np.float32([k0[m.queryIdx].pt for m in ms]), np.float32([k1[m.trainIdx].pt for m in ms]), method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None or inl.sum() < 8: return None
    return float(np.hypot(M[0,0], M[1,0]))
def load(r, md):
    m = np.load(f"{HD}/{md}/{r['file'][:-4]}.npz"); H, W = m["baby"].shape[1:] if len(m["baby"]) else m["hand"].shape[1:]
    baby = m["baby"].any(0) if len(m["baby"]) else np.zeros((H, W), bool)
    hands = []
    for h in sorted(m["hand"], key=lambda x: -x.sum()):
        if h.sum()/(H*W) < MIN_AREA: continue
        if any((h & k).sum()/min(h.sum(), k.sum()) > 0.5 for k in hands): continue
        hands.append(h)
    return hands, baby
def ring(h, baby):
    hh = h & ~baby; rg = dil(hh, 6) & ~hh; return (rg & baby).sum()/max(rg.sum(), 1)
out = {}
for i, ks in by.items():
    if 0 not in ks: continue
    h0, b0 = load(ks[0], "masks"); g0 = cv2.cvtColor(cv2.imread(f"{HD}/frames/{ks[0]['file']}"), cv2.COLOR_BGR2GRAY)
    mh0, _ = load(ks[0], "mpmasks")
    near = dil(b0, 12)
    on0 = [h for h in h0 if (h & near).sum() > 50]
    mon0 = [h for h in mh0 if (h & near).sum() > 50]
    row = defaultdict(list)
    allh = np.zeros_like(b0)
    for h in h0: allh |= h
    scene = ~dil(allh, 30); babyref = b0 & ~dil(allh, 30)
    mall = np.zeros_like(b0)
    for h in mh0: mall |= h
    mscene = ~dil(mall, 30)
    for kk in (1, 2, 3):
        if kk not in ks: continue
        h1, b1 = load(ks[kk], "masks"); g1 = cv2.cvtColor(cv2.imread(f"{HD}/frames/{ks[kk]['file']}"), cv2.COLOR_BGR2GRAY)
        # area growth: each resting hand matched to the later hand with most overlap after a 40 px search
        gr = []
        for h in on0:
            best = max(h1, key=lambda x: (x & dil(h, 40)).sum(), default=None)
            gr.append(np.sqrt(best.sum()/h.sum()) if best is not None and (best & dil(h, 40)).sum() > 0 else None)
        row["area"].append(min([g for g in gr if g], default=None) if gr and all(gr) else None)
        row["baby_vis"].append(b1.sum()/max(b0.sum(), 1))
        r0 = max([ring(h, b0) for h in on0], default=0); r1 = max([ring(h, b1) for h in h1 if (h & near).sum() > 50], default=0)
        row["ring_drop"].append(r0 - r1)
        for name, hs, ref in (("sift_sam_scene", on0, scene), ("sift_sam_baby", on0, babyref), ("sift_mp_scene", mon0, mscene)):
            sr = scale(g0, ref, g1, dil(ref, 40)); per = []
            for h in hs:
                sh = scale(g0, h, g1, dil(h, 60))
                per.append(sh/sr if sh and sr else None)
            row[name].append(min(per) if per and all(per) else None)
    out[i] = {"label": meta[i]["label"], "scene": meta[i]["scene"], "split": meta[i]["split"], "lift_cm": meta[i]["lift_cm"], **row}
json.dump(out, open("feats.json", "w"), indent=0)
def auc(pos, neg):
    if not pos or not neg: return None
    return sum((p > n) + 0.5*(p == n) for p in pos for n in neg)/(len(pos)*len(neg))
for feat, sign in (("area", 1), ("baby_vis", -1), ("ring_drop", 1), ("sift_sam_scene", 1), ("sift_sam_baby", 1), ("sift_mp_scene", 1)):
    line = [feat]
    for scene in ("changing_table", "bath", None):
        rows = [r for r in out.values() if scene in (None, r["scene"])]
        val = lambda r: (lambda v: sign*float(np.median(v)) if v else None)([x for x in r[feat] if x is not None])
        pos = [val(r) for r in rows if r["label"] == "hover"]; neg = [val(r) for r in rows if r["label"] == "touch"]
        line.append(f"{scene or 'all'} auc={auc([p for p in pos if p is not None], [n for n in neg if n is not None]):.2f} none={sum(p is None for p in pos)}/{sum(n is None for n in neg)}")
    print(" | ".join(line))
