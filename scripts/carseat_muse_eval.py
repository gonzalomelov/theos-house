"""Muse Spark Open's vision check of the car seat, scored on the labeled rendered clips (issue #30).

For each clip one still frame (at --at seconds, after the camera has settled on the carrier) is read into memory
and sent to Muse Spark Open on Baseten with the strict JSON schema in parenting_agent/carseat/muse_check.py.
Each install step is one focused question on that frame. Each answer is scored check by check against the clip's
label, alone and combined with the SAM 3.1 verdicts already stored in results/carseat/<set>.json by the
second-opinion rule (a pass needs both) on the checks Muse votes on.

    python scripts/carseat_muse_eval.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips/dev --tag v1

Frames are never saved. Only the scores and Muse's short notes are written, to results/carseat/muse/.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent.agent.config import load_env  # noqa: E402
from parenting_agent.carseat.muse_check import CHECKS, MUSE_VOTES, PROMPT_VERSION, MuseSeatCheck, combine  # noqa: E402
from parenting_agent.muse_senses import MuseSenses  # noqa: E402

PLANTED = {"twisted": ["no_twist"], "recline": ["level_line"], "handle": ["handle"]}


def truth(label):
    """{check: pass|fail|unseen} for one clip."""
    error = label["params"]["error"]
    if error == "unseen":
        return {c: "unseen" for c in CHECKS}
    wrong = PLANTED.get(error, [])
    if error == "outside_guide":
        wrong = ["shoulder_guide"] if label["params"].get("miss") == "rear" else ["lap_guides"]
    return {c: "fail" if c in wrong else "pass" for c in CHECKS}


def frame_at(path, seconds):
    import cv2
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"no frame at {seconds}s in {path}")
    return frame


def score(rows, key):
    """Per check: right, wrong, abstained, and the dangerous error (a pass where the truth is fail or unseen)."""
    out = {}
    for check in CHECKS:
        s = {"right": 0, "wrong": 0, "abstained": 0, "false_pass": 0, "false_fail": 0, "of": 0}
        for row in rows:
            t, p = row["truth"][check], row[key][check]
            s["of"] += 1
            if p in ("unseen", "unsure"):
                s["abstained" if t != "unseen" else "right"] += 1
            elif p == t:
                s["right"] += 1
            else:
                s["wrong"] += 1
                s["false_pass" if p == "pass" else "false_fail"] += 1
        out[check] = s
    return out


def frame_level(rows, key):
    wrong = [r for r in rows if r["error"] not in ("correct", "unseen")]
    correct = [r for r in rows if r["error"] == "correct"]
    unseen = [r for r in rows if r["error"] == "unseen"]
    return {
        "wrong_installs_flagged": sum(any(r[key][c] == "fail" for c in CHECKS) for r in wrong),
        "wrong_installs_planted_check_passed": sum(any(r[key][c] == "pass" for c in CHECKS if r["truth"][c] == "fail")
                                                   for r in wrong),
        "wrong_installs_all_pass": sum(all(r[key][c] == "pass" for c in CHECKS) for r in wrong),
        "wrong_installs_not_passed": sum(any(r[key][c] in ("fail", "unsure") for c in CHECKS if r["truth"][c] == "fail")
                                         for r in wrong),
        "wrong": len(wrong),
        "correct_all_pass": sum(all(r[key][c] == "pass" for c in CHECKS) for r in correct),
        "false_alarms": sum(any(r[key][c] == "fail" for c in CHECKS) for r in correct),
        "correct_with_unsure": sum(any(r[key][c] == "unsure" for c in CHECKS) for r in correct),
        "correct": len(correct),
        "unseen_any_pass": sum(any(r[key][c] == "pass" for c in CHECKS) for r in unseen),
        "unseen": len(unseen),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True)
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--at", type=float, default=3.0)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--only", nargs="*", help="clip names to run, for prompt work on a few")
    ap.add_argument("--checks", nargs="*", default=list(CHECKS), help="steps to ask Muse about")
    ap.add_argument("--samples", type=int, default=1, help="answers per step, majority wins")
    args = ap.parse_args()
    load_env("~/.parenting-agent.env")
    clips = Path(args.clips).expanduser()
    set_name = clips.name
    labels = json.loads((clips / "labels.json").read_text())
    sam = {c["clip"]: c["results"] for c in json.loads((ROOT / "results" / "carseat" / f"{set_name}.json").read_text())["clips"]}
    senses = MuseSenses({"reasoning_effort": args.effort, "samples_per_step": args.samples, "checks_asked": args.checks, "max_tokens": 8000})
    checker = MuseSeatCheck(senses, samples=args.samples)
    rows, calls = [], []
    for label in labels:
        if args.only and label["clip"] not in args.only:
            continue
        frame = frame_at(clips / label["clip"], args.at)
        steps = {c: checker.look(frame, c) if c in args.checks else {"result": None, "skipped": True} for c in CHECKS}
        calls += [s for s in steps.values() if s["result"] is not None]
        muse = {c: steps[c]["result"] or "unseen" for c in CHECKS}
        sam_row = {c: sam[label["clip"]][c] for c in CHECKS}
        both = {c: combine(sam_row[c], muse[c] if c in MUSE_VOTES and steps[c]["result"] else None)["result"]
                for c in CHECKS}
        row = {"clip": label["clip"], "error": label["params"]["error"], "truth": truth(label), "muse": muse,
               "sam": sam_row, "combined": both,
               "muse_steps": {c: {k: v for k, v in s.items() if k not in ("check", "host")} for c, s in steps.items()}}
        rows.append(row)
        bad = [c for c in CHECKS if muse[c] == "pass" and row["truth"][c] != "pass"]
        print(label["clip"], " ".join(f"{c}={muse[c]}" for c in CHECKS),
              "FALSE PASS " + ",".join(bad) if bad else "", flush=True)
    secs = [c["seconds"] for c in calls]
    summary = {
        "set": set_name, "tag": args.tag, "frames": len(rows), "frame_at_s": args.at,
        "prompt": PROMPT_VERSION, "model": senses.cfg["model"], "host": senses.destination, "reasoning_effort": args.effort, "samples_per_step": args.samples, "checks_asked": args.checks,
        "muse_alone": {"per_check": score(rows, "muse"), "frames": frame_level(rows, "muse")},
        "sam_alone": {"per_check": score(rows, "sam"), "frames": frame_level(rows, "sam")},
        "second_opinion": {"per_check": score(rows, "combined"), "frames": frame_level(rows, "combined")},
        "latency_s": {"median": statistics.median(secs), "max": max(secs), "mean": round(statistics.mean(secs), 3)} if secs else None,
        "usd": round(senses.spent_usd, 4), "usd_per_frame": round(senses.spent_usd / max(len(rows), 1), 5),
        "calls": senses.calls, "usd_per_call": round(senses.spent_usd / max(senses.calls, 1), 5),
        "errors": sum(1 for r in rows for s in r["muse_steps"].values() if s["result"] is None and not s.get("skipped")),
        "muse_votes_on": list(MUSE_VOTES),
    }
    out = ROOT / "results" / "carseat" / "muse"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{set_name}-{args.tag}.json").write_text(json.dumps({"summary": summary, "frames": rows}, indent=1))
    print(json.dumps({k: summary[k] for k in ("latency_s", "usd", "errors")}))
    for key in ("muse_alone", "sam_alone", "second_opinion"):
        print(key, json.dumps(summary[key]["frames"]))
        print("  ", {c: f"{v['right']}/{v['of']} fp{v['false_pass']} ff{v['false_fail']} ab{v['abstained']}" for c, v in summary[key]["per_check"].items()})


if __name__ == "__main__":
    main()
