"""Sleep and feed forecasts from the baby log alone: no house, no device, no network.

The predicted sleep windows and usual times the house plan, the day engine and the house brain share, and the next
feed the night feed and the families bot read. Kept apart from house_plan.py so the public demo can run the house brain
(house_brain.py) without the Home Assistant client in its image.
"""
import datetime
import statistics

from .rhythm import patterns
from .rhythm.log import ordered, parse, when


def as_of(entries, now):
    """The log as it looked at now: nothing that started later, and a sleep still going on has no end yet."""
    out = []
    for e in ordered(entries, now):
        if e.get("end") and parse(e["end"]) > now:
            e = {**e, "end": None}
        out.append(e)
    return out


def _median(values, default):
    return statistics.median(values) if values else default


def usual(entries, now, tz, days=2):
    """Usual awake minutes and sleep minutes, by day and night, from the last days of the log."""
    since = now - datetime.timedelta(days=days)
    done = [e for e in entries if e["kind"] == "sleep" and e.get("end") and when(e) >= since]
    night = lambda t: patterns.is_night(t.astimezone(tz))
    awake = {True: [], False: []}
    for a, b in zip(done, done[1:]):
        gap = (when(b) - parse(a["end"])).total_seconds() / 60
        if 0 < gap < 240:
            awake[night(parse(a["end"]))].append(gap)
    length = {True: [], False: []}
    for e in done:
        length[night(when(e))].append((parse(e["end"]) - when(e)).total_seconds() / 60)
    return {"awake": {True: _median(awake[True], 30), False: _median(awake[False], 60)},
            "sleep": {True: _median(length[True], 120), False: _median(length[False], 75)},
            "computed_from": [e["ref"] for e in done[-6:]]}


def sleep_windows(entries, now, tz, horizon_h=20):
    """Predicted sleeps from now on: the one going on (if any), then a chain of usual awake time and usual sleep."""
    seen = as_of(entries, now)
    sleeps = [e for e in seen if e["kind"] == "sleep"]
    if not sleeps:
        return []
    u = usual(seen, now, tz)
    night = lambda t: patterns.is_night(t.astimezone(tz))
    windows = []
    current = sleeps[-1] if not sleeps[-1].get("end") else None
    if current:
        start = when(current)
        end = max(start + datetime.timedelta(minutes=u["sleep"][night(start)]), now + datetime.timedelta(minutes=5))
        windows.append({"start": start, "end": end, "ongoing": True})
        cursor = end
    else:
        cursor = parse(sleeps[-1]["end"])
    while cursor < now + datetime.timedelta(hours=horizon_h):
        start = max(cursor + datetime.timedelta(minutes=u["awake"][night(cursor)]), now)
        end = start + datetime.timedelta(minutes=u["sleep"][night(start)])
        windows.append({"start": start, "end": end, "ongoing": False})
        cursor = end
    for w in windows:
        w["kind"] = "nap" if 7 <= w["start"].astimezone(tz).hour < 19 else "sleep"
        w["computed_from"] = u["computed_from"]
    return windows


SESSION_GAP = datetime.timedelta(minutes=30)


def sessions(rows):
    """The log rows with feeds that start within 30 minutes of the previous feed folded into it, for the rhythm."""
    out, last = [], None
    for row in sorted(rows, key=lambda r: patterns.when(r)):
        if row["kind"] == "feeding":
            start = patterns.when(row)
            if last is not None and start - last < SESSION_GAP:
                continue
            last = start
        out.append(row)
    return out


def predict_feed(rows, now, max_gap_h=6):
    """The next feed from the log, or None before two feeds or when the last feed is too old to guess from."""
    rows = sessions(rows)
    feeds = patterns.feeds(rows, now)
    if not feeds or now - patterns.when(feeds[-1]) > datetime.timedelta(hours=max_gap_h):
        return None
    return patterns.next_feed(rows, now)
