"""The families log is never wrong, whatever the brain says (issue #77, round 2 real-new-parent judge).

In 1 of 3 judge nights Muse logged a new 70 ml bottle for "nono eran 70" and said "corregido", and "se mando doble
perdon" deleted the only breast feed. These tests script the brain the way it failed, so they run with no network.
"""
import datetime
import os
import subprocess
import sys
import unittest
from pathlib import Path

from parenting_agent.agent import rules
from parenting_agent.agent.loop import EDIT_CHECK, TEXTS, logged_text
from parenting_agent.agent.memory import LocalBabyLog, Memory
from parenting_agent.families import service as service_mod
from parenting_agent.families.texts import ES

from test_log_edit import Base, delete, edit
from test_no_false_logged import Recording
from test_one_message_one_entry import ScriptedBrain, log

ROOT = Path(__file__).resolve().parent.parent


class Words(unittest.TestCase):
    def test_tired_corrections_are_corrections(self):
        for text in ("nono eran 70, dejo 20", "ahh no, 110", "no no eran 80", "eran 70 nomas", "se mando doble",
                     "me equivoque fueron 80", "perdon era de 60", "en realidad fue 90", "no fue a las 3, fue 3 y media"):
            self.assertTrue(rules.is_edit_request(text), text)
        for text in ("mamadera 120", "teta der 12min", "fueron 2 mamaderas", "le di 90 de formula"):
            self.assertFalse(rules.is_edit_request(text), text)

    def test_double_answers(self):
        for text in ("se mando doble perdon", "la mande 2 veces", "una", "una sola", "sin querer", "se mandó dos veces"):
            self.assertEqual(rules.double_answer(text), "once", text)
        for text in ("dos", "fueron dos tomas", "tomó otra", "le di una más", "si, otra mamadera"):
            self.assertEqual(rules.double_answer(text), "two", text)
        for text in ("eh?", "mmm", "q"):
            self.assertIsNone(rules.double_answer(text), text)

    def test_change_claims_and_their_negations(self):
        for text in ("Perfecto, corregido a 70 ml.", "Corregí la toma.", "Borré la toma de pecho de las 05:20.",
                     "Fixed it.", "Deleted the last one.", "Listo, lo cambié."):
            self.assertTrue(rules.claims_change(text), text)
        for text in ("No cambié nada.", "No borré nada: está una sola vez.", "Nothing changed.", "Anoté la mamadera.",
                     "No hay nada que corregir.", "I didn't delete anything."):
            self.assertFalse(rules.claims_change(text), text)

    def test_sides(self):
        self.assertEqual(rules.side_said("teta der 12min"), "right breast")
        self.assertEqual(rules.side_said("pecho izq 10"), "left breast")
        self.assertEqual(rules.side_said("teta izq y der 20 min"), "both breasts")
        self.assertEqual(rules.side_said("teta 15 min"), None)
        details, _ = rules.said_only("teta der 12min", "feeding", {"method": "breast", "duration_min": 12})
        self.assertEqual(details["method"], "right breast")
        details, _ = rules.said_only("teta 12min", "feeding", {"method": "left breast", "duration_min": 12})
        self.assertEqual(details["method"], "breast")

    def test_an_earlier_bottle_never_rides_along(self):
        details, _ = rules.said_only("teta izq 15 min", "feeding", {"amount_ml": 120, "method": "bottle"})
        self.assertEqual(details, {"method": "left breast"})
        details, _ = rules.said_only("mamadera 90", "feeding", {"amount_ml": 120, "method": "bottle"})
        self.assertEqual(details, {"method": "bottle"})

    def test_ounces_are_30_ml(self):
        self.assertEqual(rules.ounces_ml("tomo 3 onzas"), 90)
        self.assertEqual(rules.ounces_ml("me equivoque, eran 2 onzas"), 60)
        details, _ = rules.said_only("tomo 3 onzas", "feeding", {"amount_ml": 89, "method": "bottle"})
        self.assertEqual(details["amount_ml"], 90)

    def test_minutes_after_y(self):
        now = datetime.datetime(2026, 10, 30, 3, 45, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        self.assertEqual(rules.named_time("se quedo dormida a las 3 y 20", now)[11:16], "03:20")
        self.assertEqual(rules.named_time("a las 1 y veinte", now)[11:16], "01:20")

    def test_questions_without_accents_or_marks(self):
        for text in ("a q hr le toca", "cuanto durmio", "y cuantos pañales", "hace cuanto q no hace caca", "q tomo hoy"):
            self.assertTrue(rules.is_question(text), text)


class Corrections(Base):
    def test_a_new_entry_claimed_as_a_correction_is_taken_back_and_the_entry_edited(self):
        brain = Recording([[log("feeding", {"amount_ml": 90, "method": "bottle", "type": "formula"})], "Anotado."],
                          [[log("feeding", {"amount_ml": 70, "method": "bottle"})], "Perfecto, corregido a 70 ml."],
                          [[edit({"amount_ml": 70}, kind="feeding", last=True)], "Listo."])
        # The judge's words do match EDIT now, so the claim guard is tested with a message EDIT does not know.
        app, f, clock = self.family(brain)
        self.send(app, clock, "02:10", "le di 90 de formula")
        reply = self.send(app, clock, "02:12", "70 dejo 20")
        self.assertEqual(self.ml(f), [70.0])
        self.assertEqual(reply, "Corregí la mamadera de las 02:10: 90 ml → 70 ml.")
        self.assertIn(EDIT_CHECK.format(request="70 dejo 20"), brain.users)

    def test_a_claim_with_no_edit_is_replaced_with_the_honest_answer(self):
        brain = Recording([[log("feeding", {"amount_ml": 90, "method": "bottle"})], "Anotado."],
                          ["Listo, corregido."], ["Listo, corregido."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "02:10", "mamadera 90")
        reply = self.send(app, clock, "02:12", "70 dejo 20")
        self.assertEqual(reply, TEXTS["es"]["NOT_CHANGED"])
        self.assertEqual(self.ml(f), [90.0])

    def test_nono_eran_70_edits_and_never_adds(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 90, "method": "bottle"})], "Anotado."],
                              [[log("feeding", {"amount_ml": 70, "method": "bottle"})],
                               [edit({"amount_ml": 70}, kind="feeding", last=True)], "Perfecto, corregido a 70 ml."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "02:10", "le di 90")
        reply = self.send(app, clock, "02:12", "nono eran 70, dejo 20")
        self.assertEqual(self.ml(f), [70.0])
        self.assertEqual(reply, "Corregí la mamadera de las 02:10: 90 ml → 70 ml.")


