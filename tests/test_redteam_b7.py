"""Red team judge, round b7 (Nov 2). Each test fails on the code before the fix.

a. "last feed, dirty diapers tonight and who is on duty" answered only the feed.
b. "vacuum over the sleeping baby" got "I could not log that. Could you send it again?".
c. After a fever was logged, the house plan still had the floor clean that day.
"""
import unittest

from parenting_agent import day_sim
from parenting_agent.agent import rules

import test_day_engine as day
import test_demo_house as house
from test_blind_b6 import night_demo
from test_one_message_one_entry import ScriptedBrain


class EveryPartWithTheRota(unittest.TestCase):
    def test_feed_diapers_and_who_is_on_duty(self):
        app, _ = night_demo(ScriptedBrain(["The last feed was at 01:10."]))
        self.addCleanup(app.close)
        reply = app.message("v", False, "last feed, dirty diapers tonight and who is on duty")[1]["reply"]
        self.assertIn("01:10", reply)
        self.assertIn("dirty", reply)
        self.assertRegex(reply, r"Next night wake-up: Parent [AB]\.")

    def test_the_rota_is_one_of_the_parts(self):
        self.assertEqual(rules.log_questions("last feed, dirty diapers tonight and who is on duty"),
                         ["last_feed", "diapers", "on_duty"])
        self.assertEqual(rules.log_questions("¿cuándo fue la última toma, cuántos pañales sucios y quién está de turno?"),
                         ["last_feed", "diapers", "on_duty"])
        self.assertNotIn("on_duty", rules.log_questions("¿cuándo fue la última toma y cuál es la farmacia de turno?"))


class UnsafeOrderRefused(unittest.TestCase):
    def reply(self, text, lang="en"):
        app, _ = night_demo()
        self.addCleanup(app.close)
        return app.message("v", False, text, lang=lang)[1]["reply"]

    def test_the_vacuum_over_the_sleeping_baby_says_why_once(self):
        for text in ("vacuum over the sleeping baby", "Run the vacuum in the nursery right now while he sleeps"):
            reply = self.reply(text)
            self.assertEqual(reply, rules.UNSAFE_ORDER_REPLY["en"])
            self.assertNotRegex(reply, r"(?i)again|could not log")

    def test_spanish(self):
        reply = self.reply("pasá la aspiradora al lado de la cuna mientras duerme", lang="es")
        self.assertEqual(reply, rules.UNSAFE_ORDER_REPLY["es"])

    def test_pauses_questions_and_reports_are_no_order(self):
        for text in ("pause the vacuum, he is asleep", "can the vacuum run while he naps?",
                     "the vacuum woke him from his nap", "he fell asleep at 9", "apagá la aspiradora que duerme"):
            self.assertFalse(rules.unsafe_house_order(text), text)


class FeverDropsTheFloorClean(unittest.TestCase):
    def test_the_day_engine_holds_the_floor_clean_after_a_fever_reading(self):
        engine, sim, bus, entries = day.make()
        entries = entries + [day_sim.note(day_sim.at(0, 12, 0), "Fever 38.2 C")]
        day.run(engine, sim, entries, day_sim.at(0, 13, 30), day_sim.at(0, 14, 30))
        self.assertFalse(any(e["kind"] == "ask_parent" and e["action"] == "floor_clean" for e in bus.history))
        holds = [e for e in bus.history if e["kind"] == "routine" and e["name"] == "floor_clean" and e["step"] == "hold"]
        self.assertTrue(holds and holds[0]["why"] == rules.FEVER_HOLD, holds)
        self.assertEqual(day.dry(bus, "vacuum.start"), [])

    def test_a_feeling_warm_note_keeps_it(self):
        engine, sim, bus, entries = day.make()
        entries = entries + [day_sim.note(day_sim.at(0, 12, 0), "he feels warm")]
        day.run(engine, sim, entries, day_sim.at(0, 13, 30), day_sim.at(0, 13, 57))
        self.assertTrue(any(e["kind"] == "ask_parent" and e["action"] == "floor_clean" for e in bus.history))

    def test_the_demo_card_shows_no_floor_clean_that_day(self):
        app = house.make(house.FakeMuse(house.answer(floor_clean=[{"start": "23:00", "end": "23:50", "why": "clean"}])))
        self.addCleanup(app.close)
        app.visitor("v").baby_log.add("note", {"text": "Fever 38.2 C"})
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        text = {r["label"]: r["text"] for r in card["rows"]}
        self.assertEqual(text["Floor clean"], "Off today: " + rules.FEVER_HOLD)


if __name__ == "__main__":
    unittest.main()
