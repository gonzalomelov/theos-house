"""Run the simulated full day and write the timeline report and the KR result files.

    python -m parenting_agent.fullday                       # the real day: Muse brain, Baby Buddy, SAM 3.1, live clips
    python -m parenting_agent.fullday --no-video            # skip the two clip steps (marked pending)
    python -m parenting_agent.fullday --wipe-only           # remove the entries earlier runs wrote

It wipes the previous run's entries (tag full-day-sim) first, then writes results/fullday/day.json, day.md
and results/fullday/kr222/ (table, voice-log, reminder) in the schema measure-kr222.sh reads.
"""
import argparse
import datetime
import json
import os
import tempfile
from pathlib import Path

from ..agent import build
from ..agent import config as config_mod
from ..agent.babybuddy import BabyBuddyLog
from ..rhythm.log import BabyBuddyLog as ReadLog
from . import day as day_mod

ROOT = day_mod.ROOT
CLIPS = "~/Engineering/gonza/meta-hackathon-2026-synthetic/kt/clips"
ENDPOINTS = ("feedings", "changes", "sleep", "notes")


def wipe(log):
    """Delete every Baby Buddy entry tagged full-day-sim. Returns how many were removed."""
    removed = 0
    for endpoint in ENDPOINTS:
        page = log.request("GET", f"/api/{endpoint}/?child={log.child()}&limit=500")
        for record in page["results"]:
            if day_mod.TAG in (record.get("tags") or []):
                log.request("DELETE", f"/api/{endpoint}/{record['id']}/")
                removed += 1
    return removed


def markdown(report, meta):
    lines = [f"# Simulated full day, {meta['generated_at']}", "",
             f"Brain: {meta['brain']['provider']} ({meta['brain']['model']}), calls to {meta['brain']['destination']}. "
             f"Baby log: Baby Buddy, entries tagged {day_mod.TAG}. Clock: the day 06:10 to 02:30 compressed into this run, "
             "every entry timed at the real moment its step ran.", "",
             "| Time | Step | Result | Channel | What happened | Dry run |", "|---|---|---|---|---|---|"]
    for row in report:
        dry = "<br>".join(row.get("dry") or []) or "none"
        lines.append(f"| {row['sim_time']} | {row['step']} | {row['status']} | {row.get('channel', '')} | "
                     f"{row.get('action', '').replace('|', '/')} | {dry} |")
    passed = sum(1 for r in report if r["status"] == "pass")
    lines += ["", f"{passed} of {len(report)} steps passed."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m parenting_agent.fullday")
    parser.add_argument("--config", default=str(ROOT / "config" / "agent.json"))
    parser.add_argument("--clips", default=CLIPS)
    parser.add_argument("--no-video", action="store_true", help="skip the changing-table and bath clip steps")
    parser.add_argument("--wipe-only", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "results" / "fullday"))
    args = parser.parse_args(argv)

    config = config_mod.load(args.config)
    config_mod.load_env(config["env_file"])
    if (config.get("baby_log") or {}).get("provider") != "babybuddy":
        raise SystemExit("the full day needs the Baby Buddy log (baby_log.provider babybuddy)")
    config = dict(config, data_dir=tempfile.mkdtemp(prefix="fullday-"), plugins=[],
                  baby_log={**config["baby_log"], "tags": ["agent", day_mod.TAG]},
                  allowed_tools=sorted((set(config["allowed_tools"]) | set(day_mod.HOUSE_TOOLS))
                                       - {"start_changing_table", "finish_changing_table"}))
    log = BabyBuddyLog.from_config(config["baby_log"])
    print(f"wiped {wipe(log)} entries from an earlier run", flush=True)
    if args.wipe_only:
        return 0

    agent = build(config)
    agent.plugins = [day_mod.HouseTools(agent, config)]
    agent.start()
    env = dict(os.environ)
    rhythm_log = ReadLog(env["BABYBUDDY_URL"], env["BABYBUDDY_TOKEN"], "Test")
    week_log = ReadLog(env["BABYBUDDY_URL"], env["BABYBUDDY_TOKEN"], "Test", tag="simulated-week")
    day = day_mod.Day(agent, env, args.clips, Path(f"runs/fullday-{datetime.datetime.now():%Y%m%d-%H%M%S}"),
                      video=not args.no_video, rhythm_log=rhythm_log, week_log=week_log)
    try:
        report = day_mod.run(day)
    finally:
        agent.stop()
        agent.close()

    generated = day_mod.stamp()
    brain = {"provider": agent.brain.name, "model": agent.brain.model, "destination": agent.brain.destination}
    meta = {"generated_at": generated, "brain": brain}
    out = Path(args.out)
    (out / "kr222").mkdir(parents=True, exist_ok=True)
    (out / "day.json").write_text(json.dumps({**meta, "tag": day_mod.TAG, "steps": report}, indent=2, ensure_ascii=False) + "\n")
    (out / "day.md").write_text(markdown(report, meta))
    if day.evidence["table"]:
        (out / "kr222" / "table.json").write_text(json.dumps({"generated_at": generated, **day.evidence["table"]}, indent=2) + "\n")
    (out / "kr222" / "voice-log.json").write_text(json.dumps(
        {"generated_at": generated, "brain": brain, "baby_log": "babybuddy", "entries": day.evidence["voice"]},
        indent=2, ensure_ascii=False) + "\n")
    (out / "kr222" / "reminder.json").write_text(json.dumps(
        {"generated_at": generated, "source": "full_day", "reminders": day.evidence["reminders"]}, indent=2, ensure_ascii=False) + "\n")
    passed = sum(1 for r in report if r["status"] == "pass")
    print(f"{passed} of {len(report)} steps passed, report in {out / 'day.md'}", flush=True)
    return 0 if passed == len(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
