"""The car seat coach in the parent's language, and the one final guard on every text that reaches a parent (Oct 31).

The Oct 30 glasses day (results/glasses-day/README.md) found the coach speaking English to a Spanish parent, and Muse's
own words (internal text, model and tool names, English, "finish reason", JSON, Parent A or B) still reached parents in
some answers. Offline: fake vision and frames for the coach, scripted brains, the fake Telegram messenger.
"""
import tempfile
import time
import unittest

from parenting_agent.agent import final_guard
from parenting_agent import hud_cards as cards
from parenting_agent.agent import brain as brain_mod
from parenting_agent.agent import rules
from parenting_agent.bus import Bus
from parenting_agent.carseat.coach import FORBIDDEN, Coach, plan
from parenting_agent.e2e.score import english
from tests.test_carseat import CAR, SEAT, SKILL, FakeVision, FrameFeed, scene
from tests.test_family_push import CECI, GONZA, Family, at
from test_one_message_one_entry import ScriptedBrain

PEOPLE_ES = {"gonza": {"name": "Gonza", "rota": "Parent A", "chat_ids_env": "TELEGRAM_CHAT_ID", "lang": "es"},
             "ceci": {"name": "Ceci", "rota": "Parent B", "chat_ids_env": "TELEGRAM_CECI_CHAT_ID", "lang": "es"}}
ANSWERS_ES = {"car_position": "sí", "belt_path_movement": "sí", "harness_pinch": "no"}


class MuseDisagrees:
    """Muse's second opinion says fail where SAM passes: the coach is unsure."""

    def look(self, frame, check_id):
        return {"result": "fail", "seconds": 0.0, "usd": 0.0}


def run_coach(lang, found, answers, timeout=1.0, muse=None):
    bus = Bus()
    coach = Coach({**SKILL, "step_timeout_s": timeout}, bus, FakeVision(found), FrameFeed(), SEAT, CAR,
                  answer_timeout_s=0.3, muse=muse, lang=lang)
    for check, text in answers.items():
        coach.answer(check, text)
    results = coach.run()
    return bus, results, [e for e in bus.history if e["kind"] == "voice"]


def says_forbidden(text):
    words = set(text.lower().replace(".", " ").replace(",", " ").split())
    return words & set(FORBIDDEN)


