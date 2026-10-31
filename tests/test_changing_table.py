import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from parenting_agent import alarm as _prior_alarm  # noqa: E402

if not _prior_alarm.AVAILABLE:  # the MediaPipe path is prior work in a private repo (requirements-prior.txt)
    raise unittest.SkipTest("needs the prior work library, the SAM 3.1 only path is in test_sam_hands")

from parenting_agent import confirm as confirm_mod
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.sources import Latest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("kr222_table", ROOT / "scripts" / "kr222_table.py")
kr222 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kr222)


class FakeReflex:
    """on for the first frames, then both hands off."""

    def __init__(self, on_frames):
        self.on_frames, self.n = on_frames, 0

    def state(self, frame):
        self.n += 1
        return ("on" if self.n <= self.on_frames else "off"), 1, 0.001


class FakeSource(Latest):
    """Frames step seconds apart in stream time, handed over one at a time: the next frame is only put once the
    watcher took the last one, so a slow machine never drops frames and the reflex sees them all in order.
    drained is set once the watcher took the last frame."""

    def __init__(self, frames, step):
        super().__init__()
        import threading
        import numpy as np
        self.frames, self.step = frames, step
        self.blank = np.zeros((360, 640, 3), np.uint8)
        self.started = time.monotonic()
        self.taken = threading.Condition()
        self.taken_seq = 0
        self.drained = threading.Event()
        if frames == 0:
            self.drained.set()
        threading.Thread(target=self._feed, daemon=True).start()

    def latest(self, after_seq):
        got = super().latest(after_seq)
        if got is not None:
            with self.taken:
                self.taken_seq = got[1]
                self.taken.notify_all()
            if got[1] == self.frames:
                self.drained.set()
        return got

    def _feed(self):
        for n in range(self.frames):
            with self.taken:
                while self.taken_seq < self.seq and not self.stopped:
                    self.taken.wait(0.05)
            if self.stopped:
                return
            self.put(self.blank, n * self.step)


def agent_with_skill(tmp, reflex, source):
    from parenting_agent.changing_table import ChangingTable
    config = config_mod.load()
    config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                   "plugins": [], "changing_table": {"arm": "command"}})
    agent = build(config)
    plugin = ChangingTable(agent, config, reflex=reflex, confirm_detector=confirm_mod.NoConfirm(), source=source, quiet=True)
    return agent, plugin


class ChangingTablePlugin(unittest.TestCase):
    def test_tools_are_registered_and_a_change_is_watched_then_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_skill(tmp, FakeReflex(on_frames=4), FakeSource(frames=12, step=0.2))
            self.assertIn("start_changing_table", agent.tools.names())
            self.assertEqual(plugin.arm(), "watching the changing table")
            self.assertTrue(plugin._source.drained.wait(30), "the watcher never took every frame")
            self.assertEqual(plugin.finish(), "diaper change logged")
            kinds = [e["kind"] for e in agent.bus.history]
            self.assertIn("skill_armed", kinds)
            self.assertIn("voice", kinds)  # both hands off for more than the 1.2 s hold
            self.assertEqual(agent.bus.count("track_dry"), 1)  # one diaper, dry without Baby Buddy credentials
            self.assertEqual(agent.bus.count("observation"), 1)
            agent.close()

    def test_one_hand_on_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_skill(tmp, FakeReflex(on_frames=100), FakeSource(frames=12, step=0.2))
            plugin.arm()
            self.assertTrue(plugin._source.drained.wait(30), "the watcher never took every frame")
            plugin.finish()
            self.assertEqual(agent.bus.count("chime"), 0)
            self.assertEqual(agent.bus.count("voice"), 0)
            agent.close()

    def test_the_brain_tools_log_the_content_and_read_it_back(self):
        """The brain arms through its tool, no fallback fires, and finish_changing_table(solid=True) logs a dirty diaper
        and returns the entry read back from Baby Buddy for the spoken summary. Baby Buddy answers in UTC and the parent
        hears the house clock, which deploy/compose.yml sets to America/Montevideo, so the test runs on that clock."""
        from parenting_agent.tracking import Tracker

        before = os.environ.get("TZ")
        os.environ["TZ"] = "America/Montevideo"
        time.tzset()

        def restore():
            if before is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = before
            time.tzset()
        self.addCleanup(restore)

        class FakeBabyBuddy:
            def __init__(self):
                self.saved = {}

            def post(self, path, data):
                self.saved[len(self.saved) + 1] = data
                return {"id": len(self.saved)}

            def get(self, path, entry_id):
                return {"id": entry_id, **self.saved[entry_id], "time": "2026-10-29T06:46:58Z"}

        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_skill(tmp, FakeReflex(on_frames=4), FakeSource(frames=12, step=0.2))
            plugin.fallback_s = 0.2
            agent.tools.allowed.update({"start_changing_table", "finish_changing_table"})
            client = FakeBabyBuddy()
            agent.bus.publish("message", channel="glasses", text="changing time")
            self.assertEqual(agent.tools.run("start_changing_table", {})[1], "watching the changing table")
            plugin.skill.tracker = Tracker({"on_closed": "change"}, agent.bus, client=client)
            self.assertTrue(plugin._source.drained.wait(30), "the watcher never took every frame")
            time.sleep(0.4)
            status, result = agent.tools.run("finish_changing_table", {"wet": False, "solid": True})
            self.assertEqual(status, "ran")
            self.assertIn("diaper at 03:46, dirty", result)
            self.assertIn("Hand alerts spoken this change: 1", result)
            self.assertEqual(client.saved[1]["solid"], True)
            self.assertEqual(agent.bus.count("phrase_fallback"), 0)
            self.assertEqual(agent.bus.count("observation"), 0)  # the tool result carries the summary, no second answer
            self.assertEqual(next(e for e in agent.bus.history if e["kind"] == "changing_armed")["via"], "brain")
            self.assertIn("dirty", agent.memory.facts()["last-diaper-change"]["value"])
            agent.close()

    def test_fallback_content_from_words(self):
        from parenting_agent.changing_table import content_from
        self.assertEqual(content_from("Done, it was dirty!"), {"wet": False, "solid": True})
        self.assertEqual(content_from("done wet"), {"wet": True, "solid": False})

    def test_finish_without_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_skill(tmp, FakeReflex(0), FakeSource(0, 0.2))
            self.assertEqual(plugin.finish(), "the changing table was not being watched")
            agent.close()


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class SlowDetector(confirm_mod.NoConfirm):
    """Stands in for SAM 3.1: takes load_s to build, counts how many were built and closed."""

    built, closed = [], []

    def __init__(self, load_s):
        time.sleep(load_s)
        SlowDetector.built.append(self)

    def close(self):
        SlowDetector.closed.append(self)


