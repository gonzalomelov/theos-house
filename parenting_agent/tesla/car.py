"""The car the agent talks to, with two backends switched by config: a simulated Model 3 now, tesla_fleet later.

Both backends answer the same three calls the house layer already uses for Home Assistant (service, state,
attributes) on the same entity ids tesla_fleet creates (see entities.py). The agent only ever talks to Car, so moving
from the simulated car to the real one on Nov 5 is a config change:

    "car": {"backend": "simulated"}                                  today
    "car": {"backend": "home_assistant", "device_name": "Model 3"}   Nov 5, the token from the env file

Commands to the real car stay dry (published as car_dry, nothing sent) until "live_commands" is true, which only
Gonza turns on. Every event and every sentence about the simulated car says it is simulated.
"""
import datetime
import os
import urllib.error

from .entities import CLIMATE_PRESETS, SEAT_LEVELS, SEATS, entity_ids

DEFAULTS = {"backend": "simulated", "device_name": "Model 3", "live_commands": False,
            "ha_url": "http://127.0.0.1:18123", "ha_token_env": "HA_MCP_TOKEN",
            "weather_entity": "weather.forecast_home", "child_left_alone_entity": None, "car_seat": "rear_center",
            "simulated": {"inside_c": 12.0, "outside_c": 9.0, "battery": 78, "child_left_alone": True,
                          "location": "home", "latitude": -34.0000, "longitude": -56.0000}}
MIN_TEMP, MAX_TEMP = 15.0, 28.0


class Unavailable(Exception):
    pass


