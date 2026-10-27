"""Persistent memory: the conversation, facts the agent was told, and a local baby log, in one SQLite file.

The file lives in the agent's data folder on the machine that runs it, so memory survives restarts and
never leaves the house. Baby Buddy becomes the baby log later (issue #2 and #12) through the BabyLog
interface below, and LocalBabyLog keeps the same shape until then.
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
    """What every baby log offers the agent. Baby Buddy implements the same methods in issue #2."""
    name = "abstract"

    def add(self, kind, details, ts=None):
        raise NotImplementedError

    def entries(self, kind=None, since=None, limit=50):
        raise NotImplementedError


class LocalBabyLog(BabyLog):
    """The baby log kept in the agent's own memory file, used until Baby Buddy is wired in."""
    name = "local"

    def __init__(self, memory):
        self.memory = memory

    def add(self, kind, details, ts=None):
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind}, expected one of {', '.join(LOG_KINDS)}")
        entry = {"ts": ts or now(), "kind": kind, "details": details}
        with self.memory.lock:
            self.memory.db.execute("insert into baby_log (ts, kind, details) values (?, ?, ?)", (entry["ts"], kind, json.dumps(details)))
            self.memory.db.commit()
        return entry

    def entries(self, kind=None, since=None, limit=50):
        query, args = "select ts, kind, details from baby_log where 1 = 1", []
        if kind:
            query, args = query + " and kind = ?", args + [kind]
        if since:
            query, args = query + " and ts >= ?", args + [since]
        with self.memory.lock:
            rows = self.memory.db.execute(query + " order by ts desc limit ?", args + [limit]).fetchall()
        return [{"ts": ts, "kind": kind, "details": json.loads(details)} for ts, kind, details in reversed(rows)]
