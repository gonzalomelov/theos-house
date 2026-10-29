import json, sys, numpy as np
d = json.load(open(sys.argv[1])); thr = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
for name, rows in d.items():
    rec = []; first = None; lifted_any = []
    for r in rows:
        t, v = r[0], r[1]
        if v is None: continue
        rec.append(v); rec = rec[-5:]
        if len(rec) == 5 and np.median(rec) >= thr: lifted_any.append(t)
    hover = "hover" in name
    after = [t for t in lifted_any if t >= 2.5 - 0.25] if hover else lifted_any
    print(f"{name:22s} {'HOVER' if hover else 'touch'} first_lift={after[0] if after else None} n={len(lifted_any)} series={[r[1] for r in rows if r[1] is not None][::4]}")