class SimulatedTesla:
    """A Model 3 that answers like Home Assistant does for the tesla_fleet entities. Time moves only with advance().

    Labeled simulated in every state it reports (attribute "simulated": true). Commands are recorded in calls.
    """
    simulated = True

    def __init__(self, device_name="Model 3", settings=None):
        s = {**DEFAULTS["simulated"], **(settings or {})}
        self.ids = entity_ids(device_name)
        self.calls = []
        self.child_left_alone = s["child_left_alone"]
        self.calendar = list(s.get("calendar") or [])
        self.outside = float(s["outside_c"])
        i = self.ids
        self.states = {
            i["location"]: (s["location"], {"latitude": s["latitude"], "longitude": s["longitude"]}),
            i["route"]: ("unknown", {}),
            i["climate"]: ("off", {"current_temperature": float(s["inside_c"]), "temperature": 21.0,
                                   "preset_mode": "off", "preset_modes": list(CLIMATE_PRESETS),
                                   "hvac_modes": ["heat_cool", "off"], "min_temp": MIN_TEMP, "max_temp": MAX_TEMP}),
            i["inside_temp"]: (float(s["inside_c"]), {"unit_of_measurement": "°C"}),
            i["outside_temp"]: (self.outside, {"unit_of_measurement": "°C"}),
            i["driver_temp_setting"]: (21.0, {"unit_of_measurement": "°C"}),
            i["preconditioning"]: ("off", {}),
            i["shift_state"]: ("unknown", {"options": ["p", "d", "r", "n"]}),
            i["speed"]: (0, {"unit_of_measurement": "km/h"}),
            i["battery_level"]: (float(s["battery"]), {"unit_of_measurement": "%"}),
            i["battery_range"]: (round(float(s["battery"]) * 4.9), {"unit_of_measurement": "km"}),
            i["charging"]: ("disconnected", {}),
            i["status"]: ("off", {}),
            i["wake"]: ("unknown", {}),
            i["defrost"]: ("off", {}),
            i["steering_wheel_heater"]: ("off", {"options": ["off", "low", "high"]}),
            "weather.forecast_home": ("cloudy", {"temperature": self.outside, "temperature_unit": "°C"}),
        }
        for seat in SEATS:
            self.states[i[f"seat_heater_{seat}"]] = ("off", {"options": list(SEAT_LEVELS)})

    def _get(self, entity_id):
        if entity_id not in self.states:
            raise KeyError(f"no entity {entity_id} in the simulated car")
        return self.states[entity_id]

    def state(self, entity_id):
        return self._get(entity_id)[0]

    def attributes(self, entity_id):
        return {**self._get(entity_id)[1], "simulated": True}

    def _set(self, entity_id, state=None, **attributes):
        old_state, old_attributes = self._get(entity_id)
        self.states[entity_id] = (old_state if state is None else state, {**old_attributes, **attributes})

    def service(self, service, entity_id, data=None):
        """The Home Assistant services tesla_fleet entities take, applied to the simulated car."""
        data, i = data or {}, self.ids
        self._get(entity_id)
        self.calls.append((service, entity_id, dict(data)))
        self._set(i["status"], "on")  # tesla_fleet wakes the car before a command
        if entity_id == i["climate"]:
            if service == "climate.turn_on" or (service == "climate.set_hvac_mode" and data.get("hvac_mode") == "heat_cool"):
                self._set(entity_id, "heat_cool")
            elif service == "climate.turn_off" or (service == "climate.set_hvac_mode" and data.get("hvac_mode") == "off"):
                self._set(entity_id, "off")
            elif service == "climate.set_temperature":
                target = min(MAX_TEMP, max(MIN_TEMP, round(float(data["temperature"]) * 2) / 2))
                self._set(entity_id, temperature=target)
                self._set(i["driver_temp_setting"], target)
            elif service == "climate.set_preset_mode":
                if data.get("preset_mode") not in CLIMATE_PRESETS:
                    raise ValueError(f"unknown preset {data.get('preset_mode')}")
                self._set(entity_id, preset_mode=data["preset_mode"])
            else:
                raise ValueError(f"{service} is not a climate service of tesla_fleet")
            self._refresh_preconditioning()
        elif service == "select.select_option":
            if data.get("option") not in self._get(entity_id)[1].get("options", []):
                raise ValueError(f"{data.get('option')} is not an option of {entity_id}")
            self._set(entity_id, data["option"])
        elif service in ("switch.turn_on", "switch.turn_off"):
            self._set(entity_id, service.rsplit("_", 1)[-1])
        elif service == "button.press":
            pass
        else:
            raise ValueError(f"{service} on {entity_id} is not something tesla_fleet offers")
        return []

    def _parked(self):
        return self.state(self.ids["shift_state"]) in (None, "unknown", "p")

    def _refresh_preconditioning(self):
        on = self.state(self.ids["climate"]) == "heat_cool" and self._parked()
        self._set(self.ids["preconditioning"], "on" if on else "off")

    def advance(self, minutes):
        """Move simulated time: the cabin heads to the target at 1 C a minute with climate on, drifts to outside without."""
        i = self.ids
        inside = float(self.state(i["inside_temp"]))
        climate_on = self.state(i["climate"]) == "heat_cool"
        for _ in range(int(minutes)):
            goal, rate = (self._get(i["climate"])[1]["temperature"], 1.0) if climate_on else (self.outside, 0.1)
            inside += max(-rate, min(rate, goal - inside))
            if climate_on:
                self._set(i["battery_level"], round(float(self.state(i["battery_level"])) - 0.05, 2))
        inside = round(inside, 1)
        self._set(i["inside_temp"], inside)
        self._set(i["climate"], current_temperature=inside)
        self._refresh_preconditioning()

    def play(self, row):
        """Apply one row of a recorded drive (shift state, speed, position) as tesla_fleet would report it."""
        i = self.ids
        shift = row.get("shift_state")
        self._set(i["shift_state"], shift if shift else "unknown")
        self._set(i["speed"], row.get("speed_kmh") or 0)
        self._set(i["status"], "on")
        if row.get("latitude") is not None:
            self._set(i["location"], row.get("zone") or "not_home", latitude=row["latitude"], longitude=row["longitude"])
        if row.get("battery") is not None:
            self._set(i["battery_level"], float(row["battery"]))
        self._refresh_preconditioning()

    def calendar_events(self, entity_id, start, end):
        """Simulated calendar entries from settings "calendar": [{"summary", "start"}], in Home Assistant's shape."""
        found = []
        for event in self.calendar:
            at = datetime.datetime.fromisoformat(event["start"])
            if start <= at <= end:
                found.append({"summary": event["summary"], "start": {"dateTime": event["start"]}})
        return found


