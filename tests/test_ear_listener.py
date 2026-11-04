"""The Mac's ear: what reaches the core is one label, in words, and never audio or numbers about it."""
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from parenting_agent import hearing, hearing_worker

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


class CryRule(unittest.TestCase):
    FLOOR = hearing.CRY_RULE["floor"]

    def test_a_voice_that_scores_as_a_cry_but_higher_as_a_man_does_not_count(self):
        margin = hearing_worker.rival_margin(np.array([7.0, 8.0]), np.array([6.0, 6.0]), self.FLOOR)
        self.assertLess(margin, hearing.CRY_RULE["margin"])

    def test_a_cry_over_the_floor_that_beats_its_rivals_counts(self):
        margin = hearing_worker.rival_margin(np.array([1.0, 8.0]), np.array([-5.0, 1.0]), self.FLOOR)
        self.assertEqual(margin, 7.0)

    def test_a_frame_under_the_floor_never_counts_however_far_it_beats_its_rivals(self):
        margin = hearing_worker.rival_margin(np.array([5.0]), np.array([-20.0]), self.FLOOR)
        self.assertEqual(margin, hearing_worker.NO_MARGIN)
        self.assertLess(margin, hearing.CRY_RULE["margin"])

    def test_the_listener_runs_the_rule_and_the_shared_default_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder)
            (model / "model.safetensors").write_text("")
            (model / "python").write_text("")
            def started(config):
                with mock.patch("subprocess.Popen") as popen:
                    popen.return_value.stdout = io.BytesIO(b'{"ready": true}\n')
                    listener = hearing.MetaListener({"python": str(model / "python"), "model_dir": str(model), **config})
                    return listener, json.loads(popen.call_args.kwargs["env"]["HEARING_CONFIG"])
            ruled, cfg = started(ear_listener.listener_config("cpu"))
            self.assertEqual(cfg["cry_rule"], hearing.CRY_RULE)
            self.assertEqual(cfg["modes"]["cry"], "rival_margin")
            self.assertEqual(ruled.thresholds["cry"], hearing.CRY_RULE["margin"])
            shared, cfg = started({})
            self.assertNotIn("cry_rule", cfg)
            self.assertEqual(cfg["modes"]["cry"], "logit")
            self.assertEqual(shared.thresholds["cry"], hearing.THRESHOLDS["cry"])


class CameraPort(unittest.TestCase):
    CAMERA = {"TAPO_USER": "u", "TAPO_PASS": "p", "TAPO_HOST": "127.0.0.1"}

    def test_the_port_is_554_unless_the_environment_names_a_relay(self):
        self.assertEqual(hearing.camera_url(self.CAMERA), "rtsp://u:p@127.0.0.1:554/stream2")
        self.assertEqual(hearing.camera_url({**self.CAMERA, "TAPO_PORT": ""}), "rtsp://u:p@127.0.0.1:554/stream2")
        self.assertEqual(hearing.camera_url({**self.CAMERA, "TAPO_PORT": "18554"}), "rtsp://u:p@127.0.0.1:18554/stream2")


if __name__ == "__main__":
    unittest.main()
