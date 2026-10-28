"""Render the touch versus hover test set (issues #6 and #10) from the generated changing-table and bath clips.

    python scripts/hover_render.py --synthetic ~/Engineering/gonza/meta-hackathon-2026-synthetic

Every moment starts from a stretch of a generated clip where the parent's hands rest on the baby (a generated
baby or a doll, never a real child), played forward then backward so it lasts long enough. At cue_s:
  touch   nothing changes, the hands keep resting on the baby. The voice must stay silent.
  hover   the hands lift lift_cm above the baby over 0.3 s and stay there. Rendered from the head camera's view:
          the hand grows by the perspective factor D / (D - lift) about the image centre (D = 45 cm, a head over
          a changing table or a bath), and its shadow lands on the baby, offset by SHADOW_PX_PER_CM per cm of lift.
          No hand touches the baby, so the voice must speak.
Hands are found by MediaPipe hand landmarks: the convex hull of the 21 points, grown a little and feathered.
The forearm is not moved, only the hand. Each source is also rendered mirrored left to right.
natural  hover moments that the generated clips already show (hands lifted above the baby), labelled by eye.

Sources are split by scene: dev sources pick thresholds, test sources are only scored. Clips and a contact sheet
per moment go to <synthetic>/hover/set, never into git. moments.json lists every moment with its label.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent.reflex import MODELS  # noqa: E402

WIDTH, FPS, LENGTH_S, CUE_S, RAMP_S = 640, 30, 7.0, 2.5, 0.3
CAMERA_CM, SHADOW_PX_PER_CM = 45.0, 4.0
LIFTS_CM = (2.0, 3.5, 5.0)
# id, file, scene, split, start_s and end_s of the stretch where every hand in view rests on the baby (by eye)
SOURCES = [
    ("table-a", "grok-onehand.mp4", "changing_table", "test", 2.6, 4.8),
    ("table-b", "hover/hover.mp4", "changing_table", "test", 2.0, 3.6),
    ("table-d", "grok-handsoff.mp4", "changing_table", "dev", 0.0, 1.8),
    ("table-e", "kling-handsoff.mp4", "changing_table", "dev", 0.0, 1.2),
    ("table-f", "grok-handsoff.mp4", "changing_table", "dev", 2.4, 3.2),
    ("bath-a", "bath/clips/bath-handoff-01.mp4", "bath", "test", 0.4, 3.8),
    ("bath-b", "bath/clips/bath-onehand-01.mp4", "bath", "test", 0.0, 7.4),
]
# hover moments already in the generated clips: file, scene, split, clip start_s, cue_s inside the cut (by eye)
NATURAL = [
    ("natural-table-e", "kling-handsoff.mp4", "changing_table", "dev", 0.0, 3.2,
     "forearm and both hands held above the baby while unfolding a diaper, from 3.2 s"),
    ("natural-table-b", "hover/hover.mp4", "changing_table", "test", 0.0, 3.8,
     "both hands lift off the chest and hang open above the baby at 3.8 s, then move to the sides"),
    ("natural-bath-a", "bath/clips/bath-handoff-01.mp4", "bath", "test", 0.0, 4.0,
     "both hands lift open above the doll at 4.0 s, then leave"),
]


def read(path, start_s, end_s):
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    frames, index = [], 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        t = index / fps
        index += 1
        if start_s <= t < end_s:
            frames.append(cv2.resize(frame, (WIDTH, round(frame.shape[0] * WIDTH / frame.shape[1] / 2) * 2)))
    capture.release()
    step = fps / FPS
    return [frames[min(int(i * step), len(frames) - 1)] for i in range(int(len(frames) * FPS / fps))]


def ping_pong(frames, seconds, phase=0):
    cycle = frames + frames[-2:0:-1]
    return [cycle[(phase + i) % len(cycle)] for i in range(int(seconds * FPS))]


class Hands:
    def __init__(self):
        from mediapipe.tasks.python import BaseOptions, vision
        import mediapipe
        self.mp = mediapipe
        self.landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(Path(MODELS) / "hand_landmarker.task")), num_hands=2,
            min_hand_detection_confidence=0.3))
        self.last = []

    def masks(self, frame):
        h, w = frame.shape[:2]
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        found = []
        for landmarks in self.landmarker.detect(image).hand_landmarks:
            points = np.array([[p.x * w, p.y * h] for p in landmarks], np.float32)
            hull = cv2.convexHull(points)
            centre = points.mean(axis=0)
            grown = (hull - centre) * 1.18 + centre
            mask = np.zeros((h, w), np.uint8)
            cv2.fillConvexPoly(mask, grown.astype(np.int32), 255)
            found.append(mask)
        self.last = found or self.last  # a missed detection keeps the previous masks, hands move little per frame
        return self.last


def lift(frame, masks, lift_cm):
    """The hands lift_cm above where they rest, as the head camera sees it."""
    if lift_cm <= 0 or not masks:
        return frame
    h, w = frame.shape[:2]
    scale = CAMERA_CM / (CAMERA_CM - lift_cm)
    shift = SHADOW_PX_PER_CM * lift_cm
    out = frame.astype(np.float32)
    union = np.zeros((h, w), np.float32)
    for mask in masks:
        union = np.maximum(union, mask.astype(np.float32) / 255)
    shadow = cv2.warpAffine(cv2.GaussianBlur(union, (0, 0), 3 + lift_cm), np.float32([[1, 0, shift * 0.6], [0, 1, shift]]), (w, h))
    out *= 1 - 0.45 * shadow[..., None]
    zoom = cv2.getRotationMatrix2D((w / 2, h / 2), 0, scale)
    raised = cv2.warpAffine(frame, zoom, (w, h)).astype(np.float32)
    alpha = cv2.GaussianBlur(cv2.warpAffine(union, zoom, (w, h)), (0, 0), 2)[..., None]
    return (out * (1 - alpha) + raised * alpha).clip(0, 255).astype(np.uint8)


def write(frames, path):
    h, w = frames[0].shape[:2]
    process = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                                "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                                str(path)], stdin=subprocess.PIPE)
    for frame in frames:
        process.stdin.write(frame.tobytes())
    process.stdin.close()
    process.wait()


def sheet(frames, path, cue_s):
    picks = [round((CUE_S - 0.5) * FPS), round(cue_s * FPS), round((cue_s + 0.5) * FPS), round((cue_s + 2.0) * FPS)]
    tiles = [cv2.resize(frames[min(i, len(frames) - 1)], (320, round(320 * frames[0].shape[0] / frames[0].shape[1]))) for i in picks]
    cv2.imwrite(str(path), np.hstack(tiles))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.synthetic.expanduser()
    out = root / "hover" / "set"
    (out / "sheets").mkdir(parents=True, exist_ok=True)
    hands = Hands()
    moments = []
    for source_id, file, scene, split, start_s, end_s in SOURCES:
        base = read(root / file, start_s, end_s)
        for mirrored in (False, True):
            frames = [cv2.flip(f, 1) for f in base] if mirrored else base
            tag = f"{source_id}{'-m' if mirrored else ''}"
            for phase in (0, len(frames) // 2):
                clip = ping_pong(frames, LENGTH_S, phase)
                moment = f"{tag}-touch-p{phase}"
                write(clip, out / f"{moment}.mp4")
                sheet(clip, out / "sheets" / f"{moment}.jpg", CUE_S)
                moments.append({"id": moment, "source": source_id, "file": file, "scene": scene, "split": split,
                                "kind": "touch", "lift_cm": 0.0, "mirrored": mirrored, "cue_s": CUE_S, "origin": "generated"})
            clip = ping_pong(frames, LENGTH_S)
            hands.last = []
            masks = [hands.masks(f) for f in clip]
            for lift_cm in LIFTS_CM:
                moment = f"{tag}-hover-{lift_cm:g}cm"
                rendered = [f if i < CUE_S * FPS else
                            lift(f, m, lift_cm * min(1.0, (i / FPS - CUE_S) / RAMP_S))
                            for i, (f, m) in enumerate(zip(clip, masks))]
                write(rendered, out / f"{moment}.mp4")
                sheet(rendered, out / "sheets" / f"{moment}.jpg", CUE_S)
                moments.append({"id": moment, "source": source_id, "file": file, "scene": scene, "split": split,
                                "kind": "hover", "lift_cm": lift_cm, "mirrored": mirrored, "cue_s": CUE_S, "origin": "rendered"})
    for moment, file, scene, split, start_s, cue_s, note in NATURAL:
        clip = read(root / file, start_s, start_s + 30)
        clip = clip + [clip[-1]] * int(2.5 * FPS)  # the scene goes on after the clip ends
        write(clip, out / f"{moment}.mp4")
        sheet(clip, out / "sheets" / f"{moment}.jpg", cue_s)
        moments.append({"id": moment, "source": moment, "file": file, "scene": scene, "split": split, "kind": "hover",
                        "lift_cm": None, "mirrored": False, "cue_s": cue_s, "origin": "generated", "note": note})
    (out / "moments.json").write_text(json.dumps({"camera_cm": CAMERA_CM, "shadow_px_per_cm": SHADOW_PX_PER_CM,
                                                  "fps": FPS, "moments": moments}, indent=2) + "\n")
    print(f"{len(moments)} moments in {out}")


if __name__ == "__main__":
    main()
