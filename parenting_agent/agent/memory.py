"""Persistent memory: the conversation, facts the agent was told, and an offline baby log, in one SQLite file.

The file lives in the agent's data folder on the machine that runs it, so memory survives restarts and
never leaves the house. Baby Buddy on the family's server is the real baby log (babybuddy.py, issue #2),
and LocalBabyLog keeps the same shape for offline runs and tests.
"""
import datetime
import json
import sqlite3
import threading

SCHEMA = """
create table if not exists messages (id integer primary key, ts text, channel text, role text, text text);
create table if not exists facts (key text primary key, value text, ts text);
create table if not exists baby_log (id integer primary key, ts text, kind text, details text);
"""

LOG_KINDS = ("feeding", "diaper", "sleep", "bath", "note")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_time(value):
    """An ISO instant as an aware datetime in local time. A time with no offset is local."""
    moment = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment.astimezone() if moment.tzinfo else moment.astimezone(datetime.datetime.now().astimezone().tzinfo)


def start_of_today():
    return datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def hhmm(ts):
    return parse_time(ts).strftime("%H:%M") if ts else None


class Memory:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def add_message(self, channel, role, text):
        with self.lock:
            self.db.execute("insert into messages (ts, channel, role, text) values (?, ?, ?, ?)", (now(), channel, role, text))
            self.db.commit()

    def recent_messages(self, limit=20):
        with self.lock:
            rows = self.db.execute("select ts, channel, role, text from messages order by id desc limit ?", (limit,)).fetchall()
        return [{"ts": ts, "channel": channel, "role": role, "text": text} for ts, channel, role, text in reversed(rows)]

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

    def add(self, kind, details, ts=None):
        raise NotImplementedError

    def entries(self, kind=None, since=None, limit=50):
        raise NotImplementedError

    def summary(self, since=None):
        """Totals since an instant (default midnight today) and the last of each kind, computed from the log, never guessed."""
        since = since or start_of_today()
        recent = self.entries(None, None, 200)
        window = [e for e in recent if parse_time(e["ts"]) >= parse_time(since)]

        def last(kind, test=lambda e: True):
            found = [e for e in recent if e["kind"] == kind and test(e)]
            return found[-1] if found else None

        feeds = [e for e in window if e["kind"] == "feeding"]
        diapers = [e for e in window if e["kind"] == "diaper"]
        sleeps = [e for e in window if e["kind"] == "sleep"]
        last_feed, last_sleep, last_bath = last("feeding"), last("sleep"), last("bath")
        last_dirty = last("diaper", lambda e: e["details"].get("solid"))
        last_wet = last("diaper", lambda e: e["details"].get("wet"))
        return {
            "since": since, "now": now(),
            "feedings": {"count": len(feeds), "total_ml": round(sum(float(e["details"].get("amount_ml") or 0) for e in feeds)),
                         "last_at": hhmm(last_feed["ts"]) if last_feed else None,
                         "last_amount_ml": last_feed["details"].get("amount_ml") if last_feed else None,
                         "last_method": last_feed["details"].get("method") if last_feed else None},
            "diapers": {"count": len(diapers), "wet": sum(1 for e in diapers if e["details"].get("wet")),
                        "dirty": sum(1 for e in diapers if e["details"].get("solid")),
                        "last_dirty_at": hhmm(last_dirty["ts"]) if last_dirty else None,
                        "last_dirty_date": last_dirty["ts"][:10] if last_dirty else None,
                        "last_wet_at": hhmm(last_wet["ts"]) if last_wet else None},
            "sleep": {"count": len(sleeps), "total_min": sum(int(e["details"].get("duration_min") or 0) for e in sleeps),
                      "last_start_at": hhmm(last_sleep["details"].get("start")) if last_sleep and last_sleep["details"].get("start") else None,
                      "last_end_at": hhmm(last_sleep["ts"]) if last_sleep else None},
            "baths": {"count": sum(1 for e in window if e["kind"] == "bath"),
                      "last_at": hhmm(last_bath["ts"]) if last_bath else None,
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
