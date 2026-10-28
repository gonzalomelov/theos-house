"""Tests for the heartbeat plug-in and the always-on config (issue #15). Fake brain, no network."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.heartbeat import Heartbeat, fresh

ROOT = Path(__file__).resolve().parents[1]


def fake_agent(data_dir):
    config = config_mod.load()
    config.update({"data_dir": str(data_dir), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                   "plugins": ["parenting_agent.agent.heartbeat:Heartbeat"], "heartbeat": {"interval_s": 0.05}})
    return build(config), config


class HeartbeatPlugin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = fake_agent(self.tmp.name)
        self.path = Path(self.tmp.name) / "heartbeat.json"

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_writes_a_fresh_heartbeat_while_the_loop_runs(self):
        self.agent.start()
        heartbeat = self.agent.plugins[0]
        heartbeat.start()
        time.sleep(0.2)
        heartbeat.stop()
        self.agent.stop()
        beat = json.loads(self.path.read_text())
        self.assertEqual(beat["brain"], "fake")
        self.assertTrue(fresh(self.path))

    def test_exits_when_the_loop_is_gone(self):
        exits = []
        heartbeat = Heartbeat(self.agent, self.config, exit=exits.append)
        heartbeat.start()
        heartbeat.thread.join(timeout=2)
        self.assertEqual(exits, [1])
        self.assertFalse(self.path.exists())

    def test_stale_or_missing_heartbeat_is_not_fresh(self):
        self.assertFalse(fresh(self.path))
        self.path.write_text(json.dumps({"ts": time.time() - 200}))
        self.assertFalse(fresh(self.path))
        self.path.write_text("not json")
        self.assertFalse(fresh(self.path))


class VostroConfig(unittest.TestCase):
    def test_no_console_no_vision_and_the_heartbeat_on(self):
        config = json.loads((ROOT / "config/agent.vostro.json").read_text())
        self.assertIn("parenting_agent.agent.heartbeat:Heartbeat", config["plugins"])
        self.assertNotIn("parenting_agent.agent.console:Console", config["plugins"])
        self.assertNotIn("parenting_agent.changing_table:ChangingTable", config["plugins"])
        self.assertEqual(config["baby_log"]["provider"], "babybuddy")


if __name__ == "__main__":
    unittest.main()
