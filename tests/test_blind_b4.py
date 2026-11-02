"""Blind review round B4 (Nov 1), on baby.bygmv.com and the agent. Each test fails on the code before the fix.

1. "When did he last eat?" was answered by a fixed rule while Muse was up: Muse answers from the newest feed now.
2. Muse's why on the house card came back empty, and after a fever note it talked about paracetamol.
3. "Parent B" in English in a Spanish session.
4. A feed told with a safe sleep question, and a diaper told with a health question, were not logged.
5. Diaper counts that did not add up ("3 pañales: 3 con pis y 1 con caca").
6. "Awake 4 h 1 min" for a 6 week old: a sleep in progress was dropped, and an implausible awake time was said as fact.
7. The "let me sleep" button wrote a ready-made "I'm exhausted" note into the log.
"""
import datetime
import re
import tempfile
import unittest

from parenting_agent import cry_reason
from parenting_agent.agent import brain as brain_mod
from parenting_agent.agent import rules
from parenting_agent.agent.memory import LocalBabyLog, Memory, feed_start
from parenting_agent.demo import tonight
from parenting_agent.demo.babylog import DemoBabyLog, started, finished

import test_demo_house as house
from test_one_message_one_entry import ScriptedBrain
from test_redteam_r1 import EVENING, call, demo

TZ = datetime.timezone(datetime.timedelta(hours=-3))


class LastFeedBrain:
    """A model that answers the last feed question from the fact the agent gives it, with the time."""
    name, model, destination = "openai_compatible", "meta-models/muse-spark-open-1026", "inference.baseten.co"

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def step(self, system, transcript, tools):
        self.calls += 1
        if self.fail:
            raise brain_mod.BrainError("timed out")
        at = re.findall(r"\b\d\d:\d\d\b", transcript[-1]["text"])
        return brain_mod.Reply(f"Theo tomó por última vez a las {at[-1]}, según el registro." if at else "No hay tomas.")


class LastFeedGoesToMuse(unittest.TestCase):
    def test_the_demo_answers_with_muse_when_the_brain_is_up(self):
        brain = LastFeedBrain()
        app = demo(brain)
        self.addCleanup(app.close)
        _, body = app.message("v", False, "¿cuándo comió por última vez?", lang="es")
        last = app.visitor("v").agent.latest_of("feeding")
        self.assertEqual(brain.calls, 1)
        self.assertEqual(body["answered_by"], {"kind": "brain", "model": brain.model, "muse": True})
        self.assertIn(feed_start(last)[11:16], body["reply"])
        self.assertTrue(body["reply"].startswith("Theo tomó"), body["reply"])

    def test_a_muse_error_gets_the_fixed_line_labelled_busy(self):
        app = demo(LastFeedBrain(fail=True))
        self.addCleanup(app.close)
        _, body = app.message("v", False, "When did he last eat?")
        self.assertEqual(body["answered_by"], {"kind": "busy"})
        self.assertIn("The last feed was", body["reply"])

    def test_with_no_brain_the_fixed_rule_answers_and_says_so(self):
        app = demo()
        self.addCleanup(app.close)
        _, body = app.message("v", False, "When did he last eat?")
        self.assertEqual(body["answered_by"], {"kind": "rule"})
        self.assertTrue(body["reply"].startswith("The last feed was"), body["reply"])

    def test_no_empty_tools_list_is_sent_to_the_api(self):
        sent = {}
        b = brain_mod.OpenAICompatibleBrain.__new__(brain_mod.OpenAICompatibleBrain)
        b.url, b.model, b.max_tokens, b.timeout, b.prices, b.reasoning_effort, b.headers = "u", "m", 10, 1, None, None, {}
        real = brain_mod.post_json
        brain_mod.post_json = lambda url, headers, body, timeout: sent.update(body) or {"choices": [{"message": {"content": "ok"}}]}
        try:
            b.step("s", [{"role": "user", "text": "hi"}], [])
        finally:
            brain_mod.post_json = real
        self.assertNotIn("tools", sent)


