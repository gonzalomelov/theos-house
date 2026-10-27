"""Tests for issue #17: the simulated full day runs its steps in order, reports pass or fail per step, shows
what ran dry, and writes the KR result files.

Offline: the fake brain and the in-memory Baby Buddy (fake_babybuddy.py), no clips. The real day runs with
python -m parenting_agent.fullday.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.fullday import __main__ as fullday_main
from parenting_agent.fullday import day as day_mod
from parenting_agent.rhythm.log import FixtureLog

from fake_babybuddy import TOKEN, FakeBabyBuddy

FIXTURE = Path(__file__).parent / "fixtures" / "simweek.json"


def make_agent(server, data_dir):
    os.environ["PA_TEST_BB_URL"], os.environ["PA_TEST_BB_TOKEN"] = server.url, TOKEN
    config = config_mod.load()
    config.update({"data_dir": str(data_dir), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                   "allowed_tools": config["allowed_tools"] + list(day_mod.HOUSE_TOOLS),
                   "baby_log": {"provider": "babybuddy", "url_env": "PA_TEST_BB_URL", "token_env": "PA_TEST_BB_TOKEN",
                                "child": "test-baby", "tags": ["agent", day_mod.TAG]}})
    agent = build(config)
    agent.plugins = [day_mod.HouseTools(agent, config)]
    return agent


class FullDay(unittest.TestCase):
    def setUp(self):
        self.server = FakeBabyBuddy()
        self.tmp = tempfile.TemporaryDirectory()
        self.agent = make_agent(self.server, self.tmp.name)
        self.agent.start()
        week = FixtureLog(FIXTURE)
        self.day = day_mod.Day(self.agent, {}, self.tmp.name, Path(self.tmp.name) / "run", video=False,
                               rhythm_log=week, week_log=week)

    def tearDown(self):
        self.agent.stop()
        self.agent.close()
        self.server.close()
        self.tmp.cleanup()

    def test_house_tools_run_dry_and_ask_before_replying_to_a_visitor(self):
        status, result = self.agent.tools.run("announce", {"text": "one moment please"})
        self.assertEqual(status, "ran")
        self.assertIn("dry run", result)
        status, _ = self.agent.tools.run("reply_to_visitor", {"text": "leave the package"})
        self.assertEqual(status, "ask_parent")
        dry = [e for e in self.agent.bus.history if e["kind"] == "house_dry"]
        self.assertEqual([e["action"] for e in dry], ["announce"])

    def test_bottle_step_logs_a_tagged_entry_read_back_from_baby_buddy(self):
        result = self.day.bottle()
        self.assertTrue(result["passed"])
        self.assertEqual(self.day.evidence["voice"][0]["babybuddy"]["type"], "feeding")
        feeds = list(self.server.all("feedings"))
        self.assertEqual(len(feeds), 1)
        self.assertIn(day_mod.TAG, feeds[0]["tags"])

    def test_nap_note_is_longer_than_the_usual_nap_and_never_advice(self):
        result = self.day.nap_note()
        self.assertTrue(result["passed"])
        self.assertIn("40 min longer", result["action"])
        reminder = self.day.evidence["reminders"][0]
        self.assertEqual((reminder["channel"], reminder["asked"]), ("telegram", False))
        self.assertTrue(reminder["computed_from"])

    def test_video_steps_are_pending_without_clips_and_a_broken_step_is_a_failed_step(self):
        class Broken(day_mod.Day):
            def doorbell(self):
                raise RuntimeError("boom")

        broken = Broken(self.agent, {}, self.tmp.name, Path(self.tmp.name) / "run", video=False,
                        rhythm_log=FixtureLog(FIXTURE), week_log=FixtureLog(FIXTURE))
        report = day_mod.run(broken)
        by_time = {row["sim_time"]: row for row in report}
        self.assertEqual([row["sim_time"] for row in report], [s[0] for s in day_mod.STEPS])
        self.assertEqual(by_time["06:40"]["status"], "pending")
        self.assertEqual(by_time["18:30"]["status"], "pending")
        self.assertEqual(by_time["09:15"]["status"], "fail")
        self.assertIn("boom", by_time["09:15"]["action"])
        markdown = fullday_main.markdown(report, {"generated_at": "now", "brain": {"provider": "fake", "model": "rules",
                                                                                     "destination": "none"}})
        self.assertIn("| 06:10 | Bottle by voice | pass |", markdown)
        self.assertIn("Home Assistant dry run", json.dumps(report))

    def test_usual_nap_comes_from_daytime_sleep_in_the_simulated_week(self):
        usual = day_mod.usual_nap_min(FixtureLog(FIXTURE).entries())
        self.assertTrue(30 <= usual <= 180)


if __name__ == "__main__":
    unittest.main()
