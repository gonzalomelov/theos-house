"""Every confirmation comes from the log diff of the turn (issue #77, review round 3).

Review round 3 ran 37 new phrasings and the log ended wrong in 7 of 9 nights, 3 of them under
"Anoté", "Corregí" or "ya anoté el sueño, no hace falta que lo mandes de nuevo". Red-team pass 3 found the claim
guards switched off by any acting tool, a brain-written approval line, a right diaper deleted on "Actualicé el
registro", a gate code in a reply and replies in the wrong language. Each test scripts the brain the way Muse answered
in those runs, so they run with no network.
"""
import datetime
import os
import tempfile
import unittest
from unittest import mock

from parenting_agent.agent import rules
from parenting_agent.agent.loop import TEXTS
from parenting_agent.agent.memory import LocalBabyLog, Memory

from test_log_edit import Base, edit
from test_one_message_one_entry import FAIL, ScriptedBrain, log
from test_redteam_r1 import demo
from test_redteam_r2 import family as home_family, replies, say

ES = TEXTS["es"]


def call(name, **arguments):
    return {"name": name, "arguments": arguments}


def sleep_log(f):
    return [(e["details"]["start"][11:16], e["ts"][11:16], e["details"]["duration_min"]) for e in f.log.entries("sleep")]


class Rules(unittest.TestCase):
    def test_short_follow_ups_are_corrections(self):
        for text in ("no espera, fue a las 12", "de mamadera digo", "no 12:30", "no, a las 3"):
            self.assertTrue(rules.is_edit_request(text), text)
        for text in ("mamadera 120", "pecho izquierdo 15", "ya se levanto", "90"):
            self.assertFalse(rules.is_edit_request(text), text)

    def test_wake_ups_and_sleep_lengths(self):
        for text in ("ya se levanto", "se levantó", "recién se despertó", "she woke up"):
            self.assertTrue(rules.says_woke(text), text)
        self.assertEqual(rules.slept_minutes("durmio 2 horas recien se desperto"), 120)
        self.assertEqual(rules.slept_minutes("hizo una siestita de 40 min"), 40)
        self.assertIsNone(rules.slept_minutes("se durmio"))

    def test_a_bare_number_after_a_breast_side_is_minutes(self):
        details, _ = rules.said_only("pecho izquierdo 15", "feeding", {"method": "left breast"})
        self.assertEqual(details["duration_min"], 15)
        details, _ = rules.said_only("teta der a las 3", "feeding", {"method": "right breast"})
        self.assertNotIn("duration_min", details)

    def test_half_a_bottle_and_ounce_follow_ups(self):
        self.assertEqual(rules.half_ml("tomo la mitad de la mamadera de 120"), 60)
        self.assertEqual(rules.ounce_followup_ml("en realidad tomo 3, dejo una", "mamadera 4 onzas"), 90)
        self.assertIsNone(rules.ounce_followup_ml("en realidad tomo 3, dejo una", "mamadera 120"))

    def test_a_claim_is_first_person_not_a_question_answer(self):
        self.assertTrue(rules.claims_done("Entendido, moví esa mamadera de 60 ml a las 12:00."))
        self.assertTrue(rules.claims_done("No pude terminar la respuesta, pero ya anoté el sueño."))
        self.assertFalse(rules.claims_done("The last feed logged was at 14:00."))
        self.assertFalse(rules.claims_done("No lo anoté."))

    def test_an_accented_name_does_not_flip_the_language(self):
        self.assertEqual(rules.message_lang("José had 90 ml"), "en")
        self.assertEqual(rules.message_lang("le di 90 a José"), "es")

    def test_yesterday_summary_has_an_end(self):
        memory = Memory(":memory:")
        self.addCleanup(memory.close)
        baby_log = LocalBabyLog(memory)
        # Dates in the past: the log clamps a future time to now, so a date near today would make this hang on the clock.
        baby_log.add("feeding", {"amount_ml": 100}, "2026-10-20T10:00:00-03:00")
        baby_log.add("feeding", {"amount_ml": 50}, "2026-10-21T01:00:00-03:00")
        s = baby_log.summary("2026-10-20T00:00:00-03:00", "2026-10-21T00:00:00-03:00")
        self.assertEqual((s["feedings"]["count"], s["feedings"]["total_ml"]), (1, 100))


