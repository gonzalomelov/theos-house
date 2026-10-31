import unittest

import cv2
import numpy as np

from parenting_agent import alarm as _prior_alarm  # noqa: E402

if not _prior_alarm.AVAILABLE:  # the MediaPipe path is prior work in a private repo (requirements-prior.txt)
    raise unittest.SkipTest("needs the prior work library, the SAM 3.1 only path is in test_sam_hands")

from parenting_agent.alarm import Alarm
from parenting_agent.bus import Bus
from parenting_agent.lift import LiftCheck

W, H, CAMERA_CM = 640, 360, 45.0
HAND = np.array([[260, 140], [380, 140], [380, 250], [260, 250]], np.float32)


def scene(seed=1):
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 255, (H // 4, W // 4), np.uint8)
    return cv2.GaussianBlur(cv2.resize(noise, (W, H), interpolation=cv2.INTER_NEAREST), (3, 3), 0)


def frame(lift_cm, background, hand_texture):
    """The hand patch lifted lift_cm toward a camera CAMERA_CM above, as the head camera sees it: zoomed about the centre."""
    out = background.copy()
    mask = np.zeros((H, W), np.uint8)
    cv2.fillConvexPoly(mask, HAND.astype(np.int32), 1)
    scale = CAMERA_CM / (CAMERA_CM - lift_cm)
    zoom = cv2.getRotationMatrix2D((W / 2, H / 2), 0, scale)
    hand = cv2.warpAffine(hand_texture, zoom, (W, H))
    moved = cv2.warpAffine(mask, zoom, (W, H)).astype(bool)
    out[moved] = hand[moved]
    landmarks = (HAND - HAND.mean(axis=0)) / 1.18 + HAND.mean(axis=0)  # landmarks lie inside the hand, the hull is grown 1.18
    return out, [(landmarks - [W / 2, H / 2]) * scale + [W / 2, H / 2]]


class LiftTest(unittest.TestCase):
    def run_check(self, lifts):
        background, texture = scene(1), scene(2)
        check = LiftCheck({"camera_cm": CAMERA_CM, "refresh_s": 100})
        out = []
        for i, lift in enumerate(lifts):
            gray, hands = frame(lift, background, texture)
            out.append(check.update(gray, hands, i / 15))
        return out, check

    def test_resting_hand_never_reads_lifted(self):
        lifted, check = self.run_check([0.0] * 20)
        self.assertFalse(any(lifted))
        self.assertLess(abs(check.lift_cm), 0.3)

    def test_two_cm_lift_reads_lifted_and_measures_it(self):
        lifted, check = self.run_check([0.0] * 8 + [2.0] * 8)
        self.assertFalse(any(lifted[:8]))
        self.assertTrue(lifted[-1])
        self.assertAlmostEqual(check.lift_cm, 2.0, delta=0.4)

    def test_hand_coming_back_down_rests_again(self):
        lifted, _ = self.run_check([0.0] * 8 + [3.0] * 8 + [0.0] * 8)
        self.assertTrue(lifted[15])
        self.assertFalse(lifted[-1])

    def test_no_hands_resets(self):
        _, check = self.run_check([0.0] * 6)
        self.assertFalse(check.update(scene(1), [], 1.0))
        self.assertIsNone(check.base)


    def test_bath_asks_for_both_hands_one_hand_never_reads_lifted(self):
        background, texture = scene(1), scene(2)
        check = LiftCheck({"camera_cm": CAMERA_CM, "refresh_s": 100, "min_hands": 2})
        out = [check.update(*frame(lift, background, texture), i / 15) for i, lift in enumerate([0.0] * 8 + [3.0] * 8)]
        self.assertFalse(any(out))
        self.assertIsNone(check.base)


class SamRegionsTest(unittest.TestCase):
    def hand_mask(self):
        mask = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(mask, HAND.astype(np.int32), 1)
        return mask.astype(bool)

    def test_no_anchor_no_reading(self):
        check = LiftCheck({"camera_cm": CAMERA_CM, "regions": "sam3"})
        gray, hands = frame(3.0, scene(1), scene(2))
        self.assertFalse(check.update(gray, hands, 0.0))
        self.assertTrue(check.wants_anchor)
        self.assertIsNone(check.lift_cm)

    def test_anchored_hand_mask_measures_the_lift(self):
        background, texture = scene(1), scene(2)
        check = LiftCheck({"camera_cm": CAMERA_CM, "regions": "sam3", "refresh_s": 100})
        rest, _ = frame(0.0, background, texture)
        check.anchor(rest, [self.hand_mask()], None, 0.0)
        self.assertFalse(check.wants_anchor)
        out = [check.update(*frame(lift, background, texture), 0.1 + i / 15) for i, lift in enumerate([0.0] * 6 + [2.5] * 8)]
        self.assertFalse(any(out[:6]))
        self.assertTrue(out[-1])
        self.assertAlmostEqual(check.lift_cm, 2.5, delta=0.5)

    def test_hand_away_from_the_baby_is_not_anchored(self):
        check = LiftCheck({"camera_cm": CAMERA_CM, "regions": "sam3"})
        baby = np.zeros((H, W), bool)
        baby[300:, :100] = True
        check.anchor(scene(1), [self.hand_mask()], baby, 0.0)
        self.assertIsNone(check.base)


class LiftedAlarmTest(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        contact = {"off_frames_to_alert": 1}
        self.alarm = Alarm(self.bus, contact, {"voice_hold_s": 1.2, "confirm_wait_s": 2.3, "clear_after_on_s": 0.5,
                                               "voice_text": "hand"}, waits_for_confirm=True)

    def voices(self):
        return [e for e in self.bus.history if e["kind"] == "voice"]

    def test_lifted_reading_raises_and_a_confirm_on_cannot_cancel_it(self):
        self.alarm.on_reflex("on", 0.0, lifted=True)
        self.alarm.on_confirm(1, "on", 0.5)
        self.alarm.on_reflex("on", 1.3, lifted=True)
        self.assertEqual(len(self.voices()), 1)

    def test_lifted_reading_reraises_an_alarm_the_detector_cancelled(self):
        self.alarm.on_reflex("off", 0.0, near=True)
        self.alarm.on_confirm(1, "on", 0.4)
        self.assertTrue(self.alarm.cancelled)
        self.alarm.on_reflex("on", 0.5, lifted=True)
        self.alarm.on_reflex("on", 1.8, lifted=True)
        self.assertEqual(len(self.voices()), 1)
        self.assertEqual(self.alarm.episode, 2)


class HeldRegionTest(unittest.TestCase):
    """A grip on a diaper hides the hand from MediaPipe: the anchored SAM 3.1 region is followed instead (results/hover/held)."""

    def anchored(self):
        background, texture = scene(1), scene(2)
        check = LiftCheck({"camera_cm": CAMERA_CM, "regions": "sam3", "refresh_s": 100})
        mask = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(mask, HAND.astype(np.int32), 1)
        check.anchor(frame(0.0, background, texture)[0], [mask.astype(bool)], None, 0.0)
        return check, background, texture

    def test_no_anchor_no_held_reading(self):
        check = LiftCheck({"camera_cm": CAMERA_CM, "regions": "sam3"})
        self.assertIsNone(check.held(scene(1), 0.0))

    def test_region_in_place_reads_on_and_a_lift_reads_lifted(self):
        check, background, texture = self.anchored()
        out = [check.held(frame(lift, background, texture)[0], 0.1 + i / 15) for i, lift in enumerate([0.0] * 6 + [3.0] * 8)]
        self.assertEqual(set(out[:6]), {"on"})
        self.assertEqual(out[-1], "lifted")

    def test_region_that_leaves_reads_gone_after_held_gone_s(self):
        check, background, _ = self.anchored()
        out = [check.held(background, 0.1 + i / 15) for i in range(8)]
        self.assertEqual(out[0], "on")  # held through a short miss
        self.assertEqual(out[-1], "gone")


class UnseenAlarmTest(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.alarm = Alarm(self.bus, {"off_frames_to_alert": 1}, {"voice_hold_s": 1.2, "confirm_wait_s": 2.3,
                                                                  "clear_after_on_s": 0.5, "voice_text": "hand"},
                           waits_for_confirm=True)

    def voices(self):
        return [e for e in self.bus.history if e["kind"] == "voice"]

    def test_unseen_alarm_waits_past_the_voice_hold_and_a_confirm_on_cancels_it(self):
        for i in range(19):
            self.alarm.on_reflex("off", i * 0.1, unseen=True)
        self.assertEqual(self.voices(), [])
        self.alarm.on_confirm(1, "on", 1.9)
        self.alarm.on_reflex("off", 2.5)
        self.assertEqual(self.voices(), [])

    def test_unseen_alarm_speaks_at_the_confirm_wait_without_an_answer(self):
        for i in range(25):
            self.alarm.on_reflex("off", i * 0.1, unseen=True)
        self.assertEqual(len(self.voices()), 1)

    def test_seen_alarm_keeps_the_voice_hold(self):
        for i in range(13):
            self.alarm.on_reflex("off", i * 0.1)
        self.assertEqual(len(self.voices()), 1)


class HiddenReflex:
    """MediaPipe that never finds the hand: off with no hands, every frame."""
    near, on_hands, landmarks_px = False, [], []

    def state(self, frame):
        return "off", 0, 0.001


class HeldMasks:
    name = "sam3_local"

    def __init__(self, mask):
        self.mask, self.held_calls = mask, 0

    def judge(self, frame_bgr):  # asked only after the hand left
        return "off"

    def masks(self, frame_bgr, held=False):
        self.held_calls += held
        return [self.mask], None


class HeldSkillTest(unittest.TestCase):
    def run_skill(self, lifts):
        from parenting_agent import config as config_mod
        from parenting_agent.skill import Skill
        from parenting_agent.tracking import Tracker
        background, texture = scene(1), scene(2)
        mask = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(mask, HAND.astype(np.int32), 1)
        cfg = config_mod.load("skills/changing-table.json")
        cfg = dict(cfg, house={"allowed": {}, "on_armed": [], "on_voice": [], "on_closed": []})
        bus, detector = Bus(), HeldMasks(mask.astype(bool))
        skill = Skill(cfg, bus, HiddenReflex(), confirm_detector=detector, tracker=Tracker({"on_closed": None}, bus))
        for i, lift in enumerate(lifts):
            gray = frame(lift, background, texture)[0] if lift is not None else background
            skill.on_frame(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), i / 15)
            skill.confirm.pending and skill.confirm.pending[2].result()
            skill.confirm.collect()
        skill.close()
        return bus, detector

    def voices(self, bus):
        return [e["stream_s"] for e in bus.history if e["kind"] == "voice"]

    def test_hidden_hand_resting_stays_silent(self):
        bus, detector = self.run_skill([0.0] * 60)
        self.assertEqual(detector.held_calls, 1)
        self.assertEqual(self.voices(bus), [])

    def test_hidden_hand_lifting_speaks(self):
        bus, _ = self.run_skill([0.0] * 30 + [3.0] * 30)
        self.assertEqual(len(self.voices(bus)), 1)
        self.assertGreater(self.voices(bus)[0], 2.0)

    def test_hidden_hand_leaving_speaks(self):
        bus, _ = self.run_skill([0.0] * 30 + [None] * 30)
        self.assertEqual(len(self.voices(bus)), 1)
        self.assertGreater(self.voices(bus)[0], 2.0)


if __name__ == "__main__":
    unittest.main()
