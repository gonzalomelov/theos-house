"""The misses of run 1 of the held-out set (Oct 29, 45 tired-parent messages, Muse): each one replayed with the brain
doing what Muse did, and the log checked after."""
import unittest

from parenting_agent.agent import rules
from parenting_agent.agent.loop import TEXTS

from test_log_edit import Base
from test_one_message_one_entry import ScriptedBrain, log


def feeds(f):
    return [(e["ts"][11:16], e["details"].get("method"), e["details"].get("amount_ml"), e["details"].get("duration_min"),
             e["details"].get("type")) for e in f.log.entries("feeding")]


class Words(unittest.TestCase):
    def test_half_an_ounce_counts(self):
        self.assertEqual(rules.ounces_ml("le di 3 onzas y media"), 105)
        self.assertEqual(rules.ounces_ml("3 y media onzas"), 105)
        self.assertEqual(rules.ounces_ml("no, eran 3 onzas justas"), 90)

    def test_half_of_what_was_made(self):
        self.assertEqual(rules.half_ml("le prepare 120 y tomo la mitad"), 60)
        self.assertIsNone(rules.half_ml("tomo 120, la mitad de la noche dormida"))

    def test_addenda(self):
        self.assertEqual(rules.addendum("como 14 min"), ("feeding", {"duration_min": 14}, 60))
        self.assertEqual(rules.addendum("y pis tmb"), ("diaper", {"wet": True}, 15))
        self.assertEqual(rules.addendum("ah y era formula"), ("feeding", {"type": "formula"}, 20))
        for text in ("lado izquierdo 16 min", "siesta de 30 min", "no, eran 80 de formula", "pañal mojado y con caca",
                     "durmio 20 min", "cuantos min tomo?"):
            self.assertIsNone(rules.addendum(text), text)

    def test_chat_is_not_a_note(self):
        self.assertTrue(rules.chat_only("hoy esta re sonriente, no para de mirar el movil"))
        self.assertFalse(rules.chat_only("sonrió por primera vez"))
        self.assertFalse(rules.chat_only("tiene la nariz tapada y hace ruidito"))


class HeldOut(Base):
    def test_step_2_era_formula_changes_the_bottle(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 110, "method": "bottle"})], "Anotado."], ["Entendido, era fórmula."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "00:35", "mamadera de 110, se la tomo toda")
        reply = self.send(app, clock, "00:37", "ah y era formula")
        self.assertEqual(feeds(f), [("00:35", "bottle", 110.0, 0, "formula")])
        self.assertIn("fórmula", reply)

    def test_step_5_como_14_min_is_the_left_breast_feed(self):
        brain = ScriptedBrain([[log("feeding", {"method": "left breast"})], "Anotado."],
                              [[log("feeding", {"method": "breast", "duration_min": 14})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "02:50", "le di la teta izq")
        reply = self.send(app, clock, "02:52", "como 14 min")
        self.assertEqual(feeds(f), [("02:50", "left breast", None, 14, "breast milk")])
        self.assertIn("14 min", reply)

    def test_step_25_15_min_is_the_right_breast_feed_never_a_bottle(self):
        brain = ScriptedBrain([[log("feeding", {"method": "right breast"})], "Anotado."],
                              [[log("feeding", {"duration_min": 15})], "Anoté la mamadera de 15 min."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "05:20", "arranco con la derecha")
        reply = self.send(app, clock, "05:35", "15 min, ya la largo")
        self.assertEqual(feeds(f), [("05:20", "right breast", None, 15, "breast milk")])
        self.assertNotIn("mamadera", reply)

    def test_step_18_y_pis_tmb_is_the_same_diaper(self):
        brain = ScriptedBrain([[log("diaper", {"solid": True})], "Anotado."], [[log("diaper", {"wet": True})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "00:50", "pañal re cargado de caca")
        self.send(app, clock, "00:51", "y pis tmb")
        diapers = f.log.entries("diaper")
        self.assertEqual(len(diapers), 1)
        self.assertTrue(diapers[0]["details"].get("wet") and diapers[0]["details"].get("solid"))

    def test_step_9_half_of_120_is_60(self):
        brain = ScriptedBrain([[log("feeding", {"method": "bottle"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "05:50", "le prepare 120 y tomo la mitad")
        self.assertEqual(feeds(f)[0][2], 60.0)

    def test_step_27_three_and_a_half_ounces_is_105(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 90, "method": "bottle"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "08:30", "le di 3 onzas y media")
        self.assertEqual(feeds(f)[0][2], 105.0)

    def test_step_7_the_same_sleep_sent_twice_keeps_its_start(self):
        brain = ScriptedBrain([[log("sleep", {"action": "start"})], "Anotado."],
                              [[log("sleep", {"action": "start"})], "Anoté que se durmió a las 03:21."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "03:20", "se quedo frita en upa")
        reply = self.send(app, clock, "03:21", "se quedo frita en upa")
        self.assertEqual(str(f.log.open_sleep())[11:16], "03:20")
        self.assertIn("03:20", reply)
        self.assertFalse(rules.claims_logged(reply))

    def test_step_30_a_smile_logs_no_sleep_and_no_note(self):
        brain = ScriptedBrain([[log("sleep", {"action": "start"}),
                                log("note", {"text": "hoy esta re sonriente, no para de mirar el movil"})],
                               "Qué lindo."])
        app, f, clock = self.family(brain)
        reply = self.send(app, clock, "12:40", "hoy esta re sonriente, no para de mirar el movil")
        self.assertIsNone(f.log.open_sleep())
        self.assertEqual(f.log.entries("note"), [])
        self.assertFalse(rules.claims_logged(reply))
        self.assertNotEqual(reply, TEXTS["es"]["NOT_IN_LOG"])


if __name__ == "__main__":
    unittest.main()
