"""hands "sam3_only": the camera skills watch with SAM 3.1 alone, no MediaPipe and no prior work library.
Offline: a scripted stand-in answers with masks, no model loads."""
import copy
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import numpy as np

from parenting_agent import config as config_mod
from parenting_agent import hands as hands_mod
from parenting_agent.bus import Bus
from parenting_agent.sam_hands import SamAlarm, SamOnlySkill, touching

ROOT = Path(__file__).resolve().parent.parent
SHAPE = (360, 640)


def masks_for(on):
    baby = np.zeros(SHAPE, bool)
    baby[100:260, 200:440] = True
    hand = np.zeros(SHAPE, bool)
    if on:
        hand[150:200, 250:300] = True
    else:
        hand[10:40, 10:40] = True
    return [hand], baby


class ScriptedSam:
    """masks(frame, held) answers on for the first on_looks looks, then off."""
    name = "sam3_local"

    def __init__(self, on_looks):
        self.on_looks, self.looks = on_looks, 0

    def masks(self, frame_bgr, held=False):
        self.looks += 1
        return masks_for(self.looks <= self.on_looks)

    def judge(self, frame_bgr):
        return "unsure"


def config():
    cfg = copy.deepcopy(config_mod.load("skills/changing-table.json"))
    cfg["lift"]["enabled"] = False
    cfg["house"] = {"allowed": {}, "on_armed": [], "on_voice": [], "on_closed": []}
    cfg["tracking"] = {"provider": "none", "on_closed": None}
    return cfg


def run(skill, frames, step=0.1):
    frame = np.zeros((*SHAPE, 3), np.uint8)
    for i in range(frames):
        skill.on_frame(frame, i * step)
        time.sleep(0.01)  # lets the background look land


class SamOnly(unittest.TestCase):
    def test_both_hands_off_is_spoken_at_the_first_look_that_sees_it(self):
        bus = Bus()
        skill = SamOnlySkill(config(), bus, ScriptedSam(on_looks=3))
        skill.arm()
        run(skill, 40)
        skill.close()
        voices = [e for e in bus.history if e["kind"] == "voice"]
        self.assertEqual(len(voices), 1)
        self.assertEqual((voices[0]["reason"], voices[0]["text"]), ("sam3", "hand"))
        self.assertEqual(bus.count("chime"), 1)
        self.assertEqual([e["mode"] for e in bus.history if e["kind"] == "hands_mode"], ["sam3_only"])

    def test_hands_on_stay_silent(self):
        bus = Bus()
        skill = SamOnlySkill(config(), bus, ScriptedSam(on_looks=10_000))
        run(skill, 30)
        skill.close()
        self.assertEqual((bus.count("voice"), bus.count("chime")), (0, 0))

    def test_no_sam_no_watch(self):
        from parenting_agent.confirm import NoConfirm
        with self.assertRaises(RuntimeError):
            SamOnlySkill(config(), Bus(), NoConfirm())

    def test_touching_uses_the_baby_mask(self):
        self.assertTrue(touching(*masks_for(True)))
        self.assertFalse(touching(*masks_for(False)))
        self.assertFalse(touching(masks_for(True)[0], None))


class TexturedHands:
    """A head camera frame: a textured table, and the textured hand patch on the baby while hands_on."""
    HAND = (slice(140, 250), slice(260, 380))

    def __init__(self):
        import cv2

        def noise(seed):
            cells = np.random.default_rng(seed).integers(0, 255, (90, 160), np.uint8)
            return cv2.GaussianBlur(cv2.resize(cells, SHAPE[::-1], interpolation=cv2.INTER_NEAREST), (3, 3), 0)
        self.table, self.hand = noise(1), noise(2)

    def frame(self, hands_on):
        import cv2
        gray = self.table.copy()
        if hands_on:
            gray[self.HAND] = self.hand[self.HAND]
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


class SlowSam:
    """SAM 3.1 that reads the frame it was sent (hand patch there or not) and answers look_s later in stream time."""
    name = "sam3_local"

    def __init__(self, scene):
        import threading
        self.scene, self.release = scene, threading.Event()

    def masks(self, frame_bgr, held=False):
        self.release.wait(5)
        self.release.clear()
        hand = np.zeros(SHAPE, bool)
        hand[TexturedHands.HAND] = True
        baby = np.zeros(SHAPE, bool)
        baby[100:300, 200:440] = True
        on = np.array_equal(frame_bgr[TexturedHands.HAND][..., 0], self.scene.hand[TexturedHands.HAND])
        return ([hand] if on else []), baby