class CoachInSpanish(unittest.TestCase):
    def assert_spanish(self, lines):
        for line in lines:
            self.assertTrue(rules.looks_spanish(line), line)
            self.assertFalse(english(line), line)
            self.assertFalse(says_forbidden(line), line)

    def test_every_step_is_said_in_spanish(self):
        steps = plan(SKILL, SEAT, CAR, "es")
        self.assertEqual([s["id"] for s in steps], [s["id"] for s in plan(SKILL, SEAT, CAR)])
        self.assert_spanish([s["say"] for s in steps])
        self.assertIn("airbag", steps[0]["say"])
        self.assertTrue(steps[0]["say"].endswith("Decí sí o no."))

    def test_a_correct_install_in_spanish_and_never_seguro(self):
        found, _ = scene()
        bus, results, spoken = run_coach("es", found, ANSWERS_ES)
        self.assertTrue(all(r["result"] == "pass" for r in results.values()))
        self.assert_spanish([e["text"] for e in spoken])
        self.assertTrue(all(e["lang"] == "es" for e in spoken))
        summary = spoken[-1]["text"]
        self.assertIn("Esto no es un veredicto sobre la instalación.", summary)
        self.assertIn("técnico certificado", summary)
        self.assertIn("Chequeos con cámara que pasaron", summary)

    def test_what_sam_saw_unsure_open_and_by_hand_in_spanish(self):
        found, _ = scene(belt_through=False)
        _, results, spoken = run_coach("es", found, {"car_position": "sí"}, muse=MuseDisagrees())
        texts = [e["text"] for e in spoken]
        self.assertEqual(results["lap_guides"]["result"], "fail")
        self.assertIn("El cinturón de cadera no está en las guías laterales de los dos lados.", texts)
        self.assertTrue(any(t.startswith("Mis dos chequeos no coinciden") for t in texts), texts)
        self.assertIn("Dejo este chequeo abierto en el resumen.", texts)
        self.assertIn("Chequeos a mano todavía abiertos", texts[-1])
        self.assert_spanish(texts)
        _, results, spoken = run_coach("es", {}, ANSWERS_ES, timeout=0.3)
        self.assertEqual(results["level_line"]["result"], "unseen")
        self.assertIn("No pude ver la línea de nivel. Lo dejo como no revisado.", [e["text"] for e in spoken])
        self.assertIn("Chequeos con cámara que no pude ver", spoken[-1]["text"])

    def test_a_failed_hand_check_says_to_fix_it_in_spanish(self):
        found, _ = scene()
        _, results, spoken = run_coach("es", found, {**ANSWERS_ES, "harness_pinch": "sí"})
        self.assertEqual(results["harness_pinch"]["result"], "fail")
        self.assertIn("Anotado. Corregilo antes de manejar y pedime que lo revise de nuevo.", [e["text"] for e in spoken])

    def test_english_stays_the_default(self):
        found, _ = scene()
        _, _, spoken = run_coach("en", found, {"car_position": "yes", "belt_path_movement": "yes", "harness_pinch": "no"})
        self.assertIn("This is not a verdict on the install.", spoken[-1]["text"])

    def test_the_coach_refuses_seguro_and_safe_in_both_languages(self):
        for lang in ("es", "en"):
            coach = Coach(SKILL, Bus(), FakeVision({}), FrameFeed(frames=1), SEAT, CAR, lang=lang)
            for line in ("La instalación es segura.", "Quedó seguro.", "It is safe now."):
                with self.assertRaises(ValueError):
                    coach.say(line)
            coach.say("Pasá el cinturón de seguridad por la guía.")  # the seat belt's name is allowed

    def test_the_speaker_forwards_the_lines_language(self):
        from parenting_agent.speaker import Speaker
        pushed = []
        source = type("Source", (), {"push": lambda self, event: pushed.append(event)})()
        Speaker(source, quiet=True).on_event({"kind": "voice", "text": "Poné la manija hacia arriba.", "lang": "es",
                                              "skill": "car-seat", "step": "handle"})
        self.assertEqual(pushed[0]["lang"], "es")

    def test_the_glasses_card_for_a_step_is_spanish(self):
        card = cards.car_seat("lap_guides", "es", 2, 8, "pass")
        self.assertEqual((card["status"], card["detail"]), ("Cinturón de cadera en las dos guías", "Visto en cámara: bien"))


class CoachOnTelegram(unittest.TestCase):
    """Ceci asks on Telegram: every coach line reaches her chat in Spanish, nothing reaches Gonza, and the summary is
    the coach's own words, never the brain's."""

    def test_started_from_telegram_by_a_spanish_parent(self):
        from parenting_agent.carseat.plugin import CarSeatCoach
        found, _ = scene()
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 12, 0), extra={"people": PEOPLE_ES}, plugins=())
            try:
                from parenting_agent.agent.people import People
                family.agent.people = People(PEOPLE_ES)
                plugin = CarSeatCoach(family.agent, {**family.config, "car_seat": {"step_timeout_s": 1.0}},
                                      vision=FakeVision(found), source=FrameFeed(), quiet=True)
                plugin.skill_cfg = {**plugin.skill_cfg, "step_timeout_s": 1.0}
                asked = family.agent.bus.publish("message", channel="telegram", text="Ayudame con la silla del auto.",
                                                 chat_id=CECI, person="ceci")
                family.agent.current_event = asked
                plugin.start_coach()
                family.agent.current_event = None
                self.assertEqual(plugin.coach.lang, "es")
                deadline = time.monotonic() + 10
                while plugin.coach.asking != "car_position" and time.monotonic() < deadline:
                    time.sleep(0.02)
                family.say(CECI, "Sí.")
                self.assertIn("Anotado: sí.", family.sent_to(CECI))
                plugin.coach.answer("belt_path_movement", "sí")
                plugin.coach.answer("harness_pinch", "no")
                plugin.thread.join(timeout=30)
                self.assertFalse(plugin.thread.is_alive())
                lines = [t for t in family.sent_to(CECI) if t != "Anotado: sí."]
                self.assertGreaterEqual(len(lines), 7)
                for line in lines:
                    self.assertTrue(rules.looks_spanish(line), line)
                    self.assertFalse(english(line), line)
                    self.assertFalse(says_forbidden(line), line)
                self.assertTrue(lines[0].startswith("Te guío con la"))
                self.assertIn("Esto no es un veredicto", lines[-1])
                self.assertEqual(family.sent_to(GONZA), [])
                self.assertFalse([e for e in family.agent.bus.history if e["kind"] == "observation"],
                                 "the summary is never handed to the brain to say again")
                said = [m["text"] for m in family.agent.memory.recent_messages(5) if m["role"] == "assistant"]
                self.assertIn(lines[-1], said)
            finally:
                plugin.stop()
                family.close()


