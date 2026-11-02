"""The family agent as one always-on first-month assistant (Oct 30, the end-to-end day, results/e2e-day/).

Offline: fake Telegram, fixed logs and clocks. Each test is one thing the end-to-end day found.
"""
import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

from parenting_agent import baby_phase
from parenting_agent.channels import morning
from parenting_agent.channels.push import in_lang
from parenting_agent.day_engine import DayEnginePlugin, HouseReader
from parenting_agent.house_brain import HouseBrain, MuseClient, compact, fixed_explanation, text_ok
from parenting_agent.prep import Prep
from parenting_agent.rhythm import log as rhythm_log
from parenting_agent.rhythm.engine import RhythmPlugin
from parenting_agent import sitter
from tests.test_family_push import CECI, ENV, GONZA, PEOPLE, Family, at
from tests.test_home_automations import Clock, ListLog

PEOPLE_ES = {k: {**v, "lang": "es"} for k, v in PEOPLE.items()}


def feeds(*times):
    return [{"kind": "feeding", "start": t.isoformat(), "end": (t + datetime.timedelta(minutes=15)).isoformat(),
             "ref": f"feeding#{i}"} for i, t in enumerate(times)]


class Language(unittest.TestCase):
    def test_a_push_reaches_each_parent_in_their_language(self):
        event = {"text": "Next feed", "texts": {"en": "Next feed", "es": "Próxima toma"}}
        self.assertEqual(in_lang(event, "es"), "Próxima toma")
        self.assertEqual(in_lang(event, "en"), "Next feed")
        self.assertEqual(in_lang({"text": "Only English"}, "es"), "Only English")

    def test_family_lang_is_set_only_when_everyone_agrees(self):
        from parenting_agent.agent.people import People
        self.assertEqual(People(PEOPLE_ES).family_lang(), "es")
        self.assertIsNone(People(PEOPLE).family_lang())


class NextFeed(unittest.TestCase):
    def family(self, tmp, now, rows, extra=None):
        family = Family(tmp, now, plugins=("push",), extra={"people": PEOPLE_ES, **(extra or {})})
        family.agent.people = __import__("parenting_agent.agent.people", fromlist=["People"]).People(PEOPLE_ES)
        family.push.people = family.agent.people
        rhythm = RhythmPlugin(family.agent, family.config, log=ListLog(rows), clock=family.clock)
        family.agent.plugins.insert(1, rhythm)
        return family, rhythm

    def test_one_reminder_per_feed_by_day_to_both_in_spanish(self):
        rows = feeds(at(29, 8, 0), at(29, 10, 45), at(29, 13, 30))
        with tempfile.TemporaryDirectory() as tmp:
            family, rhythm = self.family(tmp, at(29, 16, 0), rows)
            try:
                self.assertEqual(rhythm.tick(at(29, 15, 50)), [])  # 25 min before 16:15, outside the 20 min lead
                self.assertEqual(len(rhythm.tick(at(29, 16, 0))), 1)
                self.assertEqual(rhythm.tick(at(29, 16, 5)), [])  # the same feed is never told twice
                for chat in (GONZA, CECI):
                    sent = family.sent_to(chat)
                    self.assertEqual(len(sent), 1)
                    self.assertTrue(sent[0].startswith("Próxima toma en unos 15 min, cerca de las 16:15"), sent[0])
            finally:
                family.close()

    def test_no_guess_at_night_and_nothing_before_the_birth(self):
        rows = feeds(at(29, 19, 0), at(29, 21, 0), at(29, 23, 0))
        with tempfile.TemporaryDirectory() as tmp:
            family, rhythm = self.family(tmp, at(30, 0, 50), rows)
            try:
                self.assertEqual(rhythm.tick(at(30, 0, 50)), [])  # 01:00 is night: the night feed's job
            finally:
                family.close()
        rows = feeds(at(29, 8, 0), at(29, 10, 45), at(29, 13, 30))
        with tempfile.TemporaryDirectory() as tmp:
            family, rhythm = self.family(tmp, at(29, 16, 0), rows, extra={"baby": {"born": False}})
            try:
                self.assertEqual(rhythm.tick(at(29, 16, 0)), [])
            finally:
                family.close()


