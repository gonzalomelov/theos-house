"""A frame posted to the glasses endpoint is kept, and its arrival time can be read back."""
import unittest

from parenting_agent.glasses import GlassesHub

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None


class FrameTest(unittest.TestCase):
    def test_arrival_is_none_for_an_unknown_frame(self):
        self.assertIsNone(GlassesHub(port=0).arrival(1.0))

    @unittest.skipUnless(cv2, "needs OpenCV")
    def test_a_posted_frame_is_kept(self):
        hub = GlassesHub(port=0)
        ok, jpeg = cv2.imencode(".jpg", np.zeros((8, 8, 3), np.uint8))
        self.assertTrue(ok)
        self.assertTrue(hub._frame(jpeg.tobytes()))
        frame, seq, stream_s = hub.latest(0)
        self.assertEqual(seq, 1)
        self.assertIsNotNone(hub.arrival(stream_s))