class Guard(unittest.TestCase):
    def test_internal_sentences_go_and_the_rest_stays(self):
        cases = [
            ("Anotado, 80 ml de mamadera. finish_reason length", "Anotado, 80 ml de mamadera."),
            ("Anotado. Invalid answer: not a JSON object.", "Anotado."),
            ("Listo. Lo anoté con log_baby_event.", "Listo."),
            ("Fue a las 10:40. Muse Spark Open lo calculó del registro.", "Fue a las 10:40."),
            ("Fue a las 10:40.\nLa casa de noche: At 06:11 a plan was armed.", "Fue a las 10:40."),
            ('Listo. {"action": "nap_mode", "on": true}', "Listo."),
            ("Prueba en seco. Dry run: house.live is off, so this was only written down.", "Prueba en seco."),
        ]
        for text, want in cases:
            result = final_guard.guard(text, "es")
            self.assertEqual(result.text, want, text)
            self.assertTrue(result.removed)

    def test_the_parents_language_and_their_own_quoted_words(self):
        self.assertEqual(final_guard.guard("Le di la mamadera. She slept well after the feed.", "es").text,
                         "Le di la mamadera.")
        kept = "«gave her the bottle at 3» Anotado: 90 ml a las 03:00."
        self.assertEqual(final_guard.guard(kept, "es").text, kept)
        self.assertEqual(final_guard.guard("None of the feeds were long.", "en").text, "None of the feeds were long.")
        self.assertEqual(final_guard.guard("Logged the bottle. Anotado el pañal de la mañana.", "en").text,
                         "Logged the bottle.")

    def test_rota_labels_become_names_or_go(self):
        self.assertEqual(final_guard.guard("Esta noche está de turno Parent A.", "es", {"Parent A": "Gonza"}).text,
                         "Esta noche está de turno Gonza.")
        self.assertEqual(final_guard.guard("Hola. Parent B duerme esta noche.", "es").text, "Hola.")
        demo = {"Parent A": "Parent A", "Parent B": "Parent B"}
        self.assertEqual(final_guard.guard("Parent A is up next.", "en", demo).text, "Parent A is up next.")

    def test_nothing_left_is_a_short_line_in_the_parents_language(self):
        result = final_guard.guard("finish reason length", "es")
        self.assertTrue(result.fallback)
        self.assertEqual(result.text, final_guard.FALLBACK["es"])
        self.assertEqual(final_guard.guard("Gave her the bottle and she slept well.", "es").text, final_guard.FALLBACK["es"])

    def test_clean_text_is_untouched(self):
        for text in ("Anotado, 80 ml en mamadera.", "Buen día, Gonza.\nAnoche: 3 tomas.\nClima: nublado, 14 a 15 C.",
                     "Llamá al 911 ya.", "Visitá baby.bygmv.com cuando quieras.", "Next feed in about 20 min, around 12:40."):
            result = final_guard.guard(text, "es" if rules.looks_spanish(text) else "en")
            self.assertEqual(result.text, text)
            self.assertFalse(result.changed)

    def test_a_lens_never_shows_what_the_guard_removes(self):
        self.assertIsNone(cards.clean("Muse Spark Open lo calculó."))
        self.assertIsNone(cards.clean("Parent A está de turno."))


