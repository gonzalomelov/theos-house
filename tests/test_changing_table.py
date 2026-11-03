"""The changing table on SAM 3.1 alone, through the plugin: a change is watched, then logged. Scripted masks, no model loads."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.sources import Latest

ROOT = Path(__file__).resolve().parent.parent
SHAPE = (360, 640)


def scripted_masks(on):
    baby = np.zeros(SHAPE, bool)
    baby[100:260, 200:440] = True
    hand = np.zeros(SHAPE, bool)
    if on:
        hand[150:200, 250:300] = True
    else:
        hand[10:40, 10:40] = True
    return [hand], baby


class ScriptedSam:
    """The stand-in for SAM 3.1: a hand on the baby for on_looks looks, then none."""
    name = "sam3_local"

    def __init__(self, on_looks):
        self.on_looks, self.looks = on_looks, 0

    def masks(self, frame_bgr, held=False):
        self.looks += 1
        return scripted_masks(self.looks <= self.on_looks)

    def close(self):
        pass


class FakeSource(Latest):
    """Frames step seconds apart in stream time, each one only after the watcher took the last. drained is set after the last."""

    def __init__(self, frames, step):
        super().__init__()
        self.frames, self.step = frames, step
        self.blank = np.zeros((*SHAPE, 3), np.uint8)
        self.started = time.monotonic()
        self.taken = threading.Condition()
        self.taken_seq = 0
        self.drained = threading.Event()
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
            time.sleep(0.02)  # room for a look to land between frames
            self.put(self.blank, n * self.step)


def agent_with_skill(tmp, detector, source):
    from parenting_agent.changing_table import ChangingTable
    config = config_mod.load()
    config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                   "plugins": [], "changing_table": {"arm": "command"}})
    agent = build(config)
    return agent, ChangingTable(agent, config, confirm_detector=detector, source=source, quiet=True)


class ChangingTablePlugin(unittest.TestCase):
    def test_a_change_is_watched_then_logged_and_hands_off_speak(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_skill(tmp, ScriptedSam(on_looks=3), FakeSource(frames=30, step=0.2))
            self.assertIn("start_changing_table", agent.tools.names())
            self.assertEqual(plugin.arm(), "watching the changing table")
            self.assertTrue(plugin._source.drained.wait(30), "the watcher never took every frame")
            self.assertEqual(plugin.finish(), "diaper change logged")
            self.assertGreaterEqual(agent.bus.count("voice"), 1)
            self.assertEqual(agent.bus.count("track_dry"), 1)
            agent.close()

    def test_hands_on_stay_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_skill(tmp, ScriptedSam(on_looks=10_000), FakeSource(frames=30, step=0.2))
            plugin.arm()
            self.assertTrue(plugin._source.drained.wait(30), "the watcher never took every frame")
            plugin.finish()
            self.assertEqual(agent.bus.count("chime"), 0)
            self.assertEqual(agent.bus.count("voice"), 0)
            agent.close()

    def test_finish_without_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_skill(tmp, ScriptedSam(on_looks=1), FakeSource(frames=1, step=0.2))
            self.assertIsInstance(plugin.finish(), str)
            agent.close()


class SkillConfig(unittest.TestCase):
    def test_changing_table_maps_every_house_action(self):
        cfg = json.loads((ROOT / "skills/changing-table.json").read_text())
        house = cfg["house"]
        for name in house["on_armed"] + house["on_closed"]:
            self.assertIn(name, house["allowed"])
        self.assertEqual(cfg["confirm"]["provider"], "sam3_local")


if __name__ == "__main__":
    unittest.main()
