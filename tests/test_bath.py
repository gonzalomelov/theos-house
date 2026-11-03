"""The bath on SAM 3.1 alone: its config, and that nothing it says implies leaving the baby. No model loads."""
import unittest
from pathlib import Path

from parenting_agent.camera_skill import check, implies_left_alone, spoken_texts
from parenting_agent.config import ConfigError, load

ROOT = Path(__file__).resolve().parent.parent
BATH = str(ROOT / "skills" / "bath.json")


class BathConfig(unittest.TestCase):
    def test_bath_confirms_with_sam3_on_this_machine(self):
        cfg = load(BATH)
        self.assertEqual(cfg["confirm"]["provider"], "sam3_local")
        self.assertLessEqual(cfg["alarm"]["voice_hold_s"], 2.5)

    def test_a_missing_agent_text_fails_at_start(self):
        cfg = load(BATH)
        del cfg["agent"]["finish_tool"]
        with self.assertRaises(ConfigError):
            check(cfg)


class NeverLeftAlone(unittest.TestCase):
    def test_every_bath_text_passes(self):
        cfg = load(BATH)
        texts = spoken_texts(cfg)
        self.assertGreaterEqual(len(texts), 8)
        for text in texts:
            self.assertFalse(implies_left_alone(text), text)

    def test_texts_that_imply_leaving_the_baby_fail(self):
        for text in ("You can step away, she is fine in the water.",
                     "Go answer the door, I'll keep an eye on her.",
                     "I will watch the baby while you grab the towel.",
                     "Leave her for a second and get the towel.",
                     "Be right back is fine, the water is shallow.",
                     "She can stay in the bath alone for a moment.",
                     "Let me watch her while you open the door."):
            self.assertTrue(implies_left_alone(text), text)

    def test_texts_that_keep_hands_on_pass(self):
        for text in ("Never leave the baby alone in the water.",
                     "Keep a hand on the baby, I will tell the courier one moment.",
                     "Both hands left the baby. Hand.",
                     "It is listening for both hands to leave the baby.",
                     "Do not step away, I can ask your partner to come.",
                     "Nothing left on in the kitchen.",
                     "I can hold notifications so nothing interrupts the bath."):
            self.assertFalse(implies_left_alone(text), text)

    def test_a_skill_file_that_implies_leaving_fails_at_start(self):
        cfg = load(BATH)
        cfg["reminders"]["on_armed"] = "Bath time. You can step out for the towel, I will watch her."
        with self.assertRaises(ConfigError):
            check(cfg)


if __name__ == "__main__":
    unittest.main()
