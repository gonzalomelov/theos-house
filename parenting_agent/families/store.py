"""The families registry, the session rows for the real-user scorer, and spend.

One SQLite file, families.sqlite, next to one file per family (babylog.py). It holds no baby data and no
message text: only which hashed parent belongs to which family, the chat to answer, invite code hashes,
session rows and spend.

Scorer contract, table sessions(ts TEXT ISO8601 UTC, visitor_id TEXT, channel TEXT, kind TEXT,
internal INTEGER, family_id TEXT): one row per parent message the service takes in. visitor_id is the sha256 of
the Telegram user id. kind is 'family'. internal is 1 for Gonza's own test accounts.
"""
import datetime
import hashlib
import secrets
import sqlite3
import threading
from pathlib import Path

DB_NAME = "families.sqlite"
CHANNEL = "telegram"
KIND = "family"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
SCHEMA = """
create table if not exists families (family_id TEXT primary key, created TEXT);
create table if not exists invites (code_hash TEXT primary key, family_id TEXT, created TEXT, expires TEXT,
                                    used_at TEXT, used_by TEXT, internal INTEGER);
create table if not exists parents (visitor_id TEXT primary key, chat_id TEXT, family_id TEXT, step TEXT,
                                    joined TEXT, internal INTEGER);
create table if not exists sessions (ts TEXT, visitor_id TEXT, channel TEXT, kind TEXT, internal INTEGER, family_id TEXT);
create index if not exists sessions_family on sessions (family_id);
create table if not exists spend (day TEXT, scope TEXT, usd REAL, calls INTEGER, primary key (day, scope));
"""
ALL = "all"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def iso_utc(moment):
    return moment.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def visitor_id(telegram_user_id):
    return hashlib.sha256(str(telegram_user_id).encode()).hexdigest()


def clean_code(text):
    return "".join(c for c in (text or "").upper() if c.isalnum())


def code_hash(code):
    return hashlib.sha256(clean_code(code).encode()).hexdigest()


def new_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


class Store:
    def __init__(self, data_dir, clock=utc_now):
        path = Path(data_dir)
        path.mkdir(parents=True, exist_ok=True)
        self.path = path / DB_NAME
        self.clock = clock
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def _run(self, query, args=()):
        with self.lock:
            cursor = self.db.execute(query, args)
            self.db.commit()
            return cursor

    def _all(self, query, args=()):
        with self.lock:
            return self.db.execute(query, args).fetchall()

    def _one(self, query, args=()):
        rows = self._all(query, args)
        return rows[0] if rows else None

    def today(self):
        return self.clock().astimezone(datetime.timezone.utc).date().isoformat()

    # Invites

    def create_invite(self, family_id=None, days=7, internal=False):
        """A fresh single-use code. Only its hash is stored, so the file never holds a usable code.
        internal marks whoever joins with it as one of Gonza's test accounts."""
        now = self.clock()
        code = new_code()
        self._run("insert into invites (code_hash, family_id, created, expires, internal) values (?, ?, ?, ?, ?)",
                  (code_hash(code), family_id, iso_utc(now), iso_utc(now + datetime.timedelta(days=days)), 1 if internal else 0))
        return code

    def invite(self, code):
        """{"family_id": id or None, "internal": bool} for an unused, unexpired code, else None."""
        if len(clean_code(code)) != CODE_LENGTH:
            return None
        row = self._one("select family_id, expires, used_at, internal from invites where code_hash = ?", (code_hash(code),))
        if row is None or row[2] is not None or row[1] <= iso_utc(self.clock()):
            return None
        return {"family_id": row[0], "internal": bool(row[3])}

    def use_invite(self, code, visitor):
        cursor = self._run("update invites set used_at = ?, used_by = ? where code_hash = ? and used_at is null",
                           (iso_utc(self.clock()), visitor, code_hash(code)))
        return cursor.rowcount == 1

    def open_invites(self):
        return self._one("select count(*) from invites where used_at is null and expires > ?", (iso_utc(self.clock()),))[0]

    # Families and parents

    def create_family(self):
        family_id = secrets.token_hex(8)
        self._run("insert into families (family_id, created) values (?, ?)", (family_id, iso_utc(self.clock())))
        return family_id

    def family_count(self):
        return self._one("select count(*) from families")[0]

    def family_ids(self):
        return [row[0] for row in self._all("select family_id from families order by created")]

    def add_parent(self, visitor, chat_id, family_id, step, internal):
        self._run("insert into parents (visitor_id, chat_id, family_id, step, joined, internal) values (?, ?, ?, ?, ?, ?) "
                  "on conflict(visitor_id) do update set chat_id = excluded.chat_id, family_id = excluded.family_id, "
                  "step = excluded.step, joined = excluded.joined, internal = excluded.internal",
                  (visitor, str(chat_id), family_id, step, iso_utc(self.clock()), 1 if internal else 0))

    def parent(self, visitor):
        row = self._one("select chat_id, family_id, step, internal from parents where visitor_id = ?", (visitor,))
        if row is None:
            return None
        return {"visitor_id": visitor, "chat_id": row[0], "family_id": row[1], "step": row[2], "internal": bool(row[3])}

    def set_step(self, visitor, step):
        self._run("update parents set step = ? where visitor_id = ?", (step, visitor))

    def parents_of(self, family_id):
        rows = self._all("select visitor_id, chat_id, step from parents where family_id = ? order by joined", (family_id,))
        return [{"visitor_id": v, "chat_id": c, "step": s} for v, c, s in rows]

    def delete_family(self, family_id):
        """Every row about the family: parents, invites, session rows and its own spend. The daily total stays."""
        with self.lock:
            for query in ("delete from parents where family_id = ?", "delete from invites where family_id = ?",
                          "delete from sessions where family_id = ?", "delete from spend where scope = ?",
                          "delete from families where family_id = ?"):
                self.db.execute(query, (family_id,))
            self.db.commit()

    # Session rows and caps

    def add_message(self, visitor, family_id, internal):
        self._run("insert into sessions (ts, visitor_id, channel, kind, internal, family_id) values (?, ?, ?, ?, ?, ?)",
                  (iso_utc(self.clock()), visitor, CHANNEL, KIND, 1 if internal else 0, family_id))

    def family_messages_today(self, family_id):
        return self._one("select count(*) from sessions where family_id = ? and substr(ts, 1, 10) = ?",
                         (family_id, self.today()))[0]

    def spent_today(self, scope=ALL):
        row = self._one("select usd from spend where day = ? and scope = ?", (self.today(), scope))
        return row[0] if row else 0.0

    def add_spend(self, family_id, usd):
        with self.lock:
            for scope in (ALL, family_id):
                self.db.execute("insert into spend (day, scope, usd, calls) values (?, ?, ?, 1) on conflict(day, scope) "
                                "do update set usd = usd + excluded.usd, calls = calls + 1", (self.today(), scope, usd))
            self.db.commit()

    def rows(self):
        rows = self._all("select ts, visitor_id, channel, kind, internal, family_id from sessions order by rowid")
        return [{"ts": ts, "visitor_id": v, "channel": c, "kind": k, "internal": i, "family_id": f}
                for ts, v, c, k, i, f in rows]

    def close(self):
        with self.lock:
            self.db.close()