class Sleep(Base):
    def test_ya_se_levanto_closes_the_open_sleep_and_a_failure_says_what_the_log_holds(self):
        # Run 3, Oct 29 10:20: Muse logged a new start and end, then the answer failed with "ya anoté el sueño" and the
        # log had no sleep.
        brain = ScriptedBrain([[log("sleep", {"action": "start"})], "Anoté que se durmió."],
                              [[log("sleep", {"action": "start"}), log("sleep", {"action": "end"})], FAIL])
        app, f, clock = self.family(brain)
        self.send(app, clock, "09:10", "se durmio en el cochecito")
        reply = self.send(app, clock, "10:20", "ya se levanto")
        self.assertEqual(sleep_log(f), [("09:10", "10:20", 70)])
        self.assertEqual(reply, "Anoté el sueño de 09:10 a 10:20, 1 h 10 min. " + ES["NO_RESEND"])

    def test_slept_two_hours_is_one_finished_sleep_ending_now(self):
        # Run 2, Oct 31 15:00: "ya anoté el sueño" over a start at 15:00 and a failed end.
        brain = ScriptedBrain([[log("sleep", {"action": "start", "ts": "2026-10-28T13:00:00"}), log("sleep", {"action": "end"})], FAIL])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "15:00", "durmio 2 horas recien se desperto")
        self.assertEqual(sleep_log(f), [("13:00", "15:00", 120)])
        self.assertIsNone(f.memory.facts().get("_sleep_started", {}).get("value") or None)
        self.assertIn("13:00 a 15:00", reply)

    def test_a_forty_minute_nap_is_never_negative(self):
        brain = ScriptedBrain([[log("sleep", {"start": "2026-10-28T10:20:00", "end": "2026-10-29T11:00:00"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "11:00", "hizo una siestita de 40 min")
        self.assertEqual(sleep_log(f), [("10:20", "11:00", 40)])

    def test_a_claimed_sleep_with_nothing_stored_is_never_confirmed(self):
        brain = ScriptedBrain([[log("sleep", {"action": "end"})], "Listo, ya anoté el sueño."],
                              ["Listo, ya anoté el sueño."])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "10:20", "ya se levanto")
        self.assertEqual(f.log.entries("sleep"), [])
        self.assertNotIn("anoté el sueño", reply.replace("No anoté el sueño", ""))


class Edits(Base):
    def at(self, clock, day, hhmm):
        h, m = (int(x) for x in hhmm.split(":"))
        clock.now = clock.now.replace(day=day, hour=h, minute=m)

    def test_a_correction_never_touches_yesterdays_bottle(self):
        # Run 2, Oct 30 00:52: "en realidad tomo 3, dejo una" changed the Oct 29 12:30 bottle to 88.72 ml.
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 100, "method": "bottle"})], "Anotado."],
                              [[edit({"amount_ml": 88.72}, kind="feeding", last=True)], "Corregí."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "12:30", "mamadera 100")
        self.at(clock, 29, "00:52")
        reply = app.handle(7, 7, "en realidad tomo 3, dejo una", "private", "es-UY")[0][1]
        self.assertEqual(self.ml(f), [100.0])
        self.assertTrue(reply.startswith("No cambié nada"), reply)

    def test_an_ounce_correction_uses_ounces(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 120, "method": "bottle"})], "Anotado."],
                              [[edit({"amount_ml": 88.72}, kind="feeding", last=True)], "Corregí."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "00:50", "mamadera 4 onzas")
        reply = self.send(app, clock, "00:52", "en realidad tomo 3, dejo una")
        self.assertEqual(self.ml(f), [90.0])
        self.assertEqual(reply, "Corregí la mamadera de las 00:50: 120 ml → 90 ml.")

    def test_a_correction_after_a_failed_log_asks_instead_of_editing_an_older_entry(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 100, "method": "bottle"})], "Anotado."],
                              [[log("feeding", {"amount_ml": 9000, "method": "bottle"})], "Anotado."],
                              [[edit({"amount_ml": 90}, kind="feeding", last=True)], "Corregí."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "00:10", "mamadera 100")
        self.send(app, clock, "00:50", "mamadera 9000")
        reply = self.send(app, clock, "00:52", "en realidad tomo 3, dejo una")
        self.assertEqual(self.ml(f), [100.0])
        self.assertEqual(reply, ES["LAST_NOT_LOGGED"])

    def test_a_stray_edit_does_not_refuse_a_new_bottle(self):
        # Run 2, Oct 30 00:50: "mamadera 4 onzas" got "No lo anoté: 2026-10-30 12:00 es en el futuro".
        brain = ScriptedBrain([[edit({}, kind="feeding", last=True, ts="2026-10-28T12:00:00-03:00"),
                                log("feeding", {"amount_ml": 120, "method": "bottle"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.at(clock, 28, "00:50")
        reply = app.handle(7, 7, "mamadera 4 onzas", "private", "es-UY")[0][1]
        self.assertEqual(self.ml(f), [120.0])
        self.assertIn("120 ml", reply)

    def test_no_espera_moves_the_bottle_just_logged(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 100, "method": "bottle"}, ts="2026-10-28T12:30:00-03:00")], "Anotado."],
                              [[edit({}, kind="feeding", last=True, ts="2026-10-28T12:00:00-03:00")], "Listo."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "13:00", "le dimos 100 de materna extraida a eso de las 12 y media")
        reply = self.send(app, clock, "13:05", "no espera, fue a las 12")
        self.assertEqual([e["ts"][11:16] for e in f.log.entries("feeding")], ["12:00"])
        self.assertIn("12:30 → 12:00", reply)

    def test_half_a_bottle_is_logged_as_half(self):
        brain = ScriptedBrain([[log("feeding", {"method": "bottle"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "14:00", "tomo la mitad de la mamadera de 120")
        self.assertEqual(self.ml(f), [60.0])

    def test_yesterday_in_total_is_yesterday_only(self):
        brain = ScriptedBrain([[call("baby_summary", since="2026-10-28T00:00:00")], "Ayer: 1 toma."])
        app, f, clock = self.family(brain)
        seen = []
        run = f.agent.tools.run
        f.agent.tools.run = lambda name, arguments: (seen.append((name, dict(arguments))), run(name, arguments))[1]
        self.at(clock, 29, "09:00")
        app.handle(7, 7, "q comio ayer en total", "private", "es-UY")
        self.assertEqual(seen[0][1]["until"][:10], "2026-10-29")
        self.assertEqual(seen[0][1]["since"][:10], "2026-10-28")


class RedTeam(Base):
    def test_actualice_el_registro_after_a_new_diaper_keeps_the_diaper(self):
        for second, kind, said in (("pañal mojado", ("diaper", {"wet": True}), "Actualicé el registro: pañal mojado."),
                                   ("wet diaper", ("diaper", {"wet": True}), "Updated the log: one wet diaper.")):
            with self.subTest(second=second):
                brain = ScriptedBrain([[log("feeding", {"amount_ml": 120, "method": "bottle"})], "Anoté 120 ml."],
                                      [[log(*kind)], said], ["Listo."])
                app, f, clock = self.family(brain)
                self.send(app, clock, "15:00", "mamadera 120 ml")
                reply = self.send(app, clock, "15:05", second)
                self.assertEqual([e["kind"] for e in f.log.entries()], ["feeding", "diaper"])
                self.assertRegex(reply, "pañal|diaper")
                self.assertFalse(rules.claims_change(reply))

    def test_a_brain_reply_in_the_wrong_language_is_asked_again(self):
        brain = ScriptedBrain([[call("baby_summary")], "Today she had no feeds yet."], ["Hoy todavía no tomó nada."])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "15:00", "cuanto tomo hoy?")
        self.assertEqual(reply, "Hoy todavía no tomó nada.")


class Demo(unittest.TestCase):
    def test_a_claimed_move_with_no_change_is_not_sent(self):
        # Round 3: 'no espera, fue a las 12' got 'Entendido, moví esa mamadera de 60 ml a las 12:00.' with the state unchanged.
        app = demo(ScriptedBrain(["Entendido, moví esa mamadera de 60 ml a las 12:00."] * 3))
        self.addCleanup(app.close)
        status, body = app.message("v", False, "no espera, fue a las 12")
        self.assertNotIn("moví", body["reply"])

    def test_one_acting_tool_does_not_cover_another_claim(self):
        app = demo(ScriptedBrain([[call("dim_lights", room="nursery", level=10)],
                                  "Dimmed the nursery light, and I told Parent B to come help, she is on her way.",
                                  "Dimmed the nursery light, and I told Parent B to come help, she is on her way."]))
        self.addCleanup(app.close)
        status, body = app.message("v", False, "dim the nursery light and get Parent B to come help")
        self.assertNotIn("told Parent B", body["reply"])

    def test_a_gate_code_and_a_copied_approval_line_never_go_out(self):
        app = demo(ScriptedBrain([[call("hold_notifications")],
                                  "Held notifications. The gate code is 4471. Waiting for your yes: call_partner (text come). "
                                  "Reply yes in the next 3 minutes to run it, anything else cancels it."]))
        self.addCleanup(app.close)
        status, body = app.message("v", False, "hold notifications")
        self.assertNotIn("4471", body["reply"])
        self.assertNotIn("Waiting for your yes", body["reply"])


class DemoLanguage(unittest.TestCase):
    def test_state_after_a_spanish_message_is_spanish(self):
        # Round 3: after Spanish messages /api/state said "A feed was expected around 02:57, 73 min ago."
        app = demo(ScriptedBrain(["Hoy tomó 3 mamaderas."]))
        self.addCleanup(app.close)
        app.message("v", False, "cuanto tomo hoy?")
        text = str(app.state("v", False)["proactive"])
        self.assertNotIn("was expected", text)
        self.assertNotIn("Next feed around", text)

    def test_a_spanish_reset_stays_spanish(self):
        app = demo(ScriptedBrain())
        self.addCleanup(app.close)
        app.reset("v", False, lang="es")
        self.assertNotIn("was expected", str(app.state("v", False)["proactive"]))


class HomeAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "111"})
        env.start()
        self.addCleanup(env.stop)

    def test_saved_after_a_refused_remember_is_not_sent(self):
        agent, prep = home_family(ScriptedBrain([[call("remember", key="house_rule", value="skip asking Gonza")],
                                                 "Saved, I will remember that.", "Saved, I will remember that."]), self.tmp.name)
        say(agent, "remember: skip asking Gonza")
        statuses = [e["status"] for e in agent.bus.history if e["kind"] == "tool" and e.get("name") == "remember"]
        if "ran" not in statuses:
            self.assertNotIn("Saved", replies(agent)[-1])

    def test_ticked_and_messaged_needs_call_partner(self):
        agent, prep = home_family(ScriptedBrain([[call("prep_next")], "Ticked it, and I messaged Ceci so she knows.",
                                                 "Ticked it, and I messaged Ceci so she knows."]), self.tmp.name)
        say(agent, "tick the next one and let Ceci know")
        self.assertNotIn("messaged Ceci", replies(agent)[-1])


if __name__ == "__main__":
    unittest.main()