class DoubleSend(Base):
    def breast(self):
        return ScriptedBrain([[log("feeding", {"method": "breast", "duration_min": 12})], "Anotado, teta derecha 12 min."],
                             [[log("feeding", {"method": "breast", "duration_min": 12})], "Anotado."],
                             [[delete(last=True)], "Borré la toma de pecho de las 05:20."],
                             [[delete(last=True)], "Borré la toma de pecho de las 05:20."])

    def test_the_breast_feed_question_names_breast_feeds_and_the_answer_keeps_it(self):
        app, f, clock = self.family(self.breast())
        self.assertEqual(self.send(app, clock, "05:20", "teta der 12min"), "Anoté la toma de pecho derecho de 12 min de las 05:20.")
        asked = self.send(app, clock, "05:21", "teta der 12min")
        self.assertIn("dos tomas de pecho", asked)
        self.assertNotIn("mamadera", asked)
        self.assertEqual(self.send(app, clock, "05:23", "se mando doble perdon"),
                         "Dale, queda una sola: la toma de pecho de las 05:20.")
        entries = f.log.entries("feeding")
        self.assertEqual([(e["ts"][11:16], e["details"]["method"]) for e in entries], [("05:20", "right breast")])

    def test_a_sent_twice_delete_with_one_entry_is_held(self):
        app, f, clock = self.family(self.breast())
        self.send(app, clock, "05:20", "teta der 12min")
        # Long after the question window, the brain deletes "the last" for a double send that was never logged twice.
        reply = self.send(app, clock, "07:00", "se mando doble perdon")
        self.assertEqual(len(f.log.entries("feeding")), 1)
        self.assertEqual(reply, "No borré nada: en el registro la toma de pecho de las 05:20 está una sola vez.")

    def test_a_real_duplicate_is_deleted(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 110, "method": "bottle"})], "Anotado."],
                              [[log("feeding", {"amount_ml": 110, "method": "bottle"})], "Anotado."],
                              [[delete(last=True)], "Listo."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "04:40", "mamadera 110")
        self.send(app, clock, "04:45", "mamadera 110")
        self.assertEqual(self.ml(f), [110.0, 110.0])
        self.assertEqual(self.send(app, clock, "04:50", "la mande 2 veces sin querer"), "Borré la mamadera de 110 ml de las 04:45.")
        self.assertEqual(self.ml(f), [110.0])

    def test_q_is_an_unclear_answer(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 100, "method": "bottle"})], "Anotado."],
                              [[log("feeding", {"amount_ml": 100, "method": "bottle"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "13:15", "le di 100")
        self.send(app, clock, "13:16", "le di 100")
        self.assertIn("Respondé una o dos", self.send(app, clock, "13:18", "q?"))
        self.assertEqual(self.send(app, clock, "13:19", "fue una sola, la mande 2 veces"),
                         "Dale, queda una sola: la mamadera de 100 ml de las 13:15.")
        self.assertEqual(self.ml(f), [100.0])

    def test_a_message_that_corrects_nothing_edits_nothing(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 100, "method": "bottle"})], "Anotado."],
                              [[log("feeding", {"amount_ml": 120, "method": "bottle"}), log("diaper", {"wet": True}),
                                log("diaper", {"wet": True, "solid": False}),
                                edit({"amount_ml": 100}, kind="feeding", last=True)], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "00:40", "mamadera 100")
        self.assertEqual(self.send(app, clock, "01:30", "pañal pis nomas"), "Anoté el pañal mojado de las 01:30.")
        self.assertEqual(self.ml(f), [100.0])
        self.assertEqual(len(f.log.entries("diaper")), 1)

    def test_an_explicit_delete_runs(self):
        brain = ScriptedBrain([[log("diaper", {"solid": True})], "Anotado."], [[delete(last=True)], "Listo."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "03:15", "pañal con caca")
        self.assertEqual(self.send(app, clock, "03:16", "borra ese q me equivoque"), "Borré el pañal de las 03:15.")
        self.assertEqual(f.log.entries("diaper"), [])


class Confirmations(Base):
    def test_the_reply_is_the_stored_entry(self):
        brain = ScriptedBrain([[log("feeding", {"method": "breast", "duration_min": 20})], "Anotado, pecho de ambos lados."],
                              [[log("feeding", {"amount_ml": 90, "method": "bottle", "type": "formula", "duration_min": 15})],
                               "Anotado 90 de fórmula en 15 min."])
        app, f, clock = self.family(brain)
        self.assertEqual(self.send(app, clock, "06:00", "teta izq y der 20 min"),
                         "Anoté la toma de pecho de los dos lados de 20 min de las 06:00.")
        self.assertEqual(self.send(app, clock, "09:00", "le di 90 de mamadera"), "Anoté la mamadera de 90 ml de las 09:00.")
        d = f.log.entries("feeding")[-1]["details"]
        self.assertEqual((d["type"], d["duration_min"]), ("unknown", 0))

    def test_a_note_the_brain_answered_with_safety_keeps_the_safety_line(self):
        brain = ScriptedBrain([[log("note", {"text": "tiene la nariz tapada y hace ruidito"})],
                               "Lo anoto. Llamá a tu pediatra o al 911 si te preocupa."])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "04:30", "tiene la nariz tapada y hace ruidito")
        self.assertEqual(reply, 'Anoté una nota a las 04:30: "tiene la nariz tapada y hace ruidito". '
                                + rules.NO_ADVICE["es"])

    def test_logged_text_in_english(self):
        entry = {"ts": "2026-10-29T05:20:00-03:00", "kind": "feeding", "details": {"method": "right breast", "duration_min": 12}}
        self.assertEqual(logged_text([entry], "en"), "Logged the 05:20 right breast feed of 12 min.")


