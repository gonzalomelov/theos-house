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

A fresh render reuses the method with other lifts and other points in each source, for a check the design never saw:
    python scripts/hover_render.py --synthetic ... --out fresh --splits test --lifts 2.5,4 --touch-phases 0.25,0.75 \
        --hover-phase 0.33 --no-natural
It also writes labels.json, labelled by construction (a rendered lift is a hover, an untouched stretch a touch).

A seeded render draws new poses per moment from --seed: every moment starts at its own point in the stretch, every
hover gets its own lift (2 to 5 cm), ramp (0.25 to 0.45 s), cue (2.2 to 2.8 s) and centre of perspective (the head
up to 40 px off the image centre). It is the blind set for issue #6 wave 2:
    python scripts/hover_render.py --synthetic ... --out blind --splits test --seed 1029 --hovers-per-tag 4 --no-natural
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


def lift(frame, masks, lift_cm, centre=None):
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
    zoom = cv2.getRotationMatrix2D(centre or (w / 2, h / 2), 0, scale)
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
    parser.add_argument("--out", default="set", help="folder under <synthetic>/hover")
    parser.add_argument("--splits", default="dev,test")
    parser.add_argument("--lifts", default=",".join(f"{v:g}" for v in LIFTS_CM))
    parser.add_argument("--touch-phases", default=None, help="fractions of the stretch, default 0 and 0.5")
    parser.add_argument("--hover-phase", type=float, default=0.0, help="fraction of the stretch")
    parser.add_argument("--no-natural", action="store_true")
    parser.add_argument("--seed", type=int, default=None, help="draw new poses per moment, see the docstring")
    parser.add_argument("--hovers-per-tag", type=int, default=4, help="with --seed")
    args = parser.parse_args(argv)
    root = args.synthetic.expanduser()
    out = root / "hover" / args.out
    splits, lifts = args.splits.split(","), [float(v) for v in args.lifts.split(",")]
    touch_phases = [float(v) for v in args.touch_phases.split(",")] if args.touch_phases else [0.0, 0.5]
    (out / "sheets").mkdir(parents=True, exist_ok=True)
    hands = Hands()
    moments = []
    if args.seed is not None:
        seeded(args, root, out, splits, hands, moments)
        return finish(args, out, moments)
    for source_id, file, scene, split, start_s, end_s in SOURCES:
        if split not in splits:
            continue
        base = read(root / file, start_s, end_s)
        for mirrored in (False, True):
            frames = [cv2.flip(f, 1) for f in base] if mirrored else base
            tag = f"{source_id}{'-m' if mirrored else ''}"
            for phase in [int(len(frames) * f) for f in touch_phases]:
                clip = ping_pong(frames, LENGTH_S, phase)
                moment = f"{tag}-touch-p{phase}"
                write(clip, out / f"{moment}.mp4")
                sheet(clip, out / "sheets" / f"{moment}.jpg", CUE_S)
                moments.append({"id": moment, "source": source_id, "file": file, "scene": scene, "split": split,
                                "kind": "touch", "lift_cm": 0.0, "mirrored": mirrored, "cue_s": CUE_S, "origin": "generated"})
            clip = ping_pong(frames, LENGTH_S, int(len(frames) * args.hover_phase))
            hands.last = []
            masks = [hands.masks(f) for f in clip]
            for lift_cm in lifts:
                moment = f"{tag}-hover-{lift_cm:g}cm"
                rendered = [f if i < CUE_S * FPS else
                            lift(f, m, lift_cm * min(1.0, (i / FPS - CUE_S) / RAMP_S))
                            for i, (f, m) in enumerate(zip(clip, masks))]
                write(rendered, out / f"{moment}.mp4")
                sheet(rendered, out / "sheets" / f"{moment}.jpg", CUE_S)
                moments.append({"id": moment, "source": source_id, "file": file, "scene": scene, "split": split,
                                "kind": "hover", "lift_cm": lift_cm, "mirrored": mirrored, "cue_s": CUE_S, "origin": "rendered"})
    for moment, file, scene, split, start_s, cue_s, note in ([] if args.no_natural else NATURAL):
        clip = read(root / file, start_s, start_s + 30)
        clip = clip + [clip[-1]] * int(2.5 * FPS)  # the scene goes on after the clip ends
        write(clip, out / f"{moment}.mp4")
        sheet(clip, out / "sheets" / f"{moment}.jpg", cue_s)
        moments.append({"id": moment, "source": moment, "file": file, "scene": scene, "split": split, "kind": "hover",
                        "lift_cm": None, "mirrored": False, "cue_s": cue_s, "origin": "generated", "note": note})
    finish(args, out, moments)


