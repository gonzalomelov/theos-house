"""One family's own log: a SQLite file per family with its baby log, its conversation and its facts.

Nothing in here talks to Baby Buddy or any server. The file is data/families/family-<id>.sqlite and nothing
else ever opens it: a family's agent gets only its own file, and delete-my-data removes it. Entries keep the
agent's {ts, kind, details} shape, and rhythm_rows() gives the rhythm engine the simulated week's shape.
"""
import datetime
import json
import re
from pathlib import Path

from ..agent.memory import LOG_KINDS, BabyLog, Memory, parse_time

DEFAULT_FEED_MINUTES = 15
FAMILY_ID = re.compile(r"^[0-9a-f]{16}$")


def family_path(data_dir, family_id):
    if not FAMILY_ID.match(family_id or ""):
        raise ValueError("bad family id")
    return Path(data_dir) / f"family-{family_id}.sqlite"


def open_memory(data_dir, family_id):
    return Memory(family_path(data_dir, family_id))


def wipe(data_dir, family_id):
    """Remove the family's file and any SQLite side files. Returns the paths removed."""
    base = family_path(data_dir, family_id)
    removed = []
    for path in (base, base.with_name(base.name + "-journal"), base.with_name(base.name + "-wal"),
                 base.with_name(base.name + "-shm")):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


class FamilyBabyLog(BabyLog):
    name = "family"

    def __init__(self, memory, clock):
        self.memory, self.clock = memory, clock

    def now(self):
        return self.clock()

    def at_or_before_now(self, ts):
        current = self.now()
        moment = parse_time(ts) if ts else None
        return current if moment is None or moment > current else moment

    def _store(self, kind, when, details):
        stamp = when.isoformat(timespec="seconds")
        with self.memory.lock:
            cursor = self.memory.db.execute("insert into baby_log (ts, kind, details) values (?, ?, ?)",
                                            (stamp, kind, json.dumps(details)))
            self.memory.db.commit()
        return {"id": cursor.lastrowid, "ts": stamp, "kind": kind, "details": details}

    def add(self, kind, details, ts=None):
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind}, expected one of {', '.join(LOG_KINDS)}")
        details = dict(details or {})
        when = self.at_or_before_now(ts or details.get("end") or details.get("time"))
        if kind == "feeding":
            method = details.get("method") or "bottle"
            length = float(details.get("duration_min") or DEFAULT_FEED_MINUTES)
            start = (self.at_or_before_now(details["start"]) if details.get("start")
                     else when - datetime.timedelta(minutes=length))
            out = {"method": method, "type": details.get("type") or ("breast milk" if "breast" in method else "formula"),
                   "start": start.isoformat(timespec="seconds"), "duration_min": round((when - start).total_seconds() / 60)}
            if details.get("amount_ml") is not None:
                out["amount_ml"] = float(details["amount_ml"])
            return self._store("feeding", when, out)
        if kind == "diaper":
            wet, solid = bool(details.get("wet")), bool(details.get("solid"))
            return self._store("diaper", when, {"wet": wet or not solid, "solid": solid, "color": details.get("color") or None})
        if kind == "sleep":
            return self._sleep(details, when)
        text = str(details.get("text") or details.get("note") or "").strip()[:300]
        if kind == "bath" and not text.lower().startswith("bath"):
            text = f"Bath. {text}".strip()
        return self._store(kind, when, {"text": text or kind.capitalize()})

    def _sleep(self, details, when):
        action = details.get("action")
        started = self.memory.facts().get("_sleep_started", {}).get("value")
        if details.get("start") and details.get("end"):
            start, end = self.at_or_before_now(details["start"]), self.at_or_before_now(details["end"])
        elif action == "end" or (details.get("end") and not details.get("start")):
            if not started:
                raise ValueError("no sleep was started, tell me when the baby fell asleep")
            start, end = parse_time(started), when
            self.memory.remember("_sleep_started", "")
        else:
            self.memory.remember("_sleep_started", when.isoformat(timespec="seconds"))
            return {"kind": "sleep", "ts": when.isoformat(timespec="seconds"), "details": {"action": "start"}}
        if end <= start:
            raise ValueError("a sleep must end after it starts")
        local = start.astimezone(self.now().tzinfo)
        return self._store("sleep", end, {"start": start.isoformat(timespec="seconds"),
                                          "duration_min": round((end - start).total_seconds() / 60),
                                          "nap": 7 <= local.hour < 19})

    def entries(self, kind=None, since=None, limit=50):
        query, args = "select id, ts, kind, details from baby_log", []
        if kind:
            query, args = query + " where kind = ?", [kind]
        with self.memory.lock:
            rows = self.memory.db.execute(query, args).fetchall()
        items = [{"id": i, "ts": ts, "kind": k, "details": json.loads(d)} for i, ts, k, d in rows]
        if since:
            since_time = parse_time(since)
            items = [e for e in items if parse_time(e["ts"]) >= since_time]
        items.sort(key=lambda e: parse_time(e["ts"]))
        return items[-max(int(limit or 50), 1):]

    def rhythm_rows(self):
        """Every entry in the shape the rhythm engine reads: feeding and sleep with start and end, change, note."""
        rows = []
        for e in self.entries(None, None, 100_000):
            ref, d = f"{e['kind']}#{e['id']}", e["details"]
            if e["kind"] == "feeding":
                rows.append({"kind": "feeding", "start": d.get("start") or e["ts"], "end": e["ts"],
                             "amount": d.get("amount_ml"), "method": d.get("method"), "ref": ref})
            elif e["kind"] == "sleep":
                rows.append({"kind": "sleep", "start": d.get("start") or e["ts"], "end": e["ts"], "nap": d.get("nap"), "ref": ref})
            elif e["kind"] == "diaper":
                rows.append({"kind": "change", "time": e["ts"], "wet": d.get("wet"), "solid": d.get("solid"), "ref": ref})
            else:
                rows.append({"kind": "note", "time": e["ts"], "note": d.get("text") or "", "ref": ref})
        return rows
