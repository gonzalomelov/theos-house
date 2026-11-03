"""A mock Home Assistant MCP server: the real server's tool names and answers, on a home state you can set.

The agent connects to it exactly as it connects to the real one, so its code is the same on both sides. It has no route
to the real home. moves lists every change the agent made.
"""
import datetime
import json
import threading
import time

import uvicorn
from mcp.server.fastmcp import FastMCP

START = {
    "Nursery climate humidity": {"domain": "sensor", "entity_id": "sensor.nursery_climate_humidity", "state": "52.0",
                                 "unit": "%", "device_class": "humidity", "area": "Theo's room"},
    "Nursery climate temperature": {"domain": "sensor", "entity_id": "sensor.nursery_climate_temperature", "state": "21.5",
                                    "unit": "°C", "device_class": "temperature", "area": "Theo's room"},
    "Tapo P110 - Dehumidifier": {"domain": "switch", "entity_id": "switch.study_tapo_p110_dehumidifier", "state": "off", "area": "Theo's room"},
    "Tapo P110 - Bottle Warmer": {"domain": "switch", "entity_id": "switch.study_tapo_p110_bottle_warmer", "state": "off", "area": "Kitchen"},
    "Desk light": {"domain": "light", "entity_id": "light.desk", "state": "off", "area": "Theo's room"},
    "Kitchen Echo": {"domain": "media_player", "entity_id": "media_player.echo", "state": "idle", "area": "Kitchen"},
    "Robot vacuum": {"domain": "vacuum", "entity_id": "vacuum.robot", "state": "docked", "area": "Living room"},
}


# The real warmer plug turns itself off after 30 minutes, and a vacuum finishes and docks.
AUTO_END = {"Tapo P110 - Bottle Warmer": ("on", "off", 30), "Robot vacuum": ("cleaning", "docked", 60)}
# The room answers over time: a running dehumidifier brings the air down, and the temperature drifts back to normal.
DRY_PER_HOUR, DRY_FLOOR, ROOM_TEMP, TEMP_PER_HOUR = 8.0, 40.0, 21.5, 1.0


