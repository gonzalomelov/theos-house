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

FEEDING_FIELDS = ("amount_ml", "method", "type", "duration_min")
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

    def time(self, ts):
        """An ISO instant in the family's time zone, never the server's, so stored and shown clock times are theirs."""
        return parse_time(ts, self.now().tzinfo)

    def at_or_before_now(self, ts):
        current = self.now()
        moment = parse_time(ts, current.tzinfo) if ts else None
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
        self.check_bounds(kind, details, ts)
        when = self.at_or_before_now(ts or details.get("end") or details.get("time"))
        if kind == "feeding":
            return self._store("feeding", when, self._feeding(details, when))
        if kind == "diaper":
            wet, solid = bool(details.get("wet")), bool(details.get("solid"))
            return self._store("diaper", when, {"wet": wet or not solid, "solid": solid, "color": details.get("color") or None})
        if kind == "sleep":
            return self._sleep(details, when)
        text = str(details.get("text") or details.get("note") or "").strip()[:300]
        if kind == "bath" and not text.lower().startswith("bath"):
            text = f"Bath. {text}".strip()
        return self._store(kind, when, {"text": text or kind.capitalize()})

    def _feeding(self, details, when):
        """A feed at the time the parent logged it. Its start is earlier only when the parent said how long it lasted
        or when it started, and a bottle with no milk type named keeps the type unknown: nothing is made up."""
        method = details.get("method") or "bottle"
        if details.get("start"):
            start = self.at_or_before_now(details["start"])
        elif details.get("duration_min"):
            start = when - datetime.timedelta(minutes=float(details["duration_min"]))
        else:
            start = when
        out = {"method": method, "type": details.get("type") or ("breast milk" if "breast" in method else "unknown"),
               "start": start.isoformat(timespec="seconds"), "duration_min": round((when - start).total_seconds() / 60)}
        if details.get("amount_ml") is not None:
            out["amount_ml"] = float(details["amount_ml"])
        return out

    def get(self, entry_id):
        with self.memory.lock:
            row = self.memory.db.execute("select id, ts, kind, details from baby_log where id = ?", (int(entry_id),)).fetchone()
        return {"id": row[0], "ts": row[1], "kind": row[2], "details": json.loads(row[3])} if row else None

    def update(self, entry_id, details=None, ts=None):
        """Change an entry in place. Returns the entry before and after, so the reply can say exactly what changed."""
        before = self.get(entry_id)
        if before is None:
            raise ValueError(f"no entry with id {entry_id}")
        new = dict(details or {})
        self.check_bounds(before["kind"], {k: v for k, v in new.items() if k in ("amount_ml", "duration_min", "start", "end")}, ts)
        when = self.at_or_before_now(ts) if ts else self.time(before["ts"])
        d = dict(before["details"])
        if before["kind"] == "feeding":
            shift = when - self.time(before["ts"])
            merged = {k: d.get(k) for k in FEEDING_FIELDS if d.get(k) is not None}
            if "method" in new and "type" not in new and d.get("type") == ("breast milk" if "breast" in str(d.get("method")) else "unknown"):
                merged.pop("type", None)
            merged.update({k: v for k, v in new.items() if k in FEEDING_FIELDS and v is not None})
            if "duration_min" not in new and d.get("start"):
                merged["start"] = (self.time(d["start"]) + shift).isoformat(timespec="seconds")
                merged.pop("duration_min", None)
            after = self._feeding(merged, when)
        elif before["kind"] == "diaper":
            wet, solid = bool(new.get("wet", d.get("wet"))), bool(new.get("solid", d.get("solid")))
            after = {"wet": wet or not solid, "solid": solid, "color": new.get("color", d.get("color"))}
        elif before["kind"] == "sleep":
            start = self.at_or_before_now(new["start"]) if new.get("start") else self.time(d["start"])
            if new.get("end"):
                when = self.at_or_before_now(new["end"])
            if when <= start:
                raise ValueError("a sleep must end after it starts")
            after = {**d, "start": start.isoformat(timespec="seconds"), "duration_min": round((when - start).total_seconds() / 60)}
        else:
            after = {"text": str(new.get("text") or new.get("note") or d.get("text") or "").strip()[:300]}
        stamp = when.isoformat(timespec="seconds")
        with self.memory.lock:
            self.memory.db.execute("update baby_log set ts = ?, details = ? where id = ?", (stamp, json.dumps(after), before["id"]))
            self.memory.db.commit()
        return {"before": before, "after": {"id": before["id"], "ts": stamp, "kind": before["kind"], "details": after}}

    def delete(self, entry_id):
        before = self.get(entry_id)
        if before is None:
            raise ValueError(f"no entry with id {entry_id}")
        with self.memory.lock:
            self.memory.db.execute("delete from baby_log where id = ?", (before["id"],))
            self.memory.db.commit()
        return {"deleted": before}

    def open_sleep(self):
        return self.memory.facts().get("_sleep_started", {}).get("value") or None

    def _sleep(self, details, when):
        action = details.get("action")
        started = self.memory.facts().get("_sleep_started", {}).get("value")
        if details.get("start") and details.get("end"):
            start, end = self.at_or_before_now(details["start"]), self.at_or_before_now(details["end"])
        elif action == "end" or (details.get("end") and not details.get("start")):
            if not started:
                raise ValueError("no sleep was started, tell me when the baby fell asleep")
            start, end = self.time(started), when
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
