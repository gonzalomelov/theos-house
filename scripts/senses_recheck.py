"""The two local senses again on Nov 3, on recordings, with every setting frozen earlier. Numbers only, no audio or pixels.

    python scripts/senses_recheck.py hearing   # Perception Encoder Audio, the frozen held-out set, tune.json thresholds
    python scripts/senses_recheck.py sam       # SAM 3.1, the dog watch's blind split, as it is and through a Tapo-like channel

The Tapo-like channels stand in for the C200, no real camera frame is used. hd: 1920x1080 H.264 at 2 Mbit/s. sd: 640x360
H.264 at 400 kbit/s, the camera's low stream. night: sd in grayscale with sensor noise, as under infrared. Near ratio and
scores are dog_watch.DEFAULTS, not changed for these channels. Run one sense at a time, they share the Mac's GPU.
"""
import json
import subprocess
import sys
import tempfile
import time
from argparse import Namespace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
OUT = REPO / "results/senses-recheck"
BLIND = Path.home() / "Engineering/gonza/pa-local-data/dog-near-baby"
CHANNELS = {"source": None, "hd": ("1920:1080", "2M", False), "sd": ("640:360", "400k", False), "night": ("640:360", "400k", True)}


def hearing():
    import meta_hearing_eval as m
    with tempfile.TemporaryDirectory() as scratch:
        m.CACHE = Path(scratch)
        m.scores(Namespace(listener="meta", split="held_out"))
        got = m.cached("meta", "held_out")
    data, choices = m.split(), json.loads(m.TUNE.read_text())
    items = [i for i in data["items"] if i["split"] == "held_out"]
    OUT.mkdir(exist_ok=True)
    tally = m.tally(items, m.fired_by("meta", got["items"], choices))
    (OUT / "hearing.json").write_text(json.dumps({"at": got["at"], "window_s": got["window_s"], "load_s": got["load_s"], "wall_s": got["wall_s"], "tally": tally}, indent=1) + "\n")
    print(json.dumps(tally, indent=1))


def through(cv2, np, frame, channel, scratch):
    """The frame through a real H.264 encode and decode at the channel's size and bitrate."""
    if channel is None:
        return frame
    size, rate, night = channel
    source, coded = Path(scratch) / "in.png", Path(scratch) / "out.mp4"
    cv2.imwrite(str(source), frame)
    look = f"scale={size}:force_original_aspect_ratio=decrease,pad={size}:(ow-iw)/2:(oh-ih)/2" + (",format=gray,noise=alls=18:allf=t" if night else "") + ",format=yuv420p"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", "1", "-r", "15", "-i", str(source), "-vf", look, "-c:v", "libx264", "-preset", "veryfast", "-b:v", rate, str(coded)], check=True)
    capture = cv2.VideoCapture(str(coded))
    capture.set(cv2.CAP_PROP_POS_FRAMES, 10)
    ok, out = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError("no frame out of the channel")
    return out


def sam():
    import cv2
    import numpy as np
    from dog_watch_eval import latency, score
    from parenting_agent.carseat.sam3_masks import Sam3Masks
    from parenting_agent.dog_watch import DEFAULTS, measure, prompts
    cfg = {**DEFAULTS}
    labels = [r for r in json.loads((BLIND / "labels.json").read_text()) if r["split"] == "blind"]
    masks = Sam3Masks({"confidence": 0.3})
    report = {"near_ratio": cfg["near_ratio"], "channels": {name: list(c) if c else "the image as it is" for name, c in CHANNELS.items()}, "results": {}}
    OUT.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as scratch:
            for name, channel in CHANNELS.items():
                rows = []
                for item in labels:
                    frame = through(cv2, np, cv2.imread(str(BLIND / item["file"])), channel, scratch)
                    started = time.monotonic()
                    found, sam_s = masks.masks(frame, prompts(cfg))
                    m = measure(found, cfg)
                    rows.append({"id": item["id"], "label": item["label"], "kind": item["kind"], "measure": m, "sam_s": round(sam_s, 3), "total_s": round(time.monotonic() - started, 3)})
                result = {"score": score(rows, cfg), "latency": latency(rows),
                          "photos": score([r for r in rows if r["kind"] == "photo"], cfg), "composites": score([r for r in rows if r["kind"] == "composite"], cfg)}
                report["results"][name] = result
                (OUT / "sam.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
                print(name, json.dumps({k: result["score"][k] for k in ("caught", "near", "false_alerts", "not_near")}), result["latency"]["sam_median_s"], flush=True)
    finally:
        masks.close()


{"hearing": hearing, "sam": sam}[sys.argv[1]]()
