"""The live glasses HUD path (results/glasses-live): one SAM 3.1 process for the whole agent, kept between changes and
shared with the dog look on the glasses frames, the held object named, and the dog alert captured, never sent."""
import io
import json
import struct
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from parenting_agent import alarm as _prior_alarm  # noqa: E402

if not _prior_alarm.AVAILABLE:  # the MediaPipe path is prior work in a private repo (requirements-prior.txt)
    raise unittest.SkipTest("needs the prior work library, the SAM 3.1 only path is in test_sam_hands")

from parenting_agent import confirm as confirm_mod
from parenting_agent import dog_watch, sam3_local
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.bus import Bus
from parenting_agent.sam3_worker import DEFAULTS, held_objects
from parenting_agent.sources import Latest
from tests.test_changing_table import FakeReflex, FakeSource, wait_until
from tests.test_dog_watch import BABY, FakeSegmenter, box, found


def mask(x1, y1, x2, y2, shape=(200, 200)):
    out = np.zeros(shape, bool)
    out[y1:y2, x1:x2] = True
    return out


class HeldObjects(unittest.TestCase):
    CFG = {**DEFAULTS, "min_hand_area": 0.001}

    def test_names_what_the_hand_holds_and_not_the_worn_diaper(self):
        hand = mask(80, 50, 120, 90)
        baby = mask(0, 100, 200, 200)
        held = mask(70, 88, 130, 99)  # in the hand, above the baby
        worn = mask(20, 150, 60, 190)  # inside the baby mask: the baby's own diaper
        far = mask(150, 10, 190, 30)
        self.assertEqual(held_objects([hand], {"diaper": [worn, held], "wipe": [far]}, self.CFG, baby), ["diaper"])
        self.assertEqual(held_objects([hand], {"diaper": [worn]}, self.CFG, baby), [])


class FakeWorker(sam3_local.Sam3Local):
    """A Sam3Local without the model: its stdin and stdout are in memory."""

    def __init__(self, replies, alive=True):
        self.process = type("P", (), {"poll": lambda self: None if alive else 0})()
        self.process.stdin = io.BytesIO()
        self.process.stdout = io.BytesIO(b"".join(json.dumps(r).encode() + b"\n" for r in replies))
        self.lock = __import__("threading").Lock()
        self.codec = "png"


class SharedWorker(unittest.TestCase):
    def tearDown(self):
        sam3_local._LIVE.clear()

    def test_live_is_the_running_worker(self):
        self.assertIsNone(sam3_local.live())
        dead, running = FakeWorker([], alive=False), FakeWorker([])
        sam3_local._LIVE.extend([running, dead])
        self.assertIs(sam3_local.live(), running)

    def test_prompt_masks_ride_on_the_confirm_worker(self):
        import base64
        import cv2
        png = base64.b64encode(cv2.imencode(".png", mask(10, 10, 50, 50).astype(np.uint8) * 255)[1].tobytes()).decode()
        worker = FakeWorker([{"seconds": 0.8, "found": {"dog": [{"score": 0.93, "box": [], "mask": png}], "baby": []}}])
        found_masks, seconds = worker.prompt_masks(np.zeros((200, 200, 3), np.uint8), ["dog", "baby"])
        self.assertEqual(seconds, 0.8)
        self.assertEqual(found_masks["dog"][0][0], 0.93)
        self.assertTrue(found_masks["dog"][0][1][20, 20] and not found_masks["dog"][0][1][100, 100])
        sent = worker.process.stdin.getvalue()
        size = struct.unpack(">I", sent[:4])[0]
        self.assertTrue(size & sam3_local.PROMPTS and not size & sam3_local.MASKS)
        body = sent[4:4 + (size & ~sam3_local.PROMPTS)]
        length = struct.unpack(">I", body[:4])[0]
        self.assertEqual(json.loads(body[4:4 + length]), {"prompts": ["dog", "baby"]})
        self.assertEqual(body[4 + length:4 + length + 8], b"\x89PNG\r\n\x1a\n")

    def test_shared_segmenter_never_loads_a_model(self):
        with self.assertRaises(confirm_mod.Unavailable):
            dog_watch.SharedSam3().masks(np.zeros((10, 10, 3), np.uint8), ["dog"])


class SlowDetector:
    """Stands in for SAM 3.1 (a real detector, not NoConfirm): takes load_s to build, counts builds and closes."""

    built, closed = [], []
    name = "sam3_local"

    def __init__(self, load_s):
        time.sleep(load_s)
        SlowDetector.built.append(self)

    def judge(self, frame_bgr):
        return "unsure"

    def close(self):
        SlowDetector.closed.append(self)


