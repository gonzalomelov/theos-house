"""Effortless tracking: the routine logs itself into Baby Buddy on the family's own server.

A closed changing-table skill becomes a diaper change with its start and end, a bath becomes a note, and
voice entries ("bottle 120 ml", "dirty", "asleep") become feedings, changes and sleep. Baby Buddy rejects
times in the future, so entries are logged at or after the event.

BABY_BUDDY_URL and BABY_BUDDY_TOKEN (or BABYBUDDY_URL and BABYBUDDY_TOKEN) come from the environment (LAN or Tailscale only, never public).
Without them the tracker runs dry and only publishes what it would log.
"""
import datetime
import json
import os
import urllib.error
import urllib.request


def iso(moment):
    return moment.astimezone().isoformat(timespec="seconds")


class BabyBuddy:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def post(self, path, data):
        request = urllib.request.Request(
            f"{self.url}/api/{path}/", data=json.dumps(data).encode(),
            headers={"Authorization": f"Token {self.token}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def get(self, path, entry_id):
        request = urllib.request.Request(f"{self.url}/api/{path}/{entry_id}/", headers={"Authorization": f"Token {self.token}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())


def parse_voice(text):
    """Voice entries the agent understands without a model. Returns (kind, fields) or None."""
    words = text.lower().replace(",", " ").split()
    if "bottle" in words:
        amount = next((float(w) for w in words if w.replace(".", "", 1).isdigit()), None)
        return "feedings", {"type": "formula", "method": "bottle", "amount": amount}
    if words and words[0] in ("wet", "dirty", "solid"):
        return "changes", {"wet": words[0] == "wet", "solid": words[0] in ("dirty", "solid")}
    if "asleep" in words:
        return "sleep_start", {}
    if "awake" in words:
        return "sleep_end", {}
    return None


class Tracker:
    def __init__(self, config, bus, client=None):
        self.cfg, self.bus = config, bus
        url = os.environ.get("BABY_BUDDY_URL") or os.environ.get("BABYBUDDY_URL")
        token = os.environ.get("BABY_BUDDY_TOKEN") or os.environ.get("BABYBUDDY_TOKEN")
        if client is None and url and token:
            client = BabyBuddy(url, token)
        self.client, self.child = client, config.get("child_id", 1)

    def log(self, path, data):
        data = {"child": self.child, **data}
        if self.client is None:
            self.bus.publish("track_dry", entry=path, data=data)
            return
        try:
            saved = self.client.post(path, data)
            self.bus.publish("tracked", entry=path, id=saved.get("id"))
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            self.bus.publish("track_error", entry=path, error=str(error)[:200])

    def read(self, path, entry_id):
        """One entry as Baby Buddy stores it, or None when the tracker runs dry or the read fails."""
        if self.client is None or entry_id is None:
            return None
        try:
            return self.client.get(path, entry_id)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            self.bus.publish("track_error", entry=path, error=str(error)[:200])
            return None

    def skill_closed(self, skill, started, ended, content=None):
        """content is the diaper's {"wet": bool, "solid": bool} when the parent said it, both false otherwise."""
        kind = self.cfg.get("on_closed")
        content = content or {}
        if kind == "change":
            self.log("changes", {"time": iso(ended), "wet": bool(content.get("wet")), "solid": bool(content.get("solid")),
                                 "notes": f"logged by {skill}, {iso(started)} to {iso(ended)}"})
        elif kind == "bath":
            self.log("notes", {"note": f"bath {iso(started)} to {iso(ended)}", "time": iso(ended)})

    def voice(self, text, now=None):
        parsed = parse_voice(text)
        if parsed is None:
            self.bus.publish("track_unknown", text=text)
            return
        kind, fields = parsed
        stamp = iso(now or datetime.datetime.now(datetime.timezone.utc))
        if kind == "feedings":
            self.log("feedings", {"start": stamp, "end": stamp, **{k: v for k, v in fields.items() if v is not None}})
        elif kind == "changes":
            self.log("changes", {"time": stamp, **fields})
        else:
            self.bus.publish("track_timer", action=kind, time=stamp)
