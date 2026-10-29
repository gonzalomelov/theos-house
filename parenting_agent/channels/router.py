"""Channel picking: one agent, one memory, and it chooses where to speak (issue #8).

The router looks at where the parent is (Home Assistant presence: person.* first, then the phone's
device_tracker) and what their hands are doing (a skill is armed), then picks one channel:

| Situation | Channel |
|---|---|
| Help is needed (the message asks for the partner) | partner, a stub until Ceci has a phone channel |
| Away from home, or presence unknown | telegram |
| At home, a skill is armed (hands on the baby) | ear |
| At home, the baby is asleep | ear, the home speaker would wake her |
| At home, hands free | home_speaker, the kitchen Echo at low volume |

Use it as the plug-in "parenting_agent.channels.router:Router". Anything published as a "notify" event
(text, optional help_needed and baby_asleep), and any agent "reply" on the channel "auto", is routed. A
"routed" event records the choice and the reason. Config block "router":
    {"person": "person.gonza", "tracker": "device_tracker.gonzas_iphone",
     "ha_url": "http://127.0.0.1:18123", "ha_token_env": "HA_MCP_TOKEN",
     "speaker": {"notify": "notify.gonza_s_echo_dot_announce", "media_player": "media_player.gonza_s_echo_dot",
                 "volume": 0.2, "restore_after_s": 10}}
Without a Home Assistant token presence is unknown, so messages go to Telegram and the speaker runs dry.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
from dataclasses import dataclass

from ..agent import rules
from ..agent.plugins import Plugin
from ..house import HomeAssistant

# From the action policy in docs/home-assistant-inventory.md: announce or speak on the Echo Dot, low volume.
ALLOWED_SPEAKERS = {"notify.gonza_s_echo_dot_announce", "notify.gonza_s_echo_dot_speak"}
MAX_VOLUME = 0.3
CHANNELS = ("ear", "home_speaker", "telegram", "partner")


@dataclass
class Situation:
    presence: str = "unknown"  # home, away or unknown
    skill_active: bool = False
    baby_asleep: bool = False
    help_needed: bool = False


def pick(situation):
    """Returns (channel, reason) for one situation. Pure, so the routing test runs without a house."""
    if situation.help_needed:
        return "partner", "help is needed"
    if situation.presence != "home":
        return "telegram", f"presence is {situation.presence}"
    if situation.skill_active:
        return "ear", "at home with hands on the baby"
    if situation.baby_asleep:
        return "ear", "at home and the baby is asleep"
    return "home_speaker", "at home with hands free"


def presence_from_states(person_state, tracker_state):
    for state in (person_state, tracker_state):
        if state in (None, "", "unknown", "unavailable"):
            continue
        return "home" if state == "home" else "away"
    return "unknown"


class HomeSpeaker:
    """Announces on the kitchen Echo at low volume, then puts the volume back. Only allowed speakers."""

    def __init__(self, client, cfg, bus):
        self.client, self.bus = client, bus
        self.cfg = {"notify": "notify.gonza_s_echo_dot_announce", "media_player": "media_player.gonza_s_echo_dot",
                    "volume": 0.2, "restore_after_s": 10, **cfg}
        if self.cfg["notify"] not in ALLOWED_SPEAKERS:
            raise ValueError(f"{self.cfg['notify']} is not an allowed speaker")
        if not 0 < self.cfg["volume"] <= MAX_VOLUME:
            raise ValueError(f"speaker volume must be low, at most {MAX_VOLUME}")
        self.restorer = None

    def __call__(self, text):
        if self.client is None:
            self.bus.publish("house_dry", action="announce", service="notify.send_message", entity=self.cfg["notify"])
            return {"dry": True}
        before_volume = self.client.attributes(self.cfg["media_player"]).get("volume_level")
        before_sent = self.client.state(self.cfg["notify"])
        self.client.service("media_player.volume_set", self.cfg["media_player"], {"volume_level": self.cfg["volume"]})
        response = self.client.service("notify.send_message", self.cfg["notify"], {"message": text})
        after_sent = self.client.state(self.cfg["notify"])
        result = {"volume_before": before_volume, "volume_used": self.cfg["volume"], "response": response,
                  "last_sent_before": before_sent, "last_sent_after": after_sent, "confirmed": after_sent != before_sent}
        if before_volume is not None and before_volume != self.cfg["volume"]:
            self.restorer = threading.Timer(self.cfg["restore_after_s"], self.restore, args=(before_volume,))
            self.restorer.daemon = True
            self.restorer.start()
        self.bus.publish("house_done", action="announce", entity=self.cfg["notify"], confirmed=result["confirmed"])
        return result

    def restore(self, volume):
        try:
            self.client.service("media_player.volume_set", self.cfg["media_player"], {"volume_level": volume})
            self.bus.publish("house_done", action="restore_volume", entity=self.cfg["media_player"], volume=volume)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            self.bus.publish("house_error", action="restore_volume", error=str(error)[:200])


def mac_say(text):
    """The ear for now: the Mac speaker. Glasses or an earpiece replace this later."""
    if sys.platform == "darwin" and shutil.which("say"):
        subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"played": True}
    return {"played": False}


class Router(Plugin):
    name = "router"
    kind = "router"

    def __init__(self, agent, config, client=None, outputs=None, presence=None):
        super().__init__(agent, config)
        self.cfg = {"person": "person.gonza", "tracker": "device_tracker.gonzas_iphone",
                    "ha_url": "http://127.0.0.1:18123", "ha_token_env": "HA_MCP_TOKEN", "speaker": {},
                    **config.get("router", {})}
        token = os.environ.get(self.cfg["ha_token_env"])
        self.client = client if client is not None else (HomeAssistant(self.cfg["ha_url"], token) if token else None)
        self._presence = presence
        self.outputs = {"ear": mac_say, "home_speaker": HomeSpeaker(self.client, self.cfg["speaker"], agent.bus),
                        "telegram": self.to_telegram, "partner": self.to_partner, **(outputs or {})}
        agent.bus.subscribe(self.on_event, ["notify", "reply"])

    def presence(self):
        if self._presence is not None:
            return self._presence()
        if self.client is None:
            return "unknown"
        try:
            return presence_from_states(self.client.state(self.cfg["person"]), self.client.state(self.cfg["tracker"]))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return "unknown"

    def skill_active(self):
        return any(getattr(p, "kind", "") == "skill" and getattr(p, "skill", None) is not None
                   for p in getattr(self.agent, "plugins", []))

    def situation(self, event):
        return Situation(self.presence(), self.skill_active(), bool(event.get("baby_asleep")), bool(event.get("help_needed")))

    def on_event(self, event):
        if event["kind"] == "reply" and event.get("channel") != "auto":
            return
        self.deliver(event["text"], self.situation(event))

    def deliver(self, text, situation):
        channel, reason = pick(situation)
        if channel in ("home_speaker", "ear") and rules.has_secret(text):
            # A code or a long number is never read aloud in the house: it goes to the parent's phone instead.
            channel, reason = "telegram", "holds a code, never read aloud"
        started = time.monotonic()
        try:
            result = self.outputs[channel](text)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            result = {"error": str(error)[:200]}
        self.agent.bus.publish("routed", channel=channel, reason=reason, presence=situation.presence,
                               skill_active=situation.skill_active, seconds=round(time.monotonic() - started, 3))
        return channel, result

    def to_telegram(self, text):
        self.agent.bus.publish("reply", channel="telegram", text=text)
        return {"sent_to": "telegram"}

    def to_partner(self, text):
        # Stub: Ceci has no Telegram or phone in Home Assistant yet, and a message to anyone but Gonza needs his yes.
        self.agent.bus.publish("partner_stub", text=text, note="not sent, needs a partner channel and the parent's yes")
        return {"sent": False, "stub": True}
