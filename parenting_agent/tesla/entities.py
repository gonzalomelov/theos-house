"""The entity ids the official Home Assistant core integration tesla_fleet creates for one car.

Home Assistant builds each id from the car's name in the Tesla app and the entity's English name in the integration's
strings.json: "Model 3" plus "Battery level" becomes sensor.model_3_battery_level. The suffixes below are those names
slugified, checked against a verbatim excerpt of homeassistant/components/tesla_fleet/strings.json in
tests/fixtures/tesla_fleet_strings.json (core commit ff2c6d4, Oct 15 2026).

Two entities the agent reads are disabled by default in Home Assistant and must be enabled once on Nov 5: Speed and
Preconditioning (see docs/tesla.md). tesla_fleet has no entity for Child Left Alone Detection.
"""
import re

# role: (domain, suffix, tesla_fleet translation key)
ENTITIES = {
    "location": ("device_tracker", "location", "location"),
    "route": ("device_tracker", "route", "route"),
    "climate": ("climate", "climate", "driver_temp"),
    "inside_temp": ("sensor", "inside_temperature", "climate_state_inside_temp"),
    "outside_temp": ("sensor", "outside_temperature", "climate_state_outside_temp"),
    "driver_temp_setting": ("sensor", "driver_temperature_setting", "climate_state_driver_temp_setting"),
    "preconditioning": ("binary_sensor", "preconditioning", "climate_state_is_preconditioning"),
    "shift_state": ("sensor", "shift_state", "drive_state_shift_state"),
    "speed": ("sensor", "speed", "drive_state_speed"),
    "battery_level": ("sensor", "battery_level", "charge_state_battery_level"),
    "battery_range": ("sensor", "battery_range", "charge_state_battery_range"),
    "charging": ("sensor", "charging", "charge_state_charging_state"),
    "status": ("binary_sensor", "status", "state"),
    "wake": ("button", "wake", "wake"),
    "defrost": ("switch", "defrost", "climate_state_defrost_mode"),
    "steering_wheel_heater": ("select", "steering_wheel_heater", "climate_state_steering_wheel_heat_level"),
    "seat_heater_front_left": ("select", "seat_heater_front_left", "climate_state_seat_heater_left"),
    "seat_heater_front_right": ("select", "seat_heater_front_right", "climate_state_seat_heater_right"),
    "seat_heater_rear_left": ("select", "seat_heater_rear_left", "climate_state_seat_heater_rear_left"),
    "seat_heater_rear_center": ("select", "seat_heater_rear_center", "climate_state_seat_heater_rear_center"),
    "seat_heater_rear_right": ("select", "seat_heater_rear_right", "climate_state_seat_heater_rear_right"),
}
SEATS = ("front_left", "front_right", "rear_left", "rear_center", "rear_right")
SEAT_LEVELS = ("off", "low", "medium", "high")
SHIFT_STATES = ("p", "d", "r", "n")
CLIMATE_PRESETS = ("off", "keep", "dog", "camp")
CLIMATE_HVAC_MODES = ("heat_cool", "off")


def slugify(text):
    """Home Assistant's entity id rule for plain ASCII names: lower case, every run of other characters becomes one _."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def entity_ids(device_name="Model 3"):
    """role -> entity id for a car with this name in the Tesla app."""
    device = slugify(device_name)
    return {role: f"{domain}.{device}_{suffix}" for role, (domain, suffix, _) in ENTITIES.items()}
