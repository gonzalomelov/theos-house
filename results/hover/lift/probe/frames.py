"""Extract frames at fixed offsets from the cue for every labelled moment."""
import json, sys
from pathlib import Path
import cv2, numpy as np
SET = Path(sys.argv[1]).expanduser(); OUT = Path(sys.argv[2])
OFFS = [-0.5, 0.8, 1.5, 2.2]
OUT.mkdir(parents=True, exist_ok=True)
labels = json.loads((SET / "labels.json").read_text())["moments"]
index = []
for m in labels:
    cap = cv2.VideoCapture(str(SET / f"{m['id']}.mp4"))
    for k, off in enumerate(OFFS):
        cap.set(cv2.CAP_PROP_POS_MSEC, (m["cue_s"] + off) * 1000)
        ok, f = cap.read()
        if not ok: continue
        f = cv2.resize(f, (640, round(f.shape[0] * 640 / f.shape[1])))
        name = f"{m['id']}@{k}.png"; cv2.imwrite(str(OUT / name), f)
        index.append({"file": name, "id": m["id"], "k": k, "off": off, "split": m["split"], "scene": m["scene"], "label": m["label"], "lift_cm": m.get("lift_cm")})
    cap.release()
(OUT / "index.json").write_text(json.dumps(index, indent=1))
print(len(index))
