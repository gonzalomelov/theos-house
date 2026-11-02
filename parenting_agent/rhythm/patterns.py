"""Patterns learned from the baby log: the next feed, days that differ from usual, and night shifts.

Everything here is plain arithmetic on the log. The texts are notes and reminders, never advice or a
diagnosis: no_advice() is the guard every outgoing text passes.
"""
import datetime
import re
import statistics

from .log import ordered, parse, when

NIGHT_START, NIGHT_END = 22, 6
# The median of the last 5 gaps: one or two feeds logged close together (a top-up, a test log) do not move the next
# feed by an hour (round b5 saw 154 min become 54 after two test logs, with the median of 2).
RECENT_GAPS = 5
# A gap longer than this is a hole in the log (days nobody logged, a test log that stopped), not the rhythm. The e2e day
# (Nov 1) started from a history with 19 h and 29 h holes in its last five gaps, so the first guesses of the day landed
# hours after the real feeds and the 08:15 and 10:40 feeds got no reminder.
LOG_HOLE = datetime.timedelta(hours=6)
PARENT_RE = re.compile(r"handled by (.+)$", re.IGNORECASE)
ADVICE_RE = re.compile(r"\b(should|must|try|recommend|consider|doctor|pediatrician|worr\w*|normal|concern\w*|"
                       r"sick|ill|fever|medicine|medication|dose|diagnos\w*|need to|advise\w*)\b", re.IGNORECASE)


def no_advice(text):
    """True when the text only states facts from the log: no advice, no health judgment."""
    return ADVICE_RE.search(text) is None


def hhmm(t):
    return t.strftime("%H:%M")


def is_night(t):
    return t.hour >= NIGHT_START or t.hour < NIGHT_END


def feeds(entries, until=None):
    return [e for e in ordered(entries, until) if e["kind"] == "feeding"]


def next_feed(entries, now):
    """Estimated start of the next feed and the feeds it was computed from, or None before two feeds. The median of the
    last gaps that are not holes in the log."""
    rows = feeds(entries, now)
    if len(rows) < 2:
        return None
    starts = [when(e) for e in rows]
    gaps = [(b - a).total_seconds() for a, b in zip(starts, starts[1:]) if b - a <= LOG_HOLE][-RECENT_GAPS:]
    if not gaps:
        return None
    gap = datetime.timedelta(seconds=statistics.median(gaps))
    return {"at": starts[-1] + gap, "gap_min": round(gap.total_seconds() / 60),
            "computed_from": [e["ref"] for e in rows[-(RECENT_GAPS + 1):]]}


def next_feed_sentence(nxt, now, tz):
    """The next feed as one sentence, the same wherever it is shown: ahead of now, or how long ago it was expected."""
    at = hhmm(nxt["at"].astimezone(tz))
    late = round((now - nxt["at"]).total_seconds() / 60)
    return f"Next feed expected around {at}." if late <= 0 else f"A feed was expected around {at}, {late} min ago."


def backtest_next_feed(entries, warmup=4):
    """For each feed after the warmup, the minutes between the estimate made just before it and the real start."""
    rows = feeds(entries)
    errors = []
    for i in range(warmup, len(rows)):
        before = rows[i - 1]
        estimate = next_feed(rows[:i], when(before))
        errors.append({"feed": rows[i]["ref"], "error_min": round(abs((when(rows[i]) - estimate["at"]).total_seconds()) / 60, 1)})
    return errors


def local_day(t, tz):
    return t.astimezone(tz).date()


def daily(entries, tz):
    """Per local day: feeds, the shortest gap between feeds and when, total sleep hours, refs."""
    days, last_feed = {}, None
    for e in ordered(entries):
        t = when(e).astimezone(tz)
        d = days.setdefault(t.date(), {"feeds": 0, "min_gap_min": None, "min_gap_at": None, "sleep_h": 0.0, "refs": []})
        if e["kind"] == "feeding":
            d["feeds"] += 1
            d["refs"].append(e["ref"])
            if last_feed is not None:
                gap = (t - last_feed).total_seconds() / 60
                if d["min_gap_min"] is None or gap < d["min_gap_min"]:
                    d["min_gap_min"], d["min_gap_at"] = round(gap), t
            last_feed = t
        elif e["kind"] == "sleep" and e.get("end"):
            d["sleep_h"] += (parse(e["end"]) - parse(e["start"])).total_seconds() / 3600
            d["refs"].append(e["ref"])
    return days


def _odd(value, others, ratio):
    if len(others) < 3:
        return None
    usual = statistics.median(others)
    if usual and abs(value - usual) >= ratio * usual:
        return usual
    return None


