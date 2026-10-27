"""Replay the daily rhythm over the baby log and record what the agent said first.

    python -m parenting_agent.rhythm --source babybuddy --out results/kr222/reminder.json
    python -m parenting_agent.rhythm --source fixture

It runs the real agent (fake brain, no network besides the log read) and moves a replay clock through
the log's last day: the morning night summary, the evening notes on unusual days, and the warning before
the next feed after the last logged one. Each reminder is spoken through agent.say on the configured
channel, and delivered_at is the wall-clock instant that happened. The file follows measure-kr222.sh.
"""
import argparse
import datetime
import json
import os
import tempfile
from pathlib import Path

from ..agent import build
from ..agent import config as config_mod
from . import patterns
from .engine import DEFAULTS, Rhythm, deliver, make_log


def replay_clock(entries, rhythm):
    """The replay instants: morning and evening of the log's last full day, then just before the next feed."""
    last = max(patterns.when(e) for e in entries).astimezone(rhythm.tz)
    day = last - datetime.timedelta(days=1) if last.hour < 12 else last
    instants = [rhythm._at(day, rhythm.s["summary_at"]) + datetime.timedelta(minutes=1),
                rhythm._at(day, rhythm.s["notes_at"]) + datetime.timedelta(minutes=1)]
    nxt = patterns.next_feed(entries, last)
    if nxt:
        instants.append(nxt["at"] - datetime.timedelta(minutes=rhythm.s["lead_min"] // 2))
    return sorted(instants)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m parenting_agent.rhythm")
    parser.add_argument("--source", choices=["babybuddy", "fixture"], default="babybuddy")
    parser.add_argument("--env", default="~/.parenting-agent.env")
    parser.add_argument("--channel", default=DEFAULTS["channel"])
    parser.add_argument("--tag", default="simulated-week",
                        help="only read Baby Buddy entries with this tag (empty string reads every entry)")
    parser.add_argument("--out", help="write the reminders as results/kr222/reminder.json")
    args = parser.parse_args(argv)

    config_mod.load_env(args.env)
    settings = {**DEFAULTS, "source": args.source, "channel": args.channel, "tag": args.tag or None}
    rhythm = Rhythm(make_log(settings, os.environ), settings)
    entries = rhythm.log.entries()
    agent = build({**config_mod.load(), "data_dir": tempfile.mkdtemp(prefix="rhythm-"), "env_file": args.env})

    reminders = []
    for now in replay_clock(entries, rhythm):
        for r in rhythm.tick(now):
            event = deliver(agent, r)
            reminders.append({"text": r["text"], "computed_from": r["computed_from"], "channel": r["channel"],
                              "delivered_at": event["ts"], "asked": False, "kind": r["kind"],
                              "replay_clock": now.astimezone(rhythm.tz).isoformat(timespec="seconds")})
            print(f"[{r['kind']} at {now.astimezone(rhythm.tz):%a %d %H:%M} -> {r['channel']}] {r['text']}")
    agent.close()

    if args.out:
        doc = {"generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               "source": args.source, "tag": args.tag or None, "log_entries": len(entries), "reminders": reminders}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {args.out} with {len(reminders)} reminders")
    return 0 if reminders else 1


if __name__ == "__main__":
    raise SystemExit(main())
