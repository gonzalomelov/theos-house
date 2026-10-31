"""A parent is never told "logged" when nothing was saved.

With the real brain, a burst of notes in Spanish or English got "Anotado" or "Logged" with no log tool call in about
a third of the replies (issue #40). The shared decide loop now holds back such an answer: it asks the brain once more
to call the tool, and if it still does not, the parent hears that it could not be logged. These tests script the
brain, so they run with no network: a brain that claims logging without a call, one that calls the tool, one whose
call fails, and the questions and small talk the guard must leave alone.
"""
import unittest

from parenting_agent.agent import rules
from parenting_agent.agent.loop import LOG_CHECK, NOT_LOGGED, Agent, logged_text
from parenting_agent.agent.memory import LocalBabyLog, Memory
from parenting_agent.agent.tools import core_tools
from parenting_agent.bus import Bus
from parenting_agent.demo.app import DemoApp
from parenting_agent.families.texts import EN, ES

import test_demo
from test_families import family_of, make
from test_families_spanish import onboard
from test_one_message_one_entry import BOTTLE, LANG_CODE, NOTES, Clock, ScriptedBrain, log

TABLES = {"en": EN, "es": ES}
CLAIM = {"en": "Logged: a 120 ml bottle for Mia.", "es": "Anoté la mamadera de 120 ml de Mia."}


class Recording(ScriptedBrain):
    """A scripted brain that also keeps the last user turn it saw, to check the agent asked it to call the tool."""

    def __init__(self, *plans):
        super().__init__(*plans)
        self.users = []

    def step(self, system, transcript, tools):
        if transcript[-1]["role"] == "user":
            self.users.append(transcript[-1]["text"])
        return super().step(system, transcript, tools)


class FamiliesGuard(unittest.TestCase):
    def family(self, brain, lang, user=7):
        clock = Clock()
        # These tests script the guarded loop, so they run the families bot in its guards log mode (#77).
        app = make(self, brain=brain, clock=clock, PA_FAMILIES_LOG_MODE="guards")
        onboard(app, user, LANG_CODE[lang])
        return app, app.family(family_of(app, user)), clock

    def test_a_claim_without_a_log_call_is_never_sent(self):
        for lang in ("en", "es"):
            with self.subTest(lang=lang):
                brain = Recording([CLAIM[lang]], [CLAIM[lang]])
                app, f, _ = self.family(brain, lang)
                reply = app.handle(7, 7, NOTES[lang]["feeding"], "private", LANG_CODE[lang])[0][1]
                self.assertEqual(reply, TABLES[lang]["NOT_LOGGED"])
                self.assertEqual(f.log.entries(), [])
                self.assertEqual(brain.users[-1], LOG_CHECK.format(request=NOTES[lang]["feeding"]))
                self.assertEqual(f.memory.recent_messages(1)[0]["text"], reply)

    def test_the_spanish_and_english_answers(self):
        self.assertEqual(ES["NOT_LOGGED"], "No pude anotarlo, ¿me lo repetís?")
        self.assertEqual(EN["NOT_LOGGED"], "I could not log that. Could you send it again?")

    def test_a_brain_that_logs_after_the_check_logs_once(self):
        for lang in ("en", "es"):
            with self.subTest(lang=lang):
                brain = Recording([CLAIM[lang]], [[log("feeding", BOTTLE), log("feeding", BOTTLE)], CLAIM[lang]])
                app, f, _ = self.family(brain, lang)
                reply = app.handle(7, 7, NOTES[lang]["feeding"], "private", LANG_CODE[lang])[0][1]
                self.assertEqual(reply, logged_text(f.log.entries("feeding"), lang))
                self.assertEqual(len(f.log.entries("feeding")), 1)

    def test_a_brain_that_calls_the_tool_is_not_asked_again(self):
        for lang in ("en", "es"):
            for kind in ("feeding", "diaper"):
                with self.subTest(lang=lang, kind=kind):
                    details = BOTTLE if kind == "feeding" else {"wet": True, "solid": True}
                    brain = Recording([[log(kind, details)], CLAIM[lang]])
                    app, f, _ = self.family(brain, lang)
                    reply = app.handle(7, 7, NOTES[lang][kind], "private", LANG_CODE[lang])[0][1]
                    # The confirmation comes from the stored entry, never from the brain's words (here a wrong bottle).
                    self.assertEqual(reply, logged_text(f.log.entries(kind), lang))
                    self.assertEqual(len(f.log.entries(kind)), 1)
                    self.assertFalse(any(u.startswith("[check") for u in brain.users))

    def test_a_confirmation_that_contradicts_a_failed_log_call_is_never_sent(self):
        brain = Recording([[log("poop", {"wet": True})], "Anoté el pañal."], ["Anoté el pañal."])
        app, f, _ = self.family(brain, "es")
        reply = app.handle(7, 7, "pañal sucio", "private", "es-UY")[0][1]
        self.assertEqual(reply, ES["NOT_LOGGED"])
        self.assertEqual(f.log.entries(), [])

    def test_a_claim_for_a_note_the_parser_misses_is_caught(self):
        brain = Recording(["Anoté 120 de fórmula."], ["Anoté 120 de fórmula."])
        app, f, _ = self.family(brain, "es")
        self.assertFalse(rules.is_log_request("120 de fórmula"))
        self.assertEqual(app.handle(7, 7, "120 de fórmula", "private", "es-UY")[0][1], ES["NOT_LOGGED"])

    def test_questions_and_small_talk_go_through(self):
        cases = [("en", "how much did she drink this morning?", "She drank 120 ml this morning, all logged."),
                 ("es", "¿cuánto tomó hoy?", "Hoy tomó 240 ml, todo anotado."),
                 ("en", "thanks!", "You are welcome."),
                 ("es", "gracias", "De nada.")]
        for lang, text, answer in cases:
            with self.subTest(text=text):
                brain = Recording([answer])
                app, _, _ = self.family(brain, lang)
                self.assertEqual(app.handle(7, 7, text, "private", LANG_CODE[lang])[0][1], answer)
                self.assertFalse(any(u.startswith("[check") for u in brain.users))


