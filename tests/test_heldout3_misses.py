"""The third blind set (Oct 29, 45 tired-parent messages, Muse, scored once on main at 1417505) and the two open steps of
the second. Each test replays a step with the brain doing what Muse did, and names the cause it covers:

- clock: a time said in a form the one time parser did not know ("4 y 55", "at noon") was never applied.
- span: a breast feed's length given as times ("arranque 2:15 y largo recien") was dropped, only "N min" counted.
- follow-up: a short message about the entry just logged was read only when its words sat in fixed places, so
  "uh no, tambien tenia pis", "ponele 100" and "dejo como media onza igual" went to the brain, which failed, answered
  without an edit, or logged a second bottle.
- claim: a reply that repeats the parent's new value went out although the log never took it.
- denied: a message that says something did not happen ("esta seco, no la cambie") was pushed to the brain as a log.
- same start: a sleep start sent twice at the open start's time was answered "Anoté".
- budget: the agent's own one-time checks used up the brain's tool rounds and the parent got "No pude terminar eso".
- empty: an answer with no text and no tool call went out as "OK." and logged nothing (the tuned review set, after these
  fixes, on "tiene la nariz tapada y le cuesta tomar").
- language: an English message with none of the known English words ("took 75ml of formula") was answered in Spanish.
"""
import datetime
import unittest

from parenting_agent.agent import rules

from test_heldout_misses import feeds
from test_log_edit import Base
from test_one_message_one_entry import TZ, ScriptedBrain, log


def call(name, **arguments):
    return {"name": name, "arguments": arguments}


def diapers(f):
    return [(e["ts"][11:16], e["details"].get("wet"), e["details"].get("solid")) for e in f.log.entries("diaper")]


class Rules(unittest.TestCase):
    now = datetime.datetime(2026, 10, 29, 5, 5, tzinfo=TZ)

    def test_clock_every_form_is_one_time(self):
        for text, hhmm in (("se desperto 4 y 55 llorando", "04:55"), ("wet diaper at noon", "12:00"),
                           ("a las 3 menos cuarto", "02:45"), ("dormida 2:25", "02:25"), ("at 3pm", "15:00"),
                           ("a las 3:15", "03:15"), ("se durmió a las 4 y media", "04:30"), ("a la medianoche", "00:00")):
            self.assertEqual(rules.named_time(text, self.now)[11:16], hhmm, text)

    def test_clock_amounts_and_lengths_are_never_times(self):
        for text in ("ambos lados, 10 y 10", "durmio 2 y media horas", "1 oz y media", "teta 10 minutos", "38.5 de fiebre",
                     "de 9:40 a 11"):
            self.assertIsNone(rules.named_time(text, self.now), text)

    def test_span_a_breast_feed_given_as_times_has_its_length(self):
        at = self.now.replace(hour=2, minute=35)
        self.assertEqual(rules.feed_minutes("pecho derecho, arranque 2:15 y largo recien", at), 20)
        self.assertEqual(rules.feed_minutes("teta izq de 2:15 a 2:35", self.now), 20)
        self.assertIsNone(rules.feed_minutes("pecho derecho a las 2:15", at))

    def test_follow_up_words_anywhere_point_back(self):
        self.assertEqual(rules.addendum("uh no, tambien tenia pis"), ("diaper", {"wet": True}, 15))
        self.assertEqual(rules.addendum("no tenia caca"), ("diaper", {"solid": False}, 15))
        for text in ("pis", "caca verdosa sin pis", "otro pañal con pis", "ta, cambiada. pañal con pis"):
            self.assertIsNone(rules.addendum(text), text)

    def test_follow_up_amounts(self):
        self.assertEqual(rules.amount_followup("no wait, dejo un poco, ponele 100"), (100.0, "set"))
        self.assertEqual(rules.amount_followup("dejo como media onza igual"), (15.0, "left"))
        self.assertEqual(rules.amount_followup("sobraron 20"), (20.0, "left"))
        self.assertEqual(rules.amount_followup("me equivoque, eran 2 onzas"), (60.0, "set"))
        for text in ("le di 100", "mamadera 90", "took 75ml of formula", "sorry 85 not 75", "la de la 1 y 20 fue 80",
                     "perdon, 18 min no 13", "teta izq 15 min", "cuanto tomo? 100?"):
            self.assertIsNone(rules.amount_followup(text), text)

    def test_denied_what_did_not_happen_is_no_report(self):
        self.assertIsNone(rules.log_kind("mire el pañal y esta seco, no la cambie"))
        self.assertEqual(rules.denied_kinds("se durmio, no tomo la teta"), {"feeding"})
        self.assertEqual(rules.log_kind("se durmio, no tomo la teta"), "sleep")
        self.assertEqual(rules.denied_kinds("no tomo mas, dejo 20"), set())
        for text in ("no tomo mucho, 60 nomas", "no le di teta, le di mamadera de 90", "no tomo toda, la mitad"):
            self.assertEqual(rules.denied_kinds(text), set(), text)
        self.assertEqual(rules.denied_kinds("no tomo nada a las 3"), {"feeding"})

    def test_language_an_english_note_is_english(self):
        self.assertEqual(rules.message_lang("took 75ml of formula"), "en")
        for text in ("le di 100 y eructo", "mamadera 90 con formula", "teta izq y der"):
            self.assertEqual(rules.message_lang(text), "es", text)