class GuardOnEveryPath(unittest.TestCase):
    def test_the_family_agents_answer_and_the_log_of_what_went(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = ScriptedBrain(["La lista tiene pañales. The finish reason was length."])
            family = Family(tmp, at(30, 11, 0), brain=brain, extra={"people": PEOPLE_ES}, plugins=())
            try:
                from parenting_agent.agent.people import People
                family.agent.people = People(PEOPLE_ES)
                family.say(GONZA, "Hola, ¿cómo va la lista de compras?")
                self.assertEqual(family.sent_to(GONZA), ["La lista tiene pañales."])
                logged = [e for e in family.agent.bus.history if e["kind"] == "final_guard"]
                self.assertEqual(logged[0]["where"], "agent:telegram")
                self.assertEqual(logged[0]["removed"][0]["text"], "The finish reason was length.")
                self.assertEqual(logged[0]["lang"], "es")
            finally:
                family.close()

    def test_a_push_on_the_chat_channel_in_each_parents_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            people = {**PEOPLE_ES, "ceci": {**PEOPLE_ES["ceci"], "lang": "en"}}
            family = Family(tmp, at(30, 11, 0), extra={"people": people}, plugins=())
            try:
                from parenting_agent.agent.people import People
                family.agent.people = People(people)
                family.agent.bus.publish("reply", channel="telegram", chat_id=GONZA, person="gonza", proactive=True,
                                         text="Plan de esta noche. For Parent A: on duty with the bottle at 02:30.")
                self.assertEqual(family.sent_to(GONZA), ["Plan de esta noche."])
                family.agent.bus.publish("reply", channel="telegram", chat_id=CECI, proactive=True,
                                         text="Tonight's plan. Parent B sleeps. Muse wrote this plan.")
                self.assertEqual(family.sent_to(CECI), ["Tonight's plan. Ceci sleeps."])
                where = {e["where"] for e in family.agent.bus.history if e["kind"] == "final_guard"}
                self.assertEqual(where, {"channel:telegram"})
            finally:
                family.close()

    def test_a_red_flag_line_is_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 11, 0), extra={"people": PEOPLE_ES}, plugins=())
            try:
                family.say(GONZA, "Test: está azul y no respira bien.")
                self.assertIn("911", family.sent_to(GONZA)[0])
                self.assertFalse([e for e in family.agent.bus.history if e["kind"] == "final_guard"])
            finally:
                family.close()

    def test_the_families_bot_logs_why_never_the_familys_words(self):
        from tests.test_families import family_of, make, onboard

        class Leaky:
            name, model, destination = "scripted", "test", "inference.baseten.co"

            def step(self, system, transcript, tools):
                return brain_mod.Reply("Here is what the log says. Muse hit the finish reason.",
                                       usage={"input_tokens": 10, "output_tokens": 5})

        app = make(self, brain=Leaky())
        onboard(app, "111")
        replies = app.handle("111", "111", "hello there")
        self.assertEqual(" ".join(t for _, t in replies), "Here is what the log says.")
        family = app.family(family_of(app, "111"))
        logged = [e for e in family.bus.history if e["kind"] == "final_guard"]
        self.assertEqual(logged[-1]["removed"], [{"why": "internal: finish reason", "chars": len("Muse hit the finish reason.")}])
        self.assertNotIn("sent", logged[-1])

    def test_the_demo_keeps_its_simulated_parents_names(self):
        from parenting_agent.demo.app import DemoAgent
        agent = DemoAgent.__new__(DemoAgent)
        agent.page_lang, agent.turn_lang = "en", "en"
        self.assertEqual(final_guard.guard("Parent B is up next.", "en", agent.guard_names()).text, "Parent B is up next.")
        agent.turn_lang = "es"
        self.assertEqual(final_guard.guard("Le toca a Parent B.", "es", agent.guard_names()).text, "Le toca a Persona B.")
        self.assertTrue(DemoAgent.guard_models_ok, "the demo names Muse Spark Open on purpose")
        self.assertEqual(final_guard.guard("Muse kept the night rota.", "en", models_ok=True).text, "Muse kept the night rota.")
        self.assertEqual(final_guard.guard("Hola. Muse kept the night rota.", "es").text, "Hola.")

    def test_an_approval_ask_names_the_call_in_plain_words(self):
        from parenting_agent.agent.loop import describe_call
        self.assertEqual(describe_call({"name": "call_partner", "arguments": {"text": "vení"}}), 'call partner "vení"')
        line = "Espero tu sí: call partner \"vení\". Respondé sí en los próximos 3 minutos para hacerlo."
        self.assertEqual(final_guard.guard(line, "es").text, line)


