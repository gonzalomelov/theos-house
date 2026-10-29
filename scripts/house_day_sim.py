"""A full simulated day of the day engine with the house in dry run. Writes results/house-day/README.md and timeline.json.

    .venv/bin/python scripts/house_day_sim.py               # the day from the saved house read
    .venv/bin/python scripts/house_day_sim.py --read-house  # first read the real house again, read only, through the tunnel

--read-house needs HA_MCP_TOKEN in the environment and the tunnel on 127.0.0.1:18123. It reads states, the weather
forecast and the shopping list (HouseReader), saves the read to results/house-day/house-read.json and stops at the
first 401 or 403. It never calls a service that changes a device.
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent import day_sim  # noqa: E402
from parenting_agent.day_engine import ROUTINES, HouseReader  # noqa: E402
from parenting_agent.house import HomeAssistant, token_rejected  # noqa: E402

OUT = ROOT / "results/house-day"


def read_house():
    token = os.environ.get("HA_MCP_TOKEN")
    if not token:
        sys.exit("HA_MCP_TOKEN is not set")
    client = HomeAssistant("http://127.0.0.1:18123", token)
    client.ping()
    now = datetime.datetime.now(day_sim.TZ)
    house = HouseReader(client, day_sim.TZ).read(now)
    if token_rejected():
        sys.exit(f"Home Assistant answered {token_rejected()}, stopped")
    saved = {k: (v.isoformat() if isinstance(v, datetime.datetime) else v) for k, v in house.items()}
    saved["read_at"] = now.isoformat(timespec="seconds")
    saved["presence"] = {k: "(private)" for k in saved["presence"]}
    (OUT / "house-read.json").write_text(json.dumps(saved, indent=1, ensure_ascii=False, default=str))
    print(f"read the house: vacuum {house['vacuum']}, echo dnd {house['echo_dnd']}, "
          f"weather {(house['weather'] or {}).get('condition')}, shopping list {len(house['shopping'])} items")


def cell(text):
    return str(text).replace("|", "/").replace("\n", " ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-house", action="store_true")
    args = parser.parse_args()
    if args.read_house:
        read_house()
    result = day_sim.simulate_day()
    rows, stats = result["rows"], result["stats"]
    fired = {}
    for r in rows:
        if r["routine"] in ROUTINES:
            fired.setdefault(r["routine"], []).append(r["at"].strftime("%a %H:%M"))
    timeline = [{"at": r["at"].isoformat(), "routine": r["routine"], "what": r["what"], "detail": r.get("detail")} for r in rows]
    (OUT / "timeline.json").write_text(json.dumps({"stats": stats, "rows": timeline}, indent=1, ensure_ascii=False))
    start = json.loads(day_sim.HOUSE_START.read_text())
    lines = [
        "# A simulated day of the whole house, in dry run",
        "",
        "Issues #9 and #29, built during the Meta hackathon on Oct 29 2026. `scripts/house_day_sim.py` runs the day engine",
        "(`parenting_agent/day_engine.py`) minute by minute through Sat Oct 24 06:00 to Sun Oct 25 07:00 of the simulated",
        "week, the morning after the hard night of Fri Oct 23 (4 wake-ups).",
        "",
        "## What is real and what is simulated",
        "",
        "| Part | Source |",
        "|---|---|",
        "| The baby log | the simulated week (`tests/fixtures/simweek.json`) plus scripted notes: diaper, wipes and formula stock on Thu, tummy times on Wed to Fri, \"Feeding in the bedroom\" at 13:56 |",
        f"| The starting house | the real house read on Oct 29 2026 through the tunnel, read only: vacuum {start['vacuum']}, both TVs off, Echo do not disturb {'on' if start['echo_dnd'] else 'off'}, kitchen {start['kitchen_temp_c']} C, shopping list empty (`house-start.json`) |",
        f"| The weather | the real met.no forecast read on Oct 29 2026 ({start['weather_today']['condition']}, {start['weather_today']['templow']} to {start['weather_today']['temperature']} C), used as the simulated Saturday's weather |",
        "| The vacuum run length | 31 min for the whole house (the house plan's figure). Its own run calendar logged 32 runs in two weeks, median 16 min, most of them single rooms |",
        "| What people do | scripted: TVs turned on and off, the vacuum started by hand, Echo motion, two doorbells |",
        "| Appointments | two invented calendar entries, Home Assistant has no family calendar yet |",
        "| Recipes | one real read-only Cookidoo run saved Oct 28 (`tests/fixtures/fast_recipes.json`) |",
        "| Gonza's yes | given 2 min after the question |",
        "| Every house write | a dry run. The writer has no client, `house.live` is false. A simulated house follows the dry writes so the next minute sees the change |",
        "| White noise | the simulated device from #32, nothing plays |",
        "",
        "## Checks over the whole day",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Sleeps in the day | {stats['sleeps_in_day']} |",
        f"| Minutes the vacuum cleaned while he slept | {stats['vacuum_cleaning_while_asleep_min']} |",
        f"| Minutes a TV was on and not muted while he slept | {stats['tv_unmuted_while_asleep_min']} |",
        f"| Minutes the Echo was not on do not disturb while he slept | {stats['echo_dnd_off_while_asleep_min']} |",
        f"| Loudest white noise at the crib | {stats['white_noise_max_db']} dB (cap {stats['cap_db']} dB) |",
        f"| House writes | {stats['dry_writes']} dry runs, {stats['live_writes']} live |",
        "",
        "## Routines that fired",
        "",
        "| Routine | Kind | Fired at |",
        "|---|---|---|",
    ]
    for name, kind in ROUTINES.items():
        times = sorted(set(fired.get(name, [])))
        lines.append(f"| `{name}` | {kind} | {', '.join(times) if times else 'did not fire'} |")
    lines += ["", "## Timeline", "", "Each house write is the exact request the engine would send, in dry run.", "",
              "| Time | Routine | What | Detail |", "|---|---|---|---|"]
    for r in rows:
        detail = r.get("detail") or ""
        if isinstance(detail, dict):
            if "text" in detail:
                detail = detail["text"]
            elif "data" in detail:
                data = {k: v for k, v in detail["data"].items() if k != "data"}
                detail = (f"{json.dumps(data, ensure_ascii=False)} " if data else "") + f"({detail['reason']})"
            else:
                detail = ", ".join(f"{k} {v}" for k, v in detail.items() if k != "computed_from")
        lines.append(f"| {r['at']:%a %H:%M} | {r['routine']} | {cell(r['what'])} | {cell(detail)} |")
    lines += ["", "## Run it", "", "```bash", ".venv/bin/python scripts/house_day_sim.py", "```", "",
              "The same day is a test: `tests/test_day_engine.py` (SimulatedDayTest).", ""]
    (OUT / "README.md").write_text("\n".join(lines))
    print(json.dumps(stats))
    print({k: len(v) for k, v in fired.items()})


if __name__ == "__main__":
    main()
