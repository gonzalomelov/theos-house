"""Run the end-to-end day, then score it.

    python -m parenting_agent.e2e --label before --day 2026-10-29
    python -m parenting_agent.e2e --score results/e2e-day/before --day 2026-10-29   # score an earlier run again

Needs the Baby Buddy and Home Assistant tunnels (docs/deploy-agent.md) and the secrets file. Nothing goes to Telegram
and every house write is refused: see harness.py.
"""
import argparse
import datetime
import json
from pathlib import Path

from . import day, score
from .harness import ROOT, Run


def main(argv=None):
    parser = argparse.ArgumentParser(prog="parenting_agent.e2e")
    parser.add_argument("--label", default="run")
    parser.add_argument("--day", default="2026-10-29", help="day 0, in the past: Baby Buddy refuses future times")
    parser.add_argument("--config", default=str(ROOT / "config/agent.vostro.json"))
    parser.add_argument("--out", default=None)
    parser.add_argument("--set", action="append", default=[], help="config override key.path=json, for the run only")
    parser.add_argument("--score", default=None, help="only score this run directory again")
    args = parser.parse_args(argv)
    day0 = datetime.date.fromisoformat(args.day)
    if args.score:
        summary = score.write(args.score, day0)
    else:
        out = Path(args.out or ROOT / "results/e2e-day" / args.label)
        overrides = {k: json.loads(v) for k, v in (s.split("=", 1) for s in args.set)}
        start, end = day.window(day0)
        Run(args.label, args.config, out, start, end, day.script(day0), overrides).execute()
        summary = score.write(out, day0)
    print(json.dumps(summary["numbers"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
