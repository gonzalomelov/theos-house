"""Per-action live house writes (Oct 30, Gonza's yes in chat: "Yes, light and vacuum pause").

Everything in the house is a dry run unless its action is named in "house": {"live_actions": [...]} in the agent
config. The list is empty by default. A name only counts when it is in CATALOG below, kept in code:

| Action | Routine | Entity | Live services | When | Cap |
|---|---|---|---|---|---|
| night_feed_light | night_feed | the study light | light.turn_on (dim, warm), light.turn_off | on only on a real awake signal (cry, parent message, he's up button, logged wake-up or feed), off only when the same episode turned it on for real | 6 writes a night (noon to noon) |
| nap_mode_vacuum | nap_mode | the robot vacuum | vacuum.pause, vacuum.return_to_base | only when a nap or a night sleep starts | 4 writes a day |

Never live, whatever the config says: vacuum.start and vacuum.clean_area (no start, no resume, no floor clean), the
never list in house.py, and every other service and entity. A write the gate does not allow goes down the caller's
usual dry path, so the reply and the event log say it was only written down.

A device that reads unavailable in Home Assistant gets nothing sent: the "house_live" event says unavailable and the
reply says nothing moved. Every live write, refused live write and rate limited write is a "house_live" event with the routine, entity, service
and reason, so it lands in data/events.jsonl. The counts live in memory: an agent restart starts them over.
"""
import datetime
import re
import threading
import urllib.error

from .house import never_reason

STUDY_LIGHT = "light.wiz_824512_192_0_2_10"
VACUUM = "vacuum.xiaomi_ov71gl_0681_robot_cleaner"
AWAKE_SIGNALS = ("cry", "parent", "button", "log")
SLEEP_START = "sleep_start"
MAX_LIGHT_PCT = 30
WARM_KELVIN = 2700
NEVER_LIVE = ("vacuum.start", "vacuum.clean_area")
RECENT = datetime.timedelta(minutes=60)
UNREACHABLE = ("unavailable", "unknown", None)

CATALOG = {
    "night_feed_light": {"routine": "night_feed", "entity": STUDY_LIGHT, "services": ("light.turn_on", "light.turn_off"),
                         "cap": 6, "per": "night", "device": "the study light",
                         "words": re.compile(r"\b(lights?|lamps?|luz|luces)\b", re.I)},
    "nap_mode_vacuum": {"routine": "nap_mode", "entity": VACUUM, "services": ("vacuum.pause", "vacuum.return_to_base"),
                        "cap": 4, "per": "day", "device": "the vacuum",
                        "words": re.compile(r"\b(vacuum|aspiradora)\b", re.I)},
}
SAID = {"light.turn_on": "went on, dim and warm", "light.turn_off": "went off", "vacuum.pause": "was paused",
        "vacuum.return_to_base": "was sent to its base"}


def live_actions(house_cfg):
    """The listed actions that exist in CATALOG. Anything else in the list is ignored."""
    listed = (house_cfg or {}).get("live_actions") or []
    return [name for name in listed if name in CATALOG]