class KeptDetector(unittest.TestCase):
    """keep_confirm: the SAM 3.1 worker loads once and serves every change, so the dog look can share it."""

    def setUp(self):
        SlowDetector.built, SlowDetector.closed = [], []
        self.real_build = confirm_mod.build
        confirm_mod.build = lambda cfg: SlowDetector(0.2)

    def tearDown(self):
        confirm_mod.build = self.real_build

    def test_one_detector_for_two_changes_closed_at_stop(self):
        from parenting_agent.changing_table import ChangingTable, KeptConfirm
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load()
            config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                           "plugins": [], "changing_table": {"preload_confirm": True, "keep_confirm": True}})
            agent = build(config)
            plugin = ChangingTable(agent, config, reflex=FakeReflex(on_frames=100), source=FakeSource(frames=3, step=0.2), quiet=True)
            plugin.start()
            self.assertTrue(wait_until(lambda: agent.bus.count("confirm_ready") == 1))
            for _ in range(2):
                plugin._source = FakeSource(frames=3, step=0.2)
                plugin.arm()
                self.assertIsInstance(plugin.skill.confirm.detector, KeptConfirm)
                self.assertIs(plugin.skill.confirm.detector.detector, SlowDetector.built[0])
                plugin._source.drained.wait(10)
                plugin.finish()
                self.assertEqual(SlowDetector.closed, [], "a change never closes the kept detector")
            self.assertEqual(len(SlowDetector.built), 1)
            plugin.stop()
            self.assertEqual(SlowDetector.closed, SlowDetector.built)
            agent.close()


    def test_an_arm_that_fails_keeps_the_detector_for_the_next_one(self):
        # Oct 30 live run: MediaPipe could not open its model, the arm failed after taking the preloaded SAM 3.1, and
        # the next arm would have loaded a second one.
        from unittest import mock
        from parenting_agent import changing_table
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load()
            config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                           "plugins": [], "changing_table": {"preload_confirm": True, "keep_confirm": True}})
            agent = build(config)
            plugin = changing_table.ChangingTable(agent, config, reflex=FakeReflex(on_frames=100),
                                                  source=FakeSource(frames=3, step=0.2), quiet=True)
            plugin.start()
            self.assertTrue(wait_until(lambda: agent.bus.count("confirm_ready") == 1))
            real = changing_table.hands_mod.build
            with mock.patch.object(changing_table.hands_mod, "build", side_effect=RuntimeError("no hand model")):
                with self.assertRaises(RuntimeError):
                    plugin.arm()
            self.assertIsNone(plugin.skill)
            with mock.patch.object(changing_table.hands_mod, "build", real):
                plugin.arm()
            self.assertIs(plugin.skill.confirm.detector.detector, SlowDetector.built[0])
            self.assertEqual(len(SlowDetector.built), 1)
            plugin._source.drained.wait(10)
            plugin.stop()
            self.assertEqual(SlowDetector.closed, SlowDetector.built)
            agent.close()

    def test_stop_closes_a_detector_kept_by_a_failed_arm(self):
        from unittest import mock
        from parenting_agent import changing_table
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load()
            config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                           "plugins": [], "changing_table": {"preload_confirm": True, "keep_confirm": True}})
            agent = build(config)
            plugin = changing_table.ChangingTable(agent, config, reflex=FakeReflex(on_frames=100),
                                                  source=FakeSource(frames=0, step=0.2), quiet=True)
            plugin.start()
            with mock.patch.object(changing_table.hands_mod, "build", side_effect=RuntimeError("no hand model")):
                with self.assertRaises(RuntimeError):
                    plugin.arm()
            plugin.stop()
            self.assertEqual(SlowDetector.closed, SlowDetector.built)
            self.assertEqual(len(SlowDetector.built), 1)
            agent.close()


class Frames(Latest):
    def __init__(self):
        super().__init__()
        self.n = 0

    def add(self):
        self.n += 1
        self.put(np.zeros((480, 640, 3), np.uint8), self.n * 0.1)


