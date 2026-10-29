"""The car seat segment of the hero video: the car seat coach on rendered test clips, with the SAM 3.1 masks it
decided from drawn on each frame, its verdict per check, and its spoken lines in MMS-TTS (Meta, on this Mac).

    python scripts/carseat_hero_segment.py --out-dir results/hero2 --name carseat \
        --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips/test

The coach runs exactly as in scripts/carseat_eval.py (the clip streamed in real time, SAM 3.1 on the newest frame
after each step is spoken, scripted answers to the hand checks). Each SAM 3.1 call is kept with its frame, so the
frame a verdict came from is the frame shown, with that call's masks. Writes <name>.mp4 (portrait, the hero
recording's size, to be joined after it) and <name>.json with every check, every SAM 3.1 call's seconds and every
spoken line. The clips are renders of a doll in a carrier, no real child.

MMS-TTS runs in the family's voice service on the Vostro (pa-voice-family, int8 ONNX decoder, CPU), reached over
ssh with docker exec, because the Mac's venv has no torch. Only the coach's text goes there, never a frame.
"""
import argparse
import base64
import io
import os
import json
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent.bus import Bus  # noqa: E402
from parenting_agent.carseat.coach import CAMERA_STEPS, Coach, load_profiles  # noqa: E402
from scripts.carseat_eval import ANSWERS  # noqa: E402

W, H, FPS = 588, 1280, 30
COLORS = [(255, 170, 40), (60, 200, 255), (200, 90, 255), (90, 255, 140)]  # BGR, one per prompt
VERDICT = {"pass": ((80, 200, 80), "PASS"), "fail": ((60, 60, 235), "FAIL"), "unseen": ((150, 150, 150), "NOT SEEN")}
NAMES = {"lap_guides": "Lap belt in both side guides", "shoulder_guide": "Shoulder belt in the rear guide",
         "no_twist": "No twist in the lap belt", "level_line": "Level line level", "handle": "Handle upright"}


class KeptVision:
    """SAM 3.1 masks, with every call's frame and answer kept for drawing."""

    def __init__(self, vision):
        self.vision, self.calls = vision, []

    def masks(self, frame, prompts):
        found, seconds = self.vision.masks(frame, prompts)
        self.calls.append({"frame": frame.copy(), "found": found, "seconds": seconds, "prompts": list(prompts)})
        return found, seconds


def wrap(text, width=34):
    lines, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width and line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


def put(canvas, lines, y, scale=0.8, color=(240, 240, 240), thick=2, gap=34, x=24):
    for line in lines:
        cv2.putText(canvas, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)
        y += gap
    return y


def card(title, body, footer=""):
    canvas = np.full((H, W, 3), 18, np.uint8)
    y = put(canvas, wrap(title, 26), 380, 1.05, (255, 255, 255), 2, 46)
    y = put(canvas, wrap(body, 36), y + 30, 0.72, (210, 210, 210), 2, 32)
    put(canvas, wrap(footer, 40), 1180, 0.6, (150, 150, 150), 1, 26)
    return canvas