class NextFeed(Base):
    def feeds(self, f, clock, *times):
        for hhmm in times:
            h, m = (int(x) for x in hhmm.split(":"))
            clock.now = clock.now.replace(hour=h, minute=m)
            f.log.add("feeding", {"amount_ml": 90, "method": "bottle"})

    def test_a_question_after_next_feed_is_never_send_it_again(self):
        brain = ScriptedBrain([[{"name": "next_feed", "arguments": {}}], "Según la última toma anotada, no sé."])
        app, f, clock = self.family(brain)
        self.feeds(f, clock, "02:00", "05:00", "08:00", "11:00")
        reply = self.send(app, clock, "11:30", "a q hr le toca")
        self.assertNotIn("No pude anotarlo", reply)
        self.assertEqual(reply, app.next_feed(f)["text"])
        self.assertIn("14:00", reply)

    def test_the_interval_needs_four_feeds_a_day(self):
        app, f, clock = self.family(ScriptedBrain())
        self.feeds(f, clock, "06:00", "09:00")
        clock.now = clock.now.replace(hour=10, minute=0)
        text = app.next_feed(f)["text"]
        self.assertIn("12:00", text)
        self.assertNotIn("cada", text)
        self.feeds(f, clock, "12:00", "15:00")
        clock.now = clock.now.replace(hour=16, minute=0)
        self.assertIn("cada 3 h 00 min", app.next_feed(f)["text"])

    def test_a_sparse_log_names_the_last_feed_and_how_long_ago(self):
        app, f, clock = self.family(ScriptedBrain())
        self.feeds(f, clock, "02:00", "14:40")
        clock.now = clock.now.replace(hour=15, minute=0)
        nxt = app.next_feed(f)
        self.assertEqual(nxt["kind"], "few")
        self.assertEqual(nxt["text"], "La última toma anotada de Mia fue a las 14:40, hace 20 min. Todavía hay pocas tomas "
                                      "anotadas en el último día para saber cada cuánto come Mia.")

    def test_two_entries_minutes_apart_are_one_feed_for_the_rhythm(self):
        app, f, clock = self.family(ScriptedBrain())
        self.feeds(f, clock, "02:10", "02:12", "05:10", "08:10", "11:10")
        clock.now = clock.now.replace(hour=11, minute=20)
        self.assertIn("cerca de las 14:10", app.next_feed(f)["text"])