class HouseWhy(unittest.TestCase):
    def test_an_empty_why_is_asked_once_more(self):
        muse = house.FakeMuse(house.answer(summary=""), house.answer(summary="Warm water at 02:40, before the 02:50 feed."))
        app = house.make(muse)
        self.addCleanup(app.close)
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        self.assertEqual(len(muse.asked), 2)
        self.assertEqual(card["why"], "Warm water at 02:40, before the 02:50 feed.")

    def test_two_empty_whys_hide_the_field(self):
        muse = house.FakeMuse(house.answer(summary=""), house.answer(summary=""))
        app = house.make(muse)
        self.addCleanup(app.close)
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        self.assertEqual((len(muse.asked), card["why"]), (2, ""))
        self.assertNotIn("Muse's why", tonight.text(app.visitor("v").house.plans["tonight"]))

    def test_a_why_about_a_fever_note_keeps_only_the_plan(self):
        muse = house.FakeMuse(house.answer(summary="He had a fever at 20:00 and got paracetamol. "
                                                   "Warm water at 02:40, before the 02:50 feed."))
        app = house.make(muse)
        self.addCleanup(app.close)
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        self.assertEqual(card["why"], "Warm water at 02:40, before the 02:50 feed.")

    def test_a_spanish_visitor_gets_the_why_asked_in_spanish(self):
        muse = house.FakeMuse(house.answer(summary="El agua se calienta a las 02:40, antes de la toma de las 02:50."))
        app = house.make(muse)
        self.addCleanup(app.close)
        card = app.house("v", False, "tonight", lang="es")[1]["house"]["tonight"]
        self.assertIn("Rioplatense Spanish", muse.asked[0]["system"])
        self.assertEqual(card["why"], "El agua se calienta a las 02:40, antes de la toma de las 02:50.")


class SpanishLabels(unittest.TestCase):
    def test_the_card_names_persona_b(self):
        app = house.make(house.FakeMuse(house.answer()))
        self.addCleanup(app.close)
        card = app.house("v", False, "tonight", lang="es")[1]["house"]["tonight"]
        self.assertIn(card["on_duty"], ("Papá", "Mamá"))

    def test_set_on_duty_and_the_rota_read_spanish(self):
        brain = ScriptedBrain([[call("set_on_duty", parent="Parent B")], "Listo, Mamá queda de turno esta noche."],
                              [[call("night_rota")], "Le toca a Mamá."])
        app = demo(brain)
        self.addCleanup(app.close)
        _, body = app.message("v", False, "poné a Mamá de turno esta noche", lang="es")
        self.assertEqual(body["actions"][0]["arguments"], {"parent": "Mamá"})
        v = app.visitor("v")
        self.assertIn("Mamá queda de turno", v.agent.tools.items["set_on_duty"].handler(parent="Parent B"))
        self.assertNotIn("Parent", v.night_rota())


class SafetyLineAndTheLog(unittest.TestCase):
    def test_a_feed_with_a_safe_sleep_question_is_logged_after_the_line(self):
        app = demo()
        self.addCleanup(app.close)
        log = app.visitor("v").baby_log
        before = len(log.entries("feeding", None, 1000))
        _, body = app.message("v", False, "le di 60 ml de mamadera. ¿puede dormir boca abajo?", lang="es")
        self.assertTrue(body["reply"].startswith(rules.SAFE_SLEEP_FACT["es"]), body["reply"])
        self.assertIn("60 ml", body["reply"][len(rules.SAFE_SLEEP_FACT["es"]):])
        feeds = log.entries("feeding", None, 1000)
        self.assertEqual((len(feeds), feeds[-1]["details"]["amount_ml"]), (before + 1, 60.0))

    def test_a_green_poop_diaper_is_logged_then_the_fixed_line(self):
        app = demo()
        self.addCleanup(app.close)
        log = app.visitor("v").baby_log
        before = len(log.entries("diaper", None, 1000))
        _, body = app.message("v", False, "le cambié el pañal, hizo caca verde, ¿es normal?", lang="es")
        diapers = log.entries("diaper", None, 1000)
        self.assertEqual(len(diapers), before + 1)
        self.assertTrue(diapers[-1]["details"]["solid"])
        self.assertIn("pediatra", body["reply"])
        self.assertTrue(body["reply"].startswith("Anoté"), body["reply"])

    def test_a_question_alone_logs_nothing(self):
        self.assertEqual(rules.reported_entries("¿es normal la caca verde?"), [])
        self.assertEqual(rules.reported_entries("¿puede tomar 60 ml y dormir boca abajo?"), [])
        self.assertEqual(rules.reported_entries("no hizo caca, ¿es normal?"), [])


