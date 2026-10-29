"""Offline: one-hand lift measured against SAM 3.1 anchored baselines (hand mask, baby mask as reference)."""
import json, sys, os, time
from pathlib import Path
PA = Path.home()/"Engineering/gonza/parenting-agent-worktrees/sam-essential/parenting_agent"
sys.path.insert(0, str(PA/"sam3_stubs")); sys.path.insert(0, str(PA))
import numpy as np, cv2
from PIL import Image
import sam3_worker as W
sam = W.Sam3(dict(W.DEFAULTS))
K = lambda n: np.ones((2*n+1,)*2, np.uint8)
sift = cv2.SIFT_create(nfeatures=3000, contrastThreshold=0.01); bf = cv2.BFMatcher(cv2.NORM_L2)
def masks(f):
    st = sam.processor.set_image(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
    H, W_ = f.shape[:2]
    hm = sam.processor.set_text_prompt("hand", st)["masks"][:, 0].cpu().numpy()
    bm = sam.processor.set_text_prompt("baby", st)["masks"][:, 0].cpu().numpy()
    baby = bm.any(0) if len(bm) else np.zeros((H, W_), bool)
    near = cv2.dilate(baby.astype(np.uint8), K(12)).astype(bool)
    hands = []
    for h in sorted(hm, key=lambda x: -x.sum()):
        if h.sum()/(H*W_) < 0.012 or not (h & near).sum(): continue
        if any((h & k).sum()/min(h.sum(), k.sum()) > 0.5 for k in hands): continue
        hands.append(h)
    return hands, baby
def feats(g, m):
    k, d = sift.detectAndCompute(g, m.astype(np.uint8)*255); return np.float32([x.pt for x in k]).reshape(-1, 2), d
def scale(b, cur, region):
    (p0, d0), (p1, d1) = b, cur
    if d0 is None or d1 is None or len(d0) < 8 or len(d1) < 8: return None
    keep = region[np.clip(p1[:, 1].astype(int), 0, region.shape[0]-1), np.clip(p1[:, 0].astype(int), 0, region.shape[1]-1)]
    p1, d1 = p1[keep], d1[keep]
    if len(d1) < 8: return None
    ms = [a for a, c in bf.knnMatch(d0, d1, k=2) if a.distance < 0.8*c.distance]
    if len(ms) < 8: return None
    M, inl = cv2.estimateAffinePartial2D(np.float32([p0[m.queryIdx] for m in ms]), np.float32([p1[m.trainIdx] for m in ms]), method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None or inl.sum() < 8: return None
    return float(np.hypot(M[0,0], M[1,0]))
def run(path, period=2.0, lag=2.0, step=2):
    cap = cv2.VideoCapture(str(path)); fr = []; fps = cap.get(cv2.CAP_PROP_FPS) or 30
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(cv2.resize(f, (640, round(f.shape[0]*640/f.shape[1]))))
    out = []; anchors = {}
    for i in range(0, len(fr), step):
        t = i/fps
        # the newest anchor whose SAM answer has arrived by t
        bt = int((t - lag)//period)*period if t >= lag else None
        if bt is None: out.append([round(t, 2), None]); continue
        bi = int(round(bt*fps))
        if bi not in anchors:
            hands, baby = masks(fr[bi]); g = cv2.cvtColor(fr[bi], cv2.COLOR_BGR2GRAY)
            allh = np.zeros_like(baby)
            for h in hands: allh |= h
            ref = baby & ~cv2.dilate(allh.astype(np.uint8), K(15)).astype(bool)
            anchors[bi] = ([(feats(g, h), cv2.dilate(h.astype(np.uint8), K(60)).astype(bool)) for h in hands], (feats(g, ref), cv2.dilate(ref.astype(np.uint8), K(40)).astype(bool)), len(hands))
        hs, (rf, rr), n = anchors[bi]
        g = cv2.cvtColor(fr[i], cv2.COLOR_BGR2GRAY); cur = sift.detectAndCompute(g, None); cur = (np.float32([x.pt for x in cur[0]]).reshape(-1, 2), cur[1])
        sr = scale(rf, cur, rr); lifts = []
        for hf, hr in hs:
            sh = scale(hf, cur, hr); lifts.append(None if not (sh and sr) else 45*(1 - sr/sh))
        out.append([round(t, 2), None if not lifts or None in lifts else round(min(lifts), 2), n])
    return out
res = {}
for name, path in json.loads(open(sys.argv[1]).read()):
    t0 = time.monotonic(); res[name] = run(path); print(name, round(time.monotonic()-t0, 1), flush=True)
json.dump(res, open(sys.argv[2], "w"))
