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
import threading
import time
import urllib.error
import urllib.request


class HomeAssistant:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def _call(self, path, data=None):
        request = urllib.request.Request(
            self.url + path, data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST" if data is not None else "GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read() or b"null")

    def service(self, service, entity_id, data=None):
        domain, name = service.split(".", 1)
        self._call(f"/api/services/{domain}/{name}", {"entity_id": entity_id, **(data or {})})

    def state(self, entity_id):
        return self._call(f"/api/states/{entity_id}").get("state")


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
