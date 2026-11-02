"""Blind round b7, items 4 and 5. Right after a logged 38.2 the crying reply said "Si además tiene 38 °C o más": it now
says the fever is logged and gives the fixed line. "He just woke up crying" got nothing back: it now logs the wake-up
by code and says what the house did, labelled simulated (demo) or dry run (family agent). Fake brains, no network.
"""
import sys
import tempfile
import unittest
from pathlib import Path

from parenting_agent.agent import rules
from parenting_agent.house_tools import HouseTools
from parenting_agent.night_feed import NightFeed
from tests.test_home_automations import Clock, FakeHA, at, events, make_agent, night_log

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_demo import CountingBrain  # noqa: E402
from test_demo_r2 import at as demo_at, demo  # noqa: E402


class FeverThenCrying(unittest.TestCase):
    def run_demo(self, fever, cry):
        brain = CountingBrain()
        app, _ = demo(brain, now=demo_at(3, 10))
        self.addCleanup(app.close)
        app.message("v", True, fever)
        _, body = app.message("v", True, cry)
        return body["reply"], brain.calls

    def test_spanish_long_cry_says_the_fever_is_logged(self):
        reply, calls = self.run_demo("tiene 38.2 de fiebre", "no para de llorar hace media hora y ya comió")
        self.assertIn("Hay una fiebre anotada a las 03:10.", reply)
        self.assertIn(rules.FEVER_LOGGED_LINE["es"][:40], reply)
        self.assertNotIn("Si además tiene 38", reply)
        self.assertEqual(calls, 0)

    def test_english_long_cry_says_the_fever_is_logged(self):
        reply, _ = self.run_demo("temp 38.2", "he has been crying for half an hour and he already ate, I'm exhausted")
        self.assertIn("A fever was logged at 03:10.", reply)
        self.assertNotIn("also has a temperature", reply)

    def test_bare_cry_question_leads_with_the_logged_fever(self):
        reply, _ = self.run_demo("tiene 38.2 de fiebre", "¿por qué llora?")
        self.assertTrue(reply.startswith("Hay una fiebre anotada a las 03:10."), reply)

    def test_no_fever_keeps_the_when_to_call_line(self):
        brain = CountingBrain()
        app, _ = demo(brain, now=demo_at(3, 10))
        self.addCleanup(app.close)
        _, body = app.message("v", True, "no para de llorar hace media hora y ya comió")
        self.assertIn("Si además tiene 38 °C o más", body["reply"])


class WakeReportWords(unittest.TestCase):
    def test_bare_wake_ups_about_him(self):
        for text in ("He just woke up crying", "se despertó llorando", "he's awake", "ya se levantó"):
            with self.subTest(text=text):
                self.assertTrue(rules.is_wake_report(text))

    def test_everything_else_stays_on_its_path(self):
        for text in ("I woke up to pee", "is he up?", "he woke up at 3", "se despertó 4 y 55 llorando",
                     "se despertó y tomó 60 ml", "durmió 2 horas y se despertó", "se quedó dormido",
                     "woke up and he is not breathing"):
            with self.subTest(text=text):
                self.assertFalse(rules.is_wake_report(text))


class WakeUpOnTheDemo(unittest.TestCase):
    def test_night_wake_up_logs_and_dims_the_simulated_lights(self):
        for text, logged, simulated in (("He just woke up crying", "Logged", "Simulated in the demo"),
                                        ("se despertó llorando", "Anoté", "Simulado en la demo")):
            with self.subTest(text=text):
                brain = CountingBrain()
                app, _ = demo(brain, now=demo_at(3, 10))
                self.addCleanup(app.close)
                before = len(app.visitor("v").baby_log.entries(None, None, 1000))
                _, body = app.message("v", True, text)
                self.assertTrue(body["reply"].startswith(logged), body["reply"])
                self.assertIn(simulated, body["reply"])
                self.assertEqual([a["action"] for a in body["actions"]], ["dim_lights"])
                self.assertEqual(brain.calls, 0)
                rows = app.visitor("v").baby_log.entries(None, None, 1000)
                self.assertTrue(len(rows) > before or rows[-1]["kind"] == "sleep")

    def test_day_wake_up_says_the_house_does_nothing(self):
        app, _ = demo(CountingBrain(), now=demo_at(15, 0))
        self.addCleanup(app.close)
        _, body = app.message("v", True, "He just woke up crying")
        self.assertIn(rules.WAKE_NO_STEP["en"], body["reply"])
        self.assertEqual(body["actions"], [])


class WakeUpOnTheFamilyAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.config["people"] = {"gonza": {"name": "Gonza", "rota": "Parent A"},
                                 "ceci": {"name": "Ceci", "rota": "Parent B"}}
        self.clock = Clock(at(21, 1, 0))
        self.house = HouseTools(self.agent, self.config, client=FakeHA())
        self.feed = NightFeed(self.agent, self.config, log=night_log(), clock=self.clock)
        self.agent.plugins = [self.house, self.feed]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_the_reply_says_what_the_house_did_once(self):
        event = {"kind": "message", "channel": "telegram", "text": "He just woke up crying"}
        self.agent.bus.publish("message", channel="telegram", text=event["text"])  # the night feed hears it first
        step = self.feed.wake_step(event, "en")
        self.assertIn("Study light", step)
        self.assertIn("is on duty", step)
        self.assertEqual(len(events(self.agent, "night_feed", step="prepare")), 1)
        self.assertEqual(self.feed.wake_step(event, "es").count("Luz del estudio"), 1)
        self.assertEqual(len(events(self.agent, "night_feed", step="prepare")), 1)

    def test_the_loop_reply_has_the_log_and_the_step(self):
        self.agent.handle({"kind": "message", "channel": "telegram", "text": "He just woke up crying"})
        replies = [e["text"] for e in self.agent.bus.history if e["kind"] == "reply"]
        self.assertTrue(replies, "no reply")
        self.assertIn("Study light", replies[-1])
        self.assertNotIn(rules.WAKE_NOT_LOGGED["en"], replies[-1])


if __name__ == "__main__":
    unittest.main()
