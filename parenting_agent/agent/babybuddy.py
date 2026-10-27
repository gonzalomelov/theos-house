"""Baby Buddy as the baby log (issue #2): the family's own server keeps every feed, diaper, sleep and bath.

Baby Buddy runs on the Vostro and is reached on the house network only (docs/deploy-babybuddy.md).
The agent talks to its REST API with a token read from the git-ignored env file. Each record the agent
writes carries the tag "agent", and every entry is timed at or before now, because Baby Buddy rejects
future times. Baths and free-form notes are Baby Buddy notes, a bath note starts with "Bath".
"""
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .memory import BabyLog, LOG_KINDS, parse_time

ENDPOINTS = {"feeding": "feedings", "diaper": "changes", "sleep": "sleep", "note": "notes"}
DEFAULT_FEED_MINUTES = 15


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
            if details.get("amount_ml") is not None:
                body["amount"] = float(details["amount_ml"])
            record = self.post_without_overlap("feedings", body)
        elif kind == "diaper":
            body = dict(base, time=iso(when), wet=bool(details.get("wet")), solid=bool(details.get("solid")))
            if not body["wet"] and not body["solid"]:
                body["wet"] = True
            if details.get("color"):
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
        if action == "end" and details.get("start") is None:
            timers = [t for t in self.request("GET", f"/api/timers/?child={base['child']}&limit=50")["results"] if t.get("name") == "sleep"]
            if not timers:
                raise ValueError("no sleep was started, tell me when she fell asleep")
            timer = max(timers, key=lambda t: t["start"])
            record = self.request("POST", "/api/sleep/", dict(base, start=timer["start"], end=iso(when)))
            self.request("DELETE", f"/api/timers/{timer['id']}/")
            return record
        start = at_or_before_now(details.get("start"))
        end = at_or_before_now(details.get("end")) if details.get("end") else when
        return self.request("POST", "/api/sleep/", dict(base, start=iso(start), end=iso(end)))

    def normalize(self, endpoint, record):
        tags = record.get("tags") or []
        if endpoint == "feedings":
            details = {"amount_ml": record.get("amount"), "type": record.get("type"), "method": record.get("method"),
                       "start": iso(parse_time(record["start"])), "duration_min": minutes(record.get("duration"))}
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
