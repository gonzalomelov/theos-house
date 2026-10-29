"""Home Assistant tools for the agent (issue #9), behind the action policy in docs/home-assistant-inventory.md.

Three lists, kept in code:
- Alone: the tools in ALONE. Add them to the agent's allowed_tools and they run on the brain's word.
- Only with Gonza's yes: the tools in ASK_FIRST. They are never on the allowed list (the plug-in removes them if a
  config adds them), so the agent asks first and only the parent's yes runs them.
- Never: entities in house.never_reason (camera privacy, sirens, the bathroom Shelly plug, the refrigerator and the
  rest). Every call is checked against it and refused, whatever asked for it.

Nothing changes in the house until "house": {"live": true} is set in the agent config. That switch is off by default
and only Gonza turns it on. With it off, or without a token, every action is a dry run that says what it would do.
Reading states (house_status) changes nothing and runs whenever a token is there. Every call, dry, live, refused or
failed, is published as a "house_call" event, so it lands in data/events.jsonl.

Add "parenting_agent.house_tools:HouseTools" to the agent config plugins. Settings live under "house", see DEFAULTS.
A tool name another plug-in registered first is left to that plug-in (the house plan's vacuum tools, #29).
"""
import os
import threading
import time
import urllib.error

from .agent import rules
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .house import HomeAssistant, never_reason

DEFAULTS = {"live": False, "ha_url": "http://127.0.0.1:18123", "ha_token_env": "HA_MCP_TOKEN",
            "announce_volume": 0.2, "restore_after_s": 10, "read_back_tries": 6, "read_back_interval_s": 0.5}

STUDY_LIGHT = "light.wiz_824512_192_0_2_10"
ECHO_DND = "switch.gonza_s_echo_dot_do_not_disturb"
ECHO_ANNOUNCE = "notify.gonza_s_echo_dot_announce"
ECHO_PLAYER = "media_player.gonza_s_echo_dot"
PUSH_GONZA = "notify.mobile_app_gonzas_iphone"
VACUUM = "vacuum.xiaomi_ov71gl_0681_robot_cleaner"
TVS = {"living room": "media_player.lg_webos_tv_oled55b3psa", "bedroom": "media_player.43_crystal_uhd_un43u8000fgxpr"}
LISTS = {"to-do": "todo.family_to_do_list", "shopping": "todo.shopping_list"}
FLOODLIGHTS = {"living room": "light.tapo_c200_sofa_floodlight_timed", "barbecue": "light.tapo_c200_barbacue_floodlight_timed"}
MAX_ANNOUNCE_VOLUME = 0.3
WARM_KELVIN = 2700

ALONE = ("study_light", "echo_do_not_disturb", "announce_kitchen", "tv_mute", "vacuum_pause", "vacuum_dock",
         "push_gonza", "add_to_list", "house_status")
ASK_FIRST = ("start_vacuum", "camera_floodlight", "tv_power", "tv_volume")
READABLE = (STUDY_LIGHT, ECHO_DND, ECHO_ANNOUNCE, ECHO_PLAYER, VACUUM, *TVS.values(), *LISTS.values())
# Every service target the tools may touch. A call outside it is refused even if it is not on the never list.
TARGETS = {*READABLE, *FLOODLIGHTS.values(), None}


def pick(options, name, what):
    key = (name or "").lower().strip()
    if key not in options:
        raise ValueError(f"unknown {what} {name!r}, expected one of {', '.join(options)}")
    return options[key]