class BeforeTheBirth(unittest.TestCase):
    def test_phase_is_explicit(self):
        self.assertTrue(baby_phase.born({}))
        self.assertFalse(baby_phase.born({"baby": {"born": False}}))
        self.assertEqual(baby_phase.phase({}), None)
        self.assertEqual(baby_phase.phase({"baby": {"born": True}}), "born")

    def test_stale_test_log_sends_nothing_before_the_birth(self):
        """Oct 30: "a feed was expected 1753 min ago" in the morning brief, from a test log that stopped on Oct 29."""
        stale = feeds(at(28, 20, 0), at(28, 23, 0), at(29, 1, 0))
        stale.append({"kind": "sleep", "start": at(30, 6, 0).isoformat(), "end": None, "ref": "timers/1"})
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 7, 30), rows=stale, plugins=("night", "push"),
                            extra={"baby": {"born": False}, "people": PEOPLE_ES})
            try:
                engine = DayEnginePlugin(family.agent, family.config, client=None, log=ListLog(stale), clock=family.clock)
                engine.stopped.set = lambda: None
                with engine.lock:
                    engine.engine.tick(engine.log.entries() if engine.born else [], at(30, 7, 30), engine.house(at(30, 7, 30)))
                kinds = [e for e in family.agent.bus.history if e["kind"] == "routine"]
                self.assertNotIn("nap_mode", [e["name"] for e in kinds])
                brief = next(e for e in family.agent.bus.history if e["kind"] == "notify" and e["routine"] == "morning_brief")
                self.assertNotIn("expected", brief["text"])
                self.assertEqual(brief["facts"]["night"]["feeds"], 0)
                self.assertIsNone(family.night.tick(at(30, 2, 0)))
                family.say(GONZA, "se despertó")
                self.assertEqual([e for e in family.agent.bus.history if e["kind"] == "night_feed"], [])
            finally:
                family.close()

    def test_before_the_birth_one_morning_message_with_prep_and_no_rota(self):
        stale = feeds(at(28, 20, 0), at(28, 23, 0), at(29, 1, 0)) + [
            {"kind": "note", "time": at(29, 1, 0).isoformat(), "note": "Night wake-up handled by Gonza", "ref": "n1"}]
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 7, 30), rows=stale, plugins=("night", "push"),
                            extra={"baby": {"born": False}, "people": PEOPLE_ES, "family_push": {"morning": True}})
            try:
                from parenting_agent.agent.people import People
                family.agent.people = family.push.people = People(PEOPLE_ES)
                family.push.s["morning"] = True
                prep = Prep(family.agent, family.config, clock=family.clock)
                engine = DayEnginePlugin(family.agent, family.config, client=None, log=ListLog(stale), clock=family.clock)
                family.agent.plugins += [prep, engine]
                with engine.lock:
                    engine.engine.tick([], at(30, 7, 30), engine.house(at(30, 7, 30)))
                for chat in (GONZA, CECI):
                    sent = family.sent_to(chat)
                    self.assertEqual(len(sent), 1, sent)
                    self.assertIn("Antes de que llegue", sent[0])
                    self.assertNotIn("te toca", sent[0])
                    self.assertNotIn("Anoche", sent[0])
            finally:
                family.close()

    def test_prep_leads_before_and_leaves_the_morning_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 8, 0), plugins=(), extra={"baby": {"born": False}})
            try:
                prep = Prep(family.agent, family.config, clock=family.clock)
                self.assertTrue(prep.cfg["nudge"]["enabled"])
                self.assertIn(baby_phase.NOT_BORN_NOTE, family.agent.prompt_notes)
            finally:
                family.close()
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 8, 0), plugins=(), extra={"baby": {"born": True}})
            try:
                prep = Prep(family.agent, family.config, clock=family.clock)
                self.assertFalse(prep.cfg["nudge"]["enabled"])
                self.assertNotIn(baby_phase.NOT_BORN_NOTE, family.agent.prompt_notes)
            finally:
                family.close()


