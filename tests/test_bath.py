import json
import queue
import tempfile
import time
import unittest
from pathlib import Path

from parenting_agent import alarm as _prior_alarm  # noqa: E402

if not _prior_alarm.AVAILABLE:  # the MediaPipe path is prior work in a private repo (requirements-prior.txt)
    raise unittest.SkipTest("needs the prior work library, the SAM 3.1 only path is in test_sam_hands")

from parenting_agent import confirm as confirm_mod
from parenting_agent.agent import build
from parenting_agent.agent import config as agent_config
from parenting_agent.camera_skill import CameraSkills, check, implies_left_alone, spoken_texts
from parenting_agent.channels.router import Router
from parenting_agent.config import ConfigError, load

from test_changing_table import FakeReflex, FakeSource

ROOT = Path(__file__).resolve().parent.parent
BATH = str(ROOT / "skills" / "bath.json")


def agent_with_bath(tmp, reflex, source):
    config = agent_config.load()
    config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                   "plugins": [], "camera_skills": [{"skill": BATH}],
                   "allowed_tools": agent_config.DEFAULTS["allowed_tools"] + ["start_bath", "finish_bath"]})
    agent = build(config)
    plugin = CameraSkills(agent, config, reflex=reflex, confirm_detector=confirm_mod.NoConfirm(), source=source, quiet=True)
    agent.plugins = [plugin]
    return agent, plugin


