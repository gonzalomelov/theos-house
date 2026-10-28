"""Skill lifecycle: arm, watch, close.

Arming publishes skill_armed and fires the house on_armed actions. Each new frame goes through the reflex,
the alarm and, when the alarm raises, one confirm request. A spoken prompt fires the on_voice actions.
Closing fires on_closed, logs the routine to tracking, and publishes skill_closed with the numbers.
"""
import datetime
import time

from . import confirm as confirm_mod
from .alarm import Alarm
from .house import House
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
        self.armed_at, self.frames = None, 0

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
        self.bus.publish("frame", stream_s=round(stream_s, 3), state=state, hands=hands, seconds=round(seconds, 4))
        before = self.alarm.episode
        self.alarm.on_reflex(state, round(stream_s, 3), near=getattr(self.reflex, "near", False))
        if self.alarm.episode != before:
            self.confirm.request(self.alarm.episode, frame_bgr, round(stream_s, 3))
        self.confirm.collect()

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