class LiveGate:
    """The one door for a live house write outside the old all-or-nothing house.live switch."""

    def __init__(self, bus, house_cfg=None, client=None, utc_offset_h=-3, clock=None):
        self.bus, self.client = bus, client
        house_cfg = house_cfg or {}
        self.listed = live_actions(house_cfg)
        for name in (house_cfg.get("live_actions") or []):
            if name not in CATALOG:
                bus.publish("house_warning", error=f"live action {name!r} is not in the catalog, it stays a dry run")
        caps = house_cfg.get("live_caps") or {}
        self.caps = {name: min(int(caps.get(name, spec["cap"])), spec["cap"]) for name, spec in CATALOG.items()}
        self.tz = datetime.timezone(datetime.timedelta(hours=utc_offset_h))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self.counts = {}
        self.recent = []
        self.lock = threading.Lock()

    def enabled(self, name):
        return name in self.listed and self.client is not None

    def find(self, routine, service, entity):
        for name, spec in CATALOG.items():
            if spec["routine"] == routine and spec["entity"] == entity and service in spec["services"]:
                return name
        return None

    def period(self, name, now):
        local = now.astimezone(self.tz)
        if CATALOG[name]["per"] == "night":
            return (local - datetime.timedelta(hours=12)).date()
        return local.date()

    def used(self, name, now=None):
        now = now or self.clock()
        return self.counts.get((name, self.period(name, now)), 0)

    def log(self, status, routine, service, entity, reason, **fields):
        return self.bus.publish("house_live", status=status, routine=routine, service=service, entity=entity,
                                reason=str(reason)[:200], **fields)

    def write(self, routine, service, entity, data=None, reason="", signal=None, now=None):
        """Runs the write for real when the gate allows it and returns the house_live event. Returns None when the
        write is not live (unlisted, refused or rate limited), and the caller writes it down as a dry run."""
        name = self.find(routine, service, entity)
        if service in NEVER_LIVE:
            if self.listed and entity == VACUUM:
                self.log("refused", routine, service, entity, reason, why=f"{service} is never live")
            return None
        if name is None or name not in self.listed or never_reason(entity):
            return None
        if name == "night_feed_light" and service == "light.turn_on" and signal not in AWAKE_SIGNALS:
            self.log("refused", routine, service, entity, reason, signal=signal,
                     why="the study light goes on for real only on a real awake signal, never on a guess")
            return None
        if name == "nap_mode_vacuum" and signal != SLEEP_START:
            self.log("refused", routine, service, entity, reason, signal=signal,
                     why="the vacuum pauses for real only when a nap or night sleep starts")
            return None
        if self.client is None:
            return None
        now = now or self.clock()
        with self.lock:
            key = (name, self.period(name, now))
            if self.counts.get(key, 0) >= self.caps[name]:
                self.log("rate_limited", routine, service, entity, reason, signal=signal,
                         why=f"{self.caps[name]} live writes a {CATALOG[name]['per']} already used")
                return None
            self.counts[key] = self.counts.get(key, 0) + 1
        data = self.clean(service, data)
        try:
            before = self.client.state(entity)
            if before in UNREACHABLE:
                return self.log("unavailable", routine, service, entity, reason, signal=signal, state=before,
                                why=f"{entity} reads {before} in Home Assistant, nothing was sent")
            self.client.service(service, entity, data)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            return self.log("error", routine, service, entity, reason, signal=signal, data=data, error=str(error)[:200])
        event = self.log("ran", routine, service, entity, reason, signal=signal, data=data,
                         at=now.isoformat(timespec="seconds"))
        with self.lock:
            self.recent.append((now, name, service))
        return event

    @staticmethod
    def clean(service, data):
        """The light goes on dim and warm: only brightness and warmth pass, brightness at most MAX_LIGHT_PCT."""
        if service != "light.turn_on":
            return None
        pct = int((data or {}).get("brightness_pct") or 10)
        return {"brightness_pct": max(1, min(MAX_LIGHT_PCT, pct)), "color_temp_kelvin": WARM_KELVIN}

    def claims(self, now=None):
        """(device words, true sentence) for each device written for real in the last hour, latest write per device."""
        now = now or self.clock()
        latest = {}
        with self.lock:
            for moment, name, service in self.recent:
                if now - moment <= RECENT:
                    latest[name] = (moment, service)
        return [(CATALOG[name]["words"], f"Done for real: {CATALOG[name]['device']} {SAID[service]} at "
                 f"{moment.astimezone(self.tz):%H:%M}.") for name, (moment, service) in latest.items()]


def gate_for(agent, config, client=None, clock=None):
    """One gate per agent, shared by the night feed and the day engine, so the reply guard sees every live write."""
    gate = getattr(agent, "house_live", None)
    if gate is None:
        rhythm = config.get("rhythm") or {}
        gate = LiveGate(agent.bus, config.get("house") or {}, client, rhythm.get("utc_offset_h", -3), clock)
        agent.house_live = gate
    elif gate.client is None and client is not None:
        gate.client = client
    return gate
