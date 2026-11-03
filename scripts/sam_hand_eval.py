"""The "hand" alarm on SAM 3.1 alone, on recordings, on a set frozen before it ran. Numbers only, no pixels.

    python scripts/sam_hand_eval.py freeze                 hashes the clips into results/sam-hand/set.json, commit that first
    python scripts/sam_hand_eval.py run --group leave      leave, held, plain or repeat, or all
    python scripts/sam_hand_eval.py report                 writes results/sam-hand/summary.json

Each clip streams in real time through a fresh SamOnlySkill, with one SAM 3.1 worker for all of them. House and log are off.
A moment that must alarm is caught if "hand" is spoken within SPEAK_WITHIN_S of the cue, the bar every earlier hover round
used, and late if only within LATE_WITHIN_S. A moment that must stay silent fails on any voice. A voice before the cue counts
against the clip too: the parent still has a hand on the baby. Latency is wall time from the cue on screen to the word.
"""
import argparse
import copy
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SYNTHETIC = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic"
OUT = ROOT / "results/sam-hand"
SKILLS = {"changing_table": "skills/changing-table.json", "bath": "skills/bath.json"}
SPEAK_WITHIN_S, LATE_WITHIN_S, EARLY_TOLERANCE_S = 2.5, 5.0, 0.25
GROUPS = {"held": "hover/held-blind2", "plain": "hover/fresh", "repeat": "hover/blind"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def leave_moments():
    """Both hands leave, or one stays. Generated video, cue from the clip's own manifest."""
    clips = json.loads((SYNTHETIC / "kt/clips/manifest.json").read_text())["clips"]
    return [{"id": c["id"], "clip": f"kt/clips/{c['file']}", "group": "leave", "scene": "bath" if c["id"].startswith("bath") else "changing_table",
             "kind": "hover" if c["expect"] == "alert" else "touch", "cue_s": c["cue_s"], "what": c["label"]} for c in clips]


def set_moments(group):
    base = GROUPS[group]
    moments = json.loads((SYNTHETIC / base / "labels.json").read_text())["moments"]
    return [{"id": m["id"], "clip": f"{base}/{m['id']}.mp4", "group": group, "scene": m["scene"], "kind": m["label"], "cue_s": m["cue_s"],
             "what": m.get("held") or m["kind"], "lift_cm": m.get("lift_cm")} for m in moments]


def freeze():
    moments = leave_moments() + [m for group in GROUPS for m in set_moments(group)]
    for m in moments:
        m["sha256"] = sha(SYNTHETIC / m["clip"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "set.json").write_text(json.dumps({"bars": {"caught_s": SPEAK_WITHIN_S, "late_s": LATE_WITHIN_S}, "moments": moments}, indent=1) + "\n")
    print(len(moments), "moments frozen")


def run_moment(moment, cfg, detector):
    from parenting_agent.bus import Bus
    from parenting_agent.sam_hands import SamOnlySkill
    from parenting_agent.skill import watch
    from parenting_agent.sources import VideoSource
    bus = Bus()
    skill = SamOnlySkill(cfg, bus, detector)
    source = VideoSource(str(SYNTHETIC / moment["clip"]), loops=False)
    while source.started is None and not source.stopped:
        time.sleep(0.005)
    heard = []
    bus.subscribe(lambda e: heard.append((e["stream_s"], time.monotonic(), e["reason"])), ["voice"])
    skill.arm()
    worker = threading.Thread(target=watch, args=(skill, source), daemon=True)
    worker.start()
    worker.join()
    skill.close()
    cue = source.started + moment["cue_s"]
    early = [v for v in heard if v[0] < moment["cue_s"] - EARLY_TOLERANCE_S]
    late = [v for v in heard if v[0] >= moment["cue_s"] - EARLY_TOLERANCE_S]
    looks = [e["seconds"] for e in bus.history if e["kind"] == "sam3_look" and e.get("seconds") is not None]
    return {"id": moment["id"], "group": moment["group"], "scene": moment["scene"], "kind": moment["kind"], "what": moment["what"],
            "latency_s": round(late[0][1] - cue, 3) if late and moment["kind"] == "hover" else None,
            "voices": len(heard), "voices_before_cue": len(early), "reasons": [v[2] for v in heard],
            "looks": len(looks), "look_s_median": sorted(looks)[len(looks) // 2] if looks else None,
            "frames": sum(1 for e in bus.history if e["kind"] == "frame"), "errors": sum(1 for e in bus.history if e["kind"] == "sam3_error")}


def run(groups, limit=None):
    """Saved after every clip. A run that stops carries on from the .partial and never scores a clip twice, and limit stops
    after that many new clips, so the SAM 3.1 worker's memory can start clean in a new process."""
    from parenting_agent import confirm as confirm_mod
    from parenting_agent import config as config_mod
    frozen = json.loads((OUT / "set.json").read_text())["moments"]
    OUT.mkdir(exist_ok=True)
    detector = None
    for group in groups:
        path = OUT / f"{group}.json"
        if path.exists():
            continue
        partial = path.with_suffix(".partial")
        rows = json.loads(partial.read_text()) if partial.exists() else []
        done = {r["id"] for r in rows}
        for moment in [m for m in frozen if m["group"] == group and m["id"] not in done]:
            if limit is not None and limit <= 0:
                return False
            limit = None if limit is None else limit - 1
            assert sha(SYNTHETIC / moment["clip"]) == moment["sha256"], moment["id"]
            cfg = copy.deepcopy(config_mod.load(SKILLS[moment["scene"]]))
            cfg["house"] = {"allowed": {}, "on_armed": [], "on_voice": [], "on_closed": []}
            cfg["tracking"] = {"provider": "none", "on_closed": None}
            detector = detector or confirm_mod.build(cfg["confirm"])
            rows.append(run_moment(moment, cfg, detector))
            print(rows[-1]["id"], rows[-1]["kind"], rows[-1]["latency_s"], rows[-1]["voices"], flush=True)
            partial.write_text(json.dumps(rows, indent=1))
        path.write_text(json.dumps(rows, indent=1) + "\n")
        partial.unlink()
    return True


def score(rows):
    must = [r for r in rows if r["kind"] == "hover"]
    silent = [r for r in rows if r["kind"] == "touch"]
    def clean(r):
        return not r["voices_before_cue"]
    caught = [r for r in must if r["latency_s"] is not None and r["latency_s"] <= SPEAK_WITHIN_S and clean(r)]
    late = [r for r in must if r["latency_s"] is not None and SPEAK_WITHIN_S < r["latency_s"] <= LATE_WITHIN_S and clean(r)]
    lat = sorted(r["latency_s"] for r in caught + late)
    looks = sorted(r["look_s_median"] for r in rows if r["look_s_median"] is not None)
    return {"must_alarm": len(must), "caught": len(caught), "late": len(late), "missed": len(must) - len(caught) - len(late),
            "spoke_before_the_cue": sum(not clean(r) for r in must), "must_stay_silent": len(silent), "false_alarms": sum(bool(r["voices"]) for r in silent),
            "latency_median_s": lat[len(lat) // 2] if lat else None, "latency_max_s": lat[-1] if lat else None,
            "look_median_s": looks[len(looks) // 2] if looks else None, "errors": sum(r["errors"] for r in rows)}


def report():
    summary = {}
    for path in sorted(OUT.glob("*.json")):
        if path.name not in ("set.json", "summary.json"):
            rows = json.loads(path.read_text())
            summary[path.stem] = score(rows)
            for scene in sorted({r["scene"] for r in rows}):
                summary[f"{path.stem}/{scene}"] = score([r for r in rows if r["scene"] == scene])
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "run", "report"])
    parser.add_argument("--group", default="all", help="leave, held, plain, repeat or all")
    parser.add_argument("--limit", type=int, help="stop after this many new clips, exit 3 if clips are left")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "report":
        report()
    else:
        finished = run(["leave", "held", "plain", "repeat"] if args.group == "all" else [args.group], args.limit)
        if not finished:
            raise SystemExit(3)


if __name__ == "__main__":
    main()
