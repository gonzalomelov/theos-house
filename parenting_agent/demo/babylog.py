"""The demo baby's log: the simulated week, moved to the visitor's days, kept in memory for one visitor.

Every visitor gets their own DemoBabyLog built from the same deterministic week (simweek.generate), with the
last simulated day placed on today and everything after the current time dropped, so "when did she last eat?"
has a fresh answer. Nothing here talks to Baby Buddy or any server. Rows keep the simulated week's shape
(the rhythm engine reads them as they are) and the agent sees them through the same view as BabyBuddyLog.
"""
import datetime
import threading

from simweek import generate as simweek

from ..agent.memory import LOG_KINDS, BabyLog, parse_time

TZ = simweek.TZ
DEFAULT_FEED_MINUTES = 15
MAX_ADDED = 300
SIM_PREFIX = "[simulated] "


def iso(moment):
    return moment.astimezone(TZ).isoformat(timespec="seconds")


def week(now):
    """The simulated week ending today at now: seven days of entries, the last one today, none in the future."""
    tomorrow = now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    rows = simweek.generate(seed=7, anchor=tomorrow)
    kept = [r for r in rows if parse_time(r.get("end") or r.get("start") or r["time"]) <= now]
    for i, row in enumerate(kept):
        row["ref"] = f"{row['kind']}#{i}"
    return kept


def minutes_between(start, end):
    return round((parse_time(end) - parse_time(start)).total_seconds() / 60)


def view(row):
    """A simulated-week row as the agent's log entry: {ts, kind, details}, the same shape BabyBuddyLog returns."""
    kind = row["kind"]
    if kind == "feeding":
        details = {"amount_ml": row.get("amount"), "type": row.get("type"), "method": row.get("method"),
                   "start": row["start"], "duration_min": minutes_between(row["start"], row["end"])}
        return {"id": row["ref"], "kind": "feeding", "ts": row["end"], "details": details}
    if kind == "change":
        details = {"wet": row.get("wet"), "solid": row.get("solid"), "color": row.get("color") or None}
        return {"id": row["ref"], "kind": "diaper", "ts": row["time"], "details": details}
    if kind == "sleep":
        details = {"start": row["start"], "duration_min": minutes_between(row["start"], row["end"]), "nap": row.get("nap")}
        return {"id": row["ref"], "kind": "sleep", "ts": row["end"], "details": details}
    text = row.get("note") or ""
    plain = text[len(SIM_PREFIX):] if text.startswith(SIM_PREFIX) else text
    return {"id": row["ref"], "kind": "bath" if plain.lower().startswith("bath") else "note", "ts": row["time"],
            "details": {"text": plain}}


class DemoBabyLog(BabyLog):
    name = "demo"

    def __init__(self, now=None, clock=None):
        self.clock = clock or (lambda: datetime.datetime.now(TZ))
        self.rows = week(now or self.clock())
        self.sleep_started = None
        self.added = 0
        self.lock = threading.Lock()

    def now(self):
        return self.clock().astimezone(TZ)

    def at_or_before_now(self, ts):
        current = self.now()
        moment = parse_time(ts) if ts else None
        return current if moment is None or moment > current else moment

    def _append(self, row):
        if self.added >= MAX_ADDED:
            raise ValueError("the demo log is full, start a fresh demo baby")
        with self.lock:
            row["ref"] = f"{row['kind']}#{len(self.rows)}"
            row["tags"] = ["demo-visitor"]
            self.rows.append(row)
            self.added += 1
        return view(row)

    def add(self, kind, details, ts=None):
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind}, expected one of {', '.join(LOG_KINDS)}")
        details = dict(details or {})
        when = self.at_or_before_now(ts or details.get("end") or details.get("time"))
        if kind == "feeding":
            method = details.get("method") or "bottle"
            milk = details.get("type") or ("breast milk" if "breast" in method else "formula")
            length = float(details.get("duration_min") or DEFAULT_FEED_MINUTES)
            start = self.at_or_before_now(details["start"]) if details.get("start") else when - datetime.timedelta(minutes=length)
            row = {"kind": "feeding", "start": iso(start), "end": iso(when), "type": milk, "method": method, "notes": ""}
            if details.get("amount_ml") is not None:
                row["amount"] = float(details["amount_ml"])
            return self._append(row)
        if kind == "diaper":
            wet, solid = bool(details.get("wet")), bool(details.get("solid"))
            return self._append({"kind": "change", "time": iso(when), "wet": wet or not solid, "solid": solid,
                                 "color": details.get("color") or "", "notes": ""})
        if kind == "sleep":
            return self._sleep(details, when)
        text = str(details.get("text") or details.get("note") or "").strip()
        if kind == "bath" and not text.lower().startswith("bath"):
            text = f"Bath. {text}".strip()
        return self._append({"kind": "note", "time": iso(when), "note": text or "Note"})

    def _sleep(self, details, when):
        action = details.get("action")
        if details.get("start") and details.get("end"):
            start, end = self.at_or_before_now(details["start"]), self.at_or_before_now(details["end"])
        elif action == "end" or (details.get("end") and not details.get("start")):
            if self.sleep_started is None:
                raise ValueError("no sleep was started, tell me when she fell asleep")
            start, end, self.sleep_started = self.sleep_started, when, None
        else:
            self.sleep_started = when
            return {"kind": "sleep", "ts": iso(when), "details": {"action": "start"}}
        if end <= start:
            raise ValueError("a sleep must end after it starts")
        return self._append({"kind": "sleep", "start": iso(start), "end": iso(end), "nap": 7 <= start.hour < 19, "notes": ""})

    def entries(self, kind=None, since=None, limit=50):
        since_time = parse_time(since) if since else None
        with self.lock:
            items = [view(r) for r in self.rows]
        items = [e for e in items if (kind is None or e["kind"] == kind) and (since_time is None or parse_time(e["ts"]) >= since_time)]
        items.sort(key=lambda e: parse_time(e["ts"]))
        return items[-max(int(limit or 50), 1):]

    def rhythm_rows(self):
        """The rows in the simulated week's shape, which the rhythm engine reads."""
        with self.lock:
            return [dict(r) for r in self.rows]
