"""What the simulator's "Meta's models on real recordings" section shows, computed for real on this Mac and saved as results.

    python scripts/sim_senses.py hearing   # Perception Encoder Audio on four licensed clips, with the frozen thresholds
    python scripts/sim_senses.py sam       # SAM 3.1 on two frames of a generated clip, hand and baby masks

Run one at a time, they share the Mac's GPU. The page plays these clips and these masks, and says they were computed earlier.
The walled simulator container runs neither model.
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OUT = REPO / "parenting_agent/simulator/static/senses"
RESULT = OUT / "senses.json"
SOURCE = Path(os.path.expanduser("~/Engineering/gonza/meta-hackathon-2026-synthetic"))
CLIPS = (("cry", "audio/cry-03.wav", 3.0, "Crying newborn baby", "CC0", "https://commons.wikimedia.org/wiki/File:Crying_newborn_baby.ogg"),
         ("dog", "audio/dog-01.wav", 2.0, "Barking dog in Rome", "CC BY-SA 3.0", "https://commons.wikimedia.org/wiki/File:Barking_dog_in_Rome.ogg"),
         ("doorbell", "audio/doorbell-04.wav", 0.0, "Electronic doorbell", "CC0", "https://commons.wikimedia.org/wiki/File:Electronic_doorbell.ogg"),
         ("kitchen", "audio2/raw/Ambient Kitchen Sounds.wav", 5.0, "Ambient Kitchen Sounds", "CC0", "https://commons.wikimedia.org/wiki/File:Ambient_Kitchen_Sounds.wav"))
SECONDS = 8
CLIP = "kt/clips/handsoff/table-handsoff-01.mp4"
FRAMES = (("hands-on", 1.0), ("hands-off", 5.0))


def saved():
    return json.loads(RESULT.read_text()) if RESULT.is_file() else {"audio": [], "frames": []}


def hearing():
    from parenting_agent import hearing as h
    listener = h.MetaListener({"labels": list(h.LABELS), "device": "mps"})
    rows = []
    try:
        for name, file, start, title, license_, page in CLIPS:
            path = SOURCE / file
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(SECONDS), "-i", str(path), "-ac", "1", "-c:a", "aac", "-b:a", "48k",
                            "-map_metadata", "-1", "-movflags", "+faststart", str(OUT / f"{name}.m4a")], check=True)
            samples = h.from_file(path, start, SECONDS, camera_channel=True)
            rate, best = h.RATE, {}
            for begin in range(0, max(1, len(samples) - 2 * rate + 1), rate):
                reply = listener.score(samples[begin:begin + 2 * rate])
                for label, numbers in reply["raw"].items():
                    best[label] = max(best.get(label, -99.0), numbers["logit"])
            scores = {label: {"probability": round(1 / (1 + math.exp(-value)), 4), "logit": round(value, 2), "threshold": h.THRESHOLDS[label], "fired": value >= h.THRESHOLDS[label]}
                      for label, value in best.items()}
            rows.append({"id": name, "file": f"{name}.m4a", "title": title, "license": license_, "page": page, "scores": scores,
                         "heard": max((l for l in scores if scores[l]["fired"]), key=lambda l: scores[l]["logit"], default=None)})
    finally:
        listener.close()
    data = saved()
    data["audio"] = rows
    data["audio_model"] = "facebook/pe-a-frame-small, through the Tapo audio channel, 2 s windows, thresholds from results/sounds/meta-hearing/tune.json"
    RESULT.write_text(json.dumps(data, indent=1) + "\n")
    print(json.dumps(rows, indent=1)[:3000])


def sam():
    import cv2
    import numpy as np
    from parenting_agent.sam3_local import Sam3Local
    worker = Sam3Local({"device": "mps", "frame_codec": "png"})
    rows = []
    try:
        capture = cv2.VideoCapture(str(SOURCE / CLIP))
        for name, at in FRAMES:
            capture.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
            ok, frame = capture.read()
            assert ok, name
            frame = cv2.resize(frame, (640, round(frame.shape[0] * 640 / frame.shape[1])), interpolation=cv2.INTER_AREA)
            verdict = worker.judge(frame)
            hands, baby = worker.masks(frame)
            shown = frame.copy()
            for mask in hands:
                shown[mask] = (0.45 * shown[mask] + 0.55 * np.array((61, 184, 245))).astype(np.uint8)
            if baby is not None:
                shown[baby] = (0.65 * shown[baby] + 0.35 * np.array((208, 219, 122))).astype(np.uint8)
            cv2.imwrite(str(OUT / f"{name}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
            cv2.imwrite(str(OUT / f"{name}-mask.jpg"), shown, [cv2.IMWRITE_JPEG_QUALITY, 78])
            rows.append({"id": name, "file": f"{name}.jpg", "mask": f"{name}-mask.jpg", "hands": len(hands), "baby": baby is not None, "verdict": verdict, "at_s": at})
    finally:
        worker.process.stdin.close()
        worker.process.wait(timeout=20)
    data = saved()
    data["frames"] = rows
    data["frame_model"] = "SAM 3.1 hand and baby masks, on a generated clip with no real baby"
    RESULT.write_text(json.dumps(data, indent=1) + "\n")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    {"hearing": hearing, "sam": sam}[sys.argv[1]]()