class NightHandover(unittest.TestCase):
    def test_ceci_asks_to_sleep_gonza_takes_the_night_and_is_told_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(29, 20, 0), plugins=("night", "push"), extra={"people": PEOPLE_ES})
            try:
                family.agent.people = __import__("parenting_agent.agent.people", fromlist=["People"]).People(PEOPLE_ES)
                family.push.people = family.agent.people
                family.night.people = family.agent.people
                family.agent.bus.publish("message", channel="telegram", text="Esta noche necesito dormir.",
                                         chat_id=CECI, person="ceci")
                family.agent.bus.publish("message", channel="telegram", text="Necesito dormir, de verdad.",
                                         chat_id=CECI, person="ceci")
                self.assertEqual(family.night.on_duty(at(30, 2, 0)), "Parent A")
                told = family.sent_to(GONZA)
                self.assertEqual(len(told), 1)
                self.assertIn("Ceci pidió dormir esta noche", told[0])
                self.assertEqual(family.sent_to(CECI), [])
                self.assertEqual(family.night.on_duty(at(31, 2, 0)), family.night.rota_only(at(31, 2, 0)))
            finally:
                family.close()

    def test_the_parent_who_says_he_is_up_gets_no_push(self):
        rows = feeds(at(29, 19, 0), at(29, 22, 0))
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 1, 0), rows=rows, plugins=("night", "push"), extra={"people": PEOPLE_ES})
            try:
                duty = family.night.people.person(family.night.on_duty(at(30, 1, 0)))
                chat = GONZA if duty == "gonza" else CECI
                family.agent.bus.publish("message", channel="telegram", text="Se despertó", chat_id=chat, person=duty)
                steps = [e["step"] for e in family.agent.bus.history if e["kind"] == "night_feed"]
                self.assertIn("prepare", steps)
                self.assertNotIn("push", steps)
                self.assertEqual(family.sent_to(GONZA) + family.sent_to(CECI), [])
            finally:
                family.close()

    def test_a_cry_pushes_the_parent_on_duty_in_spanish(self):
        rows = feeds(at(29, 19, 0), at(29, 22, 0))
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 1, 0), rows=rows, plugins=("night", "push"), extra={"people": PEOPLE_ES})
            try:
                family.agent.people = __import__("parenting_agent.agent.people", fromlist=["People"]).People(PEOPLE_ES)
                family.push.people = family.agent.people
                family.agent.bus.publish("sound", label="cry", phase="start")
                sent = family.sent_to(GONZA) + family.sent_to(CECI)
                self.assertEqual(len(sent), 1)
                self.assertTrue(sent[0].startswith("Se despertó, se oyó un llanto."), sent[0])
                self.assertNotIn("Parent", sent[0])
            finally:
                family.close()


class StockTalk(unittest.TestCase):
    def test_a_count_of_diapers_at_home_is_no_diaper_change(self):
        from parenting_agent.agent import rules
        self.assertIsNone(rules.log_kind("Tenemos 26 pañales en casa."))
        self.assertIsNone(rules.log_kind("Quedan pocos pañales, agregalos a la lista de compras."))
        self.assertIsNone(rules.log_kind("We have 30 diapers left"))
        self.assertEqual(rules.log_kind("Pañal sucio, quedan 10 pañales."), "diaper")
        self.assertEqual(rules.log_kind("Cambié 2 pañales"), "diaper")

    def test_a_question_passed_on_is_a_question(self):
        from parenting_agent.agent import rules
        self.assertTrue(rules.is_question("Mi mamá pregunta cuándo comió por última vez."))
        self.assertIsNone(rules.log_kind("Mi mamá pregunta cuándo comió por última vez."))
        self.assertEqual(rules.log_kind("Le di 90 ml"), "feeding")