class GlassesDog(unittest.TestCase):
    def plugin(self, tmp, segmenter):
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": []})
        agent = build(config)
        source = Frames()
        plugin = dog_watch.GlassesDogWatch(agent, config, segmenter=segmenter, source=source)
        plugin.source = source
        plugin.watch = dog_watch.Watch(plugin.cfg, agent.bus, segmenter, plugin.alert)
        return agent, plugin, source

    def test_a_near_dog_on_the_glasses_alerts_to_the_capture_file_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, source = self.plugin(tmp, FakeSegmenter(found(dog=box(210, 200, 260, 300))))
            self.assertIsNone(plugin.step(), "no frame yet")
            source.add()
            verdict, alerted, _ = plugin.step()
            self.assertEqual((verdict, alerted), ("near", True))
            look = next(e for e in agent.bus.history if e["kind"] == "dog_watch")
            self.assertEqual((look["why"], look["stream_s"], look["dog_score"], look["baby_score"]), ("glasses", 0.1, 0.9, 0.9))
            alert = next(e for e in agent.bus.history if e["kind"] == "dog_alert")
            self.assertTrue(alert["telegram"])
            self.assertEqual(alert["announce"], {"dry": True}, "the house announce is a dry run")
            captured = [json.loads(line) for line in (Path(tmp) / "telegram-captured.jsonl").read_text().splitlines()]
            self.assertEqual([c["text"] for c in captured], ["Dog close to Theo in the changing table"])
            self.assertIsNone(plugin.step(), "the same frame is not looked at twice")
            agent.close()

    def test_paused_while_the_changing_table_watches(self):
        with tempfile.TemporaryDirectory() as tmp:
            segmenter = FakeSegmenter(found(dog=None))
            agent, plugin, source = self.plugin(tmp, segmenter)
            agent.bus.publish("skill_armed", skill="changing-table")
            source.add()
            self.assertIsNone(plugin.step())
            self.assertEqual(segmenter.calls, 0)
            agent.bus.publish("skill_closed", skill="changing-table")
            self.assertEqual(plugin.step()[0], "no_dog")
            agent.close()

    def test_paused_from_the_start_phrase_until_the_skill_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            segmenter = FakeSegmenter(found(dog=None))
            agent, plugin, source = self.plugin(tmp, segmenter)
            agent.bus.publish("phrase", skill="changing-table", action="arm")
            source.add()
            self.assertIsNone(plugin.step(), "the held look must not wait behind a dog look")
            agent.bus.publish("phrase", skill="changing-table", action="finish")
            self.assertIsNone(plugin.step())
            agent.bus.publish("skill_armed", skill="changing-table")
            agent.bus.publish("skill_closed", skill="changing-table")
            self.assertEqual(plugin.step()[0], "no_dog")
            agent.bus.publish("phrase", skill="changing-table", action="arm")
            plugin.phrase_until = time.monotonic() - 1  # the brain never armed: the pause runs out
            source.add()
            self.assertEqual(plugin.step()[0], "no_dog")
            self.assertEqual(segmenter.calls, 2)
            agent.close()

    def test_waits_while_no_sam_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, source = self.plugin(tmp, dog_watch.SharedSam3())
            source.add()
            self.assertIsNone(plugin.step())
            source.add()
            self.assertIsNone(plugin.step())
            self.assertEqual(agent.bus.count("dog_watch_wait"), 1)
            agent.close()

    def test_no_telegram_even_with_a_token_in_the_environment(self):
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "1"}):
            agent, plugin, _ = self.plugin(tmp, FakeSegmenter(found()))
            self.assertIsInstance(plugin.alert.messenger, dog_watch.CapturedMessages)
            agent.close()


if __name__ == "__main__":
    unittest.main()


class LiveScript(unittest.TestCase):
    """scripts/glasses_hud_live.py: the committed script matches the feed plan, and the run's numbers are read right."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("hud_live", Path(__file__).resolve().parent.parent / "scripts" / "glasses_hud_live.py")
        self.live = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.live)

    def test_committed_script_is_the_plan(self):
        committed = json.loads(self.live.SCRIPT_OUT.read_text())
        self.assertEqual(committed, self.live.timeline())
        names = [s["name"] for s in committed["scenes"]]
        self.assertEqual(names, ["held diaper", "both hands off", "one hand on", "hover 2.5 cm", "done", "dog near the baby"])
        said = {line["text"]: line["at"] for line in committed["say"]}
        self.assertLess(said["changing time"], 2.6, "armed while the hands still rest on the diaper")
        done = next(s for s in committed["scenes"] if s["name"] == "done")
        self.assertTrue(done["at"] <= said["done, it was dirty"] < done["at"] + 1)

    def test_frame_to_card_and_words_to_card(self):
        app = [{"kind": "say", "text": "changing time", "unix": 100.0},
               {"kind": "sent", "title": "Changing table", "status": "", "meta": "Watch on · armed by Muse in 3.0 s", "detail": "",
                "cause": "armed", "frame_unix": 0, "unix": 103.1},
               {"kind": "sent", "title": "Hands off", "status": "", "meta": "", "detail": "", "cause": "alarm",
                "frame_unix": 110.0, "unix": 110.09},
               {"kind": "say", "text": "done, it was dirty", "unix": 120.0},
               {"kind": "sent", "title": "Logged", "status": "", "meta": "", "detail": "", "cause": "logged", "frame_unix": 0,
                "unix": 123.0},
               {"kind": "sent", "title": "Logged", "status": "", "meta": "", "detail": "Muse line", "cause": "reply",
                "frame_unix": 0, "unix": 124.0}]
        self.assertEqual(self.live.latencies(app), {"alarm": [0.09]})
        self.assertEqual(self.live.words_to_card(app), {"changing_time_to_armed_card_s": 3.1, "done_to_logged_card_s": 3.0,
                                                       "done_to_muse_line_on_card_s": 4.0})

    def test_the_run_never_reaches_telegram_or_home_assistant(self):
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_FAMILIES_BOT_TOKEN", "TELEGRAM_CHAT_ID", "HA_TOKEN", "HA_URL", "HA_MCP_TOKEN"):
            self.assertIn(key, self.live.BLANKED)
        config = json.loads((Path(__file__).resolve().parent.parent / self.live.CONFIG).read_text())
        self.assertEqual(config["dog_watch_glasses"]["alert_to"], "capture")
        self.assertEqual(config["baby_log"]["child"], "test-baby")
        self.assertIs(config["house"]["live"], False)
