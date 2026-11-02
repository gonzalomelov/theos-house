"""Persistent memory: the conversation, facts the agent was told, and an offline baby log, in one SQLite file.

The file lives in the agent's data folder on the machine that runs it, so memory survives restarts. The file
stays in the house, but each turn sends the recent conversation to the brain, Muse Spark Open on Baseten. Baby Buddy on the family's server is the real baby log (babybuddy.py, issue #2),
and LocalBabyLog keeps the same shape for offline runs and tests.
"""
import datetime
import json
import re
import sqlite3
import threading

SCHEMA = """
create table if not exists messages (id integer primary key, ts text, channel text, role text, text text);
create table if not exists facts (key text primary key, value text, ts text);
create table if not exists baby_log (id integer primary key, ts text, kind text, details text);
"""

LOG_KINDS = ("feeding", "diaper", "sleep", "bath", "note")
HHMM = re.compile(r"^(\d{1,2})[:.h](\d{2})$")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_time(value, tz=None):
    """An ISO instant as an aware datetime in the zone given, or in local time. A time with no offset is in that zone."""
    moment = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if tz is not None:
        return moment.astimezone(tz) if moment.tzinfo else moment.replace(tzinfo=tz)
    return moment.astimezone() if moment.tzinfo else moment.astimezone(datetime.datetime.now().astimezone().tzinfo)


def hhmm(ts, tz=None):
    return parse_time(ts, tz).strftime("%H:%M") if ts else None


def feed_start(entry):
    """When a feed began, as an ISO time: its start when its length is known (said by the parent or recorded in Baby
    Buddy), else the time the parent told, the only time the log really has. "¿A qué hora comió?" means the start:
    held-out run-3 answered the end of the 13:10 feed, 13:25. Any other entry gives its own time."""
    details = entry.get("details") or {}
    if entry.get("kind") != "feeding" or not details.get("duration_min"):
        return entry.get("ts")
    if details.get("start"):
        return details["start"]
    begun = parse_time(entry["ts"]) - datetime.timedelta(minutes=float(details["duration_min"]))
    return begun.isoformat(timespec="seconds")


def start_after_feeds(start, end, feeds):
    """A sleep never spans a feed: its start moves past the end of the last feed logged inside it. feeds are (start,
    end) pairs. Raises ValueError when a feed covers the sleep's end, so there is no sleep left to log."""
    inside = [(a, b) for a, b in feeds if a < end and b > start]
    if not inside:
        return start
    last_start, last_end = max(inside, key=lambda pair: pair[1])
    if last_end >= end or last_start >= end:
        raise ValueError(f"a feed at {last_start.strftime('%H:%M')} is logged in that time, tell me when the baby fell asleep")
    return last_end


def place_sleep(start, end, feeds):
    """(start, end) of a finished sleep told with its length ("napped about 40 minutes") that never spans a feed. When
    moving its start past a feed would keep less than half of the length the parent said, the nap came before that
    feed: it keeps its length and ends when the feed began (round b7 logged "napped about 40 minutes" right after a
    bottle as a 1 minute sleep)."""
    length = end - start
    for _ in range(len(feeds) + 1):
        moved = None
        try:
            moved = start_after_feeds(start, end, feeds)
        except ValueError:
            pass
        if moved is not None and end - moved >= length / 2:
            return moved, end
        inside = [a for a, b in feeds if a < end and b > start]
        if not inside:
            return start, end
        end = min(inside)
        start = end - length
    return start_after_feeds(start, end, feeds), end


class Memory:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def add_message(self, channel, role, text, ts=None):
        """ts is the agent's own clock, so a simulated or family clock and the conversation agree."""
        stamp = ts.isoformat(timespec="seconds") if isinstance(ts, datetime.datetime) else (ts or now())
        with self.lock:
            self.db.execute("insert into messages (ts, channel, role, text) values (?, ?, ?, ?)", (stamp, channel, role, text))
            self.db.commit()

    def recent_messages(self, limit=20):
        with self.lock:
            rows = self.db.execute("select ts, channel, role, text from messages order by id desc limit ?", (limit,)).fetchall()
        return [{"ts": ts, "channel": channel, "role": role, "text": text} for ts, channel, role, text in reversed(rows)]

    def forget_messages_before(self, moment):
        """Drop conversation lines older than moment. The agent only ever reads the last few, so older ones are not kept."""
        with self.lock:
            rows = self.db.execute("select id, ts from messages").fetchall()
            old = [i for i, ts in rows if ts and parse_time(ts) < moment]
            if old:
                self.db.executemany("delete from messages where id = ?", [(i,) for i in old])
                self.db.commit()
        return len(old)

    def remember(self, key, value):
        with self.lock:
            self.db.execute("insert into facts (key, value, ts) values (?, ?, ?) on conflict(key) do update set value = excluded.value, ts = excluded.ts",
                            (key, value, now()))
            self.db.commit()

    def facts(self):
        with self.lock:
            rows = self.db.execute("select key, value, ts from facts order by key").fetchall()
        return {key: {"value": value, "ts": ts} for key, value, ts in rows}

    def close(self):
        with self.lock:
            self.db.close()


