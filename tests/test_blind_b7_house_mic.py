"""Blind round b7 on the live demo: "let me sleep" re-plans with a why and what changed, the why never quotes a time the
checks moved, and "did the microphone hear him cry?" is answered from the event log."""
import datetime
import unittest

from parenting_agent import house_brain as hb
from parenting_agent.agent import rules
from parenting_agent.demo.app import PARENTS

import test_demo_house as house

TZ = house.TZ


class SleepRePlans(unittest.TestCase):
    def test_a_same_plan_from_muse_still_hands_over_the_night_and_says_why(self):
        # Muse kept the plan as it was, with no why_changed: the card used to come back the same as tonight's.
        muse = house.FakeMuse(house.answer(), house.answer(), house.answer())
        app = house.make(muse)
        self.addCleanup(app.close)
        before = app.house("v", False, "tonight", lang="es")[1]["house"]["tonight"]
        card = app.house("v", False, "sleep", lang="es")[1]["house"]["sleep"]
        asker = next(p for p in PARENTS if house.tonight.name(p, "es") == before["on_duty"])
        other = next(p for p in PARENTS if p != asker)
        self.assertEqual(card["on_duty"], house.tonight.name(other, "es"))
        self.assertTrue(card["changes"] and card["changes"] != ["No cambió nada en el plan"], card["changes"])
        self.assertIn("pidió dormir a las 22:30", card["why_changed"])
        self.assertEqual(card["why_label"], "Por qué")
        self.assertEqual(app.visitor("v").rota()["on_duty"], other)

    def test_with_no_muse_the_code_still_hands_over_the_night(self):
        app = house.make(house.FakeMuse(house.BrainError("down"), house.BrainError("down")))
        self.addCleanup(app.close)
        card = app.house("v", False, "sleep")[1]["house"]["sleep"]
        self.assertEqual(card["source"], "fixed")
        self.assertIn("because", card["rows"][0]["text"])
        self.assertTrue(card["changes"][0].startswith("On duty tonight:"), card["changes"])
        self.assertIn("asked to sleep at 22:30", card["why_changed"])

    def test_typed_and_chat_text_carry_both(self):
        app = house.make(house.FakeMuse(house.answer(), house.answer()))
        self.addCleanup(app.close)
        reply = app.message("v", False, "I'm exhausted, let me sleep tonight")[1]["reply"]
        self.assertIn("Difference: On duty tonight:", reply)
        self.assertIn("asked to sleep at 22:30", reply)


class WhyQuotesThePlansTimes(unittest.TestCase):
    S = {**hb.DEFAULTS, "parents": ["Parent A", "Parent B"]}
    NOW = datetime.datetime(2026, 11, 1, 23, 0, tzinfo=TZ)

    def test_a_moved_pre_warm_time_is_not_quoted(self):
        feed = self.NOW.replace(day=2, hour=6, minute=2)  # the warmer follows it: 05:52
        answer = house.answer(bottle_prewarm=[{"start": "05:32", "why": "night feed"}], white_noise_boost=[],
                              summary="Parent B takes the night. Warm water at 05:32 for the dawn feed.",
                              summary_es="Mamá toma la noche. Agua tibia a las 05:32 para la toma del amanecer.")
        plan, _, refused, dropped = hb.validate(answer, self.NOW, TZ, self.S, [], next_feed=feed)
        self.assertEqual([w["start"].astimezone(TZ).strftime("%H:%M") for w in plan["bottle_prewarm"]], ["05:52"])
        self.assertNotIn("05:32", plan["summary"] + plan["summary_es"])
        self.assertIn("Parent B takes the night.", plan["summary"])
        self.assertTrue(any(d["why"] == "quotes a time the checked plan does not hold" for d in dropped))

    def test_a_kept_time_stays(self):
        answer = house.answer(bottle_prewarm=[{"start": "05:52", "why": "night feed"}], white_noise_boost=[],
                              summary="Warm water at 05:52 before the 06:02 feed.")
        plan, *_ = hb.validate(answer, self.NOW, TZ, self.S, [], next_feed=self.NOW.replace(day=2, hour=6, minute=2))
        self.assertEqual(plan["summary"], "Warm water at 05:52 before the 06:02 feed.")


class MicrophoneHeard(unittest.TestCase):
    def test_the_question_is_routed(self):
        for text in ("Did the microphone hear him cry?", "¿El micrófono lo escuchó llorar?", "did the mic hear crying?"):
            self.assertTrue(rules.asks_heard_cry(text), text)
        for text in ("why is he crying?", "he has been crying for an hour", "did the mic hear him cry? he has a fever"):
            self.assertFalse(rules.asks_heard_cry(text), text)

    def test_answered_from_the_event_log(self):
        app = house.make(house.FakeMuse())
        self.addCleanup(app.close)
        app.state("v", False)
        v = app.visitor("v")
        at = lambda h, m: house.NOW.replace(hour=h, minute=m).isoformat()
        v.bus.publish("sound", label="cry", phase="ongoing", episode=1, seconds=20, ts=at(21, 10))
        v.bus.publish("sound", label="cry", phase="end", episode=1, seconds=45, ts=at(21, 11))
        v.bus.publish("sound", label="dog", phase="start", episode=2, seconds=1, ts=at(21, 30))
        reply = app.message("v", False, "Did the microphone hear him cry?")[1]["reply"]
        self.assertIn("heard crying 1 time: 21:11 (45 s)", reply)
        self.assertNotIn("diaper", reply.lower())

    def test_no_microphone_says_so(self):
        app = house.make(house.FakeMuse())
        self.addCleanup(app.close)
        reply = app.message("v", False, "¿El micrófono lo escuchó llorar?", lang="es")[1]["reply"]
        self.assertIn("No hay un micrófono conectado", reply)


if __name__ == "__main__":
    unittest.main()