class WhoGotUp(unittest.TestCase):
    def test_a_named_note_counts_for_the_rota_label_in_the_morning(self):
        from parenting_agent.rhythm import patterns
        rows = feeds(at(29, 22, 30), at(30, 2, 50)) + [
            {"kind": "note", "time": at(29, 22, 20).isoformat(), "note": "Night wake-up handled by Gonza", "ref": "n1"},
            {"kind": "note", "time": at(30, 2, 50).isoformat(), "note": "Night wake-up handled by Gonza", "ref": "n2"}]
        tz = datetime.timezone(datetime.timedelta(hours=-3))
        row = patterns.night_summary(rows, at(30, 7, 30), tz, ["Parent A", "Parent B"],
                                     aliases={"gonza": "Parent A", "ceci": "Parent B"})
        self.assertEqual(row["wakeups"], {"Parent A": 2, "Parent B": 0})
        self.assertEqual(row["on_duty"], "Parent B")

    def test_each_night_wake_up_is_noted_once_with_who_took_it(self):
        rows = feeds(at(29, 19, 0), at(29, 22, 0))
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 1, 0), rows=rows, plugins=("night", "push"), extra={"people": PEOPLE_ES})
            try:
                family.agent.bus.publish("message", channel="telegram", text="Se despertó", chat_id=GONZA, person="gonza")
                family.agent.bus.publish("sound", label="cry", phase="start")
                notes = [e["details"]["text"] for e in family.agent.baby_log.entries("note")]
                self.assertEqual(notes, ["Night wake-up handled by Gonza"])
                handled = [e for e in family.agent.bus.history if e["kind"] == "night_feed" and e["step"] == "handled"]
                self.assertEqual(len(handled), 1)
            finally:
                family.close()