class ConfirmPreload(unittest.TestCase):
    """The glasses hero run (results/hero): SAM 3.1 took about 10 s to load at "changing time", and the skill watched
    nothing in that time. preload_confirm loads it when the agent starts and again after each change."""

    def setUp(self):
        SlowDetector.built, SlowDetector.closed = [], []
        self.real_build = confirm_mod.build
        confirm_mod.build = lambda cfg: SlowDetector(0.3)

    def tearDown(self):
        confirm_mod.build = self.real_build

    def plugin(self, tmp, preload):
        from parenting_agent.changing_table import ChangingTable
        config = config_mod.load()
        config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                       "plugins": [], "changing_table": {"arm": "command", "preload_confirm": preload}})
        agent = build(config)
        return agent, ChangingTable(agent, config, reflex=FakeReflex(on_frames=100), source=FakeSource(frames=4, step=0.2), quiet=True)

    def test_the_detector_loads_before_changing_time_and_again_after_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = self.plugin(tmp, preload=True)
            plugin.start()
            time.sleep(0.6)
            self.assertEqual(len(SlowDetector.built), 1)  # loaded before the parent said anything
            started = time.monotonic()
            plugin.arm()
            self.assertLess(time.monotonic() - started, 0.25)  # no load at arm
            self.assertIs(plugin.skill.confirm.detector, SlowDetector.built[0])
            self.assertEqual(agent.bus.count("confirm_preloaded"), 1)
            plugin._source.drained.wait(30)
            plugin.finish()
            self.assertEqual(SlowDetector.closed, SlowDetector.built[:1])
            self.assertIsNotNone(plugin.warm)  # the next change's detector is loading
            plugin.stop()
            self.assertEqual(len(SlowDetector.built), 2)
            self.assertEqual(SlowDetector.closed, SlowDetector.built)  # nothing left running
            agent.close()

    def test_a_hung_preload_never_freezes_changing_time_or_done(self):
        # Round 3 red team (rt3/h_preload.py): a SAM build that hangs held the lock, "changing time" did not return in
        # 8 s and "done" did not return in 3 s. Now arm waits preload_wait_s, then watches with the MediaPipe regions.
        hang = threading.Event()
        confirm_mod.build = lambda cfg: (hang.wait(), SlowDetector(0))[1]
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = self.plugin(tmp, preload=True)
            plugin.cfg["preload_wait_s"] = 0.3
            plugin.start()
            done = {}
            arm = threading.Thread(target=lambda: done.setdefault("arm", plugin.arm()), daemon=True)
            arm.start()
            arm.join(3)
            self.assertIn("MediaPipe", done.get("arm", ""))
            self.assertIsInstance(plugin.skill.confirm.detector, confirm_mod.NoConfirm)
            self.assertEqual(agent.bus.count("confirm_preload_timeout"), 1)
            self.assertTrue(any("hand check only" in e.get("text", "") for e in agent.bus.history if e["kind"] == "reply"))
            finish = threading.Thread(target=lambda: done.setdefault("finish", plugin.finish()), daemon=True)
            finish.start()
            finish.join(3)
            self.assertEqual(done.get("finish"), "diaper change logged")
            hang.set()
            self.assertTrue(wait_until(lambda: plugin.warm is not None and plugin.warm.done()))
            plugin.arm()  # the late detector is kept for the next change
            self.assertIs(plugin.skill.confirm.detector, SlowDetector.built[0])
            plugin.stop()
            agent.close()

    def test_without_preload_the_detector_loads_at_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = self.plugin(tmp, preload=False)
            plugin.start()
            time.sleep(0.4)
            self.assertEqual(SlowDetector.built, [])
            plugin.arm()
            self.assertEqual(len(SlowDetector.built), 1)
            plugin._source.drained.wait(30)
            plugin.stop()
            self.assertIsNone(plugin.warm)
            agent.close()

    def test_a_preload_that_fails_falls_back_to_loading_at_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = self.plugin(tmp, preload=True)
            calls = []

            def flaky(cfg):
                calls.append(cfg)
                if len(calls) == 1:
                    raise confirm_mod.Unavailable("busy")
                return SlowDetector(0)
            confirm_mod.build = flaky
            plugin.start()
            plugin.arm()
            self.assertEqual(agent.bus.count("confirm_preload_error"), 1)
            self.assertIs(plugin.skill.confirm.detector, SlowDetector.built[0])
            plugin._source.drained.wait(30)
            plugin.stop()
            agent.close()


