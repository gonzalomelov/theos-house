"""A red flag said out loud must not hinge on one misheard word (#167).

On Oct 30 the glasses speech run heard "está azul y no respira bien" as "está azulino respira bien" and the 911 line did
not fire. rules.spoken_emergency reads a heard transcript again with no accents, the glued "y no" split off a colour, and
key words one letter away fixed. Everyday talk with the same words must never bring the 911 line.
"""
import hashlib
import json
import pathlib
import unittest

from parenting_agent.agent import rules

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPOKEN = ROOT / "results" / "spoken-red-flags"


class SpokenEmergency(unittest.TestCase):
    def test_the_mishearing_of_oct_30_fires(self):
        self.assertFalse(rules.is_emergency("está azulino respira bien"))
        self.assertEqual(rules.spoken_emergency("está azulino respira bien"), "esta azul y no respira bien")

    def test_a_key_word_one_letter_off_fires(self):
        for heard in ("Está convulcionando", "no reaciona", "he is not breating", "she is unresponsibe",
                      "No respíra", "se esta ahohando"):
            with self.subTest(heard=heard):
                self.assertTrue(rules.spoken_emergency(heard))

    def test_everyday_talk_with_the_same_words_stays_off(self):
        for heard in ("Respira tranquilo, ya se durmió", "Respirá hondo, mi amor", "no lo despiertes, recién se durmió",
                      "Le puse el body azulino", "Ese azulejo está roto", "respiro hondo y sigo", "Breathe, honey",
                      "He has blue eyes, just like his dad", "Put him in the blue onesie", "the sky is so blue today",
                      "Mirá qué lindo ese globo morado", "she's shaking her rattle like crazy",
                      "casi no se lo escucha respirar", "I can barely hear her breathe"):
            with self.subTest(heard=heard):
                self.assertIsNone(rules.spoken_emergency(heard))

    def test_a_blue_baby_is_a_red_flag_typed_or_spoken(self):
        for text in ("el bebé está azul", "se le puso la cara azul", "the baby is blue", "his face went blue",
                     "Theo, los labios están azules"):
            with self.subTest(text=text):
                self.assertTrue(rules.is_emergency(text))
        for text in ("the baby is blue-eyed", "she's in her blue onesie", "el bebé tiene el body azul",
                     "la pared está azul"):
            with self.subTest(text=text):
                self.assertFalse(rules.is_emergency(text))


class HeldOut(unittest.TestCase):
    def test_the_everyday_held_out_set_never_gets_the_911_line(self):
        held = json.loads((ROOT / "results" / "safety-gate-r4" / "heldout.json").read_text())
        for text in held["everyday"]:
            with self.subTest(text=text):
                self.assertIsNone(rules.spoken_emergency(text))

    def test_the_spoken_set_is_the_one_hashed_before_tuning(self):
        expected = (SPOKEN / "set.sha256").read_text().split()[0]
        self.assertEqual(hashlib.sha256((SPOKEN / "set.json").read_bytes()).hexdigest(), expected)
        spoken = json.loads((SPOKEN / "set.json").read_text())
        self.assertGreaterEqual(len(spoken["red_flags"]), 30)
        self.assertGreaterEqual(len(spoken["everyday"]), 30)
        for _, text in spoken["red_flags"]:
            self.assertTrue(rules.spoken_emergency(text), text)
        for _, text in spoken["everyday"]:
            self.assertIsNone(rules.spoken_emergency(text), text)


if __name__ == "__main__":
    unittest.main()
