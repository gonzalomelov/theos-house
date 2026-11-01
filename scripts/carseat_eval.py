"""Run the car seat coach on the labeled rendered clips, streamed in real time, and score it (issue #30).

Each clip plays through the coach exactly as a camera would: the coach speaks a step, takes the newest frame,
runs SAM 3.1 on this Mac and speaks what it sees. Hand checks get scripted answers and are logged.

    python scripts/carseat_eval.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips/test

Scores:
  flagged       wrong clips where at least one visible check failed
  false alarms  correct clips where any visible check failed
  abstained     unseen clips where no belt check got a verdict (all not seen)
  latency       seconds from the step being visible (step spoken and carrier in view) to its result spoken
Writes results/carseat/<set>.json and <set>.md. Frames are never saved.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent.bus import Bus  # noqa: E402
from parenting_agent.carseat.coach import Coach, load_profiles  # noqa: E402
from parenting_agent.carseat.sam3_masks import Sam3Masks  # noqa: E402
from parenting_agent.sources import VideoSource  # noqa: E402

BELT_CHECKS = ("lap_guides", "shoulder_guide", "no_twist")
ANSWERS = {"harness_pinch": "no", "car_position": "yes", "buckle": "yes", "tension": "yes", "belt_path_movement": "yes"}
# The rendered clips are filmed from the door, the whole install already done: every step is judged at once (no wait
# for "listo"), the guides from the door (no close-ups), with the 8 s window the clips were scored with on Oct 28.
RENDERED = {"closeup": False, "ready_timeout_s": 0.0, "step_timeout_s": 8.0}


def run_clip(path, label, cfg, seat, car, vision):
    bus = Bus()
    source = VideoSource(str(path), loops=False)
    while source.started is None and not source.stopped:
        time.sleep(0.005)
    coach = Coach(cfg, bus, vision, source, seat, car)
    for check, reply in ANSWERS.items():
        coach.answer(check, reply)
    results = coach.run()
    source.close()
    camera = {k: v for k, v in results.items() if v["kind"] == "camera"}
    visible = label.get("visible_s")
    latencies = {}
    for check, r in camera.items():
        if r["result"] in ("pass", "fail") and visible is not None:
            latencies[check] = round(r["spoken_s"] - max(r["step_started_s"], visible), 3)
    spoken = [e["text"] for e in bus.history if e["kind"] == "voice"]
    return {"clip": label["clip"], "error": label["error"], "visible_s": visible,
            "results": {k: v["result"] for k, v in results.items()},
            "details": {k: {kk: vv for kk, vv in v.items() if kk not in ("kind",)} for k, v in camera.items()},
            "flagged": any(v["result"] == "fail" for v in camera.values()),
            "abstained": all(camera.get(c, {}).get("result") == "unseen" for c in BELT_CHECKS),
            "latency_s": latencies, "hand_checks_logged": sorted(k for k, v in results.items() if v["kind"] == "hand"),
            "spoken": spoken,
            "sam_frames": bus.count("carseat_frame")}


def score(rows):
    wrong = [r for r in rows if r["error"] and r["error"] != "unseen"]
    correct = [r for r in rows if not r["error"]]
    unseen = [r for r in rows if r["error"] == "unseen"]
    lat = [v for r in rows for v in r["latency_s"].values()]
    by_type = {}
    for r in wrong:
        t = by_type.setdefault(r["error"], {"clips": 0, "flagged": 0})
        t["clips"] += 1
        t["flagged"] += int(r["flagged"])
    return {
        "wrong_clips": len(wrong), "flagged": sum(r["flagged"] for r in wrong),
        "correct_clips": len(correct), "false_alarms": sum(r["flagged"] for r in correct),
        "unseen_clips": len(unseen), "abstained": sum(r["abstained"] and not r["flagged"] for r in unseen),
        "by_error": by_type,
        "latency": {"steps": len(lat), "median_s": round(statistics.median(lat), 2) if lat else None,
                    "max_s": round(max(lat), 2) if lat else None,
                    "within_2s": sum(v <= 2.0 for v in lat)},
        "said_safe": sum(any(" safe " in f" {t.lower().replace('.', ' ').replace(',', ' ')} " for t in r["spoken"]) for r in rows),
        "hand_checks_logged_every_clip": all(set(ANSWERS) <= set(r["hand_checks_logged"]) for r in rows),
    }


def markdown(name, summary, rows):
    s = summary
    lines = [f"# Car seat coach on rendered clips: {name}", "",
             f"- Wrong installs flagged: {s['flagged']} of {s['wrong_clips']}",
             f"- False alarms on correct installs: {s['false_alarms']} of {s['correct_clips']}",
             f"- Abstained when it could not see: {s['abstained']} of {s['unseen_clips']}",
             f"- Results spoken within 2 s of the step being visible: {s['latency']['within_2s']} of {s['latency']['steps']} "
             f"(median {s['latency']['median_s']} s, max {s['latency']['max_s']} s)",
             f"- Spoken texts containing 'safe': {s['said_safe']}",
             f"- Hand checks asked and logged in every clip: {s['hand_checks_logged_every_clip']}", "",
             "| Clip | Label | Lap guides | Shoulder guide | No twist | Level line | Handle | Flagged |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        res = r["results"]
        lines.append(f"| {r['clip']} | {r['error'] or 'correct'} | " + " | ".join(
            res.get(c, "-") for c in ("lap_guides", "shoulder_guide", "no_twist", "level_line", "handle"))
            + f" | {'yes' if r['flagged'] else 'no'} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", required=True)
    parser.add_argument("--skill", default=str(ROOT / "skills/car-seat.json"))
    parser.add_argument("--out", default=str(ROOT / "results/carseat"))
    args = parser.parse_args()
    clips = Path(args.clips).expanduser()
    labels = json.loads((clips / "labels.json").read_text())
    cfg = {**json.loads(Path(args.skill).read_text()), **RENDERED}
    seat, car = load_profiles(cfg, ROOT)
    vision = Sam3Masks(cfg.get("sam3"))
    rows = []
    try:
        for label in labels:
            row = run_clip(clips / label["clip"], label, cfg, seat, car, vision)
            rows.append(row)
            print(label["clip"], row["results"], "latency", row["latency_s"], flush=True)
    finally:
        vision.close()
    summary = score(rows)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = clips.name
    (out / f"{name}.json").write_text(json.dumps({"summary": summary, "sam3": vision.source, "clips": rows}, indent=1) + "\n")
    (out / f"{name}.md").write_text(markdown(name, summary, rows))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
