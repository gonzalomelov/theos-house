"""White noise as one of the agent's hands (issue #32): a simulated device and the rhythm that drives it.

SimulatedWhiteNoise has the controls the DIY ESP32-S3 + MAX98357A machine will expose through ESPHome (gonzalomelov
projects/diy-white-noise-machine.md): on, off, noise type, level and a sleep timer. Nothing plays, every change is a
"white_noise" event on the bus. The Echo fallback is not wired in this item.

The volume cap is in code, not in a setting a model can change: at most 50 dB at the crib. The calibration maps a
device level (0 to 1) to dB measured at the crib position, and the highest level at or under the cap becomes
max_level. Every level asked for is clamped to it. Until the machine is built and measured with a dB meter, the
calibration is a placeholder that assumes 70 dB at the crib at full level, so the cap is conservative.

WhiteNoisePlan decides from the log: on a few minutes before a nap or bedtime the rhythm expects, the timer down once
sleep starts, and on for a short night fuss before a parent is woken.
"""
import datetime
import math

from .rhythm import patterns
from .rhythm.log import ordered, parse

CRIB_CAP_DB = 50.0
NOISE_TYPES = ("white", "pink", "brown")
# Placeholder until measured at the crib: dB at the crib for a device level, louder by 20 log10 of the level.
PLACEHOLDER_CALIBRATION = [[1.0, 70.0]]


def crib_db(level, calibration):
    """dB at the crib for a level, from measured points, interpolated in log10(level)."""
    if level <= 0:
        return 0.0
    points = sorted(calibration)
    if len(points) == 1:
        ref_level, ref_db = points[0]
        return ref_db + 20 * math.log10(level / ref_level)
    for (l1, d1), (l2, d2) in zip(points, points[1:]):
        if level <= l2 or (l2, d2) == points[-1]:
            share = (math.log10(level) - math.log10(l1)) / (math.log10(l2) - math.log10(l1))
            return d1 + share * (d2 - d1)
    return points[-1][1]


def max_level(calibration, cap_db=CRIB_CAP_DB):
    """Highest level, in steps of 0.01, whose dB at the crib stays at or under the cap."""
    best = 0.0
    for step in range(1, 101):
        if crib_db(step / 100, calibration) <= cap_db + 1e-9:
            best = step / 100
    return best


class SimulatedWhiteNoise:
    name = "white_noise_sim"

    def __init__(self, bus, calibration=None, comfort_share=0.8):
        self.bus = bus
        self.calibration = calibration or PLACEHOLDER_CALIBRATION
        self.max_level = max_level(self.calibration)
        if self.max_level <= 0:
            raise ValueError("calibration leaves no level under the 50 dB cap")
        self.comfort_level = round(self.max_level * comfort_share, 2)
        self.state = {"on": False, "level": 0.0, "noise": "white", "timer_off_at": None}

    def _publish(self, action, reason, **extra):
        db = round(crib_db(self.state["level"], self.calibration), 1) if self.state["on"] else 0.0
        return self.bus.publish("white_noise", action=action, reason=reason, device=self.name, dry=True,
                                on=self.state["on"], level=self.state["level"], crib_db=db, noise=self.state["noise"],
                                timer_off_at=self.state["timer_off_at"], **extra)

    def level(self, level, reason=""):
        asked = float(level)
        self.state["level"] = round(max(0.0, min(asked, self.max_level)), 2)
        return self._publish("level", reason, asked=asked, capped=asked > self.max_level)

    def on(self, reason="", level=None, noise=None):
        if noise is not None:
            if noise not in NOISE_TYPES:
                raise ValueError(f"noise must be one of {NOISE_TYPES}")
            self.state["noise"] = noise
        self.state["on"] = True
        asked = self.comfort_level if level is None else float(level)
        self.state["level"] = round(max(0.0, min(asked, self.max_level)), 2)
        return self._publish("on", reason, asked=asked, capped=asked > self.max_level)

    def off(self, reason=""):
        self.state.update(on=False, level=0.0, timer_off_at=None)
        return self._publish("off", reason)

    def timer(self, minutes, now, reason=""):
        self.state["timer_off_at"] = (now + datetime.timedelta(minutes=minutes)).isoformat(timespec="seconds")
        return self._publish("timer", reason, minutes=minutes)

    def tick(self, now):
        """Turns off when the timer runs out. Returns the event, or None."""
        off_at = self.state["timer_off_at"]
        if self.state["on"] and off_at and now >= parse(off_at):
            return self.off("sleep timer ran out")
        return None


PLAN_DEFAULTS = {"lead_min": 5, "bedtime": "20:30", "timer_min": 30, "fuss_timer_min": 20, "fuss_max_s": 30,
                 "fuss_wait_s": 120, "utc_offset_h": -3}


class WhiteNoisePlan:
    """On before the sleep the rhythm expects, the timer down once he sleeps, on for a short night fuss."""

    def __init__(self, device, settings=None):
        self.device = device
        self.s = {**PLAN_DEFAULTS, **(settings or {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.s["utc_offset_h"]))
        self.done = set()

    def expected_sleep(self, entries, now):
        from . import cry_reason
        return cry_reason.context(entries, now, self.tz).get("next_sleep_at")

    def asleep_since(self, entries, now):
        for e in reversed(ordered(entries, now)):
            if e["kind"] == "sleep" and parse(e["start"]) <= now and (not e.get("end") or now < parse(e["end"])):
                return parse(e["start"])
        return None

    def tick(self, entries, now):
        """The device events due right now, in order."""
        out = []
        expired = self.device.tick(now)
        if expired:
            out.append(expired)
        local = now.astimezone(self.tz)
        h, m = map(int, self.s["bedtime"].split(":"))
        bedtime = local.replace(hour=h, minute=m, second=0, microsecond=0)
        lead = datetime.timedelta(minutes=self.s["lead_min"])
        if bedtime - lead <= local < bedtime + lead and ("bedtime", bedtime.date()) not in self.done:
            self.done.add(("bedtime", bedtime.date()))
            if not self.device.state["on"]:
                out.append(self.device.on(f"bedtime at {self.s['bedtime']}"))
        asleep = self.asleep_since(entries, now)
        if asleep is not None:
            if self.device.state["on"] and not self.device.state["timer_off_at"] and ("timer", asleep) not in self.done:
                self.done.add(("timer", asleep))
                out.append(self.device.timer(self.s["timer_min"], now, f"asleep since {patterns.hhmm(asleep.astimezone(self.tz))}"))
            return out
        if out:
            return out
        expected = self.expected_sleep(entries, now)
        if expected and expected - lead <= now < expected + lead and ("sleep", expected) not in self.done:
            self.done.add(("sleep", expected))
            if not self.device.state["on"]:
                kind = "nap" if 7 <= expected.astimezone(self.tz).hour < 19 else "sleep"
                out.append(self.device.on(f"{kind} expected around {patterns.hhmm(expected.astimezone(self.tz))}"))
        return out

    def night_fuss(self, now, cry_seconds):
        """A short cry at night: white noise on with a short timer, before waking a parent. Returns the event or None."""
        if not patterns.is_night(now.astimezone(self.tz)) or cry_seconds > self.s["fuss_max_s"]:
            return None
        event = self.device.on(f"short night fuss, {cry_seconds} s")
        self.device.timer(self.s["fuss_timer_min"], now, "short night fuss")
        return event
