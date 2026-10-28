"""Session records for the real-user scorer, and the demo's daily brain spend.

Contract with the scorer: data/demo_sessions.sqlite, table
sessions(ts TEXT ISO8601 UTC, visitor_id TEXT, channel TEXT, kind TEXT, internal INTEGER), one row per visitor
message. visitor_id is the sha256 of a random first-party cookie, never an IP. kind is 'demo'. internal is 1 for
Gonza and agents. The table never holds message text. The spend table is the demo's own and the scorer ignores it.
"""
import datetime
import hashlib
import sqlite3
import threading
from pathlib import Path

DB_NAME = "demo_sessions.sqlite"
CHANNEL = "web"
KIND = "demo"
SCHEMA = """
create table if not exists sessions (ts TEXT, visitor_id TEXT, channel TEXT, kind TEXT, internal INTEGER);
create index if not exists sessions_visitor on sessions (visitor_id);
create table if not exists spend (day TEXT primary key, usd REAL, calls INTEGER);
"""


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def iso_utc(moment):
    return moment.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def visitor_id(cookie):
    return hashlib.sha256(cookie.encode()).hexdigest()


class Records:
    def __init__(self, data_dir, clock=utc_now):
        path = Path(data_dir)
        path.mkdir(parents=True, exist_ok=True)
        self.path = path / DB_NAME
        self.clock = clock
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def today(self):
        return self.clock().astimezone(datetime.timezone.utc).date().isoformat()

    def add_message(self, visitor, internal):
        with self.lock:
            self.db.execute("insert into sessions (ts, visitor_id, channel, kind, internal) values (?, ?, ?, ?, ?)",
                            (iso_utc(self.clock()), visitor, CHANNEL, KIND, 1 if internal else 0))
            self.db.commit()

    def messages_from(self, visitor):
        with self.lock:
            return self.db.execute("select count(*) from sessions where visitor_id = ?", (visitor,)).fetchone()[0]

    def messages_today(self):
        with self.lock:
            return self.db.execute("select count(*) from sessions where substr(ts, 1, 10) = ? and internal = 0",
                                   (self.today(),)).fetchone()[0]

    def spent_today(self):
        with self.lock:
            row = self.db.execute("select usd from spend where day = ?", (self.today(),)).fetchone()
        return row[0] if row else 0.0

    def add_spend(self, usd):
        with self.lock:
            self.db.execute("insert into spend (day, usd, calls) values (?, ?, 1) on conflict(day) do update set "
                            "usd = usd + excluded.usd, calls = calls + 1", (self.today(), usd))
            self.db.commit()

    def rows(self):
        with self.lock:
            rows = self.db.execute("select ts, visitor_id, channel, kind, internal from sessions order by rowid").fetchall()
        return [{"ts": ts, "visitor_id": v, "channel": c, "kind": k, "internal": i} for ts, v, c, k, i in rows]

    def close(self):
        with self.lock:
            self.db.close()
