"""The families log can be corrected, and the bot never makes up details or talks about its own bookkeeping (issue #40).

The real-new-parent judge found that "perdón eran 100 no 120" kept the 120, that a bottle sent twice by mistake stayed
twice, that "teta 10 min" became "both breasts", that "a qué hora le toca?" had no answer, that the evening summary said
a feed "se esperaba" 7 hours ago, and that the Spanish refusal and summaries read wrong. The safety auditor found no hard
emergency line, a "send it again" answer to health messages and a bottle refused as medical. These tests script the
brain, so they run with no network.
"""
import datetime
import unittest

from parenting_agent.agent import rules
from parenting_agent.agent.loop import EDIT_CHECK, LOG_CHECK, NOT_NEW, TEXTS, Agent
from parenting_agent.agent.memory import LocalBabyLog, Memory
from parenting_agent.agent.tools import core_tools
from parenting_agent.bus import Bus
from parenting_agent.families.texts import EN, ES

from test_families import CountingBrain, family_of, make
from test_families_spanish import onboard
from test_no_false_logged import Recording
from test_one_message_one_entry import Clock, ScriptedBrain, log

ES_UY = "es-UY"


def edit(details, **which):
    return {"name": "edit_baby_event", "arguments": {**which, "details": details}}


def delete(**which):
    return {"name": "delete_baby_event", "arguments": which}


class Base(unittest.TestCase):
    def family(self, brain, lang=ES_UY, user=7, clock=None):
        clock = clock or Clock()
        app = make(self, brain=brain, clock=clock)
        onboard(app, user, lang)
        return app, app.family(family_of(app, user)), clock

    def send(self, app, clock, hhmm, text, lang=ES_UY, user=7):
        h, m = (int(x) for x in hhmm.split(":"))
        clock.now = clock.now.replace(hour=h, minute=m)
        return app.handle(user, user, text, "private", lang)[0][1]

    def ml(self, f):
        return [e["details"].get("amount_ml") for e in f.log.entries("feeding")]


