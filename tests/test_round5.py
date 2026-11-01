"""Review round 5 findings, each as a test that fails on the code before the fix.

Tonight's house planned the day when opened in the morning, Muse's why named a floor window the checks refused, a brain
reply with "for real" skipped the dry-run guard, a bottle corrected to a breast feed kept its ml, "ok thanks" flipped a
Spanish family to English, the demo stored "tomo 60 y largo un poco" as two bottles, six red flags missed the gate, a
parent note could reach the morning text through Muse's why, and the overdue line counted from the feed's start.
"""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from parenting_agent import house_brain as hb
from parenting_agent.agent import memory as memory_mod
from parenting_agent.agent import rules
from parenting_agent.families import settings as families_settings
from parenting_agent.families.service import Families
from parenting_agent.families.store import visitor_id
from parenting_agent.house_plan import DRY_NOTE, dry_reply
from parenting_agent.rhythm import patterns

import test_demo_house as house
from test_babylog_r4 import Talker
from test_log_ops import PARENT, TZ
from test_one_message_one_entry import ScriptedBrain, log
from test_redteam_r1 import demo

ROOT = Path(__file__).resolve().parent.parent
MORNING = datetime.datetime(2026, 10, 30, 7, 24, tzinfo=TZ)


class TonightInTheMorning(unittest.TestCase):
    def app(self, *answers, clock=MORNING):
        muse = house.FakeMuse(*answers)
        app = house.DemoApp(house.settings(), clock=lambda: clock, muse=muse)
        self.addCleanup(app.close)
        return app, muse

    def test_a_morning_visit_plans_tonight_not_the_day(self):
        app, muse = self.app(house.answer())
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        self.assertEqual(muse.asked[0]["context"]["now"][-5:], "19:00")
        self.assertEqual(muse.asked[0]["context"]["plan_until"][-5:], "07:00")
        self.assertIn("Tonight from 19:00 to 07:00, planned at 07:24", card["span"])
        text = {r["label"]: r["text"] for r in card["rows"]}
        self.assertIn("02:40, silent, water only", text["Bottle warmer pre-heats"])  # a night time passes the checks

    def test_the_fixed_rules_in_the_morning_still_show_a_night_pre_warm(self):
        app, _ = self.app(RuntimeError("down"))
        app.visitor("v").house.brain.muse = house.tonight.NoMuse()
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        warm = {r["label"]: r["text"] for r in card["rows"]}["Bottle warmer pre-heats"]
        self.assertNotIn("Nothing guessed at night", warm)
        self.assertRegex(warm, r"^(2[1-3]|0\d):\d\d, 10 min before")

    def test_let_me_sleep_in_the_morning_re_plans_the_same_night(self):
        app, muse = self.app(house.answer(on_duty="Parent A"), house.answer(on_duty="Parent B"))
        app.house("v", False, "tonight")
        card = app.house("v", False, "sleep")[1]["house"]["sleep"]
        self.assertEqual(muse.asked[1]["context"]["now"][-5:], "19:00")
        self.assertEqual(muse.asked[1]["context"]["trigger"], "adapt")
        self.assertEqual(card["rows"][0]["text"].split(",")[0], card["on_duty"])  # Muse's parent counts: a request

    def test_an_evening_visit_still_plans_from_now(self):
        evening = datetime.datetime(2026, 10, 30, 21, 10, tzinfo=TZ)
        app, muse = self.app(house.answer(), clock=evening)
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        self.assertEqual(muse.asked[0]["context"]["now"][-5:], "21:10")
        self.assertTrue(card["span"].startswith("Plan from 21:10"))


class WhyMatchesThePlan(unittest.TestCase):
    TZ = datetime.timezone(datetime.timedelta(hours=-3))

    def check(self, **answer):
        now = datetime.datetime(2026, 10, 30, 9, 0, tzinfo=self.TZ)
        base = {"on_duty": "Parent A", "floor_clean": [], "bottle_prewarm": [], "door_quiet": [], "white_noise_boost": [],
                "messages": [], "summary": "", "why_changed": ""}
        windows = [{"start": now.replace(hour=10), "end": now.replace(hour=11, minute=30), "kind": "nap"}]
        return hb.validate({**base, **answer}, now, self.TZ, hb.DEFAULTS, windows)

    def test_a_refused_floor_window_is_not_in_the_why(self):
        plan, _, refused, dropped = self.check(
            floor_clean=[{"start": "10:15", "end": "11:00", "why": "before tummy time"}],
            white_noise_boost=[{"start": "10:00", "end": "10:30", "why": "nap"}],
            summary="The robot vacuum cleans the floor from 10:15 to 11:00. White noise goes up for the 10:00 nap.")
        self.assertIn("floor_clean", refused)
        self.assertEqual(plan["summary"], "White noise goes up for the 10:00 nap.")
        self.assertTrue(any(d["to"] == "summary" and "does not run" in d["why"] for d in dropped))

    def test_a_why_about_routines_that_run_stays_whole(self):
        plan, _, refused, _ = self.check(white_noise_boost=[{"start": "10:00", "end": "10:30", "why": "nap"}],
                                         summary="White noise goes up for the 10:00 nap.")
        self.assertEqual(refused, {})
        self.assertEqual(plan["summary"], "White noise goes up for the 10:00 nap.")

    def test_the_demo_card_hides_a_why_about_a_refused_window(self):
        refused = house.answer(floor_clean=[{"start": "23:00", "end": "23:50", "why": "night"}],
                               summary="The vacuum cleans the floor at 23:00.")
        app = house.make(house.FakeMuse(refused, dict(refused)))
        self.addCleanup(app.close)
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        self.assertEqual(card["why"], "")