def _hm(minutes):
    h, m = divmod(round(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


ES_DAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def unusual_notes(entries, tz, gap_ratio=0.3, sleep_ratio=0.15, lang="en"):
    """Plain notes for full days that differ from the rest of the log, oldest first, in English or Spanish."""
    notes = []
    days = daily(entries, tz)
    complete = sorted(days)[1:-1] if len(days) > 2 else []
    for day in complete:
        others = [days[d] for d in complete if d != day]
        row = days[day]
        label = f"{ES_DAYS[day.weekday()]} {day:%d}" if lang == "es" else f"{day:%a %d}"
        usual = _odd(row["min_gap_min"], [o["min_gap_min"] for o in others], gap_ratio)
        if usual is not None and row["min_gap_min"] < usual:
            text = (f"{label}: hubo tomas a {_hm(row['min_gap_min'])} una de otra cerca de las {hhmm(row['min_gap_at'])}, "
                    f"cuando suelen ser al menos {_hm(usual)}." if lang == "es" else
                    f"{label}: feeds came {_hm(row['min_gap_min'])} apart around {hhmm(row['min_gap_at'])}, usually at "
                    f"least {_hm(usual)}.")
            notes.append({"day": day, "text": text, "computed_from": row["refs"]})
        usual = _odd(row["sleep_h"], [o["sleep_h"] for o in others], sleep_ratio)
        if usual is not None:
            if lang == "es":
                word = "menos" if row["sleep_h"] < usual else "más"
                hours, normal = (f"{v:.1f}".replace(".", ",") for v in (row["sleep_h"], usual))
                text = f"{label}: {hours} h de sueño en total, {word} que las {normal} h de siempre."
            else:
                word = "less" if row["sleep_h"] < usual else "more"
                text = f"{label}: {row['sleep_h']:.1f} h of sleep in total, {word} than the usual {usual:.1f} h."
            notes.append({"day": day, "text": text, "computed_from": row["refs"]})
    return notes


def night_wakeups(entries, tz):
    """Night wake-ups with who handled them, from notes like 'Night wake-up handled by Parent A'."""
    rows = []
    for e in ordered(entries):
        if e["kind"] != "note":
            continue
        match = PARENT_RE.search(e.get("note") or "")
        if match and "wake" in e["note"].lower():
            rows.append({"at": when(e).astimezone(tz), "parent": match.group(1).strip(), "ref": e["ref"]})
    return rows


def next_on_duty(handled, parents):
    """The parent who takes the next night wake-up: fewer wake-ups so far wins, a tie goes to whoever did not take the last one."""
    counts = {p: 0 for p in parents}
    for h in handled:
        if h in counts:
            counts[h] += 1
    low = min(counts.values())
    candidates = [p for p in parents if counts[p] == low]
    if len(candidates) > 1 and handled:
        candidates = [p for p in candidates if p != handled[-1]] or candidates
    return candidates[0]


def split_nights(wake_times, parents):
    """Assign each wake-up in order with next_on_duty, as the agent would night by night."""
    handled = []
    for _ in wake_times:
        handled.append(next_on_duty(handled, parents))
    return handled


def night_summary(entries, now, tz, parents, current=False, aliases=None):
    """Summary of the last night (22:00 to 06:00 before now) plus who is on duty next and the next feed.

    With current, a summary asked during the night covers the night in progress up to now, and the label names both
    dates, so a page that shows it at 01:00 never shows the night that ended a day ago."""
    local = now.astimezone(tz)
    end = local.replace(hour=NIGHT_END, minute=0, second=0, microsecond=0)
    in_progress = current and is_night(local)
    if in_progress and local.hour >= NIGHT_START:
        end += datetime.timedelta(days=1)
    elif local < end and not in_progress:
        end -= datetime.timedelta(days=1)
    start = end - datetime.timedelta(hours=24 - NIGHT_START + NIGHT_END)
    if in_progress:
        end = local
    # "handled by Gonza" counts for his rota label: aliases maps a lowercase name to its label (the people block).
    label = (lambda who: (aliases or {}).get(str(who).strip().lower(), who))
    in_night = [e for e in ordered(entries, now) if start <= when(e) < end]
    night_feeds = [e for e in in_night if e["kind"] == "feeding"]
    wakes = [{**w, "parent": label(w["parent"])} for w in night_wakeups(entries, tz) if start <= w["at"] < end]
    # Every finished sleep that overlaps the night counts, also the one that started at 19:40 "para la noche": before,
    # only sleeps that started after 22:00 counted, and a night slept in one stretch said "longest sleep 0.0 h".
    sleeps = [e for e in ordered(entries, now) if e["kind"] == "sleep" and e.get("end")
              and when(e) < end and parse(e["end"]) > start]
    longest = max(((parse(e["end"]) - parse(e["start"])).total_seconds() / 3600 for e in sleeps), default=None)
    longest = round(longest, 1) if longest and longest >= 0.05 else None  # no sleep in the log is no line, never 0.0 h
    handled_all = [label(w["parent"]) for w in night_wakeups(entries, tz) if w["at"] < now.astimezone(tz)]
    on_duty = next_on_duty(handled_all, parents)
    per_parent = ", ".join(f"{p} {sum(1 for w in wakes if w['parent'] == p)}" for p in parents)
    nxt = next_feed(entries, now)
    label = (f"Tonight so far, since {start:%a %d} {start:%H:%M}" if in_progress
             else f"Last night, {start:%a %d} to {(start + datetime.timedelta(days=1)):%a %d}" if current
             else f"Night summary for {start:%a %d}")
    text = (f"{label}: {len(night_feeds)} feeds"
            + (f" at {', '.join(hhmm(when(e).astimezone(tz)) for e in night_feeds)}" if night_feeds else "")
            + (f", longest sleep {longest:.1f} h" if longest else "") + f". Wake-ups: {per_parent}. Next on duty: {on_duty}.")
    if nxt:
        text += " " + next_feed_sentence(nxt, now, tz)
    refs = [e["ref"] for e in in_night] + [w["ref"] for w in wakes]
    return {"text": text, "on_duty": on_duty, "computed_from": refs or (nxt or {}).get("computed_from", []),
            "feeds": len(night_feeds), "longest_h": longest,
            "wakeups": {p: sum(1 for w in wakes if w["parent"] == p) for p in parents}}