class Uruguay(Base):
    def test_spanish_replies_use_uruguayan_words(self):
        self.assertEqual(service_mod.es_uy("Llevá el DNI y la obra social o prepaga, y un biberón."),
                         "Llevá la cédula y la mutualista, y una mamadera.")
        self.assertEqual(service_mod.es_uy("Los biberones y el DNI de los dos"), "Las mamaderas y la cédula de los dos")


class Clock(unittest.TestCase):
    def test_the_summary_counts_today_on_the_log_clock(self):
        class Sim(LocalBabyLog):
            def now(self):
                return datetime.datetime(2026, 10, 31, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        log_ = Sim(Memory(":memory:"))
        with log_.memory.lock:
            log_.memory.db.execute("insert into baby_log (ts, kind, details) values (?, 'feeding', ?)",
                                   ("2026-10-31T07:00:00-03:00", '{"amount_ml": 60}'))
            log_.memory.db.execute("insert into baby_log (ts, kind, details) values (?, 'feeding', ?)",
                                   ("2026-10-30T07:00:00-03:00", '{"amount_ml": 90}'))
        summary = log_.summary()
        self.assertEqual((summary["feedings"]["count"], summary["feedings"]["total_ml"]), (1, 60))
        self.assertTrue(summary["now"].startswith("2026-10-31T10:00"))


class PrepShow(unittest.TestCase):
    def test_show_needs_no_brain_key(self):
        env = {k: v for k, v in os.environ.items() if k not in ("BASETEN_API_KEY", "ANTHROPIC_API_KEY")}
        config = ROOT / "config" / "agent.vostro.json"
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as data:
            cfg = {**json.loads(config.read_text()), "data_dir": data, "env_file": "/nonexistent"}
            path = Path(data) / "agent.json"
            path.write_text(json.dumps(cfg))
            done = subprocess.run([sys.executable, "-m", "parenting_agent.prep", "show", "--config", str(path)], cwd=ROOT,
                                  env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout, r"days to the due date|días para la fecha")


if __name__ == "__main__":
    unittest.main()
