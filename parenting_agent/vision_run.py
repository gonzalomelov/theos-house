"""Run a skill on a source.

    python -m parenting_agent.vision_run --skill skills/changing-table.json --source loop.mp4 --minutes 2
    python -m parenting_agent.vision_run --skill skills/changing-table.json --source phone   # head camera page
    python -m parenting_agent.vision_run --skill skills/changing-table.json --source 0       # a camera index

Events (numbers and states only) go to runs/<timestamp>/events.jsonl.
"""
import argparse
import datetime
import json
from pathlib import Path

from . import config as config_mod
from .bus import Bus
from .reflex import MediaPipeReflex
from .skill import Skill, watch
from .sources import PhoneSource, open_source
from .speaker import Speaker


def main(argv=None):
    parser = argparse.ArgumentParser(prog="parenting_agent.vision_run")
    parser.add_argument("--skill", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--minutes", type=float, default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--quiet", action="store_true", help="do not play sounds on this machine")
    args = parser.parse_args(argv)

    skill_cfg = config_mod.load(args.skill)
    out = Path(args.out or f"runs/{datetime.datetime.now():%Y%m%d-%H%M%S}")
    out.mkdir(parents=True, exist_ok=True)
    bus = Bus(out / "events.jsonl")
    source = open_source(args.source)
    if isinstance(source, PhoneSource):
        print(f"head camera page: {source.url}", flush=True)
    speaker = Speaker(source, quiet=args.quiet)
    bus.subscribe(speaker.on_event, ["chime", "voice"])
    skill = Skill(skill_cfg, bus, MediaPipeReflex(skill_cfg["contact"]))
    skill.arm()
    try:
        watch(skill, source, minutes=args.minutes)
    except KeyboardInterrupt:
        pass
    finally:
        skill.close()
        source.close()
        bus.close()
    summary = {k: sum(1 for e in bus.history if e["kind"] == k) for k in ("frame", "chime", "voice", "voice_dropped", "ask_parent")}
    print(json.dumps({"events": str(out / "events.jsonl"), **summary}))


if __name__ == "__main__":
    main()
