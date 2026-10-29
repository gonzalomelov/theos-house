"""The SAM 3.1 contact ring around a hand and what it holds (parenting_agent/sam3_worker.py, results/hover/held)."""
import unittest

import numpy as np

from parenting_agent.sam3_worker import DEFAULTS, holding, ring_state

CFG = {**DEFAULTS, "min_hand_area": 0.001}


def box(x1, y1, x2, y2, shape=(200, 200)):
    mask = np.zeros(shape, bool)
    mask[y1:y2, x1:x2] = True
    return mask


class HeldRing(unittest.TestCase):
    def setUp(self):
        self.hand = box(80, 50, 120, 90)  # its fingers on the wipe, the baby only above it
        self.wipe = box(70, 90, 130, 140)  # in the hand, pressed on the baby, which SAM 3.1 sees around it
        self.baby = box(0, 100, 200, 200) & ~self.wipe

    def test_a_wipe_between_hand_and_baby_hides_the_contact(self):
        self.assertEqual(ring_state([self.hand], self.baby, CFG)[0], "off")

    def test_the_hand_with_what_it_holds_reads_on(self):
        self.assertEqual(ring_state(holding([self.hand], [self.wipe], CFG), self.baby, CFG)[0], "on")

    def test_an_object_away_from_the_hand_is_not_held(self):
        far = box(150, 10, 190, 30)
        self.assertFalse((holding([self.hand], [far], CFG)[0] & far).any())

    def test_no_objects_keeps_the_hands(self):
        self.assertIs(holding([self.hand], [], CFG)[0], self.hand)


if __name__ == "__main__":
    unittest.main()