class HeldOut3(Base):
    def test_step_5_span_start_and_now_give_the_length(self):
        brain = ScriptedBrain([[log("feeding", {"method": "right breast"}, ts="2026-10-28T02:15:00-03:00")], "Anoté."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "02:35", "pecho derecho, arranque 2:15 y largo recien")
        self.assertEqual(feeds(f), [("02:15", "right breast", None, 20, "breast milk")])

    def test_step_7_clock_wake_up_at_the_time_said(self):
        brain = ScriptedBrain([[log("sleep", {"action": "start"}, ts="2026-10-28T02:45:00-03:00")], "Anoté."],
                              [[log("sleep", {"action": "end"})], "Anoté."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "02:50", "por fin, la deje dormida en la cuna a las 2:45")
        self.send(app, clock, "05:05", "se desperto 4 y 55 llorando")
        sleep = f.log.entries("sleep")
        self.assertEqual(sleep[0]["ts"][11:16], "04:55")
        self.assertEqual(sleep[0]["details"]["start"][11:16], "02:45")

    def test_step_45_clock_at_noon(self):
        brain = ScriptedBrain([[log("diaper", {"wet": True})], "Logged."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "12:15", "wet diaper at noon")
        self.assertEqual(diapers(f), [("12:00", True, False)])

    def test_step_28_follow_up_adds_pee_without_the_brain(self):
        brain = ScriptedBrain([[log("diaper", {"wet": False, "solid": True})], "Anoté."],
                              [[call("read_baby_log", kind="diaper", limit=5)], "No pude."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "08:00", "caca verdosa sin pis")
        reply = self.send(app, clock, "08:02", "uh no, tambien tenia pis")
        self.assertEqual(diapers(f), [("08:00", True, True)])
        self.assertNotIn("No pude", reply)

    def test_step_40_follow_up_sets_the_amount_and_never_claims_it_unchanged(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 110, "method": "bottle", "type": "formula"})], "Anoté."],
                              ["Entendido, lo dejamos en 100 ml."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "05:50", "le prepare una de 110 de formula y se la tomo toda")
        reply = self.send(app, clock, "05:52", "no wait, dejo un poco, ponele 100")
        self.assertEqual(feeds(f), [("05:50", "bottle", 100.0, 0, "formula")])
        self.assertIn("110 ml → 100 ml", reply)

    def test_heldout2_step_2_follow_up_takes_what_was_left_and_logs_no_second_bottle(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 120, "method": "bottle", "type": "formula"})], "Anoté."],
                              [[log("feeding", {"method": "bottle"}),
                                call("edit_baby_event", last=True, kind="feeding", details={"amount_ml": 105})], "Anoté."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "00:30", "fueron 4 oz de formula")
        self.send(app, clock, "00:33", "dejo como media onza igual")
        self.assertEqual(feeds(f), [("00:30", "bottle", 105.0, 0, "formula")])

    def test_claim_a_value_the_log_never_took_is_not_confirmed(self):
        brain = ScriptedBrain(["Listo, quedó en 100 ml."])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "05:52", "dale, ponele 100")
        self.assertEqual(f.log.entries("feeding"), [])
        self.assertNotIn("100 ml", reply)

    def test_step_42_denied_a_dry_diaper_is_never_logged(self):
        brain = ScriptedBrain([[log("diaper", {"wet": False, "solid": False})], "Anoté el pañal."])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "08:30", "mire el pañal y esta seco, no la cambie")
        self.assertEqual(f.log.entries("diaper"), [])
        self.assertNotIn("Anoté", reply)

    def test_heldout2_step_8_same_start_twice_is_not_a_new_log(self):
        start = log("sleep", {"action": "start"}, ts="2026-10-28T03:15:00-03:00")
        brain = ScriptedBrain([[start], "Anoté."], [[start], "Anoté."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "03:30", "se durmio en el moises a las 3 y cuarto")
        reply = self.send(app, clock, "03:31", "se durmio en el moises a las 3 y cuarto")
        self.assertNotIn("Anoté", reply)
        self.assertIn("03:15", reply)
        self.assertEqual(str(f.log.open_sleep())[11:16], "03:15")

    def test_step_18_language_an_english_note_gets_an_english_reply(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 75, "method": "bottle", "type": "formula"})], "Logged."])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "02:20", "took 75ml of formula")
        self.assertTrue(reply.startswith("Logged"), reply)

    def test_empty_an_empty_answer_is_asked_again(self):
        brain = ScriptedBrain([""], [[log("note", {"text": "tiene la nariz tapada y le cuesta tomar"})], "Anoté la nota."])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "22:00", "tiene la nariz tapada y le cuesta tomar")
        self.assertEqual(len(f.log.entries("note")), 1)
        self.assertNotEqual(reply.strip(), "OK.")

    def test_budget_checks_never_use_up_the_tool_rounds(self):
        # The language check is a new user turn, so the brain's Spanish answer is its own plan.
        brain = ScriptedBrain([[call("read_baby_log", kind="feeding")], "She had no bottles today."], ["Hoy no tomó mamaderas."])
        app, f, clock = self.family(brain)
        f.agent.max_steps = 2
        reply = self.send(app, clock, "09:00", "cuantas mamaderas lleva hoy?")
        self.assertEqual(reply, "Hoy no tomó mamaderas.")


if __name__ == "__main__":
    unittest.main()
