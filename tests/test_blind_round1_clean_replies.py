"""Blind judging round 1 (Oct 31) and PR #163: what a parent reads, in one line and one language.

1. "¿Cuándo comió por última vez?" is answered from the log in one line: on the demo Muse said "Voy a revisar el
   registro de Theo para vos." and then asked something else. Since round b4 Muse answers it from the newest feed, and
   an answer that misses the feed's time is replaced by the fixed line, as here.
2. "el sueño más largo 0.0 h" never shows: a night slept in one stretch from 19:40 counts, no sleep means no line.
3. The Spanish demo never mixes Parent B, Persona B and English "why" lines, and the cry message is bilingual.
"""
import datetime
import tempfile
import unittest
from pathlib import Path

from parenting_agent import cry_reason, cry_sound
from parenting_agent.agent import brain as brain_mod
from parenting_agent.agent import rules
from parenting_agent.channels import morning
from parenting_agent.demo import tonight
from parenting_agent.demo.app import night_es
from parenting_agent.e2e.score import INTERNAL, english
from parenting_agent.rhythm import patterns
from parenting_agent.rhythm.log import FixtureLog
from tests.test_family_push import GONZA, Family, at

TZ = datetime.timezone(datetime.timedelta(hours=-3))
FIXTURE = Path(__file__).parent / "fixtures/simweek.json"
PEOPLE_ES = {"gonza": {"name": "Gonza", "rota": "Parent A", "chat_ids_env": "TELEGRAM_CHAT_ID", "lang": "es"},
             "ceci": {"name": "Ceci", "rota": "Parent B", "chat_ids_env": "TELEGRAM_CECI_CHAT_ID", "lang": "es"}}


class NoBrain:
    name, model, destination = "scripted", "none", "inference.baseten.co"

    def __init__(self):
        self.calls = 0

    def step(self, system, transcript, tools):
        self.calls += 1
        return brain_mod.Reply("Voy a revisar el registro de Theo para vos. ¿Querés que anote algo?")


class LastFeedInOneLine(unittest.TestCase):
    def test_the_questions_it_knows(self):
        for text in ("¿Cuándo comió por última vez?", "cuando comio x ultima vez?", "¿A qué hora tomó la última mamadera?",
                     "Mi mamá pregunta cuándo comió por última vez.", "When did he last eat?", "when was the last feed?",
                     "¿Cuál fue la última toma?"):
            self.assertTrue(rules.asks_last_feed(text), text)
        for text in ("Le di 80 ml de mamadera.", "Tomó 90 ml.", "¿Cuántos pañales van hoy?", "Se durmió.",
                     "¿Cuándo le toca bañarse?"):
            self.assertFalse(rules.asks_last_feed(text), text)

    def test_family_agent_replaces_an_answer_without_the_time_by_the_log_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = NoBrain()
            family = Family(tmp, at(30, 11, 0), brain=brain, extra={"people": PEOPLE_ES}, plugins=())
            try:
                from parenting_agent.agent.people import People
                family.agent.people = People(PEOPLE_ES)
                fed = family.agent.now() - datetime.timedelta(minutes=30)  # the local log never stores a future time
                family.agent.baby_log.add("feeding", {"method": "bottle", "amount_ml": 90, "type": "formula"},
                                          ts=fed.isoformat())
                for _ in range(3):
                    family.say(GONZA, "¿Cuándo comió por última vez?")
                answers = family.sent_to(GONZA)
                self.assertEqual(len(set(answers)), 1, "the same one line every time")
                self.assertTrue(answers[0].startswith(f"La última toma fue la mamadera de 90 ml de fórmula de las {fed:%H:%M}"),
                                answers[0])
                self.assertEqual(brain.calls, 3)
            finally:
                family.close()

    def test_an_empty_log_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 11, 0), brain=NoBrain(), extra={"people": PEOPLE_ES}, plugins=())
            try:
                family.say(GONZA, "¿Cuándo comió por última vez?")
                self.assertEqual(family.sent_to(GONZA), ["Todavía no hay ninguna toma en el registro."])
            finally:
                family.close()

    def test_families_bot_and_demo_answer_in_one_line(self):
        from tests.test_families import make, onboard, text
        brain = NoBrain()
        app = make(self, brain=brain)
        onboard(app, "111")
        from tests.test_families import family_of
        app.family(family_of(app, "111")).log.add("feeding", {"method": "bottle", "amount_ml": 120})
        calls = brain.calls
        answer = text(app.handle("111", "111", "when did she last eat?"))
        self.assertRegex(answer, r"^The last feed was the \d\d:\d\d bottle of 120 ml")
        self.assertEqual(brain.calls, calls + 1)
        from tests.test_redteam_r1 import demo
        app = demo(NoBrain())
        self.addCleanup(app.close)
        _, body = app.message("v", False, "¿cuándo comió por última vez?")
        self.assertTrue(body["reply"].startswith("La última toma fue"), body["reply"])
        self.assertNotIn("Voy a revisar", body["reply"])
        self.assertEqual(body["answered_by"], {"kind": "rule"})