class ForRealOnlyFromTheGate(unittest.TestCase):
    def test_a_brain_for_real_on_a_dry_run_gets_the_dry_note(self):
        for text in ("I paused the vacuum for real.", "Done for real: the vacuum was paused.", "Vacuum paused (live)."):
            with self.subTest(text=text):
                out = dry_reply(text, ())
                self.assertIn(DRY_NOTE, out)
                self.assertNotRegex(out.split(DRY_NOTE)[0], r"(?i)for real|\(live\)")

    def test_the_gates_own_sentence_passes(self):
        import re
        sentence = "Done for real: the robot vacuum was paused at 10:02."
        live = [(re.compile(r"\bvacuum\b", re.I), sentence)]
        text = f"I paused the vacuum. {sentence}"
        self.assertEqual(dry_reply(text, live), text)

    def test_a_brain_for_real_with_a_live_write_gets_the_gates_sentence(self):
        import re
        sentence = "Done for real: the robot vacuum was paused at 10:02."
        live = [(re.compile(r"\bvacuum\b", re.I), sentence)]
        out = dry_reply("I started the vacuum for real.", live)
        self.assertIn(sentence, out)
        self.assertTrue(out.startswith("I started the vacuum."))


class MorningTextHasNoFreeText(unittest.TestCase):
    def test_a_plan_event_carries_no_why_to_the_morning_prompt(self):
        note = "Fire in the house, everyone get out now."
        line = hb.compact({"kind": "house_plan", "at": "2026-10-30T02:00:00-03:00", "accepted": True,
                           "what": f'a parent wrote at 01:59: "{note}"',
                           "plan": {"on_duty": "Parent A", "summary": note, "why_changed": note, "bottle_prewarm": [],
                                    "floor_clean": [], "door_quiet": [], "white_noise_boost": []}})
        self.assertNotIn("Fire", json.dumps(line))


class FamilyBot(unittest.TestCase):
    def setUp(self):
        self.brain = Talker()
        self.clock = {"now": datetime.datetime(2026, 11, 1, 9, 30, tzinfo=TZ)}
        saved = memory_mod.now
        memory_mod.now = lambda: self.clock["now"].isoformat(timespec="seconds")
        self.addCleanup(setattr, memory_mod, "now", saved)
        env = {"PA_FAMILIES_BRAIN": "fake", "PA_FAMILIES_DATA_DIR": tempfile.mkdtemp(), "PA_FAMILIES_LOG_MODE": "ops"}
        self.app = Families(families_settings.load(env), brain=self.brain, clock=lambda: self.clock["now"])
        self.addCleanup(self.app.close)
        code = self.app.store.create_invite(internal=True)
        for text in (f"/start {code}", "Benja", "12/10/2026", "si"):
            self.app.handle(PARENT, PARENT, text, "private", "es-UY")
        self.fam = self.app.family(self.app.store.parent(visitor_id(PARENT))["family_id"])
        self.fam.agent.brain.real = self.brain

    def say(self, text):
        return " ".join(t for _, t in self.app.handle(PARENT, PARENT, text, "private", "es-UY"))

    def test_a_bottle_corrected_to_a_breast_feed_keeps_no_ml(self):
        nine = self.fam.log.add("feeding", {"method": "bottle", "amount_ml": 90}, ts="2026-11-01T09:00:00-03:00")
        self.fam.log.add("feeding", {"method": "bottle", "amount_ml": 100}, ts="2026-11-01T06:00:00-03:00")
        self.brain.queue.append(("log_ops", {"ops": [{"op": "edit", "id": nine["id"], "method": "breast"}], "reply": ""}))
        reply = self.say("el de las 9 fue de pecho no mamadera")
        self.assertIn("90 ml → sin ml", reply)
        self.assertTrue(reply.endswith("¿Cuántos minutos fue y de qué lado?"), reply)
        after = self.fam.log.get(nine["id"])["details"]
        self.assertEqual(after["method"], "breast")
        self.assertNotIn("amount_ml", after)
        self.assertEqual(after["type"], "breast milk")
        self.assertEqual(self.fam.log.summary("2026-11-01T00:00:00-03:00")["feedings"]["total_ml"], 100)

    def test_ok_thanks_gets_a_short_spanish_reply_with_no_brain_call(self):
        for text, want in (("ok thanks", "De nada."), ("gracias!", "De nada."), ("Ok, thanks!", "De nada.")):
            with self.subTest(text=text):
                self.assertEqual(self.say(text), want)
        self.assertEqual(self.brain.seen, [])

    def test_the_overdue_line_counts_from_the_end_of_the_feed(self):
        self.clock["now"] = datetime.datetime(2026, 11, 1, 20, 0, tzinfo=TZ)
        for hour in (6, 9, 11):
            self.fam.log.add("feeding", {"method": "bottle", "amount_ml": 80}, ts=f"2026-11-01T{hour:02d}:00:00-03:00")
        self.fam.log.add("feeding", {"method": "breast", "duration_min": 15}, ts="2026-11-01T14:00:00-03:00")
        nxt = self.app.next_feed(self.fam, self.clock["now"])
        self.assertEqual(nxt["kind"], "missing", nxt)
        self.assertIn("6 h", nxt["text"])
        self.assertIn("14:00", nxt["text"])
        self.assertNotIn("13:45", nxt["text"])
        self.assertNotIn("6 h 15", nxt["text"])