class HandsLeaveTheLens(unittest.TestCase):
    """Live Oct 31 (results/glasses-live-sam3): the lens kept "Hand on the baby" 3.3 s after both hands left, because
    a 2 s look sent while the hands were still there had to land first. The lift check reads the anchored regions
    gone in under 1 s and the lens clears, while the voice still waits for SAM 3.1."""
    STEP, LOOK_S = 1 / 3, 2.0  # about 3 frames a second and 2 s a look, as live

    def watch(self, on_until, frames=60):
        cfg = config()
        cfg["lift"]["enabled"] = True
        bus, scene = Bus(), TexturedHands()
        sam = SlowSam(scene)
        skill = SamOnlySkill(cfg, bus, sam)
        skill.arm()
        for i in range(frames):
            t = i * self.STEP
            if skill.job is not None and t - skill.job[1] >= self.LOOK_S - 1e-9:
                sam.release.set()
                skill.job[2].result(timeout=5)
            skill.on_frame(scene.frame(on_until(t)), t)
        sam.release.set()
        skill.close()
        return bus

    def frames(self, bus):
        return [(e["stream_s"], e["state"]) for e in bus.history if e["kind"] == "frame"]

    def test_the_lens_clears_within_a_second_of_the_hands_leaving(self):
        left = 9.1
        bus = self.watch(lambda t: t < left)
        states = self.frames(bus)
        self.assertEqual({s for t, s in states if 3 < t < left}, {"on"})  # no flicker while the hands rest
        first_off = min(t for t, s in states if t >= left and s == "off")
        self.assertLessEqual(first_off - left, 1.0)
        self.assertTrue(all(s == "off" for t, s in states if t >= first_off))  # stays off, the stale look is ignored
        voice = [e["stream_s"] for e in bus.history if e["kind"] == "voice"]
        self.assertEqual(len(voice), 1)  # spoken once, by the look that saw no hand
        self.assertGreater(voice[0], first_off)
        self.assertEqual(bus.count("chime"), 1)

    def test_resting_hands_never_read_gone(self):
        bus = self.watch(lambda t: True)
        self.assertEqual({s for t, s in self.frames(bus) if t > 3}, {"on"})
        self.assertEqual((bus.count("hands_gone"), bus.count("chime"), bus.count("voice")), (0, 0, 0))

    def test_hands_back_before_a_fresh_look_never_alert(self):
        bus = self.watch(lambda t: not 9.1 <= t < 9.9)
        self.assertEqual((bus.count("chime"), bus.count("voice")), (0, 0))
        self.assertEqual(self.frames(bus)[-1][1], "on")


class Alarm(unittest.TestCase):
    CFG = {"voice_hold_s": 1.2, "clear_after_on_s": 0.5, "voice_text": "hand"}

    def test_a_lift_chimes_at_once_and_speaks_after_the_hold(self):
        bus = Bus()
        alarm = SamAlarm(bus, self.CFG)
        alarm.on_state("on", 0.0)
        alarm.on_state("lifted", 1.0)
        self.assertEqual((bus.count("chime"), bus.count("voice")), (1, 0))
        alarm.on_state("lifted", 2.3)
        self.assertEqual(bus.count("voice"), 1)

    def test_back_on_before_the_hold_drops_the_prompt(self):
        bus = Bus()
        alarm = SamAlarm(bus, self.CFG)
        alarm.on_state("lifted", 1.0)
        alarm.on_state("on", 1.3)
        alarm.on_state("on", 1.9)
        self.assertEqual(bus.count("voice"), 0)
        self.assertEqual([e["action"] for e in bus.history if e["kind"] == "alarm"], ["raise", "clear"])
        self.assertEqual(bus.count("voice_dropped"), 1)

    def test_unknown_before_the_first_look_does_nothing(self):
        bus = Bus()
        SamAlarm(bus, self.CFG).on_state(None, 0.0)
        self.assertEqual(len(bus.history), 0)


class Setting(unittest.TestCase):
    def test_every_setting_runs_sam(self):
        self.assertEqual(hands_mod.mode(None), "sam3_only")
        self.assertEqual(hands_mod.mode("auto"), "sam3_only")
        with self.assertRaises(ValueError):
            hands_mod.mode("mediapipe")

    def test_build_gives_the_sam_only_skill(self):
        skill = hands_mod.build(config(), Bus(), "sam3_only", confirm_detector=ScriptedSam(1))
        self.assertIsInstance(skill, SamOnlySkill)
        skill.close()

    def test_no_runtime_code_imports_mediapipe(self):
        for path in (ROOT / "parenting_agent").rglob("*.py"):
            source = path.read_text()
            self.assertNotIn("import mediapipe", source, path)
            self.assertNotIn("from mediapipe", source, path)
        self.assertNotIn("mediapipe", (ROOT / "requirements.txt").read_text())


if __name__ == "__main__":
    unittest.main()
