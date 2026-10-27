"""Run the changing-table skill live on the generated clips and write results/kr222/table.json.

    python scripts/kr222_table.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/kt/clips --passes 3

It joins the changing-table clips into one loop at one frame size, streams the loop in real time through the
skill (local reflex, SAM 3.1 confirm, chime then voice), for a number of passes, then scores every pass of every
clip against its cue: a both_hands_off clip must speak "hand" within 2.5 s of the moment the last hand leaves,
and a one_hand clip must stay silent. Latency is wall time from the cue in the stream to the spoken prompt.
Closing the skill logs one diaper change in Baby Buddy when BABYBUDDY_URL and BABYBUDDY_TOKEN are set.
The output follows the schema read by measure-kr222.sh.
"""
import argparse
import datetime
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent import config as config_mod  # noqa: E402
from parenting_agent import confirm as confirm_mod  # noqa: E402
from parenting_agent.agent.config import load_env  # noqa: E402
from parenting_agent.bus import Bus  # noqa: E402
from parenting_agent.reflex import MediaPipeReflex  # noqa: E402
from parenting_agent.skill import Skill, watch  # noqa: E402
from parenting_agent.sources import VideoSource  # noqa: E402

WIDTH, HEIGHT, FPS = 640, 360, 30
KINDS = {"handsoff": "both_hands_off", "onehand": "one_hand"}
EARLY_TOLERANCE_S = 0.25


def table_clips(clips_dir, cues):
    """Changing-table clips with a cue: files named table-<kind>-NN, or dropped in the handsoff and onehand folders."""
    found = {}
    for folder, kind in KINDS.items():
        for n, path in enumerate(sorted((clips_dir / folder).glob("*.mp4")), start=1):
            found[f"table-{folder}-{n:02d}"] = (path, kind)
    for path in sorted(clips_dir.glob("table-*.mp4")):
        folder = path.stem.split("-")[1]
        if folder in KINDS:
            found[path.stem] = (path, KINDS[folder])
    return [(clip_id, path, kind, cues[clip_id]) for clip_id, (path, kind) in sorted(found.items()) if clip_id in cues]


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def build_loop(clips, out):
    parts, segments, offset = [], [], 0.0
    for n, (clip_id, path, kind, cue) in enumerate(clips):
        part = out / f"part-{n:02d}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-an", "-vf",
                        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:-1:-1,setsar=1,fps={FPS}",
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(part)], check=True)
        duration = probe_duration(part)
        segments.append({"clip_id": clip_id, "kind": kind, "start_s": offset, "end_s": offset + duration, "cue_s": offset + cue})
        parts.append(part)
        offset += duration
    listing = out / "parts.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                    str(out / "loop.mp4")], check=True)
    for p in parts + [listing]:
        p.unlink()
    return out / "loop.mp4", segments, offset


def score(voices, segments, period, passes):
    """voices: (stream_s, monotonic) per spoken prompt. Returns the moments of every complete pass."""
    moments = []
    for n in range(passes):
        base = n * period
        for seg in segments:
            start, end, cue = base + seg["start_s"], base + seg["end_s"], base + seg["cue_s"]
            if seg["kind"] == "both_hands_off":
                heard = [v for v in voices if cue - EARLY_TOLERANCE_S <= v["stream_s"] < end]
            else:
                heard = [v for v in voices if start <= v["stream_s"] < end]
            latency = round(max(0.0, heard[0]["heard_mono"] - v_cue_mono(heard[0], cue)), 3) if heard else None
            moments.append({"clip_id": seg["clip_id"], "kind": seg["kind"], "pass": n + 1,
                            "spoken": bool(heard), "latency_s": latency if seg["kind"] == "both_hands_off" else None})
    return moments


def v_cue_mono(voice, cue):
    """The wall instant the cue was on screen: the voice's frame shows stream_s at capture_mono."""
    return voice["capture_mono"] - (voice["stream_s"] - cue)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=Path, required=True)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--skill", default="skills/changing-table.json")
    parser.add_argument("--confirm", choices=["skill", "none"], default="skill", help="none skips SAM 3.1")
    parser.add_argument("--env-file", default="~/.parenting-agent.env")
    parser.add_argument("--out", type=Path, default=Path("results/kr222/table.json"))
    parser.add_argument("--run-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    load_env(args.env_file)
    run_dir = args.run_dir or Path(f"runs/kr222-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    run_dir.mkdir(parents=True, exist_ok=True)
    clips = table_clips(args.clips.expanduser(), json.loads((args.clips.expanduser() / "cues.json").read_text()))
    loop, segments, period = build_loop(clips, run_dir)

    cfg = config_mod.load(args.skill)
    bus = Bus(run_dir / "events.jsonl")
    detector = confirm_mod.NoConfirm() if args.confirm == "none" else confirm_mod.build(cfg["confirm"])
    confirm_name = getattr(detector, "name", "none")
    skill = Skill(cfg, bus, MediaPipeReflex(cfg["contact"]), confirm_detector=detector)
    source = VideoSource(str(loop), loops=True)
    while source.started is None and not source.stopped:
        time.sleep(0.01)

    voices = []

    def on_voice(event):
        now = time.monotonic()
        voices.append({"stream_s": event["stream_s"], "heard_mono": now,
                       "capture_mono": source.started + event["stream_s"]})

    bus.subscribe(on_voice, ["voice"])
    skill.arm()
    stop = threading.Event()
    timer = threading.Timer(period * args.passes + 0.5, stop.set)
    timer.start()
    worker = threading.Thread(target=watch, args=(skill, source), daemon=True)
    worker.start()
    stop.wait()
    source.close()
    worker.join(timeout=10)
    skill.close()
    bus.close()

    moments = score(voices, segments, period, args.passes)
    hands_off = [m for m in moments if m["kind"] == "both_hands_off"]
    table = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "live_stream",
        "skill": cfg["name"],
        "confirm": confirm_name,
        "passes": args.passes,
        "loop_s": round(period, 3),
        "clips": [{"clip_id": s["clip_id"], "kind": s["kind"], "cue_s": round(s["cue_s"] - s["start_s"], 3)} for s in segments],
        "summary": {
            "both_hands_off_spoken": f"{sum(m['spoken'] for m in hands_off)} of {len(hands_off)}",
            "max_latency_s": max((m["latency_s"] for m in hands_off if m["latency_s"] is not None), default=None),
            "one_hand_spoken": sum(m["spoken"] for m in moments if m["kind"] == "one_hand"),
            "frames": sum(1 for e in bus.history if e["kind"] == "frame"),
            "chimes": sum(1 for e in bus.history if e["kind"] == "chime"),
            "voices": len(voices),
            "confirms": sum(1 for e in bus.history if e["kind"] == "confirm"),
            "diaper_logged": [e for e in bus.history if e["kind"] in ("tracked", "track_dry", "track_error")],
            "house": [e["kind"] + ":" + e["action"] for e in bus.history if e["kind"].startswith("house") or e["kind"] == "ask_parent"],
        },
        "moments": moments,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(table, indent=2) + "\n")
    print(json.dumps(table["summary"], indent=2))


if __name__ == "__main__":
    main()
