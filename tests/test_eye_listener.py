"""The Mac's eye: only a close dog reaches the core, as a verdict with no pixels. Offline, with a scripted SAM 3.1."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import eye_listener  # noqa: E402
from parenting_agent import dog_watch  # noqa: E402
from parenting_agent.bus import Bus  # noqa: E402

SHAPE = (360, 640)


def box(x0, y0, x1, y1):
    mask = np.zeros(SHAPE, bool)
    mask[y0:y1, x0:x1] = True
    return mask


class Scripted:
    def __init__(self, found):
        self.found = found

    def masks(self, frame, prompts):
        return self.found, 0.01


def run(found):
    sent = []
    cfg = dict(dog_watch.DEFAULTS)
    watch = dog_watch.Watch(cfg, Bus(), Scripted(found), eye_listener.ToCore(sent.append))
    frame = np.zeros((*SHAPE, 3), np.uint8)
    watch.look(frame)
    watch.look(frame)
    return sent


BABY = [(0.9, box(300, 150, 360, 210))]


class Eye(unittest.TestCase):
    def test_a_close_dog_sends_one_event_with_no_pixels(self):
        sent = run({"dog": [(0.9, box(370, 150, 420, 210))], "baby": BABY})
        self.assertEqual(len(sent), 1, "the rate limit keeps it to one")
        self.assertEqual(sent[0]["type"], "camera")
        self.assertEqual(sent[0]["payload"]["saw"], "a dog close to the baby")
        self.assertLess(len(json.dumps(sent[0])), 200)

    def test_a_far_dog_sends_nothing(self):
        self.assertEqual(run({"dog": [(0.9, box(0, 0, 20, 20))], "baby": BABY}), [])

    def test_a_dog_alone_or_an_empty_room_sends_nothing(self):
        self.assertEqual(run({"dog": [(0.9, box(0, 0, 20, 20))]}), [])
        self.assertEqual(run({}), [])

    def test_a_camera_error_never_shows_the_address(self):
        with self.assertRaises(Exception) as caught:
            eye_listener.camera_frame("rtsp://user:secret@127.0.0.1:1/none", timeout=5)
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