class BabyLog:
    """What every baby log offers the agent: add, entries and a summary computed from the entries."""
    name = "abstract"

    def now(self):
        return parse_time(now())

    def add(self, kind, details, ts=None):
        raise NotImplementedError

    def entries(self, kind=None, since=None, limit=50):
        raise NotImplementedError

    def open_sleep(self):
        """The start of a sleep the parent began and has not ended yet, as an ISO time, or None."""
        return None

    def find(self, entry_id=None, kind=None, at=None, last=None):
        """One entry, by id, by kind and local time (HH:MM, the most recent one at that time), or the last one."""
        if entry_id is not None:
            entry = self.get(entry_id)
            if entry is None:
                raise ValueError(f"no entry with id {entry_id}")
            return entry
        items = self.entries(kind, None, 100_000)
        if at:
            match = HHMM.match(str(at).strip())
            if not match:
                raise ValueError("at must be a local time like 01:30")
            wanted = f"{int(match.group(1)):02d}:{match.group(2)}"
            items = [e for e in items if wanted in (e["ts"][11:16], str(e["details"].get("start") or "")[11:16])]
        elif not last:
            raise ValueError("name the entry by id, by kind and at, or by last")
        if not items:
            raise ValueError("no such entry in the log")
        return items[-1]

    def check_bounds(self, kind, details, ts=None):
        """The second wall behind the agent's own check: a value no real entry can have is never stored. A time in the
        future is the agent's question to ask, the log itself moves it to now."""
        from . import rules  # rules imports nothing from here, the late import only keeps the module order simple
        bad = rules.out_of_bounds(kind, details, ts, self.now(), parse_time, future=False)
        if bad:
            raise ValueError(f"{bad[0]} {bad[1]} is outside what one entry can be, nothing was logged")

    def summary(self, since=None, until=None):
        """Totals since an instant (default midnight today on the log's own clock, so a family clock and a server on UTC
        agree) and until one (default now), and the last of each kind, computed from the log, never guessed."""
        current = self.now()
        since = since or current.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        recent = self.entries(None, None, 200)
        window = [e for e in recent if parse_time(e["ts"]) >= parse_time(since)
                  and (until is None or parse_time(e["ts"]) < parse_time(until))]

        def last(kind, test=lambda e: True):
            # A window that ends (yesterday) names its own last entry: round 4 read "la última de ayer fue a la 01:05"
            # when the 01:05 feed was today.
            found = [e for e in (window if until is not None else recent) if e["kind"] == kind and test(e)]
            return found[-1] if found else None

        from . import rules  # rules imports nothing from here, the late import only keeps the module order simple
        feeds = [e for e in window if e["kind"] == "feeding"]
        diapers = [e for e in window if e["kind"] == "diaper"]
        sleeps = [e for e in window if e["kind"] == "sleep"]
        last_feed, last_sleep, last_bath = last("feeding"), last("sleep"), last("bath")
        last_dirty = last("diaper", lambda e: e["details"].get("solid"))
        last_wet = last("diaper", lambda e: e["details"].get("wet"))

        def at(ts):
            return hhmm(ts, current.tzinfo)

        return {
            "since": since, "until": until or current.isoformat(timespec="seconds"), "now": current.isoformat(timespec="seconds"),
            "feedings": {"count": len(feeds), "total_ml": round(sum(float(e["details"].get("amount_ml") or 0) for e in feeds)),
                         "last_at": at(feed_start(last_feed)) if last_feed else None,
                         "last_date": feed_start(last_feed)[:10] if last_feed else None,
                         "last_amount_ml": last_feed["details"].get("amount_ml") if last_feed else None,
                         "last_method": last_feed["details"].get("method") if last_feed else None},
            # Counts that add up: "4 diapers, 4 wet and 1 dirty" read as five to a round b4 judge. said is the line to use.
            "diapers": {**rules.diaper_counts(diapers),
                        "last_dirty_at": at(last_dirty["ts"]) if last_dirty else None,
                        "last_dirty_date": last_dirty["ts"][:10] if last_dirty else None,
                        "last_wet_at": at(last_wet["ts"]) if last_wet else None},
            "sleep": {"count": len(sleeps), "total_min": sum(int(e["details"].get("duration_min") or 0) for e in sleeps),
                      "last_start_at": at(last_sleep["details"].get("start")) if last_sleep and last_sleep["details"].get("start") else None,
                      "last_end_at": at(last_sleep["ts"]) if last_sleep else None,
                      "last_end_date": last_sleep["ts"][:10] if last_sleep else None},
            "baths": {"count": sum(1 for e in window if e["kind"] == "bath"),
                      "last_at": at(last_bath["ts"]) if last_bath else None,
                      "last_date": last_bath["ts"][:10] if last_bath else None},
        }


class LocalBabyLog(BabyLog):
    """The baby log kept in the agent's own memory file, for offline runs and tests."""
    name = "local"

    def __init__(self, memory):
        self.memory = memory

    def add(self, kind, details, ts=None):
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind}, expected one of {', '.join(LOG_KINDS)}")
        current = parse_time(now())
        moment = parse_time(ts) if ts else current
        entry = {"ts": min(moment, current).isoformat(timespec="seconds"), "kind": kind, "details": details}
        with self.memory.lock:
            self.memory.db.execute("insert into baby_log (ts, kind, details) values (?, ?, ?)", (entry["ts"], kind, json.dumps(details)))
            self.memory.db.commit()
        return entry

    def entries(self, kind=None, since=None, limit=50):
        query, args = "select ts, kind, details from baby_log where 1 = 1", []
        if kind:
            query, args = query + " and kind = ?", args + [kind]
        with self.memory.lock:
            rows = self.memory.db.execute(query + " order by id", args).fetchall()
        items = [{"ts": ts, "kind": kind, "details": json.loads(details)} for ts, kind, details in rows]
        if since:
            items = [e for e in items if parse_time(e["ts"]) >= parse_time(since)]
        items.sort(key=lambda e: parse_time(e["ts"]))
        return items[-limit:]
