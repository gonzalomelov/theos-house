"""The lift check on the SAM 3.1 hand regions, which runs between looks."""
import unittest

import cv2
import numpy as np

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


if __name__ == "__main__":
    unittest.main()
