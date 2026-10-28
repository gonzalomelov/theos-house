"""Frame-level check behind the ablation: what SAM 3.1 and the reflex say on one frame per moment, 1.5 s after the cue.

    python scripts/hover_frames.py --set ~/Engineering/gonza/meta-hackathon-2026-synthetic/hover/set --out runs/hover/frames.json

It shows whether either model can tell a hover from a touch at all, apart from when the alarm asks it.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent import config as config_mod  # noqa: E402
from parenting_agent import confirm as confirm_mod  # noqa: E402
from parenting_agent.reflex import MediaPipeReflex  # noqa: E402

AFTER_CUE_S = 1.5


def frame_at(path, seconds):
    capture = cv2.VideoCapture(str(path))
    capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = capture.read()
    capture.release()
    return frame if ok else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.set.expanduser()
    cfg = config_mod.load("skills/changing-table.json")
    reflex, sam = MediaPipeReflex(cfg["contact"]), confirm_mod.build(cfg["confirm"])
    rows = []
    try:
        for m in json.loads((root / "labels.json").read_text())["moments"]:
            frame = frame_at(root / f"{m['id']}.mp4", m["cue_s"] + AFTER_CUE_S)
            frame = cv2.resize(frame, (640, round(frame.shape[0] * 640 / frame.shape[1])))
            reply = (sam.judge(frame), getattr(sam.impl, "last", {}))
            rows.append({"id": m["id"], "split": m["split"], "scene": m["scene"], "label": m["label"], "lift_cm": m.get("lift_cm"),
                         "reflex": reflex.state(frame)[0], "sam3": reply[0], "rings": reply[1].get("rings"),
                         "sam3_s": reply[1].get("seconds")})
            print(json.dumps(rows[-1]), flush=True)
    finally:
        sam.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
