"""Offline ablation of the families log architecture (issue #77): every variant on every blind set, one run at a time.

Each (variant, set) pair runs scripts/families_never_wrong_run.py in its own process, because a variant patches the
agent for the whole process. A pair whose result file is already there is skipped, so a stopped run picks up where it
was. --table prints the comparison from the result files only.

    .venv/bin/python scripts/families_log_ablation.py --keys-env ~/.parenting-agent.env \
        --variants main,safety,ops-verify,ops --out results/families-log-ablation
    .venv/bin/python scripts/families_log_ablation.py --table --out results/families-log-ablation
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLIND = ROOT / "results" / "families-never-wrong"
SETS = {"heldout1": BLIND / "heldout" / "heldout-steps.json", "heldout2": BLIND / "heldout2" / "steps-oct.json",
        "heldout3": BLIND / "heldout3" / "steps.json", "heldout4": BLIND / "heldout4" / "steps.json"}


def run(args):
    for variant in args.variants.split(","):
        for name in args.sets.split(","):
            out = Path(args.out) / f"{variant}-{name}"
            if out.with_suffix(".json").exists():
                continue
            subprocess.run([sys.executable, str(ROOT / "scripts" / "families_never_wrong_run.py"), "--keys-env", args.keys_env,
                            "--steps-file", str(SETS.get(name, name)), "--variant", variant, "--out", str(out)], check=True)


def table(args):
    rows, out = {}, Path(args.out)
    for path in sorted(out.glob("*.json")):
        data = json.loads(path.read_text())
        if "variant" not in data:
            continue
        variant, name = path.stem.split("-heldout")[0], "heldout" + path.stem.split("-heldout")[-1]
        rows.setdefault(variant, {})[name] = data
    names = sorted({n for r in rows.values() for n in r})
    lines = ["| Variant | " + " | ".join(f"{n} wrong / reply" for n in names) + " | Total wrong of 180 | Total reply problems | "
             "Seconds per message | USD per message |", "|" + "---|" * (len(names) + 5)]
    for variant, sets in rows.items():
        cells = [f"{sets[n]['wrong_log_states']} / {sets[n]['reply_misses']}" if n in sets else "" for n in names]
        messages = sum(s["messages"] for s in sets.values())
        wrong = sum(s["wrong_log_states"] for s in sets.values())
        replies = sum(s["reply_misses"] for s in sets.values())
        timed = [s for s in sets.values() if s.get("seconds_per_message") is not None]
        seconds = sum(s["seconds_per_message"] * s["messages"] for s in timed) / max(1, sum(s["messages"] for s in timed))
        usd = sum(s["usd"] for s in sets.values()) / max(1, messages)
        lines.append(f"| {variant} | " + " | ".join(cells) + f" | {wrong} of {messages} | {replies} | {seconds:.1f} | {usd:.4f} |")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys-env")
    parser.add_argument("--variants", default="main,safety,ops-verify,ops")
    parser.add_argument("--sets", default=",".join(SETS))
    parser.add_argument("--out", default=str(ROOT / "results" / "families-log-ablation"))
    parser.add_argument("--table", action="store_true")
    args = parser.parse_args()
    if args.table:
        return table(args)
    if not args.keys_env:
        parser.error("--keys-env is needed to run")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    run(args)


if __name__ == "__main__":
    main()