def wait_for(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def say(agent, text, timeout=5):
    replies = queue.Queue()
    agent.bus.subscribe(replies.put, ["reply"])
    agent.bus.publish("message", channel="ear", text=text)
    return replies.get(timeout=timeout)["text"]


class BathByVoice(unittest.TestCase):
    def test_bath_time_arms_reminds_alerts_and_bath_done_logs_and_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeSource(frames=60, step=0.2)
            agent, plugin = agent_with_bath(tmp, FakeReflex(on_frames=4), source)
            agent.start()
            self.assertEqual(agent.memory.facts()["bath"]["value"], "No bath in progress.")
            say(agent, "Bath time")
            self.assertTrue(wait_for(lambda: plugin.skill is not None))
            self.assertEqual(agent.bus.count("phrase"), 1)  # armed by the phrase, without waiting for the brain
            reminder = [e for e in agent.bus.history if e["kind"] == "notify" and e.get("source") == "bath"]
            self.assertEqual(len(reminder), 1)
            for step in ("Water ready", "towel within reach", "nothing left on", "Keep a hand on the baby"):
                self.assertIn(step, reminder[0]["text"])
            self.assertIn("Never suggest stepping away", agent.memory.facts()["bath"]["value"])
            wait_for(lambda: source.stopped or agent.bus.count("voice"))
            say(agent, "bath done")
            self.assertTrue(wait_for(lambda: plugin.skill is None and agent.bus.count("read_back")))
            kinds = [e["kind"] for e in agent.bus.history]
            self.assertIn("chime", kinds)
            self.assertIn("voice", kinds)  # both hands off for longer than the hold
            baths = agent.baby_log.entries("bath")
            self.assertEqual(len(baths), 1)  # the phrase and the brain's tool call log one bath, not two
            self.assertTrue(baths[0]["details"]["text"].startswith("Bath "))
            self.assertEqual(agent.bus.count("read_back"), 1)
            self.assertIn("ask_parent", kinds)  # calling the partner on a spoken alert waits for a yes
            self.assertEqual(agent.memory.facts()["bath"]["value"], "No bath in progress.")
            agent.stop()
            agent.close()

    def test_hands_on_the_whole_bath_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_bath(tmp, FakeReflex(on_frames=100), FakeSource(frames=12, step=0.2))
            plugin.skills[0].arm()
            time.sleep(0.4)
            plugin.skills[0].finish()
            self.assertEqual(agent.bus.count("chime"), 0)
            self.assertEqual(agent.bus.count("voice"), 0)
            self.assertEqual(len(agent.baby_log.entries("bath")), 1)
            agent.close()

    def test_two_baths_in_a_row_log_twice_and_leave_no_listeners_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_bath(tmp, FakeReflex(on_frames=100), None)
            plugin.skills[0]._source = lambda: FakeSource(frames=6, step=0.2)
            listeners = len(agent.bus.listeners)
            for _ in range(2):
                plugin.skills[0].arm()
                time.sleep(0.2)
                plugin.skills[0].finish()
                self.assertEqual(len(agent.bus.listeners), listeners)
            self.assertEqual(len(agent.baby_log.entries("bath")), 2)
            agent.close()

    def test_router_sees_busy_hands_while_the_bath_is_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_bath(tmp, FakeReflex(on_frames=100), FakeSource(frames=6, step=0.2))
            router = Router(agent, {}, client=None, outputs={"ear": lambda text: None}, presence=lambda: "home")
            agent.plugins.append(router)
            self.assertFalse(router.skill_active())
            plugin.skills[0].arm()
            self.assertTrue(router.skill_active())
            routed = [e for e in agent.bus.history if e["kind"] == "routed"]
            self.assertEqual(routed[-1]["channel"], "ear")  # the reminder goes to the ear, hands are on the baby
            plugin.skills[0].finish()
            self.assertFalse(router.skill_active())
            agent.close()

    def test_one_camera_skill_at_a_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_bath(tmp, FakeReflex(on_frames=100), FakeSource(frames=6, step=0.2))

            class Busy:
                name, kind, skill = "changing-table", "skill", object()

            agent.plugins.append(Busy())
            self.assertIn("changing-table", plugin.skills[0].arm())
            self.assertIsNone(plugin.skill)
            agent.close()


class BathConfig(unittest.TestCase):
    def test_head_camera_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = agent_with_bath(tmp, FakeReflex(on_frames=1), FakeSource(frames=1, step=0.2))
            self.assertEqual(plugin.skills[0].cfg["source"], "phone")
            agent.close()
        real = json.loads((ROOT / "config" / "agent.json").read_text())
        self.assertEqual(real["camera_skills"], [{"skill": "skills/bath.json", "source": "phone"}])
        self.assertIn("parenting_agent.camera_skill:CameraSkills", real["plugins"])

    def test_bath_confirms_with_sam3_on_this_machine(self):
        cfg = load(BATH)
        self.assertEqual(cfg["confirm"]["provider"], "sam3_local")
        self.assertLessEqual(cfg["alarm"]["voice_hold_s"], 2.5)

    def test_a_missing_agent_text_fails_at_start(self):
        cfg = load(BATH)
        del cfg["agent"]["finish_tool"]
        with self.assertRaises(ConfigError):
            check(cfg)


class NeverLeftAlone(unittest.TestCase):
    def test_every_bath_text_passes(self):
        cfg = load(BATH)
        texts = spoken_texts(cfg)
        self.assertGreaterEqual(len(texts), 8)
        for text in texts:
            self.assertFalse(implies_left_alone(text), text)

    def test_texts_that_imply_leaving_the_baby_fail(self):
        for text in ("You can step away, she is fine in the water.",
                     "Go answer the door, I'll keep an eye on her.",
                     "I will watch the baby while you grab the towel.",
                     "Leave her for a second and get the towel.",
                     "Be right back is fine, the water is shallow.",
                     "She can stay in the bath alone for a moment.",
                     "Let me watch her while you open the door."):
            self.assertTrue(implies_left_alone(text), text)

    def test_texts_that_keep_hands_on_pass(self):
        for text in ("Never leave the baby alone in the water.",
                     "Keep a hand on the baby, I will tell the courier one moment.",
                     "Both hands left the baby. Hand.",
                     "It is listening for both hands to leave the baby.",
                     "Do not step away, I can ask your partner to come.",
                     "Nothing left on in the kitchen.",
                     "I can hold notifications so nothing interrupts the bath."):
            self.assertFalse(implies_left_alone(text), text)

    def test_a_skill_file_that_implies_leaving_fails_at_start(self):
        cfg = load(BATH)
        cfg["reminders"]["on_armed"] = "Bath time. You can step out for the towel, I will watch her."
        with self.assertRaises(ConfigError):
            check(cfg)


if __name__ == "__main__":
    unittest.main()