def check_frame(call, check, result, spoken, clip):
    canvas = np.full((H, W, 3), 18, np.uint8)
    frame = call["frame"].copy()
    overlay = frame.copy()
    legend = []
    for i, prompt in enumerate(call["prompts"]):
        color = COLORS[i % len(COLORS)]
        items = call["found"].get(prompt, [])
        for score, mask in items:
            if score < 0.1:
                continue
            overlay[mask] = color
            contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(frame, contours, -1, color, 2)
        legend.append((prompt, color, sum(1 for s, _ in items if s >= 0.1)))
    frame = cv2.addWeighted(overlay, 0.45, frame, 0.55, 0)
    h = int(frame.shape[0] * W / frame.shape[1])
    top = 250
    canvas[top:top + h] = cv2.resize(frame, (W, h), interpolation=cv2.INTER_AREA)
    put(canvas, ["Car seat coach"], 70, 1.1, (255, 255, 255), 2)
    put(canvas, [f"SAM 3.1 masks, this Mac, {call['seconds']:.2f} s"], 112, 0.7, (200, 200, 200), 2)
    put(canvas, [f"Rendered clip {clip}"], 146, 0.6, (150, 150, 150), 1)
    put(canvas, [NAMES.get(check, check)], 210, 0.85, (255, 255, 255), 2)
    y = top + h + 40
    for prompt, color, n in legend:
        cv2.rectangle(canvas, (24, y - 18), (46, y + 2), color, -1)
        put(canvas, [f"\"{prompt}\": {n} mask{'s' if n != 1 else ''}"], y, 0.7, (230, 230, 230), 2, x=58)
        y += 38
    color, word = VERDICT.get(result, VERDICT["unseen"])
    cv2.rectangle(canvas, (24, y + 10), (W - 24, y + 90), color, -1)
    put(canvas, [word], y + 66, 1.5, (255, 255, 255), 3)
    put(canvas, wrap(f"\"{spoken}\"", 36), y + 150, 0.72, (220, 220, 220), 2, 32)
    return canvas


TTS = """
import sys, json, base64, time
from parenting_agent.voice.tts import MmsVoice
voice = MmsVoice()
out = []
for text in json.load(sys.stdin):
    started = time.monotonic()
    wav, _ = voice.synth(text, "en")
    out.append({"wav": base64.b64encode(wav).decode(), "seconds": round(time.monotonic() - started, 3)})
print(json.dumps({"decoders": voice.decoders, "items": out}))
"""


def vostro_tts(texts, container="pa-voice-family"):
    """WAV bytes for each text from MMS-TTS in the voice service, with its seconds per line and the decoder used."""
    done = subprocess.run(["ssh", "vostro", f"docker exec -i -w /app {container} python -c '{TTS}'"],
                          input=json.dumps(texts), capture_output=True, text=True, check=True)
    reply = json.loads(done.stdout.strip().splitlines()[-1])
    return [base64.b64decode(i["wav"]) for i in reply["items"]], [i["seconds"] for i in reply["items"]], reply["decoders"]


def wav_seconds(data):
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


