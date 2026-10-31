"""SAM 3.1 only: the changing-table and bath watch with Meta's SAM 3.1 and no MediaPipe (hands "sam3_only").

Written during the hackathon (Oct 31 2026) as the switch in case the organizers rule MediaPipe out. It uses no prior
work: not the MediaPipe reflex and not the prior alarm (a private repo), so the project runs without
that library.

How it watches. SAM 3.1 is too slow for every frame (1.5 to 3 s a look on the Mac GPU), so one look runs at a time on a
background thread, on the newest frame, again and again while the skill is armed. Each look asks for the hand masks
and what they hold (the held prompt, parenting_agent/sam3_local.py masks). A hand mask touching the baby means a hand
is on: the look reads on, and when the lift check has no resting baseline the masks become it (lift.py anchor, regions
sam3). No hand mask on the baby reads off. Between looks every frame goes through the lift check on the anchored hand
regions, which runs locally in milliseconds and catches a hand held 2 to 5 cm above the baby, which SAM 3.1 itself
reads as on.

The alarm here is new and small. A look that reads off raises it, chimes and speaks "hand" at once: SAM 3.1 already is
the slow, careful look the MediaPipe path waits for. A lifted reading raises it and chimes, and speaks once it has
lasted voice_hold_s. A look or the lift check reading on for clear_after_on_s clears it, and a prompt not yet spoken is
dropped. The events are the same as the MediaPipe path (frame, alarm, chime, voice, voice_dropped, skill_armed,
skill_closed), so the speaker, the house and the glasses work unchanged.
"""
import datetime
import time
from concurrent.futures import ThreadPoolExecutor

from .house import House
from .lift import LiftCheck
from .tracking import Tracker

SAM3_MIN_LIFT_CM = 1.7


def touching(hands, baby, grow=25):
    """True when a SAM 3.1 hand mask touches the baby mask grown by grow pixels, the same test the lift anchor uses."""
    import cv2
    import numpy as np
    if baby is None or not baby.any():
        return False
    near = cv2.dilate(baby.astype(np.uint8), np.ones((grow, grow), np.uint8)).astype(bool)
    return any((mask & near).any() for mask in hands)


class SamAlarm:
    """on, off (a SAM 3.1 look found no hand on the baby) or lifted (the lift check) in, alarm events out."""

    def __init__(self, bus, alarm):
        self.bus, self.cfg = bus, alarm
        self.episode, self.raised, self.spoken, self.raised_s, self.on_since, self.lifted = 0, False, False, None, None, False
        self.cancelled = self.unseen = False  # the skill API the MediaPipe alarm has, never set here

    def on_state(self, state, stream_s):
        if state == "on":
            self.on_since = stream_s if self.on_since is None else self.on_since
            if self.raised and stream_s - self.on_since >= self.cfg["clear_after_on_s"]:
                if not self.spoken:
                    self.bus.publish("voice_dropped", episode=self.episode, stream_s=stream_s, reason="clear")
                self.bus.publish("alarm", action="clear", episode=self.episode, stream_s=stream_s)
                self.raised = False
            return
        if state not in ("off", "lifted"):
            return
        self.on_since = None
        if not self.raised:
            self.episode += 1
            self.raised, self.spoken, self.raised_s, self.lifted = True, False, stream_s, state == "lifted"
            self.bus.publish("alarm", action="raise", episode=self.episode, stream_s=stream_s, state=state)
            self.bus.publish("chime", episode=self.episode, stream_s=stream_s)
        if state == "off":
            self.speak(stream_s, "sam3")
        elif stream_s - self.raised_s >= self.cfg["voice_hold_s"]:
            self.speak(stream_s, "hold")

    def speak(self, stream_s, reason):
        if self.spoken:
            return
        self.spoken = True
        self.bus.publish("voice", episode=self.episode, stream_s=stream_s, reason=reason, text=self.cfg["voice_text"])


class _NoConfirm:
    pending = None

    def collect(self):
        pass

    def close(self):
        pass


