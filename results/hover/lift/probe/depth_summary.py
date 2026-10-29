"""Summary of the depth probe: per model, paired gap change (hover minus the touch with the same base frame) and AUC."""
import json, re, numpy as np
from collections import defaultdict
out = {}
lat = {"facebook/dpt-dinov2-large-nyu": "depth-large", "facebook/dpt-dinov2-giant-nyu": "depth-giant", "facebook/sapiens-depth-1b-torchscript": "depth-sapiens"}
for model, d in lat.items():
    rows = json.load(open(f"{d}-gaps-r10.json")); g = {(x["id"], x["k"]): x["gap"] for x in rows}
    paired = defaultdict(list)
    for (i, k), v in g.items():
        m = re.match(r"(.*)-hover-([\d.]+)cm", i)
        if not m or k == 0 or v is None: continue
        t = g.get((m.group(1) + "-touch-p0", k))
        if t is not None: paired[m.group(2)].append(v - t)
    # clip level: median post gap minus pre gap; AUC hover vs touch on all 73 moments
    by = defaultdict(dict); lab = {}
    for x in rows: by[x["id"]][x["k"]] = x["gap"]; lab[x["id"]] = (x["label"], x["split"])
    score = {}
    for i, ks in by.items():
        post = [ks[k] for k in (1, 2, 3) if ks.get(k) is not None]
        if ks.get(0) is not None and post: score[i] = float(np.median(post)) - ks[0]
    def auc(split):
        h = [s for i, s in score.items() if lab[i] == ("hover", split)]; t = [s for i, s in score.items() if lab[i] == ("touch", split)]
        return round(float(np.mean([(a > b) + 0.5 * (a == b) for a in h for b in t])), 3)
    out[model] = {"paired_gap_change_m": {l: {"n": len(v), "p10": round(float(np.percentile(v, 10)), 3), "median": round(float(np.median(v)), 3), "p90": round(float(np.percentile(v, 90)), 3)} for l, v in sorted(paired.items())},
                  "auc_dev": auc("dev"), "auc_test": auc("test")}
s = json.load(open("persp-scene-masks.json")) if False else None
print(json.dumps(out, indent=1))
json.dump(out, open("depth_summary.json", "w"), indent=1)
