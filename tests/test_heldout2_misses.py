"""The second blind set (Oct 29, 45 tired-parent messages, Muse, scored on main at 24bd72b): six of its eight misses had
one cause. The guards that keep the brain honest decided what the parent said from fixed word and number lists, so a
detail said in another form ("3 onzitas", "110 y sobraron 20", "caquita", "desde las 2 y 10", "de materna", "fue con
formula") was thrown away or never applied. Each test replays a step with the brain doing what Muse did."""
import unittest

from parenting_agent.agent import rules

from test_heldout_misses import feeds
from test_log_edit import Base
from test_one_message_one_entry import ScriptedBrain, log


class Said(unittest.TestCase):
    def test_an_amount_that_follows_from_the_message_numbers_is_said(self):
        self.assertTrue(rules.amount_said(90, "prepare 110 y sobraron 20"))
        self.assertTrue(rules.amount_said(90, "3 onzitas en la mamadera"))
        self.assertTrue(rules.amount_said(90, "le di 90"))
        self.assertEqual(rules.ounces_ml("3 onzitas en la mamadera"), 90)

    def test_an_amount_from_an_earlier_message_is_still_not_said(self):
        self.assertFalse(rules.amount_said(120, "teta izq 15 min"))
        self.assertFalse(rules.amount_said(120, "pañal con pis"))
        self.assertFalse(rules.amount_said(120, "le di 90"))

    def test_word_forms_count(self):
        self.assertEqual(rules.said_only("pis y caquita clarita", "diaper", {"wet": True, "solid": True})[0],
                         {"wet": True, "solid": True})
        self.assertEqual(rules.said_only("esta dormida desde las 2 y 10", "sleep", {"action": "start"},
                                         "2026-10-30T02:10:00-03:00")[1], "2026-10-30T02:10:00-03:00")
        self.assertEqual(rules.said_only("caca nomas", "diaper", {"wet": True, "solid": True})[0], {"solid": True})

    def test_a_milk_type_in_any_frame_is_an_addendum_and_a_new_feed_is_not(self):
        for text, milk in (("de materna, la q sacaste ayer", "breast milk"), ("la de recien fue con formula", "formula"),
                           ("ah y era formula", "formula")):
            self.assertEqual(rules.addendum(text), ("feeding", {"type": milk}, 20), text)
        for text in ("le di formula", "otra mamadera de formula", "teta izq, materna", "pañal y formula"):
            self.assertIsNone(rules.addendum(text), text)


class HeldOut2(Base):
    def test_steps_10_and_11_onzitas_then_de_materna(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 90, "method": "bottle"})], "Anotado."],
                              ["Anotado, de materna."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "05:10", "3 onzitas en la mamadera")
        self.assertEqual(feeds(f), [("05:10", "bottle", 90.0, 0, "unknown")])
        reply = self.send(app, clock, "05:11", "de materna, la q sacaste ayer")
        self.assertEqual(feeds(f), [("05:10", "bottle", 90.0, 0, "breast milk")])
        self.assertIn("materna", reply)

    def test_steps_38_and_39_prepared_minus_left_then_fue_con_formula(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 90, "method": "bottle"})], "Anotado."],
                              [[log("note", {"text": "la de recién fue con fórmula"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "05:35", "prepare 110 y sobraron 20")
        self.send(app, clock, "05:37", "la de recien fue con formula")
        self.assertEqual(feeds(f), [("05:35", "bottle", 90.0, 0, "formula")])
        self.assertEqual(f.log.entries("note"), [])

    def test_step_13_caquita_is_a_dirty_diaper(self):
        brain = ScriptedBrain([[log("diaper", {"wet": True, "solid": True})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "07:45", "pis y caquita clarita")
        d = f.log.entries("diaper")[0]["details"]
        self.assertTrue(d.get("wet"))
        self.assertTrue(d.get("solid"))

    def test_step_21_desde_las_2_y_10_is_the_sleep_start(self):
        brain = ScriptedBrain([[log("sleep", {"action": "start"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "02:30", "esta dormida desde las 2 y 10")
        self.assertEqual(str(f.log.open_sleep())[11:16], "02:10")


if __name__ == "__main__":
    unittest.main()