class MockHome:
    def __init__(self, port=0):
        self.port = port
        self.lock = threading.Lock()
        self.clock = None
        self.reset()
        self.server = None

    def reset(self):
        with self.lock:
            self.devices = {name: dict(spec) for name, spec in START.items()}
            self.moves = []
            self.shopping = []
            self.timers = {}
            self.ticked = None

    def snapshot(self):
        with self.lock:
            return {"devices": {name: dict(spec) for name, spec in self.devices.items()}, "moves": list(self.moves), "shopping": list(self.shopping)}

    def set_state(self, entity_id, state, at=None):
        """Set a device by entity id, as the world would. The simulator's way to change a reading. at is the moment it happened."""
        with self.lock:
            for name, spec in self.devices.items():
                if spec["entity_id"] == entity_id:
                    spec["state"] = str(state)
                    self.arm(name, str(state), at)
                    return True
        return False

    def arm(self, name, state, at=None):
        end = AUTO_END.get(name)
        if end and (at or self.clock):
            if state == end[0]:
                self.timers[name] = (at or self.clock()) + datetime.timedelta(minutes=end[2])
            else:
                self.timers.pop(name, None)

    def tick(self, moment):
        """The devices that end by themselves, on the clock the home is living."""
        with self.lock:
            for name, until in list(self.timers.items()):
                if until <= moment:
                    self.devices[name]["state"] = AUTO_END[name][1]
                    del self.timers[name]
                    self.moves.append({"tool": "ended by itself", "name": name, "state": AUTO_END[name][1], "at": time.time()})
            self.drift(moment)

    def drift(self, moment):
        hours = (moment - self.ticked).total_seconds() / 3600 if self.ticked else 0
        if self.ticked is None or hours > 0:
            self.ticked = moment
        if hours <= 0:
            return
        humid, temp = self.devices["Nursery climate humidity"], self.devices["Nursery climate temperature"]
        try:
            if self.devices["Tapo P110 - Dehumidifier"]["state"] == "on":
                humid["state"] = f"{max(DRY_FLOOR, float(humid['state']) - DRY_PER_HOUR * hours):.1f}"
            now = float(temp["state"])
            step = min(abs(now - ROOM_TEMP), TEMP_PER_HOUR * hours)
            temp["state"] = f"{now + (step if now < ROOM_TEMP else -step):.1f}"
        except ValueError:  # a reading set to something odd stays as it is
            pass

    def state(self, entity_id):
        with self.lock:
            return next((spec["state"] for spec in self.devices.values() if spec["entity_id"] == entity_id), None)

    def live_context(self, area=None, name=None, domain=None):
        domains = [domain] if isinstance(domain, str) else domain
        with self.lock:
            found = [(n, s) for n, s in self.devices.items()
                     if (not area or s["area"].lower() == area.lower()) and (not name or n.lower() == name.lower())
                     and (not domains or s["domain"] in domains)]
        if area and not any(s["area"].lower() == area.lower() for s in START.values()):
            return {"error": f"Area '{area}' does not exist"}
        if name and not found:
            return {"error": f"No exposed entities matched name '{name}'"}
        lines = ["Live Context: An overview of the areas and the devices in this smart home:"]
        for n, s in found:
            lines += [f"- names: {n}", f"  domain: {s['domain']}", f"  areas: {s['area']}", f"  state: '{s['state']}'"]
            if s.get("unit"):
                lines += ["  attributes:", f"    unit_of_measurement: {s['unit']}", f"    device_class: {s['device_class']}"]
        return {"result": "\n".join(lines)}

    def move(self, tool, name, state):
        with self.lock:
            spec = self.devices.get(name)
            if spec is None:
                return {"error": f"No exposed entities matched name '{name}'"}
            spec["state"] = state
            self.arm(name, state)
            self.moves.append({"tool": tool, "name": name, "state": state, "at": time.time()})
            return {"speech": {}, "response_type": "action_done",
                    "data": {"success": [{"name": name, "type": "entity", "id": spec["entity_id"]}], "failed": []}}

    def mcp(self):
        mcp = FastMCP("home-assistant", stateless_http=True, json_response=True, streamable_http_path="/api/mcp")

        @mcp.tool(name="homeassistant__GetLiveContext", description="Provides real-time information about the CURRENT state, value, or mode of devices, sensors, entities, or areas.")
        def live(area: str = None, name: str = None, domain: list = None) -> str:
            return json.dumps(self.live_context(area, name, domain))

        @mcp.tool(name="intent__HassTurnOn", description="Turns on/opens/presses a device or entity.")
        def turn_on(name: str = None, area: str = None, floor: str = None, domain: list = None, device_class: list = None) -> str:
            return json.dumps(self.move("HassTurnOn", name, "on"))

        @mcp.tool(name="intent__HassTurnOff", description="Turns off/closes a device or entity.")
        def turn_off(name: str = None, area: str = None, floor: str = None, domain: list = None, device_class: list = None) -> str:
            return json.dumps(self.move("HassTurnOff", name, "off"))

        @mcp.tool(name="vacuum__HassVacuumStart", description="Starts a vacuum.")
        def vacuum_start(name: str = None, area: str = None, floor: str = None) -> str:
            return json.dumps(self.move("HassVacuumStart", name or "Robot vacuum", "cleaning"))

        @mcp.tool(name="vacuum__HassVacuumReturnToBase", description="Returns a vacuum to base.")
        def vacuum_home(name: str = None, area: str = None, floor: str = None) -> str:
            return json.dumps(self.move("HassVacuumReturnToBase", name or "Robot vacuum", "docked"))

        @mcp.tool(name="todo__HassListAddItem", description="Add an item to a todo list.")
        def add_item(item: str, name: str = "Shopping List") -> str:
            with self.lock:
                self.shopping.append(item)
            return json.dumps({"speech": {}, "response_type": "action_done", "data": {"success": [{"name": name, "type": "entity"}], "failed": []}})

        return mcp

    def start(self):
        config = uvicorn.Config(self.mcp().streamable_http_app(), host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(100):
            if self.server.started:
                self.port = self.server.servers[0].sockets[0].getsockname()[1]
                return self
            time.sleep(0.05)
        raise RuntimeError("the mock home did not start")

    def stop(self):
        if self.server:
            self.server.should_exit = True

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/api/mcp"
