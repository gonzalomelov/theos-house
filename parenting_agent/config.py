"""Skill config: one JSON file per skill, so a new skill is config, not code.

A skill names what to watch (concepts), how to decide a hand is on the baby (contact), when to speak
(alarm), its routine phases, the house actions it may take and what it logs. load() fills defaults and
checks the fields the core relies on, so a bad file fails at start, not mid-routine.
"""
import copy
import json
from pathlib import Path

DEFAULTS = {
    "concepts": {"hand": "hand", "baby": "baby"},
    "contact": {
        "min_overlap": 0.3,
        "min_hand_area": 0.012,
        "baby_categories": ["teddy bear", "person"],
        "off_frames_to_alert": 1,
    },
    "alarm": {"voice_hold_s": 1.2, "clear_after_on_s": 0.5, "voice_text": "hand"},
    "process_width": 640,
    "phases": [],
    "confirm": {"provider": "none"},
    "reasoning": {"provider": "none"},
    "house": {"allowed": {}, "on_armed": [], "on_voice": [], "on_closed": []},
    "tracking": {"provider": "none", "on_closed": None},
}

REQUIRED = ("name",)


class ConfigError(ValueError):
    pass


def merge(base, override):
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def validate(skill):
    for key in REQUIRED:
        if not skill.get(key):
            raise ConfigError(f"skill config lacks '{key}'")
    contact, alarm = skill["contact"], skill["alarm"]
    if not 0 < contact["min_overlap"] <= 1:
        raise ConfigError("contact.min_overlap must be in (0, 1]")
    if contact["min_hand_area"] < 0:
        raise ConfigError("contact.min_hand_area must be >= 0")
    if contact["off_frames_to_alert"] < 1:
        raise ConfigError("contact.off_frames_to_alert must be >= 1")
    if alarm["voice_hold_s"] < 0 or alarm["clear_after_on_s"] < 0:
        raise ConfigError("alarm times must be >= 0")
    if alarm.get("confirm_wait_s") is not None and not alarm["voice_hold_s"] <= alarm["confirm_wait_s"] <= 2.5:
        raise ConfigError("alarm.confirm_wait_s must be between voice_hold_s and 2.5 s")
    house = skill["house"]
    for event in ("on_armed", "on_voice", "on_closed"):
        if not isinstance(house.get(event, []), list):
            raise ConfigError(f"house.{event} must be a list of action names")
    return skill


def load(path):
    raw = json.loads(Path(path).read_text())
    return validate(merge(DEFAULTS, raw))