class NoZeroLongestSleep(unittest.TestCase):
    def test_a_night_slept_from_the_evening_counts(self):
        entries = [{"kind": "sleep", "start": "2026-10-29T19:40:00-03:00", "end": "2026-10-30T02:30:00-03:00", "ref": "s1"},
                   {"kind": "feeding", "start": "2026-10-30T02:35:00-03:00", "ref": "f1"}]
        summary = patterns.night_summary(entries, datetime.datetime(2026, 10, 30, 7, 30, tzinfo=TZ), TZ, ["Parent A", "Parent B"])
        self.assertEqual(summary["longest_h"], 6.8)
        self.assertIn("longest sleep 6.8 h", summary["text"])

    def test_no_sleep_in_the_log_is_no_line_never_zero(self):
        entries = [{"kind": "feeding", "start": "2026-10-30T02:35:00-03:00", "ref": "f1"}]
        summary = patterns.night_summary(entries, datetime.datetime(2026, 10, 30, 7, 30, tzinfo=TZ), TZ, ["Parent A", "Parent B"])
        self.assertIsNone(summary["longest_h"])
        self.assertNotIn("longest sleep", summary["text"])
        self.assertNotIn("0.0", night_es(summary["text"]))
        for longest in (None, 0.0):
            brief = {"night": {"feeds": 2, "longest_h": longest, "wakeups": {"Parent A": 1, "Parent B": 0}}}
            text = morning.compose("es", "Gonza", "Parent A", brief)
            self.assertNotIn("sueño más largo", text)
            self.assertIn("Anoche: 2 tomas, te levantaste una vez.", text)
        brief = {"night": {"feeds": 2, "longest_h": 3.2, "wakeups": {"Parent A": 0, "Parent B": 0}}}
        self.assertIn("el sueño más largo 3.2 h", morning.compose("es", "Gonza", "Parent A", brief))


class SpanishDemoNeverMixes(unittest.TestCase):
    def test_night_summary_and_who_is_up_next(self):
        text = night_es("Last night, Thu 29 to Fri 30: 2 feeds at 23:10, 03:00, longest sleep 3.1 h. "
                        "Wake-ups: Parent A 1, Parent B 1. Next on duty: Parent B.")
        self.assertNotIn("Parent", text)
        self.assertIn("Le toca: Persona B.", text)
        self.assertEqual(tonight.name("Parent B", "es"), "Persona B")

    def test_the_house_cards_why_is_spanish_or_absent(self):
        card = {"source": "muse", "fixed_reason": None, "now": "19:00", "until": "07:00", "on_duty": "Parent B",
                "on_duty_by": "rota", "bottle_prewarm": [{"start": "02:20", "end": ""}], "white_noise_boost": [],
                "door_quiet": [], "floor_clean": [], "summary": "Parent B takes the night. The warmer runs at 02:20.",
                "why_changed": "", "muse": {}}
        es = tonight.view(card, "es")
        self.assertEqual(es["why"], "")
        self.assertNotIn("Parent", " ".join(r["text"] for r in es["rows"]))
        self.assertNotIn("inglés", es["why_label"])
        self.assertEqual(tonight.view(card, "en")["why"], "Parent B takes the night. The warmer runs at 02:20.")
        card["summary"] = "Persona B se queda con la noche. Parent A duerme."
        self.assertEqual(tonight.view(card, "es")["why"], "Persona B se queda con la noche. Persona A duerme.")


class CryInBothLanguages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = FixtureLog(FIXTURE).entries()

    def assert_clean_spanish(self, text):
        self.assertTrue(rules.looks_spanish(text), text)
        self.assertFalse(english(text), text)
        self.assertIsNone(INTERNAL.search(text), text)
        self.assertTrue(cry_reason.no_medical(text), text)

    def test_every_cry_reason_has_a_spanish_line(self):
        from simweek import cries
        for case in cries.sample(cries.candidates(self.entries)):
            result = cry_reason.explain(self.entries, case["at"], TZ)
            self.assert_clean_spanish(result["text_es"])

    def test_the_sound_guess_and_check_now_in_spanish(self):
        at_ = datetime.datetime(2026, 10, 24, 14, 0, tzinfo=TZ)
        result = cry_reason.explain(self.entries, at_, TZ)
        guess = {"label": "tired", "confidence": 0.9, "speak": True}
        out = cry_sound.combine(result, guess, self.entries, at_)
        self.assert_clean_spanish(out["text_es"])
        out = cry_sound.combine(result, {"label": "belly_pain", "confidence": 0.9, "speak": True}, self.entries, at_)
        self.assertTrue(out["check_now"])
        self.assertTrue(out["text_es"].startswith("El llanto suena"))
        self.assert_clean_spanish(out["text_es"])

    def test_the_cry_push_reaches_a_spanish_parent_in_spanish(self):
        from parenting_agent.channels.push import in_lang
        at_ = datetime.datetime(2026, 10, 24, 14, 0, tzinfo=TZ)
        result = cry_reason.explain(self.entries, at_, TZ)
        event = {"text": result["text"], "texts": {"en": result["text"], "es": result["text_es"]}}
        self.assert_clean_spanish(in_lang(event, "es"))
        self.assertEqual(in_lang(event, "en"), result["text"])


from simweek import cries  # noqa: E402 the simulated week's cries, as in tests/test_sounds.py

if __name__ == "__main__":
    unittest.main()
