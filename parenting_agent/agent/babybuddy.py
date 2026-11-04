"""Baby Buddy as the baby log (issue #2): the family's own server keeps every feed, diaper, sleep and bath.

Baby Buddy runs on the Vostro and is reached on the house network only (docs/deploy-babybuddy.md).
The agent talks to its REST API with a token read from the git-ignored env file. Each record the agent
writes carries the tag "agent", and every entry is timed at or before now, because Baby Buddy rejects
future times. Baths and free-form notes are Baby Buddy notes, a bath note starts with "Bath".
"""
import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .memory import BabyLog, LOG_KINDS, parse_time, place_sleep, start_after_feeds

ENDPOINTS = {"feeding": "feedings", "diaper": "changes", "sleep": "sleep", "note": "notes"}
DEFAULT_FEED_MINUTES = 15
# The stool colours a Baby Buddy change can hold.
COLORS = ("black", "brown", "green", "yellow")
OPEN_SLEEP_ID = "open-sleep"
# A feed whose length nobody said is stored with the default length, and says so in its notes, so no reply ever states
# "15 min" the parent did not say (held-out run-1: "Logged the 13:15 bottle of 60 ml, formula of 15 min").
LENGTH_NOT_SAID = "length not said"
# Baby Buddy needs a milk type: a bottle with none said is stored as formula and says so, so no reply claims formula.
TYPE_NOT_SAID = "milk type not said"


class BabyBuddyError(RuntimeError):
    """Baby Buddy refused or could not be reached. The tool reports it to the brain instead of crashing the agent."""


def iso(moment):
    return moment.astimezone().isoformat(timespec="seconds")


def at_or_before_now(ts):
    """The given instant, or now when it is missing or in the future."""
    current = datetime.datetime.now().astimezone()
    moment = parse_time(ts) if ts else None
    return current if moment is None or moment > current else moment


def minutes(duration):
    """Baby Buddy durations look like "01:53:00" or "1 02:00:00"."""
    if not duration:
        return None
    days, _, clock = duration.rpartition(" ")
    hours, mins, secs = (float(part) for part in clock.split(":"))
    return round((int(days or 0) * 24 * 60) + hours * 60 + mins + secs / 60)