class EditAndDelete(Base):
    def test_a_correction_changes_the_entry_and_says_exactly_what_changed(self):
        brain = Recording([[log("feeding", {"amount_ml": 120, "method": "bottle"})], "Anotado."],
                          [[edit({"amount_ml": 100}, kind="feeding", at="01:30")], "Listo."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "01:30", "mamadera 120")
        reply = self.send(app, clock, "01:33", "perdón eran 100 no 120")
        self.assertEqual(reply, "Corregí la mamadera de las 01:30: 120 ml → 100 ml.")
        self.assertEqual(self.ml(f), [100.0])
        self.assertIn("100 ml en total", app.summary_text(f))
        clock.now = clock.now.replace(hour=20, minute=0)
        self.assertTrue(any("100 ml en total" in text for _, text in app.tick()))

    def test_an_edit_by_id_and_in_english(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 120, "method": "bottle"})], "Logged."],
                              [[edit({"amount_ml": 80}, id=1)], "Done."])
        app, f, clock = self.family(brain, lang="en")
        self.send(app, clock, "01:30", "bottle 120 ml", "en")
        self.assertEqual(self.send(app, clock, "12:12", "the 1:30 one was 80, fix it", "en"),
                         "Fixed the 01:30 bottle: 120 ml → 80 ml.")
        self.assertEqual(self.ml(f), [80.0])

    def test_a_correction_moves_the_start_with_the_time_and_keeps_the_rest(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 90, "method": "bottle", "type": "formula"})], "Anotado."],
                              [[edit({}, kind="feeding", last=True, ts="2026-10-28T01:45:00-03:00")], "Listo."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "02:00", "mamadera de fórmula 90 ml")
        self.assertEqual(self.send(app, clock, "02:05", "perdón fue a las 01:45"), "Corregí la mamadera de las 02:00: 02:00 → 01:45.")
        entry = f.log.entries("feeding")[0]
        self.assertEqual((entry["ts"][11:16], entry["details"]["start"][11:16], entry["details"]["type"]), ("01:45", "01:45", "formula"))

    def test_delete_the_last_and_a_double_send(self):
        brain = ScriptedBrain([[log("diaper", {"solid": True})], "Anotado."], [[delete(last=True)], "Listo."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "03:30", "pañal sucio")
        self.assertEqual(self.send(app, clock, "03:31", "borrá la última"), "Borré el pañal de las 03:30.")
        self.assertEqual(f.log.entries(), [])
        self.assertIn("Todavía no hay nada", app.summary_text(f))

    def test_never_done_when_nothing_changed(self):
        brain = Recording(["Listo, corregido."], ["Listo, ya está corregido."])
        app, f, clock = self.family(brain)
        f.log.add("feeding", {"amount_ml": 120, "method": "bottle"})
        reply = self.send(app, clock, "15:05", "perdón eran 100 no 120")
        self.assertEqual(reply, TEXTS["es"]["NOT_CHANGED"])
        self.assertEqual(brain.users[-1], EDIT_CHECK.format(request="perdón eran 100 no 120"))
        self.assertEqual(self.ml(f), [120.0])

    def test_a_correction_is_never_logged_as_a_new_entry(self):
        brain = Recording([[log("feeding", {"amount_ml": 100, "method": "bottle"})], "Anoté 100 ml."],
                          [[log("note", {"text": "corrección"})], "Anotado."])
        app, f, clock = self.family(brain)
        f.log.add("feeding", {"amount_ml": 120, "method": "bottle"})
        self.assertEqual(self.send(app, clock, "15:05", "perdón eran 100 ml no 120 ml"), TEXTS["es"]["NOT_CHANGED"])
        self.assertEqual([e["kind"] for e in f.log.entries()], ["feeding"])
        self.assertEqual(self.ml(f), [120.0])

    def test_a_failed_edit_is_not_done(self):
        brain = Recording([[edit({"amount_ml": 100}, kind="feeding", at="09:99")], "Listo."], [[edit({"amount_ml": 100}, id=42)], "Listo."])
        app, f, clock = self.family(brain)
        f.log.add("feeding", {"amount_ml": 120, "method": "bottle"})
        self.assertEqual(self.send(app, clock, "15:05", "eran 100 no 120"), TEXTS["es"]["NOT_CHANGED"])
        self.assertEqual(self.ml(f), [120.0])

    def test_a_log_without_edits_says_it_cannot_change_and_adds_nothing(self):
        memory = Memory(":memory:")
        log_ = LocalBabyLog(memory)
        log_.add("feeding", {"amount_ml": 90, "method": "bottle"})
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 80, "method": "bottle"})], "Logged."], ["Logged."])
        agent = Agent(Bus(None), memory, log_, core_tools(memory, log_, ["log_baby_event", "read_baby_log"]), brain)
        said = []
        agent.bus.subscribe(lambda e: said.append(e["text"]), ["reply"])
        agent.handle({"kind": "message", "channel": "console", "text": "sorry it was 80 not 90"})
        self.assertEqual(said, [TEXTS["en"]["CANNOT_CHANGE"]])
        self.assertEqual(len(log_.entries("feeding")), 1)
        self.assertNotIn("edit_baby_event", agent.tools.items)

    def test_correction_detection(self):
        for text in ("perdón eran 100 no 120", "la de la 1 y media fue 80, corregila", "la mandé 2 veces sin querer",
                     "borrá la última", "eran 90 no 110", "sorry it was 80 not 90", "delete the last one"):
            self.assertTrue(rules.is_edit_request(text), text)
            self.assertFalse(rules.is_log_request(text) and not rules.is_edit_request(text), text)
        for text in ("mamadera 120", "pañal sucio", "se durmió", "bottle 120 ml", "¿cuánto tomó hoy?"):
            self.assertFalse(rules.is_edit_request(text), text)


