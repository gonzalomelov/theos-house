"""Blind round b7: the safety word lists that guard generated text catch Spanish, not only English."""
import datetime
import unittest

from parenting_agent import cry_reason, sitter
from parenting_agent.rhythm import patterns

SPANISH_MEDICAL = ["le duele la panza", "tiene dolor", "debe ser un cólico", "colico", "tiene fiebre", "son gases",
                   "está enfermo", "llamá al médico", "medico", "habló la pediatra", "tuvo un vómito", "vomitó",
                   "tiene reflujo", "le están saliendo los dientes", "una infección", "es alergia", "un síntoma",
                   "tiene diarrea", "se lastimó"]
EVERYDAY = ["le di la teta", "le di 90 ml", "cambié el pañal, tenía caca", "se quedó dormido a las 3",
            "un provechito después de la toma", "capaz que solo quiere brazos", "En el registro no hay una razón probable.",
            "está despierto hace 1 h 5 min"]


class SpanishMedicalWords(unittest.TestCase):
    def test_spanish_medical_words_are_caught(self):
        for text in SPANISH_MEDICAL:
            self.assertFalse(cry_reason.no_medical(text), text)

    def test_everyday_spanish_lines_pass(self):
        for text in EVERYDAY:
            self.assertTrue(cry_reason.no_medical(text), text)
            self.assertTrue(patterns.no_advice(text), text)

    def test_spanish_advice_is_caught(self):
        for text in ["deberías darle agua", "te recomiendo esperar", "consultá con el médico", "no te preocupes",
                     "tenés que llevarlo", "la dosis es de 2 ml"]:
            self.assertFalse(patterns.no_advice(text), text)

    def test_sitter_spanish_dose_words(self):
        for text in ["dale 5 gotas", "el jarabe", "ibuprofeno", "una crema para la cola"]:
            self.assertIsNotNone(sitter.DOSAGE_RE.search(text), text)
        self.assertIsNone(sitter.DOSAGE_RE.search("le di la teta"))

    def test_explain_spanish_text_passes_its_own_guard(self):
        tz = datetime.timezone(datetime.timedelta(hours=-3))
        now = datetime.datetime(2026, 11, 2, 4, 0, tzinfo=tz)
        out = cry_reason.explain([], now, tz)
        self.assertTrue(cry_reason.no_medical(out["text_es"]))
        self.assertTrue(patterns.no_advice(out["text_es"]))


if __name__ == "__main__":
    unittest.main()


class NewbornViewHidesPrep(unittest.TestCase):
    """Blind round b7: the newborn tab got the author's prep items and a countdown to the birth of a baby already born."""

    def test_newborn_state_and_replies_carry_no_prep(self):
        import json
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from test_demo import CountingBrain, settings
        from parenting_agent.demo.app import DemoApp
        app = DemoApp(settings(), brain=CountingBrain())
        self.addCleanup(app.close)
        state = app.state("v", False)
        self.assertNotIn("prep", state)
        text = json.dumps(state)
        for word in ("due date", "Litetrax", "i-Snug", "hospital bag"):
            self.assertNotIn(word, text)
        status, body = app.message("v", True, "wet diaper")
        self.assertEqual((status, body["mode"]), (200, "baby"))
        self.assertNotIn("prep", body)
        self.assertIn("countdown", app.state("v", False, view="prep")["prep"])
        status, body = app.message("v", True, "hospital bag")
        self.assertEqual(body["mode"], "prep")
        self.assertIn("prep", body)

    def test_the_page_asks_for_the_prep_cards_only_on_the_prep_tab(self):
        from pathlib import Path
        page = Path(__file__).resolve().parents[1].joinpath("parenting_agent/demo/page.html").read_text()
        self.assertIn('api("/api/state?view=prep&lang="', page)