def run_clip(path, cfg, seat, car, vision):
    from parenting_agent.sources import VideoSource
    bus = Bus()
    source = VideoSource(str(path), loops=False)
    while source.started is None and not source.stopped:
        time.sleep(0.005)
    start = len(vision.calls)
    coach = Coach(cfg, bus, vision, source, seat, car)
    for check, reply in ANSWERS.items():
        coach.answer(check, reply)
    results = coach.run()
    source.close()
    calls = vision.calls[start:]
    frames = [e for e in bus.history if e["kind"] == "carseat_frame"]
    shown = []
    for check in CAMERA_STEPS:
        r = results.get(check)
        if not r:
            continue
        mine = [i for i, e in enumerate(frames) if e["step"] == check]
        index = next((i for i in mine if frames[i]["frame_s"] == r.get("frame_s")), mine[-1] if mine else None)
        if index is None:
            continue
        spoken = next((e["text"] for e in bus.history if e["kind"] == "voice" and e.get("step") == check and e.get("result")), "")
        shown.append({"check": check, "result": r["result"], "frame_s": r["frame_s"], "spoken": spoken,
                      "sam_s": frames[index]["sam_s"] if index is not None else None, "call": index})
    return {"results": {k: v["result"] for k, v in results.items()}, "shown": shown, "calls": calls,
            "sam_seconds": [round(c["seconds"], 3) for c in calls],
            "spoken": [e["text"] for e in bus.history if e["kind"] == "voice"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", default="~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips/test")
    parser.add_argument("--clip", action="append", help="clip file names, default a correct and a twisted install")
    parser.add_argument("--skill", default=str(ROOT / "skills/car-seat.json"))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--name", default="carseat")
    args = parser.parse_args()
    clips = Path(args.clips).expanduser()
    names = args.clip or ["test-02-correct.mp4", "test-16-twisted.mp4"]
    labels = {l["clip"]: l for l in json.loads((clips / "labels.json").read_text())}
    cfg = json.loads(Path(args.skill).read_text())
    seat, car = load_profiles(cfg, ROOT)
    from parenting_agent.carseat.sam3_masks import Sam3Masks
    sam = Sam3Masks(cfg.get("sam3"))
    vision = KeptVision(sam)
    runs = []
    try:
        for name in names:
            row = run_clip(clips / name, cfg, seat, car, vision)
            print(name, row["results"], flush=True)
            runs.append((name, row))
    finally:
        sam.close()
        lock = os.environ.get("PA_GPU_LOCK_RELEASE")  # the GPU is free once SAM 3.1 closed, the voice runs elsewhere
        if lock:
            try:
                os.rmdir(lock)
            except OSError:
                pass

    lines = [item["spoken"] for _, row in runs for item in row["shown"]]
    wavs, tts, decoders = vostro_tts(lines)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        scenes, report = [], []  # (image, seconds, wav or None)
        scenes.append((card("Car seat coach", "SAM 3.1 finds the belt, the guides and the level line by text on each "
                            "frame. Simple geometry on its masks decides each check. The coach never calls an install safe.",
                            "Rendered test clips of a doll in a carrier, no real child. Voice: MMS-TTS (Meta), the home server."), 3.5, None))
        spoken = iter(wavs)
        for name, row in runs:
            label = labels.get(name, {})
            mistake = label.get("error") or "none, a correct install"
            scenes.append((card(f"Clip {name}", f"Planted mistake: {mistake}."), 2.0, None))
            for item in row["shown"]:
                call = row["calls"][item["call"]]
                wav = next(spoken)
                file = tmp / f"{len(scenes):03d}.wav"
                file.write_bytes(wav)
                seconds = max(2.2, wav_seconds(wav) + 0.5)
                scenes.append((check_frame(call, item["check"], item["result"], item["spoken"], name), seconds, file))
            report.append({"clip": name, "planted_mistake": label.get("error"), "results": row["results"],
                           "shown": [{k: v for k, v in i.items() if k != "call"} for i in row["shown"]],
                           "sam_calls": len(row["calls"]), "sam_seconds": row["sam_seconds"], "spoken": row["spoken"]})
        silent = tmp / "video.mp4"
        writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
        audio_inputs, filters, at = [], [], 0.0
        for image, seconds, wav in scenes:
            for _ in range(int(round(seconds * FPS))):
                writer.write(image)
            if wav:
                audio_inputs += ["-i", str(wav)]
                n = len(audio_inputs) // 2
                ms = int((at + 0.25) * 1000)
                filters.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=mono,adelay={ms}|{ms}[a{n}]")
            at += round(seconds * FPS) / FPS
        writer.release()
        n = len(audio_inputs) // 2
        if n == 0:
            audio_inputs, n = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"], 1
            filters.append("[1:a]anull[a1]")
        mix = "".join(f"[a{i}]" for i in range(1, n + 1))
        filters.append(f"{mix}amix=inputs={n}:normalize=0:duration=longest,apad=whole_dur={at:.3f},atrim=0:{at:.3f}[aout]")
        video = out / f"{args.name}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), *audio_inputs, "-filter_complex", ";".join(filters),
                        "-map", "0:v", "-map", "[aout]", "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p",
                        "-r", str(FPS), "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "1", "-t", f"{at:.3f}",
                        "-movflags", "+faststart", str(video)], check=True)
    all_sam = [s for r in report for s in r["sam_seconds"]]
    summary = {"date": time.strftime("%Y-%m-%d %H:%M %z"), "sam3": sam.source, "voice": f"MMS-TTS facebook/mms-tts-eng, the Vostro voice service, CPU, decoder {decoders}",
               "clips": report, "sam_calls": len(all_sam), "sam_median_s": float(np.median(all_sam)) if all_sam else None,
               "sam_max_s": max(all_sam) if all_sam else None, "tts_seconds_per_line": tts, "video": {"file": video.name,
               "bytes": video.stat().st_size, "seconds": round(at, 2)}}
    (out / f"{args.name}.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "clips"}, indent=1))


if __name__ == "__main__":
    main()
