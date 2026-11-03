"""The Mac's ear: what reaches the core is one label, in words, and never audio or numbers about it."""
import importlib.util
import unittest
from pathlib import Path

import numpy as np

from parenting_agent import hearing

spec = importlib.util.spec_from_file_location("ear_listener", Path(__file__).resolve().parent.parent / "scripts/ear_listener.py")
ear_listener = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ear_listener)


class Scripted:
    thresholds = hearing.THRESHOLDS

    def __init__(self, seconds):
        self.seconds, self.at = seconds, 0

    def score(self, samples):
        self.at += 1
        return {"scores": {label: 9.0 for label in self.seconds.get(self.at, ())}}


class EarToCore(unittest.TestCase):
    def setUp(self):
        self.sent, self.now = [], 0.0
        self.sink = ear_listener.ToCore(self.sent.append, clock=lambda: self.now)

    def play(self, seconds, length=40, settings=None):
        ear = hearing.Ear(Scripted(seconds), self.sink, settings or {"cry_report_s": 8}, "living room")
        for _ in range(length):
            ear.feed(np.zeros(hearing.STEP, np.float32))

    def test_a_long_cry_is_one_event_with_only_words_after_the_report_time(self):
        self.play({i: ("cry",) for i in range(1, 30)})
        self.assertEqual(self.sent, [{"type": "sound", "source": "ear", "payload": {"kind": "a baby crying", "room": "living room"}}])

    def test_a_short_cry_is_sent_when_it_ends(self):
        self.play({i: ("cry",) for i in range(1, 4)})
        self.assertEqual(len(self.sent), 1)

    def test_labels_not_asked_for_stay_on_this_mac(self):
        self.play({i: ("dog", "splash", "doorbell") for i in range(1, 10)})
        self.assertEqual(self.sent, [])

    def test_crying_that_comes_and_goes_waits_for_the_cooldown(self):
        self.play({3: ("cry",), 20: ("cry",)})
        self.assertEqual(len(self.sent), 1)
        self.now = 121.0
        self.play({3: ("cry",)})
        self.assertEqual(len(self.sent), 2)


if __name__ == "__main__":
    unittest.main()
