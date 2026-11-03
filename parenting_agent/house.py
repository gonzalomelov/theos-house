"""House actions through Home Assistant REST, with an allowed list and ask-first for everything else.

Skill config house.allowed maps an action name to the Home Assistant service and entity it runs, for
example {"hold_notifications": {"service": "input_boolean.turn_on", "entity_id": "input_boolean.baby_focus",
"expect": "on"}}, with an optional "data" dict for extra service fields. house.on_armed, on_voice and on_closed list action names per moment. A name that is not
in the allowed list is published as ask_parent and never runs. After each call the state is read back a
few times, because Home Assistant can report done before the device changes.

HA_URL and HA_TOKEN come from the environment (a long-lived token, LAN or Tailscale only). Without them
the house runs dry: it publishes what it would do and touches nothing.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# The "never" list from docs/home-assistant-inventory.md. No config, tool or brain answer can run a service on these.
NEVER_ENTITIES = {"switch.shellyplusplugit_bathroom": "the bathroom Shelly plug has its own safety cut automation"}
NEVER_PATTERNS = (
    (r"^siren\.", "sirens"),
    (r"privacy", "camera privacy switches"),
    (r"record", "camera recording settings"),
    (r"tamper|alarm", "tamper and alarm triggers"),
    (r"shellyplusplugit_bathroom", "the bathroom Shelly plug"),
    (r"refrigerator", "the refrigerator settings"),
    (r"^(backup|update)\.", "backups and updates"),
    (r"scale", "the body scale"),
)


def never_reason(entity_id):
    """Why this entity is on the never list, or None when it is not."""
    if not entity_id:
        return None
    if entity_id in NEVER_ENTITIES:
        return NEVER_ENTITIES[entity_id]
    for pattern, reason in NEVER_PATTERNS:
        if re.search(pattern, entity_id):
            return reason
    return None


REJECTED_MESSAGE = "Home Assistant rejected the token, not retrying to avoid an IP ban"


class TokenRejected(urllib.error.URLError):
    """Home Assistant answered 401 or 403. A URLError, so every caller that handles a network error handles this."""

    def __init__(self, code):
        super().__init__(f"HTTP {code}: {REJECTED_MESSAGE}")
        self.code = code


# Home Assistant bans an IP after a few failed logins (ip_ban_enabled), and Docker can later hand that IP to
# another container. So after the first 401 or 403 no client in this process calls Home Assistant again.
_rejected = {"code": None}
_rejected_lock = threading.Lock()


def token_rejected():
    """The 401 or 403 code Home Assistant answered in this process, or None."""
    return _rejected["code"]


class HomeAssistant:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def _call(self, path, data=None, raw=False):
        if _rejected["code"] is not None:
            raise TokenRejected(_rejected["code"])
        request = urllib.request.Request(
            self.url + path, data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                return body if raw else json.loads(body or b"null")
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                with _rejected_lock:
                    first = _rejected["code"] is None
                    if first:
                        _rejected["code"] = error.code
                if first:
                    print(REJECTED_MESSAGE, file=sys.stderr, flush=True)
                raise TokenRejected(error.code) from None
            raise

    def ping(self):
        """GET /api/, the cheapest call that proves the token."""
        return self._call("/api/")

    def service(self, service, entity_id, data=None):
        """entity_id None calls a service without a target, for example notify.mobile_app_gonzas_iphone."""
        domain, name = service.split(".", 1)
        target = {"entity_id": entity_id} if entity_id is not None else {}
        return self._call(f"/api/services/{domain}/{name}", {**target, **(data or {})})

    def response(self, service, entity_id, data=None):
        """A read service that returns data, such as todo.get_items."""
        domain, name = service.split(".", 1)
        return self._call(f"/api/services/{domain}/{name}?return_response", {"entity_id": entity_id, **(data or {})})

    def state(self, entity_id):
        return self._call(f"/api/states/{entity_id}").get("state")

    def attributes(self, entity_id):
        return self._call(f"/api/states/{entity_id}").get("attributes") or {}

    def entity(self, entity_id):
        """The whole state object: state, attributes, last_updated and last_reported."""
        return self._call(f"/api/states/{entity_id}") or {}

    def camera_image(self, entity_id):
        """The camera's current JPEG through Home Assistant's camera proxy, as bytes in memory. Read only."""
        return self._call(f"/api/camera_proxy/{entity_id}", raw=True)

    def calendar_events(self, entity_id, start, end):
        query = urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat()})
        return self._call(f"/api/calendars/{entity_id}?{query}") or []


class House:
    def __init__(self, config, bus, client=None):
        self.cfg, self.bus = config, bus
        if client is None and os.environ.get("HA_URL") and os.environ.get("HA_TOKEN"):
            client = HomeAssistant(os.environ["HA_URL"], os.environ["HA_TOKEN"])
        self.client = client
        self.threads = []

    def on_event(self, moment):
        for name in self.cfg.get(f"on_{moment}", []):
            self.run(name, moment)

    def run(self, name, moment):
        spec = self.cfg["allowed"].get(name)
        if spec is None:
            self.bus.publish("ask_parent", action=name, moment=moment)
            return
        reason = never_reason(spec.get("entity_id"))
        if reason:
            self.bus.publish("house_refused", action=name, moment=moment, entity=spec.get("entity_id"), reason=reason)
            return
        if self.client is None:
            self.bus.publish("house_dry", action=name, moment=moment, service=spec.get("service"))
            return
        thread = threading.Thread(target=self._execute, args=(name, spec, moment), daemon=True)
        thread.start()
        self.threads.append(thread)

    def _execute(self, name, spec, moment):
        started = time.monotonic()
        try:
            if spec.get("data"):
                self.client.service(spec["service"], spec["entity_id"], spec["data"])
            else:
                self.client.service(spec["service"], spec["entity_id"])
            state = None
            for _ in range(spec.get("read_back_tries", 6)):
                state = self.client.state(spec["entity_id"])
                if spec.get("expect") is None or state == spec["expect"]:
                    break
                time.sleep(spec.get("read_back_interval_s", 0.5))
            self.bus.publish("house_done", action=name, moment=moment, state=state,
                             confirmed=spec.get("expect") in (None, state), seconds=round(time.monotonic() - started, 3))
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
            self.bus.publish("house_error", action=name, moment=moment, error=str(error)[:200])

    def close(self):
        for thread in self.threads:
            thread.join(timeout=15)
