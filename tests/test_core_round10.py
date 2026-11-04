"""Round 10: a fever named as over doesn't fire, and any doubt still does; an open alarm isn't reassured away; a promise to read again comes back."""
import datetime
import unittest

from tests import test_langgraph_core as base
from tests.test_langgraph_core import READY, NoScreen, call, scripted

if READY:
    from langchain_core.messages import AIMessage
    from parenting_agent.agent import rules
    from parenting_agent.core import runtime, safety, tools as tools_mod

NIGHT = datetime.datetime.fromisoformat("2026-12-16T03:12:00-03:00")
OVER_ES = ("la fiebre ya paso", "La fiebre ya pasó.", "ya se le pasó la fiebre", "se le fue la fiebre", "la fiebre se fue", "la fiebre ya se fue, duerme", "ya le bajó la fiebre", "ya no tiene fiebre", "no tiene más fiebre", "la fiebre de ayer ya pasó")
OVER_EN = ("the fever is gone", "The fever's gone.", "his fever broke", "the fever went away", "fever gone", "the fever is over", "no more fever", "he doesn't have a fever anymore", "the fever has passed", "fever's gone and he's asleep")
# Whatever else these say, it can't be read as over.
STILL_ES = ("la fiebre no pasó", "todavía no se le pasó la fiebre", "no se le fue la fiebre", "¿ya se le pasó la fiebre?", "¿la fiebre ya pasó", "si se le fue la fiebre le doy la mamadera", "la fiebre paso a 39", "la fiebre pasó de 38 a 39", "la fiebre se fue a 38,7",
            "la fiebre ya paso pero volvió", "se le fue la fiebre y volvió", "la fiebre ya pasó, ahora tiene 38,5", "la fiebre ya paso, 38,4", "la fiebre ya pasó pero sigue caliente", "la fiebre se fue, sigue caliente", "creo que la fiebre ya pasó", "parece que se le fue la fiebre",
            "la fiebre ya paso, tiene fiebre de nuevo", "la fiebre bajó a 38,2", "la fiebre bajó un poco", "le bajó un poco la fiebre", "la fiebre pasó la noche entera", "tiene fiebre", "tuvo fiebre anoche", "la fiebre ya paso. ¿puedo darle algo?", "cuando se le pasó la fiebre tenía 38,5",
            "la fiebre ya paso y le subió otra vez", "no sé si se le fue la fiebre", "ojalá se le fue la fiebre", "no baja la fiebre", "no sé si tiene fiebre")
STILL_EN = ("the fever is not gone", "the fever isn't gone", "is the fever gone?", "the fever's gone?", "if the fever is gone I'll feed him", "the fever is over 39", "the fever is over 38.5", "fever passed 39", "the fever is gone but he's still hot", "the fever went away and came back",
            "fever's gone, now 38.5", "the fever's gone, he's at 38,3", "I think the fever is gone", "maybe the fever is gone", "the fever came down to 38.2", "the fever came down a bit", "he had a fever yesterday", "he has a fever", "the fever never went away",
            "the fever is gone. Should I give him something?", "the fever is gone, is it ok to bathe him?", "I hope the fever is gone", "the fever is gone and back up again", "fever's gone, still warm", "not sure the fever is gone", "the fever went away for an hour but it's back")
# A sign beside it is what the gate answers.
SIGN_BESIDE = ("la fiebre ya paso. no respira", "La fiebre ya pasó y se puso azul", "la fiebre ya paso, no reacciona", "the fever is gone. he isn't breathing", "the fever's gone and his lips are blue", "fever's gone. he won't wake up", "the fever is gone. he won't feed", "la fiebre ya pasó. no quiere comer", "la fiebre se fue. vomitó verde", "the fever is gone, he had a seizure")


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class FeverOver(unittest.TestCase):
    def gate(self, text, lang="es"):
        return safety.gate(text, NoScreen(), lang)

    def test_a_fever_named_as_over_doesnt_fire(self):
        for text in (*OVER_ES, *OVER_EN):
            self.assertIsNone(self.gate(text), text)

    def test_the_message_that_lost_its_feed_and_question(self):
        self.assertIsNone(self.gate("la fiebre ya paso, el medico lo vio ayer y dijo que era un virus, esta bien. le di 70 ml recien. cuanto tomo en total hoy?"))
        self.assertIsNone(self.gate("The fever is gone, the doctor saw him yesterday. I gave him 70 ml just now. How much has he had today?", "en"))

    def test_any_doubt_fires(self):
        for text in (*STILL_ES, *STILL_EN):
            self.assertIsNotNone(self.gate(text), text)

    def test_a_sign_beside_it_fires(self):
        for text in SIGN_BESIDE:
            self.assertIsNotNone(self.gate(text), text)

    def test_only_the_words_about_the_fever_go(self):
        self.assertEqual(safety.without_fever_over("la fiebre ya paso. no respira").strip(" ."), "no respira")
        for text in ("tiene fiebre", "the fever is over 39", "Le di 70 ml"):
            self.assertEqual(safety.without_fever_over(text), text)

    def test_the_screen_doesnt_read_the_over_words(self):
        read = []

        class Reads(NoScreen):
            def screen(self, text, bus=None):
                read.append(text)
                return False, "test"
        safety.gate("the fever is gone, he looks a bit pale to me today", Reads(), "en")
        self.assertTrue(read and "fever" not in read[0] and "pale" in read[0])

    def test_it_doesnt_wake_the_other_parent(self):
        self.assertFalse(safety.worth_waking("la fiebre ya paso. le di 70 ml"))
        self.assertTrue(safety.worth_waking("la fiebre ya paso pero volvió"))
        self.assertTrue(safety.worth_waking("tiene fiebre"))


if __name__ == "__main__":
    unittest.main()
