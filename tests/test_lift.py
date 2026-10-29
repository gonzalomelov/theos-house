import unittest

import cv2
import numpy as np

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


if __name__ == "__main__":
    unittest.main()