def seeded(args, root, out, splits, hands, moments):
    rng = np.random.default_rng(args.seed)
    for source_id, file, scene, split, start_s, end_s in SOURCES:
        if split not in splits:
            continue
        base = read(root / file, start_s, end_s)
        for mirrored in (False, True):
            frames = [cv2.flip(f, 1) for f in base] if mirrored else base
            tag = f"{source_id}{'-m' if mirrored else ''}"
            common = {"source": source_id, "file": file, "scene": scene, "split": split, "mirrored": mirrored, "seed": args.seed}
            for k in range(2):
                phase = int(rng.integers(len(frames)))
                cue_s = round(float(rng.uniform(2.2, 2.8)), 2)
                clip = ping_pong(frames, LENGTH_S, phase)
                moment = f"{tag}-touch-s{k}"
                write(clip, out / f"{moment}.mp4")
                sheet(clip, out / "sheets" / f"{moment}.jpg", cue_s)
                moments.append({"id": moment, **common, "kind": "touch", "lift_cm": 0.0, "phase": phase, "cue_s": cue_s,
                                "origin": "generated"})
            edges = np.linspace(2.0, 5.0, args.hovers_per_tag + 1)
            for k in range(args.hovers_per_tag):
                lift_cm = round(float(rng.uniform(edges[k], edges[k + 1])), 2)
                phase = int(rng.integers(len(frames)))
                cue_s = round(float(rng.uniform(2.2, 2.8)), 2)
                ramp_s = round(float(rng.uniform(0.25, 0.45)), 2)
                h, w = frames[0].shape[:2]
                centre = (w / 2 + float(rng.uniform(-40, 40)), h / 2 + float(rng.uniform(-40, 40)))
                clip = ping_pong(frames, LENGTH_S, phase)
                hands.last = []
                masks = [hands.masks(f) for f in clip]
                rendered = [f if i < cue_s * FPS else lift(f, m, lift_cm * min(1.0, (i / FPS - cue_s) / ramp_s), centre)
                            for i, (f, m) in enumerate(zip(clip, masks))]
                moment = f"{tag}-hover-s{k}"
                write(rendered, out / f"{moment}.mp4")
                sheet(rendered, out / "sheets" / f"{moment}.jpg", cue_s)
                moments.append({"id": moment, **common, "kind": "hover", "lift_cm": lift_cm, "phase": phase, "cue_s": cue_s,
                                "ramp_s": ramp_s, "centre_px": [round(c, 1) for c in centre], "origin": "rendered"})


def finish(args, out, moments):
    (out / "moments.json").write_text(json.dumps({"camera_cm": CAMERA_CM, "shadow_px_per_cm": SHADOW_PX_PER_CM,
                                                  "fps": FPS, "moments": moments}, indent=2) + "\n")
    if args.out != "set":  # the original set was labelled by eye in labels.json, a fresh render by construction
        (out / "labels.json").write_text(json.dumps({"labelled_by": "construction", "moments": [
            {**m, "label": m["kind"], "split": "test"} for m in moments]}, indent=2) + "\n")
    print(f"{len(moments)} moments in {out}")


if __name__ == "__main__":
    main()
