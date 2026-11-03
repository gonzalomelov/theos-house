"""Theo's room temperature and humidity, from the AHT30 on the spare ESP32-S3.

The sensor is the ESPHome device "nursery-climate". Home Assistant
names its readings sensor.nursery_climate_temperature and sensor.nursery_climate_humidity. This module only reads them.

A reading counts only when it is fresh (reported in the last max_age_min) and plausible (0 to 45 °C, 0 to 100 %).
Otherwise it is a gap, and a gap is said as a gap, never as a number.

The agent quotes one range, 16 to 20 °C, from the Lullaby Trust and the NHS, always with its source. It says the
reading and where it sits against that guide. It never says the room is safe or unsafe, never says the baby is too hot
or too cold, and never tells the parent what to do with the baby. Humidity is a number only: no safe-sleep source
gives one.

Add "parenting_agent.nursery_climate:NurseryClimate" to the agent config plugins, and "nursery_climate" to
allowed_tools. Settings live under "nursery_climate", see DEFAULTS. A question about the room's temperature or humidity
("¿qué temperatura hay en el cuarto?") is answered from here by plain code in the agent loop, with no brain call.
"""
import datetime
import os
import urllib.error

from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .house import HomeAssistant

GUIDE = {"low_c": 16.0, "high_c": 20.0, "name": "Lullaby Trust and NHS",
         "url": "https://www.lullabytrust.org.uk/safer-sleep-advice/baby-room-temperature/"}
DEFAULTS = {"temperature": "sensor.nursery_climate_temperature", "humidity": "sensor.nursery_climate_humidity",
            "max_age_min": 5, "room": {"en": "Theo's room", "es": "Cuarto de Theo"}}
TEMP_RANGE = (0.0, 45.0)


def _when(state):
    stamp = state.get("last_reported") or state.get("last_updated")
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None


def _value(state, low, high):
    try:
        value = float(state.get("state"))
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None


def reading(client, now, settings=None):
    """{"temp_c", "humidity", "age_min", "ok"} from Home Assistant. ok is False for a gap: unavailable, out of range or
    older than max_age_min. A failed read is a gap too."""
    s = {**DEFAULTS, **(settings or {})}
    try:
        temp, hum = client.entity(s["temperature"]), client.entity(s["humidity"])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, AttributeError):
        return {"temp_c": None, "humidity": None, "age_min": None, "ok": False}
    stamps = [t for t in (_when(temp), _when(hum)) if t is not None]
    age = round((now - min(stamps)).total_seconds() / 60, 1) if stamps else None
    temp_c, humidity = _value(temp, *TEMP_RANGE), _value(hum, 0.0, 100.0)
    ok = temp_c is not None and humidity is not None and age is not None and age <= s["max_age_min"]
    return {"temp_c": temp_c, "humidity": humidity, "age_min": age, "ok": ok}


def against_guide(temp_c, guide=GUIDE):
    """("inside", 0.0), ("above", degrees over) or ("below", degrees under) the guide's range."""
    if temp_c > guide["high_c"]:
        return "above", round(temp_c - guide["high_c"], 1)
    if temp_c < guide["low_c"]:
        return "below", round(guide["low_c"] - temp_c, 1)
    return "inside", 0.0


def _num(value, lang):
    text = f"{value:.1f}"
    return text.replace(".", ",") if lang == "es" else text


def answer(r, lang="en", room=None, guide=GUIDE):
    """The reading as a parent reads it: the numbers, the guide and its source. Never advice."""
    room = (room or DEFAULTS["room"])[lang]
    # The site, not the page: the final guard cuts this page's path out of a reply, and the source went with it.
    link = guide["url"].split("/safer-sleep-advice")[0] + "/"
    if not r["ok"]:
        if lang == "es":
            last = f" La última fue hace {r['age_min']:.0f} min." if r["age_min"] is not None else ""
            return f"{room}: el sensor no tiene una lectura reciente.{last} No digo una temperatura que no sé."
        last = f" The last one was {r['age_min']:.0f} min ago." if r["age_min"] is not None else ""
        return f"{room}: the sensor has no recent reading.{last} I won't give a temperature I don't know."
    where, by = against_guide(r["temp_c"], guide)
    low, high = f"{guide['low_c']:.0f}", f"{guide['high_c']:.0f}"
    if lang == "es":
        place = {"inside": "está dentro de la guía", "above": f"está {_num(by, lang)} °C arriba",
                 "below": f"está {_num(by, lang)} °C abajo"}[where]
        return (f"{room}: {_num(r['temp_c'], lang)} °C y {r['humidity']:.0f} % de humedad. La guía de {guide['name'].replace(' and ', ' y ')} "
                f"para el cuarto donde duerme un bebé es de {low} a {high} °C: {place}. {link}")
    place = {"inside": "inside the guide", "above": f"{_num(by, lang)} °C above it",
             "below": f"{_num(by, lang)} °C below it"}[where]
    return (f"{room}: {_num(r['temp_c'], lang)} °C and {r['humidity']:.0f} % humidity. The {guide['name']} guide for "
            f"the room a baby sleeps in is {low} to {high} °C: {place}. {link}")


class NurseryClimate(Plugin):
    """Agent plug-in "parenting_agent.nursery_climate:NurseryClimate". Reads only: two GET states per question."""
    name = "nursery-climate"

    def __init__(self, agent, config, client=None, clock=None):
        super().__init__(agent, config)
        self.s = {**DEFAULTS, **(config.get("nursery_climate") or {})}
        house_cfg = config.get("house") or {}
        token = os.environ.get(house_cfg.get("ha_token_env", "HA_MCP_TOKEN"))
        self.client = client if client is not None else (
            HomeAssistant(house_cfg.get("ha_url", "http://127.0.0.1:18123"), token) if token else None)
        self.clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
        agent.nursery = self
        agent.tools.add(Tool("nursery_climate", "Read the temperature and humidity in Theo's room now, with the 16 to "
                             "20 °C Lullaby Trust and NHS guide and its source. Changes nothing.",
                             schema({}), lambda: self.answer("en")))

    def read(self):
        if self.client is None:
            return {"temp_c": None, "humidity": None, "age_min": None, "ok": False}
        r = reading(self.client, self.clock(), self.s)
        self.agent.bus.publish("nursery_climate", **r)
        return r

    def answer(self, lang="en"):
        return answer(self.read(), lang, self.s["room"])