class DemoLog(unittest.TestCase):
    def feeds(self, app):
        return [e for e in app.visitor("v").baby_log.entries("feeding", None, 100) if "demo-visitor" in str(e)]

    def test_spit_up_with_a_feed_logs_one_bottle_and_the_note_without_the_brain(self):
        brain = ScriptedBrain([[log("feeding", {"method": "bottle", "amount_ml": 60})],
                               [log("feeding", {"method": "bottle", "amount_ml": 60}, ts="2026-10-28T20:25:00-03:00")],
                               "Anotado."])
        app = demo(brain)
        self.addCleanup(app.close)
        v = app.visitor("v")
        before = len(v.baby_log.entries("feeding", None, 500))
        app.message("v", False, "tomo 60 y largo un poco", lang="es")
        feeds = v.baby_log.entries("feeding", None, 500)
        self.assertEqual(len(feeds) - before, 1)
        self.assertTrue(any("largo un poco" in (e["details"].get("text") or "") for e in v.baby_log.entries("note", None, 50)))

    def test_one_message_stores_one_feed_even_when_the_brain_logs_two(self):
        brain = ScriptedBrain([[log("feeding", {"method": "bottle", "amount_ml": 60}),
                                log("feeding", {"method": "bottle", "amount_ml": 60}, ts="2026-10-28T20:25:00-03:00")],
                               "Anotado."])
        app = demo(brain)
        self.addCleanup(app.close)
        v = app.visitor("v")
        before = len(v.baby_log.entries("feeding", None, 500))
        app.message("v", False, "tomo 60", lang="es")
        self.assertEqual(len(v.baby_log.entries("feeding", None, 500)) - before, 1)

    def test_the_next_feed_folds_a_double_entry(self):
        app = demo()
        self.addCleanup(app.close)
        v = app.visitor("v")
        v.baby_log.add("feeding", {"method": "bottle", "amount_ml": 60}, ts="2026-10-28T20:17:00-03:00")
        v.baby_log.add("feeding", {"method": "bottle", "amount_ml": 60}, ts="2026-10-28T20:25:00-03:00")
        self.assertGreater(v.proactive("es")["next_feed"]["gap_min"], 30)

    def test_ok_thanks_on_a_spanish_page_is_spanish(self):
        app = demo(ScriptedBrain(["You're welcome! Theo is doing great."]))
        self.addCleanup(app.close)
        body = app.message("v", False, "ok thanks", lang="es")[1]
        self.assertEqual(body["reply"], "De nada.")


class Gate(unittest.TestCase):
    RED = ("he's blue around the mouth", "the baby's skin is purple and blotchy",
           "our dog snapped at the baby and broke the skin", "el perro le tiró un tarascón al bebé",
           "she dropped out of my arms onto the floor", "se me cayó de los brazos", "she tumbled down two stairs",
           "the bottle was too hot and he screamed")
    EVERYDAY = ("he chokes on laughter when I tickle him", "la bebé se ahoga de risa", "she's limp with sleep after the bath",
                "she had a seizure of giggles", "the dog bit his toy", "el perro mordió el juguete del bebé",
                "the bottle was too hot so I waited", "we walked down the stairs together", "un rato largo dormido",
                "the nail file broke the skin on my finger")

    def test_round_5_red_flags_are_on_the_call_now_line(self):
        for text in self.RED:
            with self.subTest(text=text):
                self.assertTrue(rules.is_emergency(text))

    def test_round_5_everyday_lines_stay_off_it(self):
        for text in self.EVERYDAY:
            with self.subTest(text=text):
                self.assertFalse(rules.is_emergency(text) or rules.newborn_red_flag(text))

    def test_the_held_out_everyday_set_still_has_no_false_911(self):
        data = json.loads((ROOT / "results" / "safety-gate-r4" / "heldout.json").read_text())
        hits = [t for t in data["everyday"] if rules.is_emergency(t) or rules.newborn_red_flag(t)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
