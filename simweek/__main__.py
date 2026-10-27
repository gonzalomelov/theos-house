"""python -m simweek {load|wipe|summary|export} [--seed N] [--source server|fixture] [--out FILE]

load     wipes the tagged week in Baby Buddy, loads 7 fresh simulated days, prints the count per entry type
wipe     removes only the tagged simulated entries
summary  prints daily totals and flags any day outside newborn ranges (exit 1 if any)
export   writes the week to a JSON fixture for tests without the server

Baby Buddy URL and token come from BABYBUDDY_URL and BABYBUDDY_TOKEN, never printed.
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

from simweek import TAG
from simweek.babybuddy import Client
from simweek.generate import TZ, generate, out_of_range, summarize


def client():
    url, token = os.environ.get("BABYBUDDY_URL"), os.environ.get("BABYBUDDY_TOKEN")
    if not url or not token:
        sys.exit("simweek: set BABYBUDDY_URL and BABYBUDDY_TOKEN")
    return Client(url, token)


def print_summary(entries):
    totals = summarize(entries)
    print(f"{'day':<12}{'feeds':>6}{'ml':>6}{'sleep_h':>9}{'longest':>9}{'wet':>5}{'dirty':>7}{'baths':>7}{'night':>7}")
    for day, t in totals.items():
        print(f"{day:<12}{t['feeds']:>6}{t['bottle_ml']:>6}{t['sleep_h']:>9}{t['longest_sleep_h']:>9}"
              f"{t['wet']:>5}{t['dirty']:>7}{t['baths']:>7}{t['night_wakeups']:>7}")
    bad = out_of_range(totals)
    for day, field, value in bad:
        print(f"OUT OF RANGE {day} {field}={value}")
    print("all days inside newborn ranges" if not bad else f"{len(bad)} values out of range")
    return not bad


def main(argv=None):
    p = argparse.ArgumentParser(prog="simweek")
    p.add_argument("command", choices=["load", "wipe", "summary", "export"])
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--anchor", help="local date the week ends on (exclusive), YYYY-MM-DD, default today")
    p.add_argument("--source", choices=["server", "fixture"], default="server")
    p.add_argument("--fixture", default="tests/fixtures/simweek.json")
    p.add_argument("--out", default="tests/fixtures/simweek.json")
    args = p.parse_args(argv)
    anchor = datetime.datetime.fromisoformat(args.anchor).replace(tzinfo=TZ) if args.anchor else None

    if args.command == "export":
        week = generate(args.seed, anchor)
        Path(args.out).write_text(json.dumps(week, indent=1) + "\n")
        print(f"wrote {len(week)} entries to {args.out}")
        return 0
    if args.command == "summary" and args.source == "fixture":
        return 0 if print_summary(json.loads(Path(args.fixture).read_text())) else 1

    bb = client()
    if args.command == "wipe":
        print("removed", bb.wipe())
        return 0
    if args.command == "load":
        removed = bb.wipe()
        counts = bb.load(generate(args.seed, anchor), bb.child_id())
        print(f"removed old simulated entries {removed}")
        print("loaded", counts, f"tag={TAG}")
        return 0
    return 0 if print_summary(bb.read_back()) else 1


if __name__ == "__main__":
    sys.exit(main())
