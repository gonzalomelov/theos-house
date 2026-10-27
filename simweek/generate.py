"""Deterministic generator: the same seed and anchor always give the same week.

The week covers the 7 days before the anchor (local midnight), so every entry is in the past.
Patterns follow a 3 to 6 week old: 8 to 12 feeds a day, sleep in short blocks between feeds,
6 to 10 wet and 3 to 6 dirty diapers a day, a bath every 2 or 3 days, night wake-ups split
between two parents. Two days are unusual on purpose: one with evening cluster feeding, one short night.
"""
import datetime
import random

from simweek import TAG

TZ = datetime.timezone(datetime.timedelta(hours=-3))
DAYS = 7
PARENTS = ("Parent A", "Parent B")
CLUSTER_DAY = 3
SHORT_NIGHT_DAY = 5


def default_anchor(now=None):
    now = now or datetime.datetime.now(TZ)
    return now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)


def _iso(t):
    return t.isoformat(timespec="seconds")


def _is_night(t):
    return t.hour >= 22 or t.hour < 6


def _feed(rng, start, day, night):
    if rng.random() < 0.35:
        amount = rng.choice([60, 70, 80, 90, 100, 110])
        end = start + datetime.timedelta(minutes=rng.randint(10, 20))
        fields = {"type": rng.choice(["breast milk", "formula"]), "method": "bottle", "amount": amount}
    else:
        end = start + datetime.timedelta(minutes=rng.randint(15, 35))
        fields = {"type": "breast milk", "method": rng.choice(["left breast", "right breast", "both breasts"])}
    note = "Night feed" if night else ""
    if day == CLUSTER_DAY and 17 <= start.hour < 22:
        note = "Cluster feeding in the evening"
    return {"kind": "feeding", "start": _iso(start), "end": _iso(end), **fields, "notes": note}, end


def generate(seed=7, anchor=None, days=DAYS):
    """Return the week as a list of entries, each a dict with a "kind" and Baby Buddy fields, sorted by time."""
    rng = random.Random(seed)
    anchor = anchor or default_anchor()
    t = anchor - datetime.timedelta(days=days) + datetime.timedelta(minutes=rng.randint(0, 40))
    entries, night_turn, wake_count = [], 0, 0
    while True:
        day = (t - (anchor - datetime.timedelta(days=days))).days
        if t >= anchor or day >= days:
            break
        night = _is_night(t)
        feed, fed_until = _feed(rng, t, day, night)
        entries.append(feed)
        if night:
            parent = PARENTS[night_turn % 2]
            night_turn += 1
            wake_count += 1
            entries.append({"kind": "note", "time": feed["start"],
                            "note": f"[simulated] Night wake-up handled by {parent}"})
        change_at = fed_until + datetime.timedelta(minutes=rng.randint(2, 8))
        if rng.random() < 0.85:
            solid = rng.random() < 0.45
            entries.append({"kind": "change", "time": _iso(change_at), "wet": True, "solid": solid,
                            "color": rng.choice(["yellow", "yellow", "yellow", "green", "brown"]) if solid else "",
                            "notes": ""})
        cluster = day == CLUSTER_DAY and 17 <= t.hour < 22
        short_night = day == SHORT_NIGHT_DAY and _is_night(t)
        if cluster:
            gap = datetime.timedelta(minutes=rng.randint(55, 85))
        elif short_night:
            gap = datetime.timedelta(minutes=rng.randint(85, 120))
        else:
            gap = datetime.timedelta(minutes=rng.randint(125, 175))
        next_feed = t + gap
        awake = datetime.timedelta(minutes=rng.randint(8, 20) if _is_night(fed_until) else rng.randint(20, 40))
        sleep_start = change_at + awake
        sleep_end = next_feed - datetime.timedelta(minutes=rng.randint(3, 10))
        if sleep_end - sleep_start >= datetime.timedelta(minutes=20) and sleep_end < anchor:
            nap = 7 <= sleep_start.hour < 19
            entries.append({"kind": "sleep", "start": _iso(sleep_start), "end": _iso(sleep_end), "nap": nap,
                            "notes": "Short, fussy sleep" if short_night else ""})
        t = next_feed
    for d in range(days):
        if d % 3 != 1 and d % 3 != 0:
            continue
        bath = anchor - datetime.timedelta(days=days - d) + datetime.timedelta(hours=18, minutes=rng.randint(15, 50))
        entries.append({"kind": "note", "time": _iso(bath), "note": "[simulated] Bath"})
    day_start = anchor - datetime.timedelta(days=days)
    entries.append({"kind": "note", "time": _iso(day_start + datetime.timedelta(days=CLUSTER_DAY, hours=21)),
                    "note": "[simulated] Unusual day: evening cluster feeding"})
    entries.append({"kind": "note", "time": _iso(day_start + datetime.timedelta(days=SHORT_NIGHT_DAY, hours=23)),
                    "note": "[simulated] Unusual night: short, fussy sleep"})
    entries = [e for e in entries if datetime.datetime.fromisoformat(e.get("end") or e.get("start") or e["time"]) < anchor]
    for e in entries:
        e["tags"] = [TAG]
    return sorted(entries, key=lambda e: e.get("start") or e["time"])


def summarize(entries, days=DAYS):
    """Daily totals keyed by local date: feeds, bottle ml, sleep hours, longest block, wet, dirty, baths, night wake-ups."""
    out = {}

    def row(stamp):
        d = datetime.datetime.fromisoformat(stamp).astimezone(TZ).date().isoformat()
        return out.setdefault(d, {"feeds": 0, "bottle_ml": 0, "sleep_h": 0.0, "longest_sleep_h": 0.0,
                                  "wet": 0, "dirty": 0, "baths": 0, "night_wakeups": 0})

    for e in entries:
        if e["kind"] == "feeding":
            r = row(e["start"])
            r["feeds"] += 1
            r["bottle_ml"] += e.get("amount") or 0
        elif e["kind"] == "sleep":
            r = row(e["start"])
            h = (datetime.datetime.fromisoformat(e["end"]) - datetime.datetime.fromisoformat(e["start"])).total_seconds() / 3600
            r["sleep_h"] = round(r["sleep_h"] + h, 2)
            r["longest_sleep_h"] = round(max(r["longest_sleep_h"], h), 2)
        elif e["kind"] == "change":
            r = row(e["time"])
            r["wet"] += 1 if e.get("wet") else 0
            r["dirty"] += 1 if e.get("solid") else 0
        elif e["kind"] == "note":
            r = row(e["time"])
            r["baths"] += 1 if e["note"].endswith("Bath") else 0
            r["night_wakeups"] += 1 if "Night wake-up" in e["note"] else 0
    return dict(sorted(out.items()))


RANGES = {"feeds": (8, 12), "sleep_h": (12.0, 18.0), "longest_sleep_h": (0.5, 4.0), "wet": (6, 12), "dirty": (2, 7)}


def out_of_range(summary):
    """Days whose totals fall outside newborn ranges, as a list of (date, field, value)."""
    bad = []
    for day, totals in summary.items():
        for field, (lo, hi) in RANGES.items():
            if not lo <= totals[field] <= hi:
                bad.append((day, field, totals[field]))
    return bad
