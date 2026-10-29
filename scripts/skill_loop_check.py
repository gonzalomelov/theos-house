"""A skill loop (both hands off and one hand on) streamed through the skill alone, n times, no brain.

    python scripts/skill_loop_check.py --scene bath --runs 10 --out runs/bath/onehand.json [--confirm sam3_local]
    python scripts/skill_loop_check.py --scene changing_table --fps 10 ...   the glasses feed: one hand, then hands off

The bath loop is the one scripts/bath_run.py builds, the changing-table loop is the glasses feed (live clips).
--fps resamples the loop, 10 is what the glasses app sends. --confirm-cfg is merged into the confirm config. A both_hands_off clip must speak "hand" within 2.5 s of the cue, the
one_hand clip must stay silent. Per run it keeps the reflex string and the lift reading per frame of each clip,
so a false voice can be traced. No Baby Buddy, no Home Assistant, no brain call.
"""
import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import kr222_table as k  # noqa: E402
from bath_run import CLIPS, bath_clips  # noqa: E402
from hover_ablation import Shared, skill_config  # noqa: E402
from parenting_agent import confirm as confirm_mod  # noqa: E402
from parenting_agent.bus import Bus  # noqa: E402
from parenting_agent.reflex import MediaPipeReflex  # noqa: E402
from parenting_agent.skill import Skill, watch  # noqa: E402
from parenting_agent.sources import VideoSource  # noqa: E402

TABLE_CLIPS = "~/Engineering/gonza/meta-hackathon-2026-synthetic/live/clips"
TABLE = [("table-onehand-01", "one_hand", 0.0), ("table-handsoff-01", "both_hands_off", 3.2)]
STATES = {"on": "1", "off": "0", "unknown": "?", "lifted": "^"}


def run_once(loop, segments, cfg, reflex, detector):
    bus = Bus()
    skill = Skill(cfg, bus, reflex, confirm_detector=detector or confirm_mod.NoConfirm())
    source = VideoSource(str(loop), loops=False)
    while source.started is None and not source.stopped:
        time.sleep(0.005)
    skill.arm()
    worker = threading.Thread(target=watch, args=(skill, source), daemon=True)
    worker.start()
    worker.join()
    time.sleep(2.5 if detector else 0)
    skill.confirm.collect()
    skill.close()
    events = list(bus.history)
    frames = [e for e in events if e["kind"] == "frame"]
    voices = [{"stream_s": e["stream_s"], "reason": e["reason"]} for e in events if e["kind"] == "voice"]
    rows = []
    for seg in segments:
        inside = [f for f in frames if seg["start_s"] <= f["stream_s"] < seg["end_s"]]
        if seg["kind"] == "both_hands_off":
            heard = [v for v in voices if seg["cue_s"] - k.EARLY_TOLERANCE_S <= v["stream_s"] < seg["end_s"]]
            latency = round(heard[0]["stream_s"] - seg["cue_s"], 3) if heard else None
            ok = latency is not None and latency <= 2.5
        else:
            heard = [v for v in voices if seg["start_s"] <= v["stream_s"] < seg["end_s"]]
            latency, ok = None, not heard
        rows.append({"clip_id": seg["clip_id"], "kind": seg["kind"], "pass": ok, "latency_s": latency,
                     "voices": [[round(v["stream_s"] - seg["start_s"], 2), v["reason"]] for v in heard],
                     "confirms": [e["verdict"] for e in events if e["kind"] == "confirm"
                                  and seg["start_s"] <= e.get("stream_s", -1) < seg["end_s"]],
                     "reflex": "".join(STATES.get(f["state"], "x") for f in inside),
                     "hands": [f.get("hands") for f in inside],
                     "lift": [[round(f["stream_s"] - seg["start_s"], 2), f.get("lift_cm")] for f in inside]})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--confirm", choices=["none", "sam3_local"], default="none")
    parser.add_argument("--lift", choices=["on", "off"], default=None)
    parser.add_argument("--lift-cfg", type=json.loads, default=None, help="JSON merged into the lift config")
    parser.add_argument("--confirm-cfg", type=json.loads, default=None, help="JSON merged into the confirm config")
    parser.add_argument("--scene", choices=["bath", "changing_table"], default="bath")
    parser.add_argument("--fps", type=float, default=None)
    parser.add_argument("--clips", type=json.loads, default=None,
                        help='JSON list of [id, path, kind, cue_s] played in order, kind both_hands_off (or a hover) or one_hand')
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    run_dir = args.out.parent / (args.out.stem + "-loop")
    run_dir.mkdir(parents=True, exist_ok=True)
    clips = [(c[0], Path(c[1]).expanduser(), c[2], c[3]) for c in args.clips] if args.clips else \
        bath_clips(Path(CLIPS).expanduser()) if args.scene == "bath" else [
        (clip_id, Path(TABLE_CLIPS).expanduser() / f"{clip_id}.mp4", kind, cue) for clip_id, kind, cue in TABLE]
    loop, segments, _ = k.build_loop(clips, run_dir)
    if args.fps:
        resampled = run_dir / "loop-fps.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(loop), "-vf", f"fps={args.fps}", "-c:v", "libx264",
                        "-preset", "veryfast", "-pix_fmt", "yuv420p", str(resampled)], check=True)
        loop = resampled
    cfg = skill_config(args.scene, None, args.lift, args.lift_cfg)
    cfg["confirm"].update(args.confirm_cfg or {})
    reflex = MediaPipeReflex(cfg["contact"])
    detector = Shared(confirm_mod.build(cfg["confirm"])) if args.confirm == "sam3_local" else None
    runs = []
    try:
        for n in range(args.runs):
            runs.append(run_once(loop, segments, cfg, reflex, detector))
            print(json.dumps([(r["clip_id"], r["pass"], r["latency_s"], r["voices"]) for r in runs[-1]]), flush=True)
    finally:
        if detector:
            detector.detector.close()
    summary = {kind: f"{sum(r['pass'] for run in runs for r in run if r['kind'] == kind)} of {len(runs)}"
               for kind in ("both_hands_off", "one_hand")}
    verdicts = [v for run in runs for r in run if r["kind"] == "both_hands_off" for v in r["confirms"]]
    summary["confirm_verdicts_on_hands_off"] = {v: verdicts.count(v) for v in sorted(set(verdicts))}
    args.out.write_text(json.dumps({"scene": args.scene, "fps": args.fps, "confirm": cfg["confirm"] if detector else "none",
                                    "lift": cfg.get("lift"), "summary": summary, "runs": runs}, indent=1) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