class HouseTools(Plugin):
    name = "house"

    def __init__(self, agent, config, client=None):
        super().__init__(agent, config)
        self.cfg = {**DEFAULTS, **(config.get("house") or {})}
        self.live = self.cfg["live"] is True
        token = os.environ.get(self.cfg["ha_token_env"])
        self.client = client if client is not None else (HomeAssistant(self.cfg["ha_url"], token) if token else None)
        self.restorer = None
        for name in ASK_FIRST:
            if name in agent.tools.allowed:
                agent.tools.allowed.discard(name)
                agent.bus.publish("house_warning", error=f"{name} removed from the allowed list, it always waits for a yes")
        on = {"type": "boolean"}
        tv = {"type": "string", "enum": list(TVS)}
        def add(tool):
            # A tool another plug-in already gave the agent wins, for example the house plan's vacuum_dock (#29).
            if tool.name in agent.tools.items:
                agent.bus.publish("house_warning", error=f"{tool.name} is already a tool, the house tools keep the other one")
                return
            agent.tools.add(tool)
        add(Tool("study_light", "Turn the study light on or off. For a night feed use on with warm true and a low brightness_pct.",
                 schema({"on": on, "brightness_pct": {"type": "integer", "minimum": 1, "maximum": 100}, "warm": on}, ["on"]),
                 self.study_light))
        add(Tool("echo_do_not_disturb", "Do not disturb on the kitchen Echo: on to hold its notifications, off after.",
                 schema({"on": on}, ["on"]), self.echo_do_not_disturb))
        add(Tool("announce_kitchen", "Say one fixed sentence on the kitchen Echo at low volume, never free text. "
                 + " ".join(f"{k}: {v}" for k, v in rules.ANNOUNCEMENTS.items()),
                 schema({"message": {"type": "string", "enum": list(rules.ANNOUNCEMENTS)}}, ["message"]), self.announce_kitchen))
        add(Tool("tv_mute", "Mute or unmute a TV.", schema({"tv": tv, "muted": on}, ["tv", "muted"]), self.tv_mute))
        add(Tool("vacuum_pause", "Pause the robot vacuum, for a nap or while a skill runs.", schema({}), self.vacuum_pause))
        add(Tool("vacuum_dock", "Send the robot vacuum back to its base.", schema({}), self.vacuum_dock))
        add(Tool("push_gonza", "Send a push notification to Gonza's iPhone. Never a code, a password or a phone number.",
                 schema({"text": {"type": "string"}, "title": {"type": "string"}}, ["text"]), self.push_gonza))
        add(Tool("add_to_list", "Add an item to the family to-do list or the shopping list, for example diapers.",
                 schema({"item": {"type": "string"}, "list": {"type": "string", "enum": list(LISTS)}}, ["item"]),
                 self.add_to_list))
        add(Tool("house_status", "Read the house: study light, kitchen Echo, TVs, robot vacuum, lists. Changes nothing.",
                 schema({}), self.status))
        add(Tool("start_vacuum", "Start the robot vacuum. Always waits for the parent's yes.", schema({}), self.start_vacuum))
        add(Tool("camera_floodlight", "Turn a camera floodlight on or off. Harsh light, always waits for the parent's yes.",
                 schema({"where": {"type": "string", "enum": list(FLOODLIGHTS)}, "on": on}, ["where", "on"]), self.floodlight))
        add(Tool("tv_power", "Turn a TV on or off. Always waits for the parent's yes.",
                 schema({"tv": tv, "on": on}, ["tv", "on"]), self.tv_power))
        add(Tool("tv_volume", "Set a TV's volume, level from 0 to 1. Always waits for the parent's yes.",
                 schema({"tv": tv, "level": {"type": "number", "minimum": 0, "maximum": 1}}, ["tv", "level"]), self.tv_volume))

    # The one way out to Home Assistant

    def log(self, action, service, entity, status, **fields):
        self.agent.bus.publish("house_call", action=action, service=service, entity=entity, live=self.live,
                               status=status, **fields)

    def call(self, action, service, entity, data=None, expect=None):
        """Runs one service call under the policy. Returns a short sentence for the brain."""
        reason = never_reason(entity)
        if reason or entity not in TARGETS:
            self.log(action, service, entity, "refused", reason=reason or "not in the house policy")
            return f"{action}: refused, {reason or 'not in the house policy'} is never controlled by the agent"
        if not self.live or self.client is None:
            why = "house.live is off" if not self.live else "no Home Assistant token"
            self.log(action, service, entity, "dry", data=data, reason=why)
            return f"{action}: dry run ({why}), nothing changed in the house"
        started = time.monotonic()
        try:
            self.client.service(service, entity, data)
            state = self.read_back(entity, expect)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            self.log(action, service, entity, "error", error=str(error)[:200])
            return f"{action}: failed, {str(error)[:120]}"
        confirmed = expect is None or state == expect
        self.log(action, service, entity, "ran", state=state, confirmed=confirmed,
                 seconds=round(time.monotonic() - started, 3))
        return f"{action}: done" + (f", now {state}" if state is not None else "") + ("" if confirmed else ", not confirmed yet")

    def read_back(self, entity, expect):
        if entity is None or entity.startswith("notify."):
            return None
        state = None
        for _ in range(self.cfg["read_back_tries"]):
            state = self.client.state(entity)
            if expect is None or state == expect:
                break
            time.sleep(self.cfg["read_back_interval_s"])
        return state

    # Alone

    def study_light(self, on, brightness_pct=None, warm=False):
        if not on:
            return self.call("study_light", "light.turn_off", STUDY_LIGHT, expect="off")
        data = {}
        if brightness_pct is not None:
            data["brightness_pct"] = max(1, min(100, int(brightness_pct)))
        if warm:
            data["color_temp_kelvin"] = WARM_KELVIN
        return self.call("study_light", "light.turn_on", STUDY_LIGHT, data or None, expect="on")

    def echo_do_not_disturb(self, on):
        return self.call("echo_do_not_disturb", "switch.turn_on" if on else "switch.turn_off", ECHO_DND,
                         expect="on" if on else "off")

    def announce_kitchen(self, message):
        """Only a fixed sentence from rules.ANNOUNCEMENTS: free text from a message never reaches the speaker."""
        if message not in rules.ANNOUNCEMENTS:
            self.log("announce_kitchen", "notify.send_message", ECHO_ANNOUNCE, "refused", reason="not a fixed sentence")
            return f"announce_kitchen: refused, it says only one of {', '.join(rules.ANNOUNCEMENTS)}"
        text = rules.ANNOUNCEMENTS[message]
        volume = min(float(self.cfg["announce_volume"]), MAX_ANNOUNCE_VOLUME)
        before = None
        if self.live and self.client is not None:
            try:
                before = self.client.attributes(ECHO_PLAYER).get("volume_level")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                before = None
        self.call("announce_volume", "media_player.volume_set", ECHO_PLAYER, {"volume_level": volume})
        result = self.call("announce_kitchen", "notify.send_message", ECHO_ANNOUNCE, {"message": str(text)[:300]})
        if before is not None and before != volume:
            self.restorer = threading.Timer(self.cfg["restore_after_s"], self.call,
                                            args=("restore_volume", "media_player.volume_set", ECHO_PLAYER, {"volume_level": before}))
            self.restorer.daemon = True
            self.restorer.start()
        return result

    def tv_mute(self, tv, muted):
        return self.call("tv_mute", "media_player.volume_mute", pick(TVS, tv, "TV"), {"is_volume_muted": bool(muted)})

    def vacuum_pause(self):
        return self.call("vacuum_pause", "vacuum.pause", VACUUM)

    def vacuum_dock(self):
        return self.call("vacuum_dock", "vacuum.return_to_base", VACUUM)

    def push_gonza(self, text, title=None):
        if rules.has_secret(text) or rules.has_secret(title):
            self.log("push_gonza", PUSH_GONZA, None, "refused", reason="holds a code or a number")
            return "push_gonza: refused, a code, a password or a long number is never sent in a push"
        data = {"message": str(text)[:500], **({"title": str(title)[:80]} if title else {})}
        return self.call("push_gonza", PUSH_GONZA, None, data)

    def add_to_list(self, item, list="shopping"):
        return self.call("add_to_list", "todo.add_item", pick(LISTS, list, "list"), {"item": str(item)[:120]})

    def status(self):
        if self.client is None:
            self.log("house_status", "read", None, "dry", reason="no Home Assistant token")
            return "house_status: no Home Assistant token, nothing read"
        states = {}
        for entity in READABLE:
            try:
                states[entity] = self.client.state(entity)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError) as error:
                states[entity] = f"unreadable: {str(error)[:60]}"
        self.log("house_status", "read", None, "ran", states=states)
        return states

    # Only with the parent's yes

    def start_vacuum(self):
        return self.call("start_vacuum", "vacuum.start", VACUUM, expect="cleaning")

    def floodlight(self, where, on):
        return self.call("camera_floodlight", "light.turn_on" if on else "light.turn_off", pick(FLOODLIGHTS, where, "place"),
                         expect="on" if on else "off")

    def tv_power(self, tv, on):
        return self.call("tv_power", "media_player.turn_on" if on else "media_player.turn_off", pick(TVS, tv, "TV"))

    def tv_volume(self, tv, level):
        return self.call("tv_volume", "media_player.volume_set", pick(TVS, tv, "TV"),
                         {"volume_level": max(0.0, min(1.0, float(level)))})

    def stop(self):
        if self.restorer and self.restorer.is_alive():
            self.restorer.cancel()
            self.restorer.function(*self.restorer.args)  # put the Echo volume back now instead of after the delay