class BabyBuddyLog(BabyLog):
    name = "babybuddy"

    def __init__(self, url, token, child, tags=("agent",), exclude_tags=(), timeout=10):
        self.url, self.token, self.child_key = url.rstrip("/"), token, child
        self.tags, self.exclude_tags, self.timeout = list(tags), set(exclude_tags), timeout
        self.child_id = None
        self.destination = urllib.parse.urlparse(self.url).hostname

    @classmethod
    def from_config(cls, config):
        url, token = os.environ.get(config.get("url_env", "BABYBUDDY_URL")), os.environ.get(config.get("token_env", "BABYBUDDY_TOKEN"))
        if not url or not token:
            raise BabyBuddyError("babybuddy: BABYBUDDY_URL and BABYBUDDY_TOKEN must be set in the env file")
        return cls(url, token, config.get("child", "test-baby"), config.get("tags", ["agent"]), config.get("exclude_tags", []))

    def request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method, headers={
            "Authorization": f"Token {self.token}", "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raise BabyBuddyError(f"Baby Buddy {method} {path.split('?')[0]}: HTTP {error.code} {error.read()[:300].decode(errors='replace')}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise BabyBuddyError(f"Baby Buddy unreachable: {error}") from error

    def child(self):
        if self.child_id is None:
            for item in self.request("GET", "/api/children/?limit=50")["results"]:
                full = f"{item['first_name']} {item['last_name']}".strip().lower()
                if self.child_key.lower() in (item["slug"], full, item["first_name"].lower()):
                    self.child_id = item["id"]
                    break
            else:
                raise BabyBuddyError(f"Baby Buddy has no child named {self.child_key}")
        return self.child_id

    def add(self, kind, details, ts=None):
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind}, expected one of {', '.join(LOG_KINDS)}")
        details = dict(details or {})
        when = at_or_before_now(ts or details.get("end") or details.get("time"))
        base = {"child": self.child(), "tags": self.tags}
        if kind == "feeding":
            method = details.get("method") or "bottle"
            milk = details.get("type") or ("breast milk" if "breast" in method else "formula")
            length = details.get("duration_min") or DEFAULT_FEED_MINUTES
            start = at_or_before_now(details.get("start")) if details.get("start") else when - datetime.timedelta(minutes=float(length))
            body = dict(base, start=iso(start), end=iso(when), type=milk, method=method)
            unsaid = [LENGTH_NOT_SAID] if not details.get("duration_min") and not details.get("start") else []
            if not details.get("type") and "breast" not in method:
                unsaid.append(TYPE_NOT_SAID)
            unsaid += [str(details["note"])] if details.get("note") else []
            if unsaid:
                body["notes"] = ", ".join(unsaid)
            if details.get("amount_ml") is not None:
                body["amount"] = float(details["amount_ml"])
            record = self.post_without_overlap("feedings", body)
        elif kind == "diaper":
            body = dict(base, time=iso(when), wet=bool(details.get("wet")), solid=bool(details.get("solid")))
            if not body["wet"] and not body["solid"]:
                body["wet"] = True
            if details.get("color") in COLORS:
                body["color"] = details["color"]
            record = self.request("POST", "/api/changes/", body)
        elif kind == "sleep":
            record = self.add_sleep(base, details, when)
            if record.get("timer"):
                return record
        else:
            text = details.get("text") or details.get("note") or ""
            if kind == "bath" and not text.lower().startswith("bath"):
                text = f"Bath. {text}".strip()
            record = self.request("POST", "/api/notes/", dict(base, note=text or "Note", time=iso(when)))
        endpoint = "notes" if kind in ("bath", "note") else ENDPOINTS[kind]
        return self.normalize(endpoint, record)

    def post_without_overlap(self, endpoint, body):
        """Baby Buddy refuses a feed or sleep that overlaps the previous one. The estimated start (from a default
        length) is what overlaps, so start it one second after the previous one ends and try once more."""
        try:
            return self.request("POST", f"/api/{endpoint}/", body)
        except BabyBuddyError as error:
            if not any(word in str(error).lower() for word in ("intersects", "overlap")):
                raise
            latest = self.request("GET", f"/api/{endpoint}/?child={body['child']}&limit=1&ordering=-end")["results"]
            if not latest:
                raise
            start = parse_time(latest[0]["end"]) + datetime.timedelta(seconds=1)
            if start >= parse_time(body["end"]):
                raise
            return self.request("POST", f"/api/{endpoint}/", dict(body, start=iso(start)))

    def add_sleep(self, base, details, when):
        """Sleep with a start and an end is one record. "asleep" starts a timer, "awake" closes it into a record."""
        action = details.get("action")
        if details.get("start") and details.get("end"):
            action = "record"
        if action == "start" or (details.get("start") is None and details.get("end") is None and action != "end"):
            timer = self.request("POST", "/api/timers/", {"child": base["child"], "name": "sleep", "start": iso(when)})
            return {"timer": timer["id"], "kind": "sleep", "ts": iso(when), "details": {"action": "start", "timer_id": timer["id"]}}
        if action == "end" and details.get("start"):
            # The open sleep closed with the length the parent said: the record starts at end minus that length.
            for timer in self.request("GET", f"/api/timers/?child={base['child']}&limit=50")["results"]:
                if timer.get("name") == "sleep":
                    self.request("DELETE", f"/api/timers/{timer['id']}/")
            start, end = self.placed(at_or_before_now(details["start"]), when)
            return self.request("POST", "/api/sleep/", dict(base, start=iso(start), end=iso(end)))
        if action == "end" and details.get("start") is None:
            timers = [t for t in self.request("GET", f"/api/timers/?child={base['child']}&limit=50")["results"] if t.get("name") == "sleep"]
            if not timers:
                raise ValueError("no sleep was started, tell me when she fell asleep")
            timer = max(timers, key=lambda t: t["start"])
            start = self.after_feeds(parse_time(timer["start"]), when)
            record = self.request("POST", "/api/sleep/", dict(base, start=iso(start), end=iso(when)))
            self.request("DELETE", f"/api/timers/{timer['id']}/")
            return record
        start = at_or_before_now(details.get("start"))
        end = at_or_before_now(details.get("end")) if details.get("end") else when
        start, end = self.placed(start, end)
        return self.request("POST", "/api/sleep/", dict(base, start=iso(start), end=iso(end)))

    def placed(self, start, end):
        """A sleep told with its start and end (or its length) keeps that length and never spans a feed."""
        return place_sleep(start, end, self.feed_spans(start))

    def after_feeds(self, start, end):
        """A sleep never spans a feed in the log: it starts after the last one inside it (round b5)."""
        return start_after_feeds(start, end, self.feed_spans(start))

    def feed_spans(self, start):
        feeds = []
        for e in self.entries("feeding", iso(start - datetime.timedelta(hours=3)), 50):
            try:
                feeds.append((parse_time((e.get("details") or {}).get("start") or e["ts"]), parse_time(e["ts"])))
            except (KeyError, TypeError, ValueError):
                continue
        return feeds

    def normalize(self, endpoint, record):
        tags = record.get("tags") or []
        if endpoint == "feedings":
            details = {"amount_ml": record.get("amount"), "type": record.get("type"), "method": record.get("method"),
                       "start": iso(parse_time(record["start"])), "duration_min": minutes(record.get("duration"))}
            unsaid = str(record.get("notes") or "")
            if LENGTH_NOT_SAID in unsaid:
                details["duration_min"] = None
            if TYPE_NOT_SAID in unsaid and "breast" not in str(record.get("method")):
                details["type"] = "unknown"
            said = [n for n in unsaid.split(", ") if n and n not in (LENGTH_NOT_SAID, TYPE_NOT_SAID)]
            if said:
                details["note"] = ", ".join(said)
            return {"id": record["id"], "kind": "feeding", "ts": iso(parse_time(record["end"])), "details": details, "tags": tags}
        if endpoint == "changes":
            details = {"wet": record.get("wet"), "solid": record.get("solid"), "color": record.get("color") or None}
            return {"id": record["id"], "kind": "diaper", "ts": iso(parse_time(record["time"])), "details": details, "tags": tags}
        if endpoint == "sleep":
            details = {"start": iso(parse_time(record["start"])), "duration_min": minutes(record.get("duration")), "nap": record.get("nap")}
            return {"id": record["id"], "kind": "sleep", "ts": iso(parse_time(record["end"])), "details": details, "tags": tags}
        note = record.get("note") or ""
        kind = "bath" if note.lower().startswith("bath") else "note"
        return {"id": record["id"], "kind": kind, "ts": iso(parse_time(record["time"])), "details": {"text": note}, "tags": tags}

    def get(self, kind, record_id):
        """Read one record back from Baby Buddy, as the KR evidence needs."""
        endpoint = "notes" if kind in ("bath", "note") else ENDPOINTS[kind]
        return self.normalize(endpoint, self.request("GET", f"/api/{endpoint}/{record_id}/"))

    # Baby Buddy numbers each endpoint on its own, so feed 12 and diaper 12 are two entries: an edit or a delete names
    # the kind with the id (tools.edit_tools passes it).
    kind_ids = True

    def sleep_timer(self):
        """The newest running sleep timer, or None: a sleep the parent started and has not ended."""
        timers = [t for t in self.request("GET", f"/api/timers/?child={self.child()}&limit=50")["results"]
                  if t.get("name") == "sleep"]
        return max(timers, key=lambda t: t["start"]) if timers else None

    def open_sleep(self):
        """The start of the open sleep as an ISO time, or None. Held-out run-1: with no open sleep read, "sigue dormido"
        started a second sleep and "se despertó llorando" was kept as a note with the sleep left open."""
        timer = self.sleep_timer()
        return iso(parse_time(timer["start"])) if timer else None

    def open_sleep_entry(self):
        timer = self.sleep_timer()
        if timer is None:
            return None
        return {"id": OPEN_SLEEP_ID, "kind": "sleep", "ts": iso(parse_time(timer["start"])),
                "details": {"action": "start"}, "timer": timer["id"]}

    def find(self, entry_id=None, kind=None, at=None, last=None):
        """One entry, by id (with its kind, ids repeat across kinds), by kind and local time HH:MM, or the last one."""
        if str(entry_id) == OPEN_SLEEP_ID:
            entry = self.open_sleep_entry()
            if entry is None:
                raise ValueError("no sleep is open")
            return entry
        if entry_id is not None:
            if kind in LOG_KINDS:
                try:
                    entry = self.get(kind, int(entry_id))
                except (BabyBuddyError, TypeError, ValueError) as error:
                    raise ValueError(f"no {kind} with id {entry_id}") from error
                if entry["kind"] != kind and {entry["kind"], kind} != {"bath", "note"}:
                    raise ValueError(f"entry {entry_id} is a {entry['kind']}, not a {kind}")
                return entry
            found = [e for e in self.entries(None, None, 200) if str(e["id"]) == str(entry_id)]
            if len(found) != 1:
                raise ValueError(f"name the kind of entry {entry_id}" if found else f"no entry with id {entry_id}")
            return found[0]
        items = self.entries(kind, None, 200)
        if at:
            match = re.match(r"^\s*(\d{1,2})[:.h](\d{2})\s*$", str(at))
            if not match:
                raise ValueError("at must be a local time like 01:30")
            wanted = f"{int(match.group(1)):02d}:{match.group(2)}"
            items = [e for e in items if wanted in (e["ts"][11:16], str(e["details"].get("start") or "")[11:16])]
        elif not last:
            raise ValueError("name the entry by id, by kind and at, or by last")
        if not items:
            raise ValueError("no such entry in the log")
        return items[-1]

    def update(self, entry_id, details=None, ts=None, kind=None):
        """Change an entry in place, as the parent corrected it (held-out run-1: 21 of 24 corrections were left wrong,
        the log could not change an entry). Returns the entry before and after, so the reply says exactly what changed.
        ts moves the entry (a feed keeps its length), details holds only the fields that change."""
        before = self.find(entry_id, kind)
        new = dict(details or {})
        self.check_bounds(before["kind"], {k: v for k, v in new.items()
                                           if k in ("amount_ml", "duration_min") and v is not None}, ts)
        if before["id"] == OPEN_SLEEP_ID:
            start = new.get("start") or ts
            if not start:
                raise ValueError("an open sleep can only move its start")
            self.request("PATCH", f"/api/timers/{before['timer']}/", {"start": iso(at_or_before_now(start))})
            return {"before": self.public(before), "after": self.public(self.open_sleep_entry())}
        endpoint = "notes" if before["kind"] in ("bath", "note") else ENDPOINTS[before["kind"]]
        record = self.request("GET", f"/api/{endpoint}/{before['id']}/")
        body = {}
        if before["kind"] == "feeding":
            start, end = parse_time(record["start"]), parse_time(record["end"])
            length = end - start
            if new.get("duration_min"):
                length = datetime.timedelta(minutes=float(new["duration_min"]))
            if ts:
                end = at_or_before_now(ts)
            if new.get("duration_min") or ts:
                body.update(start=iso(end - length), end=iso(end))
            notes = str(record.get("notes") or "").split(", ")
            unsaid = [n for n in notes if n in (LENGTH_NOT_SAID, TYPE_NOT_SAID)]
            said = [str(new["note"])] if new.get("note") else [n for n in notes if n and n not in unsaid]
            if new.get("duration_min") and LENGTH_NOT_SAID in unsaid:
                unsaid.remove(LENGTH_NOT_SAID)
            old_method = str(record.get("method") or "bottle")
            method = str(new.get("method") or old_method)
            if new.get("method"):
                body["method"] = method
            milk = new.get("type")
            if "breast" in method and "breast" not in old_method:
                # A bottle that was a breast feed keeps no ml, and its milk is the breast's (round 5).
                milk = milk or "breast milk"
                if new.get("amount_ml") is None:
                    body["amount"] = None
            elif "breast" not in method and "breast" in old_method:
                milk = milk or "formula"
            if milk in ("formula", "breast milk", "fortified breast milk"):
                body["type"] = milk
                if TYPE_NOT_SAID in unsaid:
                    unsaid.remove(TYPE_NOT_SAID)
                if not new.get("type") and "breast" not in method:
                    unsaid.append(TYPE_NOT_SAID)  # a breast feed that was a bottle: Baby Buddy needs a type, none said
            if new.get("duration_min") or "type" in body or new.get("note"):
                body["notes"] = ", ".join(unsaid + said)
            if new.get("amount_ml") is not None:
                body["amount"] = float(new["amount_ml"])
        elif before["kind"] == "diaper":
            wet = bool(new["wet"]) if new.get("wet") is not None else bool(record.get("wet"))
            solid = bool(new["solid"]) if new.get("solid") is not None else bool(record.get("solid"))
            body.update(wet=wet or not solid, solid=solid)
            if "color" in new:
                body["color"] = new["color"] if new["color"] in COLORS else ""
            if ts:
                body["time"] = iso(at_or_before_now(ts))
        elif before["kind"] == "sleep":
            start = at_or_before_now(new["start"]) if new.get("start") else parse_time(record["start"])
            moved = new.get("end") or ts
            end = at_or_before_now(moved) if moved else parse_time(record["end"])
            if end <= start:
                raise ValueError("a sleep must end after it starts")
            body.update(start=iso(start), end=iso(end))
        else:
            text = str(new.get("text") or new.get("note") or "").strip()
            if text:
                body["note"] = f"Bath. {text}" if before["kind"] == "bath" and not text.lower().startswith("bath") else text
            if ts:
                body["time"] = iso(at_or_before_now(ts))
        if not body:
            return {"before": before, "after": before}
        after = self.normalize(endpoint, self.request("PATCH", f"/api/{endpoint}/{before['id']}/", body))
        return {"before": before, "after": after}

    def delete(self, entry_id, kind=None):
        """Remove an entry the parent asked to delete, or an open sleep that never happened. Returns what was removed."""
        before = self.find(entry_id, kind)
        if before["id"] == OPEN_SLEEP_ID:
            self.request("DELETE", f"/api/timers/{before['timer']}/")
        else:
            endpoint = "notes" if before["kind"] in ("bath", "note") else ENDPOINTS[before["kind"]]
            self.request("DELETE", f"/api/{endpoint}/{before['id']}/")
        return {"deleted": self.public(before)}

    @staticmethod
    def public(entry):
        """An entry as the agent reads it, without the timer id the log keeps for itself."""
        return {k: v for k, v in entry.items() if k != "timer"} if entry else entry

    def entries(self, kind=None, since=None, limit=50):
        kinds = [kind] if kind else list(LOG_KINDS)
        endpoints = {"notes" if k in ("bath", "note") else ENDPOINTS[k] for k in kinds}
        order = {"feedings": "-end", "changes": "-time", "sleep": "-end", "notes": "-time"}
        since_time = parse_time(since) if since else None
        items = []
        for endpoint in endpoints:
            page = self.request("GET", f"/api/{endpoint}/?child={self.child()}&limit={max(limit, 1)}&ordering={order[endpoint]}")
            for record in page["results"]:
                entry = self.normalize(endpoint, record)
                if entry["kind"] not in kinds or self.exclude_tags & set(entry["tags"]):
                    continue
                if since_time and parse_time(entry["ts"]) < since_time:
                    continue
                items.append(entry)
        items.sort(key=lambda e: parse_time(e["ts"]))
        return items[-limit:]
