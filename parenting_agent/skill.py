"""Skill lifecycle: arm, watch, close.

Arming publishes skill_armed and fires the house on_armed actions. Each new frame goes through the reflex,
the lift check when the reflex reads on (config lift.enabled, see parenting_agent/lift.py), the alarm and, when
the alarm raises, one confirm request. A hand the lift check finds held above the baby counts as off, and that
alarm skips the confirm detector, because SAM 3.1 reads a hovering hand as on (results/hover). A spoken prompt fires the on_voice actions.
Closing fires on_closed, logs the routine to tracking, and publishes skill_closed with the numbers.
"""
import datetime
import time

from . import confirm as confirm_mod
from .alarm import Alarm
from .house import House
from .lift import LiftCheck
from .tracking import Tracker


class Skill:
    def __init__(self, config, bus, reflex, confirm_detector=None, house=None, tracker=None):
        self.cfg, self.bus, self.reflex = config, bus, reflex
        detector = confirm_detector or confirm_mod.build(config["confirm"])
        self.alarm = Alarm(bus, config["contact"], config["alarm"], waits_for_confirm=not isinstance(detector, confirm_mod.NoConfirm))
        self.confirm = confirm_mod.ConfirmStage(detector, bus, self.alarm)
        self.house = house or House(config["house"], bus)
        self.tracker = tracker or Tracker(config["tracking"], bus)
        self.bus.subscribe(self._on_voice, ["voice"])
        self.armed_at, self.frames, self.off_since = None, 0, None
        lift = config.get("lift", {})
        self.lift = LiftCheck(lift) if lift.get("enabled") else None

    def _on_voice(self, event):
        self.house.on_event("voice")

    def arm(self):
        self.armed_at = datetime.datetime.now(datetime.timezone.utc)
        self.bus.publish("skill_armed", skill=self.cfg["name"])
        self.house.on_event("armed")

    def on_frame(self, frame_bgr, stream_s):
        import cv2
        width = self.cfg["process_width"]
        if frame_bgr.shape[1] != width:
            frame_bgr = cv2.resize(frame_bgr, (width, round(frame_bgr.shape[0] * width / frame_bgr.shape[1])))
        state, hands, seconds = self.reflex.state(frame_bgr)
        self.frames += 1
        lifted, lift_cm, lift_s = self._lift(frame_bgr, state, stream_s)
        self.bus.publish("frame", stream_s=round(stream_s, 3), state="lifted" if lifted else state, hands=hands,
                         seconds=round(seconds, 4), lift_cm=lift_cm, lift_s=lift_s)
        before = self.alarm.episode
        self.alarm.on_reflex(state, round(stream_s, 3), near=getattr(self.reflex, "near", False), lifted=lifted)
        if self.alarm.episode != before and not lifted:
            self.confirm.request(self.alarm.episode, frame_bgr, round(stream_s, 3))
        self.confirm.collect()

    def _lift(self, frame_bgr, state, stream_s):
        """Whether every hand the reflex reads on is held above the baby, its lift in cm and the seconds it took."""
        if self.lift is None:
            return False, None, None
        if state != "on":  # a short flicker keeps the resting baseline, a longer absence drops it
            self.off_since = stream_s if self.off_since is None else self.off_since
            if stream_s - self.off_since >= self.lift.cfg["reset_after_off_s"]:
                self.lift.reset()
            return False, None, None
        self.off_since = None
        import cv2
        started = time.monotonic()
        landmarks = getattr(self.reflex, "landmarks_px", [])
        hands = [landmarks[i] for i in getattr(self.reflex, "on_hands", []) if i < len(landmarks)]
        lifted = self.lift.update(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY), hands, stream_s)
        lift_cm = None if self.lift.lift_cm is None else round(self.lift.lift_cm, 2)
        return lifted, lift_cm, round(time.monotonic() - started, 4)

    def close(self):
        self.confirm.close()
        ended = datetime.datetime.now(datetime.timezone.utc)
        self.house.on_event("closed")
        self.tracker.skill_closed(self.cfg["name"], self.armed_at or ended, ended)
        self.house.close()
        self.bus.publish("skill_closed", skill=self.cfg["name"], frames=self.frames,
                         alarms=self.bus.count("chime"), voices=self.bus.count("voice"))


def watch(skill, source, minutes=None, frames_limit=None):
    """Feed the newest frames from source into the skill until time, frame count or the source runs out."""
    deadline = time.monotonic() + minutes * 60 if minutes else None
    seq = 0
    while True:
        if deadline and time.monotonic() >= deadline:
            break
        if frames_limit and skill.frames >= frames_limit:
            break
        got = source.latest(seq)
        if got is None:
            if source.stopped:
                break
            skill.confirm.collect()
            time.sleep(0.002)
            continue
        frame, seq, stream_s = got
        skill.on_frame(frame, stream_s)
