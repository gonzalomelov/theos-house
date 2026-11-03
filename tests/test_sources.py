"""Frame sources: the newest-frame slot, a looping file, and the phone page over plain http on 127.0.0.1."""
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from parenting_agent.sam3_worker import ring_state
from parenting_agent.sources import Latest, PhoneSource, VideoSource, open_source

DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def wait_for(check, seconds=5):
    limit = time.monotonic() + seconds
    while time.monotonic() < limit:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out")


class SlotTest(unittest.TestCase):
    def test_only_the_newest_frame_and_only_once(self):
        slot = Latest()
        self.assertIsNone(slot.latest(0))
        slot.put("a", 0.1)
        slot.put("b", 0.2)
        self.assertEqual(slot.latest(0), ("b", 2, 0.2))
        self.assertIsNone(slot.latest(2))


class VideoTest(unittest.TestCase):
    def test_a_file_plays_paced_and_stops_when_not_looping(self):
        with tempfile.TemporaryDirectory() as folder:
            clip = str(Path(folder) / "clip.avi")
            writer = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"MJPG"), 20.0, (32, 32))
            for shade in range(10):
                writer.write(np.full((32, 32, 3), shade * 20, np.uint8))
            writer.release()
            source = VideoSource(clip, loops=False)
            wait_for(lambda: source.stopped)
            frame, seq, stream_s = source.latest(0)
            self.assertEqual((seq, frame.shape), (10, (32, 32, 3)))
            self.assertAlmostEqual(stream_s, 9 / 20, places=3)

    def test_a_looping_file_goes_past_its_end(self):
        with tempfile.TemporaryDirectory() as folder:
            clip = str(Path(folder) / "clip.avi")
            writer = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"MJPG"), 100.0, (16, 16))
            for _ in range(3):
                writer.write(np.zeros((16, 16, 3), np.uint8))
            writer.release()
            source = open_source(clip)
            self.addCleanup(source.close)
            wait_for(lambda: source.seq > 6)


class PhoneTest(unittest.TestCase):
    def setUp(self):
        self.source = PhoneSource(port=0, host="127.0.0.1")
        self.addCleanup(self.source.close)

    def test_page_frame_and_refusals(self):
        page = DIRECT.open(self.source.url, timeout=5).read().decode()
        self.assertIn("getUserMedia", page)
        jpeg = cv2.imencode(".jpg", np.zeros((8, 8, 3), np.uint8))[1].tobytes()
        post = lambda path, body: DIRECT.open(urllib.request.Request(self.source.url + path, data=body), timeout=5)
        self.assertEqual(post("frame", jpeg).status, 204)
        self.assertEqual(self.source.latest(0)[0].shape, (8, 8, 3))
        with self.assertRaises(urllib.error.HTTPError) as other:
            post("other", b"x")
        self.assertEqual(other.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as large:
            DIRECT.open(urllib.request.Request(self.source.url + "frame", data=b"x", headers={"Content-Length": "2000001"}), timeout=5)
        self.assertEqual(large.exception.code, 413)

    def test_a_chime_reaches_the_listening_page(self):
        stream = DIRECT.open(self.source.url + "events", timeout=5)
        wait_for(lambda: self.source.clients)
        self.source.push({"kind": "chime"})
        self.assertEqual(json.loads(stream.readline().decode().removeprefix("data: ")), {"kind": "chime"})
        stream.close()


class RingTest(unittest.TestCase):
    CFG = {"ring_px": 2, "ring_min": 0.35, "min_hand_area": 0.01}

    def scene(self, gap):
        baby, hand = np.zeros((60, 60), bool), np.zeros((60, 60), bool)
        baby[30:, :] = True
        hand[30 - gap - 10:30 - gap, 20:40] = True
        return hand, baby

    def test_a_hand_against_the_baby_reads_on_and_one_away_reads_off(self):
        share_touching = ring_state([self.scene(0)[0]], self.scene(0)[1], self.CFG)[1][0]
        state_away, shares_away = ring_state([self.scene(10)[0]], self.scene(10)[1], self.CFG)
        self.assertGreater(share_touching, 0)
        self.assertEqual((state_away, shares_away), ("off", [0.0]))

    def test_a_tiny_mask_is_skipped_and_no_baby_is_unknown(self):
        speck = np.zeros((60, 60), bool)
        speck[0, 0] = True
        self.assertEqual(ring_state([speck], self.scene(0)[1], self.CFG), ("off", []))
        self.assertEqual(ring_state([self.scene(0)[0]], np.zeros((60, 60), bool), self.CFG)[0], "unknown")


if __name__ == "__main__":
    unittest.main()