class NoToolReportOnTheLens(unittest.TestCase):
    """Live Oct 31 (results/glasses-live-sam3): "changing time" was answered "Nothing was sent. I only did this: start
    changing table." It was spoken and stayed on the lens. "Let me know when you are done" was read as a claim that
    the agent told someone, and the honest line named the tool that ran."""
    LIVE = "Nothing was sent. I only did this: start changing table."

    def test_the_guard_drops_the_tool_report_and_close_variants(self):
        cases = [
            (self.LIVE, "en", "Nothing was sent."),
            ("Nothing was sent. I only did this: start_changing_table.", "en", "Nothing was sent."),
            ("Nothing was sent. I only did this: dim lights, start changing table.", "en", "Nothing was sent."),
            ("Nothing was sent. I just did this: start changing table", "en", "Nothing was sent."),
            ("I only did: start changing table. Watching now.", "en", "Watching now."),
            ("Watching the table. Tools run: start changing table.", "en", "Watching the table."),
            ("Todavía no mandé nada. Solo hice esto: start changing table.", "es", "Todavía no mandé nada."),
            ("Todavía no mandé nada. Sólo hice esto: empezar cambiador.", "es", "Todavía no mandé nada."),
        ]
        for text, lang, want in cases:
            result = final_guard.guard(text, lang)
            self.assertEqual(result.text, want, text)
            self.assertIn("internal: tool report", [r["why"] for r in result.removed], text)

    def test_plain_did_and_done_lines_stay(self):
        for text in ("I did the bottle at 3, she took 90 ml.", "Done: the lights are dim.", "I only did the left side."):
            self.assertEqual(final_guard.guard(text, "en").text, text)

    def test_let_me_know_is_a_request_to_the_parent_not_a_claim(self):
        self.assertEqual(rules.unmet_claims("Watching the changing table. Let me know when you're done.", {"start_changing_table"}),
                         set())
        self.assertEqual(rules.unmet_claims("Watching. Let us know when it's done.", set()), set())
        self.assertEqual(rules.unmet_claims("I let your partner know.", set()), {"let your partner know"})
        self.assertEqual(rules.unmet_claims("I let Ceci know.", set()), {"let ceci know"})

    def agent(self, *plans):
        from parenting_agent.agent.tools import Tool, schema
        from test_redteam_r2 import family
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        agent, _ = family(ScriptedBrain(*plans), tmp.name)
        self.addCleanup(agent.close)
        agent.tools.add(Tool("start_changing_table", "Start watching the changing table.", schema({}),
                             lambda: "watching the changing table"))
        agent.tools.allowed.add("start_changing_table")
        return agent

    def reply_to(self, agent, text):
        from test_redteam_r2 import replies, say
        say(agent, text)
        return replies(agent)[-1]

    def test_changing_time_answered_with_let_me_know_goes_out(self):
        from test_redteam_r1 import call
        agent = self.agent([[call("start_changing_table")], "Watching the changing table. Let me know when you're done."])
        self.assertEqual(self.reply_to(agent, "changing time"), "Watching the changing table. Let me know when you're done.")
        self.assertFalse([e for e in agent.bus.history if e["kind"] == "guard" and e["status"] == "claimed_action"])

    def test_a_false_claim_after_a_tool_ran_says_what_it_did_never_its_name(self):
        from test_redteam_r1 import call
        agent = self.agent([[call("start_changing_table")], "Watching. I told your partner."], ["I told your partner."])
        reply = self.reply_to(agent, "changing time")
        self.assertEqual(reply, "Nothing was sent. Watching the changing table.")
        self.assertNotIn("start changing table", reply.lower())
        self.assertNotIn("only did", reply.lower())

    def test_in_spanish_the_english_tool_answer_is_left_out(self):
        from parenting_agent.agent.loop import did_lines
        self.assertEqual(did_lines({"start_changing_table": "watching the changing table"}, "es"), [])
        self.assertEqual(did_lines({"start_changing_table": "watching the changing table"}, "en"),
                         ["Watching the changing table."])
        self.assertEqual(did_lines({"x": {"id": 3}, "y": "ran dim_lights on light.nursery"}, "en"), [])


if __name__ == "__main__":
    unittest.main()
