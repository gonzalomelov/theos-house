"""The demo baby's log: the simulated week, moved to the visitor's days, kept in memory for one visitor.

Every visitor gets their own DemoBabyLog built from the same deterministic week (simweek.generate), with the
last simulated day placed on today and everything after the current time dropped, so "when did he last eat?"
has a fresh answer. The simulated baby is Theo, a boy a few weeks old. Nothing here talks to Baby Buddy or any server. Rows keep the simulated week's shape
(the rhythm engine reads them as they are) and the agent sees them through the same view as BabyBuddyLog.
"""
import datetime
import threading

from simweek import generate as simweek

from ..agent.memory import LOG_KINDS, BabyLog, parse_time, start_after_feeds

TZ = simweek.TZ
MAX_ADDED = 300
SIM_PREFIX = "[simulated] "


def iso(moment):
    return moment.astimezone(TZ).isoformat(timespec="seconds")


def finished(row):
    return parse_time(row.get("end") or row.get("start") or row["time"])


def started(row):
    return parse_time(row.get("start") or row["time"])


def split_week(now):
    """The simulated week around now: the entries already over, with ids, and the rest of today, still to happen."""
    tomorrow = now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    rows = simweek.generate(seed=7, anchor=tomorrow)
    kept = [r for r in rows if finished(r) <= now]
    for i, row in enumerate(kept):
        row["ref"] = f"{row['kind']}#{i}"
        row["id"] = i + 1
    return kept, sorted((r for r in rows if finished(r) > now), key=started)


def week(now):
    """The simulated week ending today at now: seven days of entries, the last one today, none in the future."""
    return split_week(now)[0]


def minutes_between(start, end):
    return round((parse_time(end) - parse_time(start)).total_seconds() / 60)


def view(row):
    """A simulated-week row as the agent's log entry: {ts, kind, details}, the same shape BabyBuddyLog returns."""
    kind = row["kind"]
    if kind == "feeding":
        # A feed a visitor logged without a start or a length keeps both unknown, the same as an unnamed milk type.
        timed = row.get("timed", True)
        details = {"amount_ml": row.get("amount"), "type": row.get("type"), "method": row.get("method"),
                   "start": row["start"] if timed else None,
                   "duration_min": minutes_between(row["start"], row["end"]) if timed else None}
        return {"id": row["id"], "kind": "feeding", "ts": row["end"], "details": details}
    if kind == "change":
        details = {"wet": row.get("wet"), "solid": row.get("solid"), "color": row.get("color") or None}
        return {"id": row["id"], "kind": "diaper", "ts": row["time"], "details": details}
    if kind == "sleep":
        details = {"start": row["start"], "duration_min": minutes_between(row["start"], row["end"]), "nap": row.get("nap")}
        return {"id": row["id"], "kind": "sleep", "ts": row["end"], "details": details}
    text = row.get("note") or ""
    plain = text[len(SIM_PREFIX):] if text.startswith(SIM_PREFIX) else text
    return {"id": row["id"], "kind": "bath" if plain.lower().startswith("bath") else "note", "ts": row["time"],
            "details": {"text": plain}}


