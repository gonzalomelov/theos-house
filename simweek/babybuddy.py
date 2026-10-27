"""Minimal Baby Buddy REST client for the simulated week: load, wipe by tag, and read back.

Only entries carrying the simulated tag are ever deleted.
"""
import json
import urllib.error
import urllib.request

from simweek import TAG

ENDPOINTS = {"feeding": "feedings", "sleep": "sleep", "change": "changes", "note": "notes"}
FIELDS = {
    "feeding": ("start", "end", "type", "method", "amount", "notes", "tags"),
    "sleep": ("start", "end", "nap", "notes", "tags"),
    "change": ("time", "wet", "solid", "color", "notes", "tags"),
    "note": ("time", "note", "tags"),
}


class Client:
    def __init__(self, url, token, timeout=15):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def _call(self, method, path, body=None):
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Token " + self.token,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"{method} {path} failed with {err.code}: {err.read().decode()[:300]}") from None

    def child_id(self, first_name="Test"):
        for child in self._call("GET", "/api/children/")["results"]:
            if child["first_name"] == first_name:
                return child["id"]
        raise RuntimeError(f"no child named {first_name!r} in Baby Buddy")

    def tagged(self, kind, tag=TAG):
        found, path = [], f"/api/{ENDPOINTS[kind]}/?tags={tag}&limit=500"
        while path:
            page = self._call("GET", path)
            found += page["results"]
            path = page["next"].replace(self.url, "") if page.get("next") else None
        return found

    def wipe(self, tag=TAG):
        removed = {}
        for kind, endpoint in ENDPOINTS.items():
            rows = [r for r in self.tagged(kind, tag) if tag in (r.get("tags") or [])]
            for row in rows:
                self._call("DELETE", f"/api/{endpoint}/{row['id']}/")
            removed[kind] = len(rows)
        return removed

    def load(self, entries, child):
        counts = {kind: 0 for kind in ENDPOINTS}
        for entry in entries:
            kind = entry["kind"]
            body = {"child": child, **{k: entry[k] for k in FIELDS[kind] if k in entry and entry[k] != ""}}
            self._call("POST", f"/api/{ENDPOINTS[kind]}/", body)
            counts[kind] += 1
        return counts

    def read_back(self, tag=TAG):
        """The tagged week from the server, in the generator's entry shape, for the summary."""
        week = []
        for kind in ENDPOINTS:
            for row in self.tagged(kind, tag):
                entry = {"kind": kind, **{k: row.get(k) for k in FIELDS[kind] if k in row}}
                for k in ("start", "end", "time"):
                    if isinstance(entry.get(k), str) and entry[k].endswith("Z"):
                        entry[k] = entry[k][:-1] + "+00:00"
                week.append(entry)
        return week