class Sam3LocalStartup(unittest.TestCase):
    def test_missing_python_is_unavailable_before_the_routine(self):
        with self.assertRaises(confirm_mod.Unavailable):
            confirm_mod.build({"provider": "sam3_local", "module": "parenting_agent.sam3_local", "python": "/nonexistent/python"})


class Kr222Scoring(unittest.TestCase):
    SEGMENTS = [
        {"clip_id": "table-handsoff-01", "kind": "both_hands_off", "start_s": 0.0, "end_s": 6.0, "cue_s": 3.0},
        {"clip_id": "table-onehand-01", "kind": "one_hand", "start_s": 6.0, "end_s": 12.0, "cue_s": 8.0},
    ]

    def voice(self, stream_s, delay):
        return {"stream_s": stream_s, "capture_mono": 100 + stream_s, "heard_mono": 100 + stream_s + delay}

    def test_spoken_hands_off_and_silent_one_hand_over_two_passes(self):
        moments = kr222.score([self.voice(4.4, 0.05), self.voice(16.3, 0.05)], self.SEGMENTS, 12.0, 2)
        self.assertEqual([(m["clip_id"], m["pass"], m["spoken"]) for m in moments],
                         [("table-handsoff-01", 1, True), ("table-onehand-01", 1, False),
                          ("table-handsoff-01", 2, True), ("table-onehand-01", 2, False)])
        self.assertEqual(moments[0]["latency_s"], 1.45)
        self.assertIsNone(moments[1]["latency_s"])

    def test_voice_in_one_hand_clip_counts_as_spoken(self):
        moments = kr222.score([self.voice(9.0, 0.0)], self.SEGMENTS, 12.0, 1)
        self.assertTrue(moments[1]["spoken"])
        self.assertFalse(moments[0]["spoken"])

    def test_clip_discovery_from_folders_and_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "handsoff").mkdir()
            (root / "onehand").mkdir()
            for path in (root / "handsoff/a.mp4", root / "onehand/b.mp4", root / "table-handsoff-03.mp4", root / "bath-handoff-01.mp4"):
                path.write_bytes(b"")
            cues = {"table-handsoff-01": 3.2, "table-onehand-01": 2.2, "table-handsoff-03": 1.5, "bath-handoff-01": 4.0}
            found = kr222.table_clips(root, cues)
            self.assertEqual([(c[0], c[2]) for c in found], [("table-handsoff-01", "both_hands_off"),
                                                             ("table-handsoff-03", "both_hands_off"),
                                                             ("table-onehand-01", "one_hand")])


class SkillConfig(unittest.TestCase):
    def test_changing_table_maps_every_house_action(self):
        cfg = json.loads((ROOT / "skills/changing-table.json").read_text())
        house = cfg["house"]
        for name in house["on_armed"] + house["on_closed"]:
            self.assertIn(name, house["allowed"])
        self.assertEqual(cfg["confirm"]["provider"], "sam3_local")


if __name__ == "__main__":
    unittest.main()
