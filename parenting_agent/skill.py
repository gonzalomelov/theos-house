"""Skill lifecycle: arm, watch, close.

Arming publishes skill_armed and fires the house on_armed actions. Each new frame goes through the reflex,
the lift check when the reflex reads on (config lift.enabled, see parenting_agent/lift.py), the alarm and, when
the alarm raises, one confirm request, sent confirm.delay_s after the raise with the newest frame (default 0). When the confirm
cancels but the reflex still reads off, the skill asks again on a newer frame, up to confirm.retries times, and an
off answer then raises the alarm again. A hand the lift check finds held above the baby counts as off, and that
alarm skips the confirm detector, because SAM 3.1 reads a hovering hand as on (results/hover). While an alarm is
raised or its confirm is due or pending, no lift anchor is sent, so the confirm never waits behind one on the shared
SAM 3.1 worker (results/hero, take 1). A spoken prompt fires the on_voice actions.

With lift.held (and SAM 3.1 regions) a hand on the baby that the reflex loses is followed by its SAM 3.1
region instead: a grip on a diaper, a wipe or a bottle hides the hand from MediaPipe (results/hover/held). While the
anchored region stays where it rested the frame counts as on, once it rises min_lift_cm it counts as lifted, and once
it cannot be found for lift.held_gone_s it counts as off and the anchor is dropped. An alarm raised with no anchor yet
(the hand was never seen) waits for one SAM 3.1 look, sent confirm.held_delay_s after the raise, that prompts for the
hand and what it holds: a region on the baby becomes the anchor and cancels the alarm, none speaks it.
Closing fires on_closed, logs the routine to tracking, and publishes skill_closed with the numbers.
"""
import datetime
import time
from concurrent.futures import ThreadPoolExecutor

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
        self.armed_at, self.frames, self.off_since, self.confirm_due = None, 0, None, None
        self.retries = 0
        lift = config.get("lift", {})
        self.masks = getattr(detector, "masks", None) if lift.get("regions") == "sam3" else None
        if lift.get("regions") == "sam3" and self.masks is None:  # no SAM 3.1: MediaPipe regions and their threshold
            lift = {**lift, "regions": "mediapipe", "min_lift_cm": lift.get("mediapipe_min_lift_cm", 1.0)}
        self.lift = LiftCheck(lift) if lift.get("enabled") else None
        self.anchor_pool = ThreadPoolExecutor(max_workers=1) if self.masks else None
        self.anchor_job = None
        self.held = bool(lift.get("held")) and self.lift is not None and self.masks is not None
        self.held_lost, self.held_anchor = False, None
        self.confirm.before_verdict = self._held_verdict if self.held else None
        source = getattr(getattr(detector, "impl", None), "source", None)
        if source:  # which weights answer the confirm and the anchors, and where they run
            self.bus.publish("confirm_model", provider=detector.name, **{k: v for k, v in source.items() if k != "ready"})

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
        seen = state
        state, held, lifted, lift_cm, lift_s = self._lift(frame_bgr, state, hands, stream_s)
        self.bus.publish("frame", stream_s=round(stream_s, 3), state="lifted" if lifted else state, hands=hands,
                         seconds=round(seconds, 4), lift_cm=lift_cm, lift_s=lift_s, **({"held": held} if held else {}))
        unseen = self.held and seen != "on" and self.lift.base is None and not self.held_lost
        before = self.alarm.episode
        self.alarm.on_reflex(state, round(stream_s, 3), near=getattr(self.reflex, "near", False), lifted=lifted, unseen=unseen)
        if self.alarm.episode != before and not lifted:
            delay = self.cfg["confirm"].get("held_delay_s", 0) if self.alarm.unseen else self.cfg["confirm"].get("delay_s", 0)
            self.confirm_due = (self.alarm.episode, stream_s + delay, self.alarm.unseen)
        if self.confirm_due and stream_s >= self.confirm_due[1]:  # the first off frame often still shows the hands leaving
            episode, _, unseen_alarm = self.confirm_due
            self.confirm_due = None
            if episode == self.alarm.episode and self.alarm.raised and not self.alarm.lifted:
                self.retries = 0
                if unseen_alarm:
                    import cv2
                    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                    self.confirm.request(episode, frame_bgr, round(stream_s, 3), kind="held",
                                         judge=lambda frame, s=round(stream_s, 3): self._held_look(frame, gray, s))
                else:
                    self.confirm.request(episode, frame_bgr, round(stream_s, 3))
        elif (self.alarm.cancelled and state != "on" and not self.confirm.pending
              and self.retries < self.cfg["confirm"].get("retries", 0)):  # still off after a cancel: ask on a newer frame
            self.retries += 1
            self.confirm.request(self.alarm.episode, frame_bgr, round(stream_s, 3))
        self.confirm.collect()

    def _lift(self, frame_bgr, state, hands_seen, stream_s):
        """The state after the lift check: on, off or unknown, the held reading (lift.held) or None, whether every hand
        is held above the baby, its lift in cm and the seconds it took."""
        if self.lift is None:
            return state, None, False, None, None
        import cv2
        if state != "on":
            if self.held and self.lift.base is not None:  # the reflex lost the hand on the baby: follow its region
                started = time.monotonic()
                held = self.lift.held(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY), stream_s)
                seconds = round(time.monotonic() - started, 4)
                if held == "gone":
                    self.lift.reset()
                    self.held_lost = True
                else:
                    self.off_since = None
                    lift_cm = None if self.lift.lift_cm is None else round(self.lift.lift_cm, 2)
                    return "on", held, held == "lifted", lift_cm, seconds
            # a short flicker keeps the resting baseline, a longer absence drops it
            self.off_since = stream_s if self.off_since is None else self.off_since
            if stream_s - self.off_since >= self.lift.cfg["reset_after_off_s"]:
                self.lift.reset()
            return state, None, False, None, None
        self.off_since = None
        self.held_lost = False
        started = time.monotonic()
        landmarks = getattr(self.reflex, "landmarks_px", [])
        hands = [landmarks[i] for i in getattr(self.reflex, "on_hands", []) if i < len(landmarks)]
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        self._anchor(frame_bgr, gray, stream_s)
        lifted = self.lift.update(gray, hands, stream_s)
        lift_cm = None if self.lift.lift_cm is None else round(self.lift.lift_cm, 2)
        return state, None, lifted, lift_cm, round(time.monotonic() - started, 4)

    def _held_look(self, frame_bgr, gray, stream_s):
        """lift.held: SAM 3.1 hand regions with what they hold, on the confirm worker. The skill's thread lands them."""
        hands, baby = self.masks(frame_bgr, held=True)
        self.held_anchor = (gray, stream_s, hands, baby)
        return "held"

    def _held_verdict(self, episode, verdict):
        """The held look's answer: its hand regions on the baby become the anchor (on), none means no hand on (off)."""
        if verdict != "held" or self.held_anchor is None:
            return verdict
        gray, stream_s, hands, baby = self.held_anchor
        self.held_anchor = None
        self.lift.anchor(gray, hands, baby, stream_s)
        based = self.lift.base is not None
        self.held_lost = False
        self.bus.publish("anchor", stream_s=round(stream_s, 3), hands=len(hands), based=based, held=True)
        return "on" if based else "off"

    def _anchor(self, frame_bgr, gray, stream_s):
        """lift.regions sam3: land a finished SAM 3.1 anchor, and send a resting frame when the check asks for one."""
        if self.masks is None:
            return
        if self.anchor_job and self.anchor_job[2].done():
            anchor_gray, anchor_s, future = self.anchor_job
            self.anchor_job = None
            try:
                hands, baby = future.result()
            except Exception as error:  # no anchor, no reading: the reflex and SAM 3.1 confirm still run
                self.bus.publish("anchor_error", error=str(error)[:200])
            else:
                self.lift.anchor(anchor_gray, hands, baby, anchor_s)
                self.bus.publish("anchor", stream_s=round(anchor_s, 3), hands=len(hands), based=self.lift.base is not None)
        confirm_first = self.alarm.raised or self.confirm_due or self.confirm.pending  # one GPU: the confirm goes first
        if self.anchor_job is None and self.lift.wants_anchor and not self.lift.lifted and not confirm_first:
            self.bus.publish("anchor_request", stream_s=round(stream_s, 3))
            self.anchor_job = (gray, stream_s, self.anchor_pool.submit(self.masks, frame_bgr.copy()))

    def close(self, content=None):
        if self.anchor_pool:
            self.anchor_pool.shutdown(wait=True)
        self.confirm.close()
        ended = datetime.datetime.now(datetime.timezone.utc)
        self.house.on_event("closed")
        self.tracker.skill_closed(self.cfg["name"], self.armed_at or ended, ended, content)
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
