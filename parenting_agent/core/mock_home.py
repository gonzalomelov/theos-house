"""A mock Home Assistant MCP server: the real server's tool names and answers, on a home state you can set.

The agent connects to it exactly as it connects to the real one, so its code is the same on both sides. It has no route
to the real home. moves lists every change the agent made.
"""
import json
import threading
import time

import uvicorn
from mcp.server.fastmcp import FastMCP

START = {
    "Nursery climate humidity": {"domain": "sensor", "entity_id": "sensor.nursery_climate_humidity", "state": "52.0",
                                 "unit": "%", "device_class": "humidity", "area": "Nursery"},
    "Nursery climate temperature": {"domain": "sensor", "entity_id": "sensor.nursery_climate_temperature", "state": "21.5",
                                    "unit": "°C", "device_class": "temperature", "area": "Nursery"},
    "Tapo P110 - Dehumidifier": {"domain": "switch", "entity_id": "switch.study_tapo_p110_dehumidifier", "state": "off", "area": "Study"},
    "Tapo P110 - Bottle Warmer": {"domain": "switch", "entity_id": "switch.study_tapo_p110_bottle_warmer", "state": "off", "area": "Kitchen"},
    "Study light": {"domain": "light", "entity_id": "light.study", "state": "off", "area": "Study"},
    "Kitchen Echo": {"domain": "media_player", "entity_id": "media_player.echo", "state": "idle", "area": "Kitchen"},
    "Robot vacuum": {"domain": "vacuum", "entity_id": "vacuum.robot", "state": "docked", "area": "Living room"},
}


class MockHome:
    def __init__(self, port=0):
        self.port = port
        self.lock = threading.Lock()
        self.reset()
        self.server = None

    def reset(self):
        with self.lock:
            self.devices = {name: dict(spec) for name, spec in START.items()}
            self.moves = []
            self.shopping = []

    def snapshot(self):
        with self.lock:
            return {"devices": {name: dict(spec) for name, spec in self.devices.items()}, "moves": list(self.moves), "shopping": list(self.shopping)}

    def set_state(self, entity_id, state):
        """Set a device by entity id, as the world would. The simulator's way to change a reading."""
        with self.lock:
            for spec in self.devices.values():
                if spec["entity_id"] == entity_id:
                    spec["state"] = str(state)
                    return True
        return False

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
