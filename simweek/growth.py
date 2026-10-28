"""Growth for the simulated week: weight and height entries in Baby Buddy, tagged like the rest of the week.

A 3 to 6 week old gains about 30 g and 0.13 cm a day. Three measurements in the week, on days 0, 3 and 6.

    python -m simweek.growth load --anchor 2026-10-27    # wipe the tagged growth entries and load fresh ones
    python -m simweek.growth wipe
    python -m simweek.growth export --anchor 2026-10-27  # tests/fixtures/simweek-growth.json
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

from simweek import TAG
from simweek.babybuddy import Client
from simweek.generate import DAYS, TZ, default_anchor

ENDPOINTS = {"weight": "weight", "height": "height"}
START = {"weight": 4.20, "height": 54.0}
PER_DAY = {"weight": 0.030, "height": 0.13}


def generate(anchor=None, days=DAYS):
    anchor = anchor or default_anchor()
    first = (anchor - datetime.timedelta(days=days)).date()
    out = []
    for d in (0, 3, 6):
        for kind in ("weight", "height"):
            value = round(START[kind] + PER_DAY[kind] * d, 2 if kind == "weight" else 1)
            out.append({"kind": kind, "date": (first + datetime.timedelta(days=d)).isoformat(), kind: value,
                        "notes": "[simulated] growth", "tags": [TAG]})
    return out


def wipe(client, tag=TAG):
    removed = {}
    for kind, endpoint in ENDPOINTS.items():
        rows = client._call("GET", f"/api/{endpoint}/?tags={tag}&limit=500")["results"]
        rows = [r for r in rows if tag in (r.get("tags") or [])]
        for row in rows:
            client._call("DELETE", f"/api/{endpoint}/{row['id']}/")
        removed[kind] = len(rows)
    return removed


def load(client, entries, child):
    for e in entries:
        body = {"child": child, "date": e["date"], e["kind"]: e[e["kind"]], "notes": e["notes"], "tags": e["tags"]}
        client._call("POST", f"/api/{ENDPOINTS[e['kind']]}/", body)
    return len(entries)


def main(argv=None):
    p = argparse.ArgumentParser(prog="simweek.growth")
    p.add_argument("command", choices=["load", "wipe", "export"])
    p.add_argument("--anchor")
    p.add_argument("--out", default="tests/fixtures/simweek-growth.json")
    args = p.parse_args(argv)
    anchor = datetime.datetime.fromisoformat(args.anchor).replace(tzinfo=TZ) if args.anchor else None
    if args.command == "export":
        Path(args.out).write_text(json.dumps(generate(anchor), indent=1) + "\n")
        print(f"wrote {args.out}")
        return 0
    url, token = os.environ.get("BABYBUDDY_URL"), os.environ.get("BABYBUDDY_TOKEN")
    if not url or not token:
        sys.exit("simweek.growth: set BABYBUDDY_URL and BABYBUDDY_TOKEN")
    client = Client(url, token)
    removed = wipe(client)
    print("removed", removed)
    if args.command == "load":
        print("loaded", load(client, generate(anchor), client.child_id()), f"tag={TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