class DiaperCounts(unittest.TestCase):
    def test_the_counts_add_up_everywhere(self):
        memory = Memory(":memory:")
        self.addCleanup(memory.close)
        log = LocalBabyLog(memory)
        for details in ({"wet": True, "solid": True}, {"wet": True}, {"wet": True}, {"wet": True}):
            log.add("diaper", details)
        diapers = log.summary()["diapers"]
        self.assertEqual(diapers["said"], {"en": "4 diapers: 3 wet only, 1 dirty", "es": "4 pañales: 3 solo pis, 1 con caca"})
        self.assertEqual(diapers["wet_only"] + diapers["dirty"] + diapers["dry"], diapers["count"])
        self.assertNotIn("wet", diapers)  # no overlapping count for a model to retell
        self.assertEqual(rules.answer("how many diapers today?", log.summary()), "Today: 4 diapers: 3 wet only, 1 dirty.")


class AwakeTime(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 1, 15, 0, tzinfo=TZ)

    def rows(self, *extra):
        t = lambda h, m=0: self.NOW.replace(hour=h, minute=m).isoformat()
        return [{"kind": "feeding", "start": t(10, 30), "end": t(10, 50), "ref": "feeding#1"},
                {"kind": "change", "time": t(10, 55), "ref": "change#1"},
                {"kind": "sleep", "start": t(9), "end": t(10, 59), "ref": "sleep#1"}] + list(extra)

    def test_a_sleep_still_open_is_no_awake_time(self):
        rows = self.rows({"kind": "sleep", "start": self.NOW.replace(hour=11, minute=30).isoformat(), "end": None,
                          "ref": "timers/1"})
        ctx = cry_reason.context(rows, self.NOW, TZ, young=False)
        self.assertNotIn("awake_min", ctx)
        self.assertNotIn("awake", cry_reason.explain(rows, self.NOW, TZ)["text"])

    def test_four_hours_awake_under_3_months_is_not_said(self):
        self.assertNotIn("awake_min", cry_reason.context(self.rows(), self.NOW, TZ))
        self.assertNotIn("awake 4 h", cry_reason.explain(self.rows(), self.NOW, TZ)["text"])
        self.assertAlmostEqual(cry_reason.context(self.rows(), self.NOW, TZ, young=False)["awake_min"], 241)

    def test_the_demo_keeps_a_simulated_sleep_open_when_the_visitor_takes_over(self):
        start = datetime.datetime(2026, 11, 1, 0, 0, tzinfo=TZ)
        for minute in range(0, 24 * 60, 5):
            now = start + datetime.timedelta(minutes=minute)
            log = DemoBabyLog(clock=lambda: now)
            asleep = [r for r in log.upcoming if r["kind"] == "sleep" and started(r) < now < finished(r)]
            if asleep and now - started(asleep[0]) > datetime.timedelta(minutes=30):
                break
        else:
            self.fail("no simulated sleep in progress")
        log.add("feeding", {"method": "bottle", "amount_ml": 30})
        self.assertEqual(log.open_sleep(), started(asleep[0]).isoformat(timespec="seconds"))
        self.assertNotIn("awake_min", cry_reason.context(log.rhythm_rows(), now, TZ))


class SleepButton(unittest.TestCase):
    def test_the_button_writes_nothing_into_the_log(self):
        muse = house.FakeMuse(house.answer(), house.answer(on_duty="Parent A"))
        app = house.make(muse)
        self.addCleanup(app.close)
        app.house("v", False, "tonight")
        log = app.visitor("v").baby_log
        before = log.entries(None, None, 1000)
        app.house("v", False, "sleep", lang="es")
        self.assertEqual(log.entries(None, None, 1000), before)
        self.assertEqual(muse.asked[-1]["context"]["trigger"], "adapt")
        self.assertIn("asked to sleep tonight", muse.asked[-1]["context"]["what_happened"])


if __name__ == "__main__":
    unittest.main()