class MorningExplanation(unittest.TestCase):
    def test_a_cut_off_plan_never_reaches_the_parents(self):
        """Oct 30 10:25: "The logged reason was invalid answer not a JSON object with finish reason length"."""
        self.assertFalse(text_ok("The logged reason was invalid answer not a JSON object with finish reason length."))
        self.assertFalse(text_ok("At 10:24 Muse was not used and fixed routines ran."))
        self.assertTrue(text_ok("At 02:50 the house got ready for a night feed, the light only written down."))
        line = compact({"kind": "house_brain_fallback", "at": "2026-10-30T10:24:58-03:00",
                        "reason": "invalid answer: not a JSON object (finish_reason length)"})
        self.assertNotIn("reason", line)
        self.assertNotIn("finish", json.dumps(line))
        self.assertNotIn("Muse", fixed_explanation([line]))

    def test_muse_is_asked_again_once_when_cut_off(self):
        answers = [{"choices": [{"finish_reason": "length", "message": {"content": "{\"a\": "}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 6000}},
                   {"choices": [{"finish_reason": "stop", "message": {"content": "{\"telegram\": \"ok\", \"echo\": \"ok\"}"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 50}}]
        calls = []

        def post(url, headers, body, timeout):
            calls.append(body)
            return answers[len(calls) - 1]

        with mock.patch.dict(os.environ, {"BASETEN_API_KEY": "x"}):
            answer, meta = MuseClient(post=post).ask("s", "t", {"type": "object"})
        self.assertEqual(answer["telegram"], "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(meta["output_tokens"], 6050)

    def test_the_house_line_is_for_a_real_night_in_spanish(self):
        explain = {"text": "Overnight the house got ready for 1 night feed.", "facts": {"night_feeds": 1, "real": 0,
                                                                                         "events": 4}}
        text = morning.compose("es", "Gonza", "Parent A", None, explain, (), None, "Parent A")
        self.assertIn("La casa de noche: Se preparó para 1 toma nocturna, todo solo anotado (prueba en seco).", text)
        self.assertNotIn("Overnight", text)
        quiet = {"text": "At 10:24 the house kept its usual routines.", "facts": {"night_feeds": 0, "real": 0, "events": 1}}
        self.assertNotIn("La casa", morning.compose("es", "Gonza", "Parent A", None, quiet, (), None, "Parent A"))
        self.assertNotIn("The house", morning.compose("en", "Gonza", "Parent A", None, quiet, (), None, "Parent A"))

    def test_tonights_plan_in_spanish_names_who_asked_to_sleep_wins(self):
        sent = []

        class Bus:
            def publish(self, kind, **fields):
                sent.append({"kind": kind, **fields})
                return fields

            def subscribe(self, *a, **k):
                pass

        class Night:
            plan = None

            def on_duty(self, now):
                return "Parent A"

        brain = HouseBrain(Bus(), None, {"lang": "es"}, night_feed=Night())
        now = at(29, 20, 30)
        plan = {"on_duty": "Parent B", "bottle_prewarm": [{"start": at(30, 1, 10), "why": "x"}], "door_quiet": [],
                "floor_clean": [], "white_noise_boost": [], "summary": "Muse summary in English",
                "why_changed": "English why", "messages": [{"to": "Parent B", "text": "English line"}]}
        brain.announce(plan, "bedtime", now)
        tonight = next(e for e in sent if e.get("routine") == "tonight")
        self.assertEqual(tonight["texts"]["es"], "Plan de esta noche. De turno: Parent A.\nCalentador de mamadera (solo "
                                                 "agua) a las 01:10. La luz espera a que se despierte.")
        self.assertNotIn("replan", [e.get("routine") for e in sent])
        self.assertTrue(next(e for e in sent if e.get("routine") == "plan_message")["quiet"])

    def test_tonights_plan_names_the_fixed_rule_pre_warm_time_when_muse_times_fail(self):
        sent = []

        class Bus:
            def publish(self, kind, **fields):
                sent.append({"kind": kind, **fields})
                return fields

            def subscribe(self, *a, **k):
                pass

        brain = HouseBrain(Bus(), None, {"lang": "es"})
        now = at(29, 20, 30)
        seen = feeds(at(29, 14, 0), at(29, 17, 0), at(29, 20, 0))
        plan = {"on_duty": "Parent B", "bottle_prewarm": None, "door_quiet": [], "floor_clean": [],
                "white_noise_boost": [], "summary": "", "why_changed": "", "messages": []}
        brain.announce(plan, "bedtime", now, seen)
        tonight = next(e for e in sent if e.get("routine") == "tonight")
        self.assertIn("the fixed rhythm rule warms the bottle at 22:50, 10 min before the night feed guessed around "
                      "23:00", tonight["texts"]["en"])
        self.assertIn("La regla fija calienta la mamadera (solo agua) a las 22:50, 10 min antes de la toma de noche "
                      "estimada cerca de las 23:00", tonight["texts"]["es"])
        sent.clear()
        brain.announce(plan, "bedtime", now, ())
        tonight = next(e for e in sent if e.get("routine") == "tonight")
        self.assertIn("no night feed is guessed yet", tonight["texts"]["en"])
        self.assertIn("todavía no hay toma de noche estimada", tonight["texts"]["es"])


class Doorbell(unittest.TestCase):
    def test_no_door_sensor_means_no_doorbell(self):
        class HA:
            def state(self, entity):
                return "on"

            def attributes(self, entity):
                return {}

            def response(self, *a, **k):
                raise ValueError

            def calendar_events(self, *a):
                return []

        reader = HouseReader(HA(), datetime.timezone(datetime.timedelta(hours=-3)), door_sensors=[])
        reader.read(at(29, 13, 0))
        self.assertEqual(reader.read(at(29, 13, 1))["door"], [])
        backyard = HouseReader(HA(), datetime.timezone(datetime.timedelta(hours=-3)))
        backyard.door_was = {s: False for s in backyard.door_sensors}
        self.assertEqual(len(backyard.read(at(29, 13, 1))["door"]), 1)


class Supplies(unittest.TestCase):
    def test_a_parent_sets_the_stock_and_it_lands_in_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(29, 6, 20), plugins=())
            try:
                engine = DayEnginePlugin(family.agent, family.config, client=None, log=ListLog([]), clock=family.clock)
                said = engine.set_stock("diapers", 26)
                self.assertIn("diapers 26", said)
                note = family.agent.baby_log.entries("note")[-1]
                self.assertEqual(note["details"]["text"], "Stock: diapers 26")
                self.assertIn("unknown item", engine.set_stock("pacifiers", 2))
                self.assertIn("already kept", engine.set_stock("diapers", 26))  # the brain asking again writes nothing
                self.assertEqual(len(family.agent.baby_log.entries("note")), 1)
                engine.set_stock("diapers", 80)
                self.assertEqual(family.agent.baby_log.entries("note")[-1]["details"]["text"], "Stock: diapers 80")
            finally:
                family.close()


class OpenSleep(unittest.TestCase):
    def test_an_open_sleep_timer_is_a_sleep_going_on(self):
        log = rhythm_log.BabyBuddyLog("http://bb", "t", "Test")
        pages = {"/api/timers/?child=1&limit=50": {"results": [{"id": 7, "name": "sleep", "start": "2026-10-29T06:35:00-03:00"},
                                                               {"id": 8, "name": "tummy", "start": "2026-10-29T06:00:00-03:00"}]}}
        log._get = lambda path: pages.get(path, {"results": []})
        log.child_id = lambda: 1
        rows = log.entries()
        self.assertEqual(rows, [{"kind": "sleep", "ref": "timers/7", "start": "2026-10-29T06:35:00-03:00", "end": None,
                                 "nap": None, "tags": []}])


class BabyName(unittest.TestCase):
    def test_after_the_birth_the_brain_knows_his_name_and_not_a_parent_name(self):
        from parenting_agent.agent.people import People
        note = baby_phase.born_note("Theo", People(PEOPLE_ES))
        self.assertEqual(note, "The baby is Theo. Gonza and Ceci are the parents: never call the baby by their names.")
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 8, 0), plugins=(), extra={"baby": {"born": True, "name": "Theo"}})
            try:
                Prep(family.agent, family.config, clock=family.clock)
                self.assertTrue(any(n.startswith("The baby is Theo.") for n in family.agent.prompt_notes))
            finally:
                family.close()


class SitterBrief(unittest.TestCase):
    def test_the_summary_counts_the_log_of_the_window_whoever_wrote_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(29, 16, 0), plugins=())
            try:
                log = family.agent.baby_log
                with mock.patch("parenting_agent.agent.memory.now", return_value=at(29, 15, 55).isoformat()):
                    log.add("feeding", {"amount_ml": 80, "method": "bottle"}, ts=at(29, 15, 55).isoformat())
                    log.add("diaper", {"solid": True}, ts=at(29, 16, 0).isoformat())
                session = sitter.GuestSession(family.agent.bus, log, None, "Mamá de Ceci", at(29, 15, 0), at(29, 18, 0),
                                              "brief", baby="Theo", clock=Clock(at(29, 18, 0)))
                text = session.summary_es()
                self.assertIn("Mamá de Ceci cuidó a Theo de 15:00 a 18:00.", text)
                self.assertIn("En el registro de esas horas: 1 toma (80 ml), 1 pañal.", text)
            finally:
                family.close()

    def test_spanish_brief_and_no_made_up_phone(self):
        notes = sitter.load_notes("/nonexistent/family-notes.json")
        self.assertEqual(notes["contacts"], [])
        rows = [{"kind": "feeding", "start": at(29, 13, 10).isoformat(), "end": at(29, 13, 25).isoformat(),
                 "method": "bottle", "type": "formula", "amount": 90, "ref": "f1"},
                {"kind": "change", "time": at(29, 13, 27).isoformat(), "wet": True, "solid": False, "ref": "c1"}]
        made = sitter.brief(rows, at(29, 14, 0), "Abuela", at(29, 15, 0), at(29, 18, 0),
                            datetime.timezone(datetime.timedelta(hours=-3)), notes, "es")
        self.assertTrue(made["text"].startswith("Hola Abuela, gracias por cuidar a Theo de 15:00 a 18:00."))
        self.assertIn("Última toma a las 13:10, mamadera de fórmula, 90 ml.", made["text"])
        self.assertNotIn("XXX", made["text"])


if __name__ == "__main__":
    unittest.main()