def make_client(cfg, env=None):
    env = os.environ if env is None else env
    if cfg["backend"] == "simulated":
        return SimulatedTesla(cfg["device_name"], cfg.get("simulated"))
    if cfg["backend"] == "home_assistant":
        token = env.get(cfg["ha_token_env"])
        if not token:
            raise Unavailable(f"car backend home_assistant needs {cfg['ha_token_env']} in the env file")
        from ..house import HomeAssistant
        return HomeAssistant(cfg["ha_url"], token)
    raise Unavailable(f"unknown car backend {cfg['backend']}, expected simulated or home_assistant")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Car:
    """What the agent knows and can do with the car. The backend is the client: SimulatedTesla or Home Assistant."""

    def __init__(self, config=None, bus=None, client=None, env=None):
        self.cfg = {**DEFAULTS, **(config or {})}
        self.cfg["simulated"] = {**DEFAULTS["simulated"], **(self.cfg.get("simulated") or {})}
        self.client = client if client is not None else make_client(self.cfg, env)
        self.simulated = bool(getattr(self.client, "simulated", False))
        self.ids = entity_ids(self.cfg["device_name"])
        self.bus = bus
        self.label = ("simulated Tesla " if self.simulated else "Tesla ") + self.cfg["device_name"]

    def _publish(self, kind, **fields):
        if self.bus is not None:
            self.bus.publish(kind, car=self.label, simulated=self.simulated, **fields)

    def _state(self, role):
        try:
            value = self.client.state(self.ids[role])
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, AttributeError):
            return None
        return None if value in ("unknown", "unavailable") else value

    def outside_c(self):
        """Outside temperature from weather.forecast_home, the car's own sensor when the weather has none."""
        try:
            value = _number(self.client.attributes(self.cfg["weather_entity"]).get("temperature"))
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, AttributeError):
            value = None
        return value if value is not None else _number(self._state("outside_temp"))

    def shift_state(self):
        return self._state("shift_state")

    def read(self):
        """One snapshot of what the agent uses. Missing values are None, never guessed."""
        seats = {seat: self._state(f"seat_heater_{seat}") for seat in ("rear_left", "rear_center", "rear_right")}
        try:
            climate = self.client.attributes(self.ids["climate"])
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, AttributeError):
            climate = {}
        return {"car": self.label, "simulated": self.simulated, "location": self._state("location"),
                "shift_state": self.shift_state(), "speed": _number(self._state("speed")),
                "climate": self._state("climate"), "target_c": _number(climate.get("temperature")),
                "inside_c": _number(self._state("inside_temp")), "outside_c": self.outside_c(),
                "preconditioning": self._state("preconditioning") == "on",
                "battery": _number(self._state("battery_level")), "range": _number(self._state("battery_range")),
                "rear_seat_heaters": seats, "child_left_alone": self.child_left_alone()}

    def child_left_alone(self):
        """on, off or unknown, and where that came from. tesla_fleet has no entity for it, so the real car says unknown
        until an entity is named in child_left_alone_entity."""
        if self.simulated:
            return {"status": "on" if self.client.child_left_alone else "off", "source": "simulated flag"}
        entity = self.cfg.get("child_left_alone_entity")
        if not entity:
            return {"status": "unknown", "source": "not reported by tesla_fleet"}
        try:
            state = self.client.state(entity)
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
            return {"status": "unknown", "source": entity}
        return {"status": state if state in ("on", "off") else "unknown", "source": entity}

    def _command(self, service, role, data=None):
        entity = self.ids[role]
        if not self.simulated and not self.cfg["live_commands"]:
            self._publish("car_dry", service=service, entity_id=entity, data=data or {})
            return "dry"
        self.client.service(service, entity, data or {})
        self._publish("car_command", service=service, entity_id=entity, data=data or {},
                      at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        return "sent"

    def precondition(self, target_c, keep_seat_off=None):
        """Target temperature, then climate on. The seat under the car seat is set to off, never heated."""
        target = min(MAX_TEMP, max(MIN_TEMP, round(float(target_c) * 2) / 2))
        results = [self._command("climate.set_temperature", "climate", {"temperature": target}),
                   self._command("climate.turn_on", "climate")]
        seat = None
        if keep_seat_off in SEATS:
            try:
                seat = self._command("select.select_option", f"seat_heater_{keep_seat_off}", {"option": "off"})
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
                # A disabled seat entity must not undo the climate the parent said yes to.
                self._publish("car_error", action="seat_heater_off", error=str(error)[:200])
                seat = "failed"
        return {"target_c": target, "result": "dry" if "dry" in results else "sent", "seat_off": seat}

    def climate_off(self):
        return self._command("climate.turn_off", "climate")

    def set_seat_heater(self, seat, level):
        if seat not in SEATS or level not in SEAT_LEVELS:
            raise ValueError(f"seat one of {', '.join(SEATS)}, level one of {', '.join(SEAT_LEVELS)}")
        if seat == self.cfg["car_seat"] and level != "off":
            raise ValueError("the seat under the baby's car seat is never heated")
        return self._command("select.select_option", f"seat_heater_{seat}", {"option": level})

    def calendar_events(self, entity_id, start, end):
        return self.client.calendar_events(entity_id, start, end)
