# Simulated baby week

There is no baby yet, so the daily rhythm, the night shifts and the demo run on a simulated first-weeks week for "Test Baby" in Baby Buddy. Built during the Meta hackathon (issue #13).

## What it contains

Seven days before the anchor date, all in the past:

- 8 to 12 feeds a day, every 2 to 3 hours, breastfeeds with durations and bottles with amounts
- sleep in short blocks between feeds, naps marked in the daytime, 12 to 18 hours a day
- 6 to 12 wet and 2 to 7 dirty diapers a day
- a bath every 2 or 3 days, as a note
- night wake-ups as notes, split between Parent A and Parent B
- two unusual days on purpose: evening cluster feeding (day 4) and a short, fussy night (day 6)

Every entry carries the tag `simulated-week`. Wiping removes only tagged entries. No real names or dates.

## Commands

From the repo root, with `BABYBUDDY_URL` and `BABYBUDDY_TOKEN` set (see docs/deploy-babybuddy.md for the SSH tunnel):

```bash
python3 -m simweek load --anchor 2026-10-27   # wipe the tagged week, load a fresh one, print counts per type
python3 -m simweek summary                    # daily totals from the server, flags anything outside newborn ranges
python3 -m simweek wipe                       # remove only the tagged entries
python3 -m simweek export --anchor 2026-10-27 # write tests/fixtures/simweek.json for tests without the server
python3 -m simweek summary --source fixture   # same summary from the fixture
```

The week is deterministic: the same `--seed` (default 7) and `--anchor` always give the same entries.

Baby Buddy also ships a `fake` management command, but it creates its own children, runs inside the container, and is neither seeded nor tagged, so it cannot be wiped safely next to real data later.