class SamOnlySkill:
    """The Skill interface (arm, on_frame, close) with SAM 3.1 as the only hand detector."""

    def __init__(self, config, bus, detector, house=None, tracker=None):
        masks = getattr(detector, "masks", None)
        if masks is None:
            raise RuntimeError("hands sam3_only needs SAM 3.1 (confirm.provider sam3_local): no hand watch without it")
        self.cfg, self.bus, self.detector, self.masks = config, bus, detector, masks
        self.alarm = SamAlarm(bus, config["alarm"])
        self.confirm = _NoConfirm()
        self.house = house or House(config["house"], bus)
        self.tracker = tracker or Tracker(config["tracking"], bus)
        self.bus.subscribe(self._on_voice, ["voice"])
        lift = dict(config.get("lift", {}))
        if lift.get("regions") != "sam3":  # SAM 3.1 hand masks read at 1.7 cm, the threshold chosen on dev (results/hover/blind)
            lift.update({"regions": "sam3", "min_lift_cm": SAM3_MIN_LIFT_CM})
        self.lift = LiftCheck(lift) if lift.get("enabled") else None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.job, self.look_state, self.armed_at, self.frames = None, None, None, 0
        source = getattr(getattr(detector, "impl", None), "source", None)
        self.bus.publish("hands_mode", mode="sam3_only", lift=self.lift is not None)
        if source:
            self.bus.publish("confirm_model", provider=getattr(detector, "name", "sam3_local"),
                             **{k: v for k, v in source.items() if k != "ready"})

    def _on_voice(self, event):
        self.house.on_event("voice")

    def arm(self):
        self.armed_at = datetime.datetime.now(datetime.timezone.utc)
        self.bus.publish("skill_armed", skill=self.cfg["name"])
        self.house.on_event("armed")

    def _look(self, frame_bgr):
        started = time.monotonic()
        hands, baby = self.masks(frame_bgr, held=True)
        return hands, baby, time.monotonic() - started

    def _land(self):
        if not (self.job and self.job[2].done()):
            return
        gray, look_s, future = self.job
        self.job = None
        try:
            hands, baby, seconds = future.result()
        except Exception as error:  # a failed look reads nothing new, the next one is sent at once
            self.bus.publish("sam3_error", error=str(error)[:200])
            return
        on = touching(hands, baby)
        if self.lift is not None and on and (self.lift.base is None or self.lift.wants_anchor) and not self.lift.lifted:
            self.lift.anchor(gray, hands, baby, look_s)
            self.bus.publish("anchor", stream_s=round(look_s, 3), hands=len(hands), based=self.lift.base is not None)
        if not on and self.lift is not None:
            self.lift.reset()
        self.look_state = "on" if on else "off"
        self.bus.publish("sam3_look", stream_s=round(look_s, 3), state=self.look_state, hands=len(hands),
                         seconds=round(seconds, 3))

    def on_frame(self, frame_bgr, stream_s):
        import cv2
        width = self.cfg["process_width"]
        if frame_bgr.shape[1] != width:
            frame_bgr = cv2.resize(frame_bgr, (width, round(frame_bgr.shape[0] * width / frame_bgr.shape[1])))
        self.frames += 1
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        self._land()
        state, lift_cm, lift_s = self.look_state, None, None
        if state == "on" and self.lift is not None and self.lift.base is not None:
            started = time.monotonic()
            if self.lift.update(gray, [True], stream_s):
                state = "lifted"
            lift_cm = None if self.lift.lift_cm is None else round(self.lift.lift_cm, 2)
            lift_s = round(time.monotonic() - started, 4)
        self.bus.publish("frame", stream_s=round(stream_s, 3), state=state or "unknown", hands=None, seconds=0.0,
                         lift_cm=lift_cm, lift_s=lift_s)
        self.alarm.on_state(state, round(stream_s, 3))
        if self.job is None:
            self.job = (gray, stream_s, self.pool.submit(self._look, frame_bgr.copy()))

    def close(self, content=None):
        self.pool.shutdown(wait=True)
        ended = datetime.datetime.now(datetime.timezone.utc)
        self.house.on_event("closed")
        self.tracker.skill_closed(self.cfg["name"], self.armed_at or ended, ended, content)
        self.house.close()
        self.bus.publish("skill_closed", skill=self.cfg["name"], frames=self.frames,
                         alarms=self.bus.count("chime"), voices=self.bus.count("voice"))
