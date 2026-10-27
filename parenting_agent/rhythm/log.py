"""Read-only views of the baby log for the rhythm engine.

Entries use the simulated week's shape: a dict with a "kind" (feeding, sleep, change, note), its times as
ISO strings with an offset, and a "ref" that names where it came from, so every reminder can say what it
was computed from. The engine only reads. Writing the log is the voice log's job (issue #2), and when its
Baby Buddy client lands this module can read through it instead.
"""
import datetime
import json
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINTS = {"feeding": "feedings", "sleep": "sleep", "change": "changes", "note": "notes"}
FIELDS = {
    "feeding": ("start", "end", "type", "method", "amount", "notes", "tags"),
    "sleep": ("start", "end", "nap", "notes", "tags"),
    "change": ("time", "wet", "solid", "color", "notes", "tags"),
    "note": ("time", "note", "tags"),
}


def parse(stamp):
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(stamp)


def when(entry):
    return parse(entry.get("start") or entry["time"])


def ordered(entries, until=None):
    """Entries sorted by time, keeping only those that started at or before until."""
    rows = sorted(entries, key=when)
    return [e for e in rows if until is None or when(e) <= until]


class FixtureLog:
    """A list of entries from a JSON file, such as tests/fixtures/simweek.json."""

    def __init__(self, path):
        self.path = Path(path)

    def entries(self):
        rows = json.loads(self.path.read_text())
        for i, row in enumerate(rows):
            row.setdefault("ref", f"{row['kind']}@{row.get('start') or row['time']}#{i}")
        return rows


class BabyBuddyLog:
    """Read-only Baby Buddy client: GET requests only, one child, every kind the engine needs."""

    def __init__(self, url, token, child_name="Test", tag=None, timeout=15):
        self.url, self.token, self.child_name, self.tag, self.timeout = url.rstrip("/"), token, child_name, tag, timeout

    def _get(self, path):
        req = urllib.request.Request(self.url + path, headers={"Authorization": "Token " + self.token})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"GET {path} failed with {err.code}") from None

    def _all(self, path):
        rows = []
        while path:
            page = self._get(path)
            rows += page["results"]
            path = page["next"].replace(self.url, "") if page.get("next") else None
        return rows

    def child_id(self):
        for child in self._all("/api/children/"):
            if child["first_name"] == self.child_name:
                return child["id"]
        raise RuntimeError(f"no child named {self.child_name!r} in Baby Buddy")

    def entries(self):
        child = self.child_id()
        rows = []
        for kind, endpoint in ENDPOINTS.items():
            for row in self._all(f"/api/{endpoint}/?child={child}&limit=500"):
                if self.tag and self.tag not in (row.get("tags") or []):
                    continue
                entry = {"kind": kind, "ref": f"{endpoint}/{row['id']}",
                         **{k: row.get(k) for k in FIELDS[kind] if k in row}}
                rows.append(entry)
        return rows