class DemoBabyLog(BabyLog):
    name = "demo"

    def __init__(self, now=None, clock=None):
        self.clock = clock or (lambda: datetime.datetime.now(TZ))
        # The simulated day keeps going while the visitor reads: an upcoming entry joins the log once it is over, and
        # one in progress (a feed or a sleep that started) is shown to the rhythm, so the next feed never reads late
        # just because the simulated baby is eating right now. Once the visitor logs or changes anything the day is
        # theirs and nothing more is added by itself.
        self.rows, self.upcoming = split_week(now or self.clock())
        self.sleep_started = None
        self.added = 0
        self.lock = threading.Lock()

    def now(self):
        return self.clock().astimezone(TZ)

    def advance(self):
        """Move the simulated entries that are over by now from upcoming into the log."""
        current = self.now()
        with self.lock:
            while self.upcoming and finished(self.upcoming[0]) <= current:
                row = self.upcoming.pop(0)
                row["id"] = max((r["id"] for r in self.rows), default=0) + 1
                row["ref"] = f"{row['kind']}#{row['id'] - 1}"
                self.rows.append(row)

    def in_progress(self):
        """Simulated entries that started and are not over yet, such as a feed going on now."""
        current = self.now()
        with self.lock:
            return [dict(r, ref=f"{r['kind']}#now", id=0) for r in self.upcoming
                    if r["kind"] in ("feeding", "sleep") and started(r) <= current < finished(r)]

    def take_over(self):
        """The visitor's day from now on. A simulated sleep going on right now stays open, as if a parent had said he
        fell asleep: dropping it left the last sleep hours back, and a cry then read "awake 4 h" (round b4)."""
        current = self.now()
        with self.lock:
            asleep = [r for r in self.upcoming if r["kind"] == "sleep" and started(r) < current < finished(r)]
            if asleep and self.sleep_started is None:
                self.sleep_started = started(asleep[0])
            self.upcoming = []

    def at_or_before_now(self, ts):
        current = self.now()
        moment = parse_time(ts) if ts else None
        return current if moment is None or moment > current else moment

    def _append(self, row):
        if self.added >= MAX_ADDED:
            raise ValueError("the demo log is full, start a fresh demo baby")
        with self.lock:
            row["id"] = max((r["id"] for r in self.rows), default=0) + 1
            row["ref"] = f"{row['kind']}#{row['id'] - 1}"
            row["tags"] = ["demo-visitor"]
            self.rows.append(row)
            self.added += 1
        return view(row)

    def add(self, kind, details, ts=None):
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind}, expected one of {', '.join(LOG_KINDS)}")
        details = dict(details or {})
        self.check_bounds(kind, details, ts)
        self.advance()
        self.take_over()
        when = self.at_or_before_now(ts or details.get("end") or details.get("time"))
        if kind == "feeding":
            # Only what the parent said: no milk type, start or length is made up. A feed with neither a start nor a
            # length is kept at the time of the message, with its start and length unknown.
            method = details.get("method") or "bottle"
            milk = details.get("type") or ("breast milk" if "breast" in method else None)
            if details.get("start"):
                start = self.at_or_before_now(details["start"])
            elif details.get("duration_min"):
                start = when - datetime.timedelta(minutes=float(details["duration_min"]))
            else:
                start = when
            row = {"kind": "feeding", "start": iso(start), "end": iso(when), "type": milk, "method": method, "notes": "",
                   "timed": bool(details.get("start") or details.get("duration_min"))}
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

    def open_sleep(self):
        """The visitor's open sleep, or the simulated one going on now that a first log keeps open (take_over). Read
        the same before and after that first log, so "bottle 60 ml" never reads as "and he fell asleep at 19:51"."""
        if self.sleep_started is not None:
            return iso(self.sleep_started)
        current = self.now()
        with self.lock:
            asleep = [r for r in self.upcoming if r["kind"] == "sleep" and started(r) < current < finished(r)]
        return iso(started(asleep[0])) if asleep else None

    def _sleep(self, details, when):
        action = details.get("action")
        if details.get("start") and details.get("end"):
            start, end = self.at_or_before_now(details["start"]), self.at_or_before_now(details["end"])
        elif action == "end" or (details.get("end") and not details.get("start")):
            if self.sleep_started is None:
                raise ValueError("no sleep was started, tell me when he fell asleep")
            start, end, self.sleep_started = self.sleep_started, when, None
        else:
            self.sleep_started = when
            return {"kind": "sleep", "ts": iso(when), "details": {"action": "start"}}
        if end <= start:
            raise ValueError("a sleep must end after it starts")
        # A feed logged inside it means the baby was awake then: the sleep starts after it (round b5 logged a nap from
        # 15:13 over two feeds).
        with self.lock:
            feeds = [(started(r), finished(r)) for r in self.rows if r["kind"] == "feeding"]
        start = start_after_feeds(start, end, feeds)
        return self._append({"kind": "sleep", "start": iso(start), "end": iso(end), "nap": 7 <= start.hour < 19, "notes": ""})

    def _row(self, entry_id):
        self.advance()
        try:
            wanted = int(entry_id)
        except (TypeError, ValueError):
            raise ValueError(f"no entry with id {entry_id}") from None
        with self.lock:
            for row in self.rows:
                if row["id"] == wanted:
                    return row
        raise ValueError(f"no entry with id {entry_id}")

    def get(self, entry_id):
        try:
            return view(self._row(entry_id))
        except ValueError:
            return None

    def update(self, entry_id, details=None, ts=None):
        """Change an entry of this visitor's copy in place. Returns the entry before and after, so the reply says
        exactly what changed. Simulated entries can be corrected too: the copy is the visitor's own."""
        row = self._row(entry_id)
        self.take_over()
        before = view(row)
        new = dict(details or {})
        self.check_bounds(before["kind"], {k: v for k, v in new.items() if k in ("amount_ml", "duration_min", "start", "end")}, ts)
        changed = dict(row)
        if before["kind"] == "feeding":
            end = self.at_or_before_now(ts) if ts else parse_time(row["end"])
            if new.get("duration_min") is not None:
                start = end - datetime.timedelta(minutes=float(new["duration_min"]))
                changed["timed"] = True
            else:
                start = parse_time(row["start"]) + (end - parse_time(row["end"]))
            changed.update(start=iso(start), end=iso(end))
            if new.get("amount_ml") is not None:
                changed["amount"] = float(new["amount_ml"])
            if "breast" in str(new.get("method") or "") and "breast" not in str(row.get("method") or "") \
                    and new.get("amount_ml") is None:
                changed.pop("amount", None)  # a bottle that was a breast feed keeps no ml, as on the families bot
                if not new.get("type"):
                    changed["type"] = "breast milk"
            for name in ("method", "type"):
                if new.get(name):
                    changed[name] = new[name]
        elif before["kind"] == "diaper":
            wet, solid = bool(new.get("wet", row.get("wet"))), bool(new.get("solid", row.get("solid")))
            changed.update(time=iso(self.at_or_before_now(ts)) if ts else row["time"], wet=wet or not solid, solid=solid,
                           color=new.get("color", row.get("color")) or "")
        elif before["kind"] == "sleep":
            start = self.at_or_before_now(new["start"]) if new.get("start") else parse_time(row["start"])
            end = self.at_or_before_now(new.get("end") or ts) if (new.get("end") or ts) else parse_time(row["end"])
            if end <= start:
                raise ValueError("a sleep must end after it starts")
            self.check_bounds("sleep", {"start": iso(start), "end": iso(end)})
            changed.update(start=iso(start), end=iso(end))
        else:
            text = str(new.get("text") or new.get("note") or before["details"].get("text") or "").strip()[:300]
            if before["kind"] == "bath" and not text.lower().startswith("bath"):
                text = f"Bath. {text}".strip()
            changed.update(note=text, time=iso(self.at_or_before_now(ts)) if ts else row["time"])
        with self.lock:
            row.clear()
            row.update(changed)
        return {"before": before, "after": view(row)}

    def delete(self, entry_id):
        row = self._row(entry_id)
        self.take_over()
        before = view(row)
        with self.lock:
            self.rows = [r for r in self.rows if r is not row]
        return {"deleted": before}

    def entries(self, kind=None, since=None, limit=50):
        since_time = parse_time(since) if since else None
        self.advance()
        with self.lock:
            items = [view(r) for r in self.rows]
        items = [e for e in items if (kind is None or e["kind"] == kind) and (since_time is None or parse_time(e["ts"]) >= since_time)]
        items.sort(key=lambda e: parse_time(e["ts"]))
        return items[-max(int(limit or 50), 1):]

    def rhythm_rows(self):
        """The rows in the simulated week's shape, which the rhythm engine reads, with a simulated feed or sleep that is
        going on now. The rhythm engine counts an entry from its start, so one in progress is read correctly."""
        self.advance()
        with self.lock:
            rows = [dict(r) for r in self.rows]
        opened = ([{"kind": "sleep", "start": iso(self.sleep_started), "end": None, "ref": "sleep#open", "id": 0}]
                  if self.sleep_started is not None else [])  # "he just fell asleep" with no wake-up yet, as Baby Buddy's timer
        return rows + self.in_progress() + opened