class Detection(unittest.TestCase):
    def test_log_requests_in_both_languages(self):
        for text in ("mamadera 120 ml", "pañal mojado y sucio", "se durmió", "se despertó", "tomó 90 ml de mamadera",
                     "le di la teta izquierda 15 min", "bottle 120 ml", "wet diaper", "she fell asleep", "bath done"):
            self.assertTrue(rules.is_log_request(text), text)
        for text in ("when did she last eat?", "¿cuándo tomó?", "cuánto tomó hoy", "how much did she drink today",
                     "thanks", "gracias", "she has a fever"):
            self.assertFalse(rules.is_log_request(text), text)

    def test_claims(self):
        for text in ("Logged: a 120 ml bottle.", "Anoté la mamadera.", "Anotado, pañal sucio.", "Listo, registré el baño."):
            self.assertTrue(rules.claims_logged(text), text)
        for text in ("Noted.", "OK.", "Entendido.", "De nada."):
            self.assertFalse(rules.claims_logged(text), text)


class SharedLoop(unittest.TestCase):
    """Gonza's family agent and the demo use the same guard."""

    def agent(self, brain):
        memory = Memory(":memory:")
        self.addCleanup(memory.close)
        baby_log = LocalBabyLog(memory)
        bus = Bus(None)
        replies = []
        bus.subscribe(replies.append, ["reply"])
        return Agent(bus, memory, baby_log, core_tools(memory, baby_log, ["log_baby_event"]), brain), baby_log, replies

    def test_plain_agent_answers_honestly_in_the_parents_language(self):
        for lang in ("en", "es"):
            with self.subTest(lang=lang):
                agent, baby_log, replies = self.agent(ScriptedBrain([CLAIM[lang]], [CLAIM[lang]]))
                agent.handle({"kind": "message", "channel": "test", "text": NOTES[lang]["feeding"]})
                self.assertEqual(replies[-1]["text"], NOT_LOGGED[lang])
                self.assertEqual(baby_log.entries(), [])

    def test_plain_agent_logs_when_the_brain_calls_the_tool(self):
        agent, baby_log, replies = self.agent(ScriptedBrain([[log("feeding", BOTTLE)], "Logged."]))
        agent.handle({"kind": "message", "channel": "test", "text": "bottle 120 ml"})
        self.assertEqual(replies[-1]["text"], "Logged.")
        self.assertEqual(len(baby_log.entries("feeding")), 1)

    def test_an_observation_from_a_skill_is_not_guarded(self):
        agent, baby_log, replies = self.agent(ScriptedBrain(["Logged the bottle the scale saw."]))
        agent.handle({"kind": "observation", "channel": "test", "source": "scale", "text": "bottle 120 ml"})
        self.assertEqual(replies[-1]["text"], "Logged the bottle the scale saw.")

    def test_demo_never_sends_a_false_logged(self):
        app = DemoApp(test_demo.settings(), brain=ScriptedBrain(["Logged."], ["Logged."]))
        self.addCleanup(app.close)
        before = len(app.visitor("v").baby_log.entries("feeding", limit=100_000))
        status, body = app.message("v", False, "bottle 120 ml")[:2]
        self.assertEqual(status, 200)
        self.assertIn(NOT_LOGGED["en"], str(body))
        self.assertEqual(len(app.visitor("v").baby_log.entries("feeding", limit=100_000)), before)


if __name__ == "__main__":
    unittest.main()
