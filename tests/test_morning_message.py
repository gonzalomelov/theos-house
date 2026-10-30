"""One morning message per parent, and every scheduled push at most once a day per parent across restarts (Oct 30).

Before: the brief and the night explanation at 07:30 and the prep nudge at 08:00, three messages each. A restart at 07:48
on Oct 30 sent the brief and the explanation again, and on Oct 29 restarts sent the brief 6 times and tonight's plan 5.

Offline: the family agent from test_family_push with a fake Telegram. Chat ids are made up.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from parenting_agent.channels.morning import compose
from parenting_agent.prep import Prep
from tests.test_family_push import CECI, GONZA, Family, at, wakeup

ROOT = Path(__file__).resolve().parent.parent
BRIEF = {"night": {"feeds": 2, "longest_h": 3.2, "wakeups": {"Parent A": 2, "Parent B": 0}},
         "weather": {"sky": "rainy", "low": 13, "high": 20, "rain_mm": 20.5},
         "low": [{"item": "diapers", "days_left": 1.5}], "appointments": [], "meals": []}
EXPLAIN = "Overnight the house got ready for 2 night feeds."


class Stub:
    def __init__(self, name):
        self.name = name


class MorningMessageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def family(self, now, parts=("day-engine", "house-brain"), hold_s=300, lang="en"):
        rows = [wakeup(30, 2, "Gonza", 1)]  # Gonza took last night's wake-up, Ceci is on duty tonight
        family = Family(self.tmp.name, now, rows, extra={
            "family_push": {"morning": True, "hold_s": hold_s},
            "prep": {"lang": lang, "nudge": {"also_chat_ids_envs": ["TELEGRAM_CECI_CHAT_ID"]}}})
        self.addCleanup(family.close)
        family.prep = Prep(family.agent, family.config, clock=family.clock)
        family.agent.plugins += [family.prep, *(Stub(p) for p in parts)]
        return family

    def morning(self, family):
        family.agent.bus.publish("notify", text="Good morning. Night summary ...", channel="telegram",
                                 source="day-engine", routine="morning_brief", facts=BRIEF)
        family.agent.bus.publish("notify", text=EXPLAIN, channel="telegram", source="house-brain",
                                 routine="morning_explain", to="both",
                                 facts={"night_feeds": 2, "real": 0, "events": 5, "on_duty": None})

    def test_one_message_each_with_only_what_is_theirs(self):
        family = self.family(at(30, 7, 30))
        self.morning(family)
        gonza, ceci = family.sent_to(GONZA), family.sent_to(CECI)
        self.assertEqual((len(gonza), len(ceci)), (1, 1))
        self.assertIn("Good morning, Gonza.", gonza[0])
        self.assertIn("you were up 2 times", gonza[0])
        self.assertIn("you were up 0 times", ceci[0])
        self.assertIn("You are on duty tonight.", ceci[0])
        self.assertNotIn("on duty tonight", gonza[0])
        self.assertIn(f"The house overnight: {EXPLAIN}", gonza[0], "he was on duty last night")
        self.assertNotIn("The house overnight", ceci[0])
        for text in (gonza[0], ceci[0]):
            self.assertIn("Running low: Diapers (about 1.5 days left).", text)
            self.assertIn("Before he arrives:", text)
            self.assertNotIn("1735 min ago", text)
        stored = [e for e in family.agent.bus.history if e["kind"] == "morning_message"][0]
        self.assertEqual(stored["facts"], BRIEF)
        self.assertEqual(stored["texts"]["gonza"], gonza[0])

    def test_the_prep_nudge_is_inside_and_not_sent_again_at_eight(self):
        family = self.family(at(30, 7, 30))
        self.morning(family)
        family.clock.moment = at(30, 8, 0)
        family.prep.tick()
        self.assertEqual((len(family.sent_to(GONZA)), len(family.sent_to(CECI))), (1, 1))

    def test_a_restart_in_the_morning_window_does_not_resend(self):
        first = self.family(at(30, 7, 30))
        self.morning(first)
        first.close()
        again = self.family(at(30, 7, 48))
        self.morning(again)
        again.clock.moment = at(30, 8, 0)
        again.prep.tick()
        self.assertEqual(again.sent_to(GONZA) + again.sent_to(CECI), [])
        repeats = [e for e in again.agent.bus.history if e["kind"] == "pushed" and "restart repeat" in e["reason"]]
        self.assertEqual(len(repeats), 2)
        marker = json.loads((Path(self.tmp.name) / "scheduled-pushes.json").read_text())
        self.assertEqual(marker["morning"], {"ceci": "2026-10-30", "gonza": "2026-10-30"})

    def test_a_missing_part_waits_then_goes_alone(self):
        family = self.family(at(30, 7, 30), hold_s=0.05)
        family.agent.bus.publish("notify", text="brief", channel="telegram", source="day-engine",
                                 routine="morning_brief", facts=BRIEF)
        self.assertEqual(family.sent_to(GONZA), [])
        time.sleep(0.3)
        self.assertEqual((len(family.sent_to(GONZA)), len(family.sent_to(CECI))), (1, 1))

    def test_prep_alone_sends_one_message_once(self):
        family = self.family(at(30, 8, 0), parts=())
        family.prep.tick()
        family.prep.tick()
        self.assertEqual((len(family.sent_to(GONZA)), len(family.sent_to(CECI))), (1, 1))
        self.assertIn("Before he arrives:", family.sent_to(CECI)[0])

    def test_spanish(self):
        family = self.family(at(30, 7, 30), lang="es")
        self.morning(family)
        ceci = family.sent_to(CECI)[0]
        self.assertIn("Buen día, Ceci.", ceci)
        self.assertIn("Esta noche te toca a vos.", ceci)
        self.assertIn("Clima: lluvia, 13 a 20 C, 20.5 mm de lluvia.", ceci)
        self.assertIn("Se está terminando: Pañales", ceci)
        self.assertIn("Antes de que llegue:", ceci)


class OncePerDayTest(unittest.TestCase):
    def test_tonights_plan_once_a_day_per_parent_across_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            for minute in (30, 35):
                family = Family(tmp, at(30, 20, minute))
                for _ in range(2):
                    family.agent.bus.publish("notify", text="Tonight: Parent A on duty.", channel="telegram",
                                             source="house-brain", routine="tonight", to="both")
                sent = (family.sent_to(GONZA), family.sent_to(CECI))
                family.close()
                self.assertEqual(sent, (["Tonight: Gonza on duty."],) * 2 if minute == 30 else ([], []))
            family = Family(tmp, at(31, 20, 30))
            family.agent.bus.publish("notify", text="Tonight.", channel="telegram", source="house-brain",
                                     routine="tonight", to="both")
            self.assertEqual((family.sent_to(GONZA), family.sent_to(CECI)), (["Tonight."], ["Tonight."]))
            family.close()

    def test_a_replan_is_not_held_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 20, 30))
            for _ in range(2):
                family.agent.bus.publish("notify", text="Plan changed.", channel="telegram", source="house-brain",
                                         routine="replan", to="both")
            self.assertEqual(len(family.sent_to(GONZA)), 2)
            family.close()


class ComposeTest(unittest.TestCase):
    def test_no_night_line_before_he_is_born(self):
        quiet = {**BRIEF, "night": {"feeds": 0, "longest_h": 0.0, "wakeups": {"Parent A": 0, "Parent B": 0}}}
        text = compose("en", "Gonza", "Parent A", quiet, None, ["About 46 days to the due date."], "Parent A")
        self.assertEqual(text.splitlines()[:2], ["Good morning, Gonza.", "You are on duty tonight."])

    def test_the_family_agent_merges_the_morning(self):
        config = json.loads((ROOT / "config" / "agent.vostro.json").read_text())
        self.assertIs(config["family_push"]["morning"], True)


if __name__ == "__main__":
    unittest.main()