class DoubleSend(Base):
    def setUp(self):
        self.brain = lambda *more: ScriptedBrain([[log("feeding", {"amount_ml": 110, "method": "bottle"})], "Anotado."],
                                                 [[log("feeding", {"amount_ml": 110, "method": "bottle"})], "Anotado."], *more)

    def test_the_same_bottle_within_3_minutes_is_asked_about_then_kept_once(self):
        app, f, clock = self.family(self.brain())
        self.send(app, clock, "04:40", "tomó 110 ml de mamadera")
        ask = self.send(app, clock, "04:41", "tomó 110 ml de mamadera")
        self.assertTrue(ask.startswith("¿La mandaste dos veces o fueron dos mamaderas?"), ask)
        self.assertEqual(self.ml(f), [110.0])
        self.assertEqual(self.send(app, clock, "04:42", "la mandé 2 veces sin querer"),
                         "Dale, queda una sola: la mamadera de 110 ml de las 04:40.")
        self.assertEqual(self.ml(f), [110.0])

    def test_two_bottles_logs_the_second_at_its_own_time(self):
        app, f, clock = self.family(self.brain())
        self.send(app, clock, "00:15", "tomó 110 ml de mamadera")
        self.send(app, clock, "00:16", "tomó 110 ml de mamadera")
        self.assertEqual(self.send(app, clock, "00:17", "fueron dos, tomó otra"), "Anoté la segunda: la mamadera de 110 ml de las 00:16.")
        self.assertEqual([e["ts"][11:16] for e in f.log.entries("feeding")], ["00:15", "00:16"])

    def test_after_3_minutes_it_is_logged_without_asking(self):
        app, f, clock = self.family(self.brain())
        self.send(app, clock, "04:40", "tomó 110 ml de mamadera")
        self.assertEqual(self.send(app, clock, "04:44", "tomó 110 ml de mamadera"), "Anoté la mamadera de 110 ml de las 04:44.")
        self.assertEqual(self.ml(f), [110.0, 110.0])

    def test_a_different_bottle_is_logged_without_asking(self):
        brain = ScriptedBrain([[log("feeding", {"amount_ml": 110, "method": "bottle"})], "Anotado."],
                              [[log("feeding", {"amount_ml": 90, "method": "bottle"})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "04:40", "mamadera 110")
        self.send(app, clock, "04:41", "mamadera 90")
        self.assertEqual(self.ml(f), [110.0, 90.0])

    def test_an_unclear_answer_keeps_one_and_is_asked_once_more(self):
        app, f, clock = self.family(self.brain(["¿Cómo dijiste?"]))
        self.send(app, clock, "04:40", "tomó 110 ml de mamadera")
        self.send(app, clock, "04:41", "tomó 110 ml de mamadera")
        self.assertEqual(self.send(app, clock, "04:42", "mmm"),
                         "No te entendí, así que quedó una sola: la mamadera de 110 ml de las 04:40. ¿Fue una sola mandada "
                         "dos veces, o fueron dos mamaderas? Respondé una o dos.")
        self.assertEqual(self.send(app, clock, "04:43", "ehh"), "¿Cómo dijiste?")
        self.assertEqual(self.ml(f), [110.0])

    def test_the_answers(self):
        for text in ("la mandé 2 veces sin querer", "dos veces", "fue una sola", "I sent it twice", "same bottle"):
            self.assertEqual(rules.double_answer(text), "once", text)
        for text in ("fueron dos, tomó otra", "dos mamaderas", "there were two bottles", "another one"):
            self.assertEqual(rules.double_answer(text), "two", text)
        self.assertIsNone(rules.double_answer("mmm"))


class NothingMadeUp(Base):
    def test_no_side_no_type_no_start_shift(self):
        brain = ScriptedBrain(
            [[log("feeding", {"method": "both breasts", "type": "breast milk", "duration_min": 10,
                              "start": "2026-10-28T14:45:00-03:00"}, ts="2026-10-28T14:55:00-03:00")], "Anotado."],
            [[log("feeding", {"amount_ml": 90, "method": "bottle", "type": "breast milk", "duration_min": 15})], "Anotado."])
        app, f, clock = self.family(brain)
        self.send(app, clock, "15:00", "teta 10 min")
        self.send(app, clock, "16:00", "mamadera 90")
        breast, bottle = f.log.entries("feeding")
        self.assertEqual((breast["details"]["method"], breast["ts"][11:16], breast["details"]["start"][11:16]), ("breast", "15:00", "14:50"))
        self.assertEqual((bottle["details"]["type"], bottle["ts"][11:16], bottle["details"]["start"][11:16]), ("unknown", "16:00", "16:00"))

    def test_what_the_parent_said_is_kept(self):
        details, ts = rules.said_only("pecho izquierdo 15 min a las 9:00", "feeding",
                                      {"method": "left breast", "duration_min": 15}, "2026-10-28T09:00:00-03:00")
        self.assertEqual((details, ts), ({"method": "left breast", "duration_min": 15}, "2026-10-28T09:00:00-03:00"))
        details, _ = rules.said_only("mamadera de fórmula 120 ml", "feeding", {"method": "bottle", "type": "formula", "amount_ml": 120})
        self.assertEqual(details["type"], "formula")

    def test_the_checks_tell_the_brain_to_keep_quiet_about_them(self):
        for check in (LOG_CHECK, EDIT_CHECK):
            self.assertIn("never mention this check", check)
            self.assertIn("ahora sí", check)

    def test_a_spanish_question_without_a_mark_is_not_held(self):
        brain = Recording(["Hoy tomó 210 ml, todo anotado."])
        app, f, clock = self.family(brain)
        self.assertEqual(self.send(app, clock, "09:35", "cuanto tomo hoy"), "Hoy tomó 210 ml, todo anotado.")
        self.assertFalse(any(u.startswith("[check") for u in brain.users))

    def test_the_prompt_bans_bookkeeping_talk(self):
        brain = CountingBrain()
        app, f, clock = self.family(brain)
        self.send(app, clock, "09:00", "hola")
        for words in ("Never talk about your own bookkeeping", "Never add a detail the parent did not say", "edit_baby_event"):
            self.assertIn(words, brain.last_system)


class NextFeed(Base):
    def feeds(self, f, clock, *times):
        for hhmm in times:
            h, m = (int(x) for x in hhmm.split(":"))
            clock.now = clock.now.replace(hour=h, minute=m)
            f.log.add("feeding", {"amount_ml": 90, "method": "bottle"})

    def test_the_brain_has_the_rhythm_as_a_tool(self):
        brain = ScriptedBrain([[{"name": "next_feed", "arguments": {}}], "A las 12:00."])
        app, f, clock = self.family(brain)
        self.feeds(f, clock, "06:00", "09:00")
        self.assertIn("next_feed", f.agent.tools.allowed)
        status, result = f.agent.tools.run("next_feed", {})
        self.assertEqual((status, result), ("ran", app.next_feed(f)["text"]))
        self.assertIn("Según tu registro", result)
        self.assertIn("12:00", result)
        self.assertEqual(self.send(app, clock, "10:00", "a q hora le toca?"), "A las 12:00.")

    def test_no_feed_logged_for_a_while_asks_if_the_baby_ate(self):
        app, f, clock = self.family(CountingBrain())
        self.feeds(f, clock, "09:10", "12:10")
        clock.now = clock.now.replace(hour=16, minute=0)
        self.assertEqual(app.next_feed(f)["text"], "Ya pasaron 3 h 50 min desde la última toma anotada, a las 12:10. ¿Comió Mia?")
        clock.now = clock.now.replace(hour=23, minute=10)
        nxt = app.next_feed(f)
        self.assertEqual((nxt["kind"], nxt["text"]), ("old", "La última toma anotada de Mia fue a las 12:10, hace 11 h 00 min."))
        self.assertNotIn("12:10.", app.summary_text(f).split("la última a las 12:10")[-1])
        for text in (app.next_feed(f)["text"], app.summary_text(f)):
            self.assertNotIn("se esperaba", text)

    def test_just_due_says_about_now_and_the_reminder_still_goes(self):
        app, f, clock = self.family(CountingBrain())
        self.feeds(f, clock, "06:00", "09:00")
        clock.now = clock.now.replace(hour=12, minute=10)
        self.assertEqual(app.next_feed(f)["kind"], "now")
        self.assertTrue(any("más o menos ahora" in text for _, text in app.tick()))

    def test_no_late_wording_left(self):
        self.assertNotIn("FEED_LATE", ES)
        for table in (EN, ES):
            self.assertNotIn("expected", table["NEXT_FEED"] + table["NO_FEED_SINCE"])
            self.assertNotIn("esperaba", table["NEXT_FEED"] + table["NO_FEED_SINCE"])


class SpanishTexts(Base):
    def test_the_refusal_reads_right_and_names_emergencies(self):
        self.assertNotIn("Por eso", ES["REFUSAL"])
        self.assertIn("Para eso, mejor llamá a tu pediatra", ES["REFUSAL"])
        self.assertIn("911", ES["REFUSAL"])
        self.assertIn("If it is urgent, call emergency services", EN["REFUSAL"])
        self.assertEqual(EN["REFUSAL"], rules.REFUSAL)

    def test_singular_and_plural_in_summaries(self):
        app, f, clock = self.family(CountingBrain())
        f.log.add("diaper", {"wet": True, "solid": True})
        f.log.add("diaper", {"wet": True})
        self.assertIn("2 pañales, 2 mojados y 1 sucio.", app.summary_text(f))
        f.log.add("diaper", {"solid": True, "wet": False})
        self.assertIn("3 pañales, 2 mojados y 2 sucios.", app.summary_text(f))


class Safety(Base):
    EMERGENCIES = ("she is not breathing", "his lips are blue", "the baby is limp", "he is choking", "she won't wake up",
                   "he fell off the bed", "she hit her head", "he is having a seizure", "no respira", "está morado",
                   "se ahoga", "no se despierta", "se cayó de la cama", "se golpeó la cabeza", "tiene una convulsión")

    def test_red_flags_get_the_emergency_line_with_no_brain_call(self):
        for lang, code in (("es", ES_UY), ("en", "en")):
            for text in self.EMERGENCIES:
                with self.subTest(lang=lang, text=text):
                    brain = CountingBrain()
                    app, f, clock = self.family(brain, lang=code)
                    reply = self.send(app, clock, "08:00", text, code)
                    self.assertEqual(reply, (ES if lang == "es" else EN)["EMERGENCY"])
                    self.assertIn("911", reply)
                    self.assertEqual(brain.calls, 0)
        self.assertIn("local emergency number", EN["EMERGENCY"])

    def test_the_shared_loop_answers_red_flags_too(self):
        memory = Memory(":memory:")
        log_ = LocalBabyLog(memory)
        brain = CountingBrain()
        agent = Agent(Bus(None), memory, log_, core_tools(memory, log_, ["log_baby_event"]), brain)
        said = []
        agent.bus.subscribe(lambda e: said.append(e["text"]), ["reply"])
        agent.handle({"kind": "message", "channel": "console", "text": "she is not breathing"})
        self.assertEqual((said, brain.calls), ([rules.EMERGENCY_REPLY["en"]], 0))

    def test_crying_is_not_an_emergency_and_gets_a_reason_from_the_log(self):
        for lang, code, guess in (("es", ES_UY, "nunca un diagnóstico"), ("en", "en", "never a diagnosis")):
            with self.subTest(lang=lang):
                brain = CountingBrain()
                app, f, clock = self.family(brain, lang=code)
                for hhmm in ("08:00", "11:00", "14:00"):
                    clock.now = clock.now.replace(hour=int(hhmm[:2]), minute=0)
                    f.log.add("feeding", {"amount_ml": 90, "method": "bottle"})
                text = "no para de llorar, ¿por qué?" if lang == "es" else "she won't stop crying, why?"
                self.assertFalse(rules.is_emergency(text))
                reply = self.send(app, clock, "17:00", text, code)
                self.assertNotIn("911", reply)
                self.assertIn(guess, reply)
                self.assertIn("hambre" if lang == "es" else "hungry", reply)
                self.assertEqual(brain.calls, 0)

    def test_crying_with_an_empty_log_says_so(self):
        app, f, clock = self.family(CountingBrain())
        self.assertEqual(self.send(app, clock, "17:00", "llora mucho, ¿por qué?"), ES["CRY_NOT_ENOUGH"].format(name="Mia"))

    def test_health_messages_never_get_send_it_again(self):
        for lang, text in (("en", "she has not pooped in 4 days"), ("en", "can I add rice cereal to her bottle so she sleeps longer"),
                           ("es", "no hizo caca hace 4 días"), ("es", "puedo ponerle cereal a la mamadera?")):
            with self.subTest(text=text):
                brain = Recording(["I can't advise on that, please call your pediatrician."])
                app, f, clock = self.family(brain, lang="en" if lang == "en" else ES_UY)
                reply = self.send(app, clock, "10:00", text, "en" if lang == "en" else ES_UY)
                self.assertNotIn(reply, (EN["NOT_LOGGED"], ES["NOT_LOGGED"]))
                self.assertFalse(any(u.startswith("[check") for u in brain.users))
                self.assertTrue(rules.is_health(text))

    def test_a_bottle_the_parent_gives_is_logged_not_refused(self):
        app, f, clock = self.family(None)  # the free rule-based brain
        self.assertFalse(rules.is_medical_es("le doy la mamadera, 120 ml"))
        reply = self.send(app, clock, "13:05", "le doy la mamadera, 120 ml")
        self.assertNotEqual(reply, ES["REFUSAL"])
        self.assertEqual(self.ml(f), [120.0])
        self.assertTrue(rules.is_medical_es("¿le puedo dar paracetamol?"))


class Privacy(unittest.TestCase):
    def test_the_note_says_plainly_where_the_text_goes(self):
        for table in (EN, ES):
            note = table["PRIVACY"]
            self.assertIn("https://privacy.claude.com/en/articles/7996866", note)
            self.assertIn("Anthropic", note)
            self.assertIn("Muse Spark Open", note)
            self.assertIn("https://docs.baseten.co/observability/security", note)
            self.assertIn("Uruguay", note)
            for wrong in ("does not keep it", "no lo guarda", "never keeps", "no data kept"):
                self.assertNotIn(wrong, note)
        self.assertIn("/borrarmisdatos", ES["PRIVACY"])
        self.assertIn("/deletemydata", EN["PRIVACY"])


if __name__ == "__main__":
    unittest.main()
