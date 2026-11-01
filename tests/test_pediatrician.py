"""The pediatrician visit summary (pediatrician.py): visits, questions, the summary, its two pushes, the glasses and the Echo.

Offline: a fixed log, a fixed clock, a fake Muse and a fake Telegram messenger. Chat ids are made up, nothing is sent.
"""
import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

from parenting_agent import hud_cards
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.channels.push import FamilyPush
from parenting_agent.channels.telegram import Telegram
from parenting_agent.pediatrician import ADVICE, Pediatrician, aligned, facts, full_days, parse_when
from parenting_agent.voice_bridge import VoiceBridge
from tests.test_channels import FakeMessenger

TZ = datetime.timezone(datetime.timedelta(hours=-3))
GONZA, CECI = "5001", "5002"
ENV = {"TELEGRAM_CHAT_ID": GONZA, "TELEGRAM_CECI_CHAT_ID": CECI}
PEOPLE = {"gonza": {"name": "Gonza", "rota": "Parent A", "chat_ids_env": "TELEGRAM_CHAT_ID", "lang": "es"},
          "ceci": {"name": "Ceci", "rota": "Parent B", "chat_ids_env": "TELEGRAM_CECI_CHAT_ID", "lang": "es"}}


def at(day, hh, mm=0, month=10):
    return datetime.datetime(2026, month, day, hh, mm, tzinfo=TZ)


def iso(moment):
    return moment.isoformat(timespec="seconds")


def week(first=20, last=27):
    """A fixed first week: each day 8 feeds (4 left breast, 2 right, 2 bottles of 60 and 90 ml), 7 diapers (6 wet, 3
    dirty, so 2 both), 3 sleeps of 4 h 20 min, a bath and a night note. One weight note and two notes worth keeping."""
    rows = []
    for day in range(first, last + 1):
        for i, hour in enumerate((1, 4, 7, 10, 13, 16, 19, 22)):
            method = ("left breast", "left breast", "right breast", "bottle", "left breast", "right breast",
                      "left breast", "bottle")[i]
            details = {"method": method, "type": "formula" if method == "bottle" else "breast milk"}
            if method == "bottle":
                details["amount_ml"] = 60.0 if hour == 10 else 90.0
            rows.append({"kind": "feeding", "ts": iso(at(day, hour, 20)), "details": details})
        for i, hour in enumerate((2, 5, 8, 11, 14, 17, 20)):
            rows.append({"kind": "diaper", "ts": iso(at(day, hour, 40)),
                         "details": {"wet": i != 6, "solid": i in (0, 3, 6), "color": "yellow" if i == 3 else None}})
        for hour in (6, 14, 22):
            end = at(day, hour) if hour < 22 else at(day, 23, 59)
            rows.append({"kind": "sleep", "ts": iso(end), "details": {"duration_min": 260 if hour < 22 else 260}})
        rows.append({"kind": "bath", "ts": iso(at(day, 18, 30)), "details": {"text": "Bath"}})
        rows.append({"kind": "note", "ts": iso(at(day, 3, 0)), "details": {"text": "Night wake-up handled by Parent A"}})
    rows.append({"kind": "note", "ts": iso(at(22, 15, 0)), "details": {"text": "Regurgitó un poco después de la toma de las 13"}})
    rows.append({"kind": "note", "ts": iso(at(24, 11, 0)), "details": {"text": "Lo pesamos en la farmacia: pesó 3,62 kg"}})
    rows.append({"kind": "note", "ts": iso(at(23, 9, 0)), "details": {"text": "Stock: diapers 26"}})
    rows.append({"kind": "diaper", "ts": iso(at(25, 9, 0)), "details": {"wet": False, "solid": True, "color": "green"}})
    return sorted(rows, key=lambda r: r["ts"])


class FixedLog:
    """The baby log as the agent reads it: entries() filtered by since, add() appends a note."""

    def __init__(self, rows, clock=None):
        self.rows, self.clock = list(rows), clock

    def entries(self, kind=None, since=None, limit=50):
        out = [r for r in self.rows if (kind is None or r["kind"] == kind)
               and (since is None or datetime.datetime.fromisoformat(r["ts"]) >= datetime.datetime.fromisoformat(since))]
        return out[-limit:]

    def add(self, kind, details, ts=None):
        entry = {"kind": kind, "ts": ts or iso(self.clock() if self.clock else datetime.datetime.now(TZ)), "details": details}
        self.rows.append(entry)
        return entry


class FakeMuse:
    def __init__(self, answers=None, error=None):
        self.answers, self.error, self.asked = list(answers or []), error, []

    def ask(self, system, text, schema, name="plan"):
        self.asked.append(text)
        if self.error:
            raise self.error
        return self.answers.pop(0), {"usd": 0.004, "model": "muse", "host": "inference.baseten.co", "seconds": 1.2,
                                     "input_tokens": 300, "output_tokens": 60}


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


class Family:
    """The family agent with Telegram for both parents, the family push and the pediatrician plug-in."""

    def __init__(self, tmp, now, rows=(), muse=None, people=PEOPLE, extra=None):
        self.env = mock.patch.dict(os.environ, ENV)
        self.env.start()
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "house": {},
                       "plugins": [], "people": people, "telegram": {"allowed_chat_ids_env": "TELEGRAM_CHAT_ID"},
                       "baby": {"born": True, "name": "Theo", "birth_date": "2026-10-19"}, **(extra or {})})
        self.config = config
        self.agent = build(config)
        self.clock = Clock(now)
        self.agent.baby_log = self.log = FixedLog(rows, self.clock)
        self.messenger = FakeMessenger()
        self.telegram = Telegram(self.agent, config, messenger=self.messenger)
        self.push = FamilyPush(self.agent, config, clock=self.clock)
        self.muse = muse or FakeMuse(error=RuntimeError("no Muse in this test"))
        self.pedi = Pediatrician(self.agent, config, clock=self.clock, muse=self.muse)
        self.agent.plugins = [self.telegram, self.push, self.pedi]

    def say(self, chat, text, channel="telegram"):
        person = self.telegram.person_of(chat)
        event = self.agent.bus.publish("message", channel=channel, text=text, chat_id=chat, person=person, voice=False)
        self.agent.current_event = event
        try:
            self.agent.handle(event)
        finally:
            self.agent.current_event = None
        return [e for e in self.agent.bus.history if e["kind"] == "reply"][-1]["text"]

    def sent_to(self, chat):
        return [text for c, text in self.messenger.sent if c == chat]

    def close(self):
        self.agent.close()
        self.env.stop()


def family(test, now, rows=(), **kw):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    fam = Family(tmp.name, now, rows, **kw)
    test.addCleanup(fam.close)
    return fam


class When(unittest.TestCase):
    NOW = at(28, 9, 0)  # a Wednesday

    def check(self, text, expected):
        self.assertEqual(parse_when(text, self.NOW)[0], expected, text)

    def test_the_ways_parents_say_it(self):
        self.check("turno con la pediatra el jueves 10:00", at(29, 10))
        self.check("control con la pediatra mañana a las 9", at(29, 9))
        self.check("pediatra el viernes a la mañana a las 9 y media", at(30, 9, 30))
        self.check("turno pediatra pasado mañana 15hs", at(30, 15))
        self.check("consulta con la pediatra el 6/11 a las 4", at(6, 16, month=11))
        self.check("control pediatra 6 de noviembre 8.45", at(6, 8, 45, month=11))
        self.check("pediatrician appointment Nov 6 at 3pm", at(6, 15, month=11))
        self.check("pediatrician visit tomorrow 10:30", at(29, 10, 30))
        self.check("turno con la pediatra hoy a las 17", at(28, 17))

    def test_the_same_weekday_is_next_week_once_its_time_passed(self):
        self.check("turno con la pediatra el miércoles 8:00", at(4, 8, month=11))
        self.check("turno con la pediatra el miércoles 11:00", at(28, 11))

    def test_what_is_missing_is_said(self):
        self.assertEqual(parse_when("turno con la pediatra el jueves", self.NOW), (None, "time"))
        self.assertEqual(parse_when("turno con la pediatra a las 10", self.NOW), (None, "day"))
        self.assertEqual(parse_when("turno el 31/2 a las 10", self.NOW), (None, "day"))

    def test_the_parents_words_come_back_with_their_accents(self):
        words, where = aligned("Preguntarle a la pediatra si ¿está bien que estornude?")
        start = words.index("si ")
        self.assertEqual("Preguntarle a la pediatra si ¿está bien que estornude?"[where[start]:], "si ¿está bien que estornude?")


class Numbers(unittest.TestCase):
    def test_the_week_in_numbers(self):
        found = facts(week(), at(19, 0), at(28, 9), TZ)
        self.assertEqual(found["days"], [datetime.date(2026, 10, d) for d in range(21, 27)])  # first and last day cut
        self.assertEqual(found["feeds"], {"mid": 8, "lo": 8, "hi": 8})
        self.assertEqual(found["sides"], {"left": 4 * 6, "right": 2 * 6, "bottle": 2 * 6})
        self.assertEqual(found["milks"], {"formula": 12})
        self.assertEqual(found["amount"], {"mid": 75, "lo": 60, "hi": 90})
        self.assertEqual(found["diapers"]["mid"], 7)
        self.assertEqual(found["wet"]["mid"], 6)
        self.assertEqual(found["dirty"]["mid"], 3)
        self.assertEqual(found["diapers"]["hi"], 8)  # Oct 25 has one more, the green one
        self.assertEqual(found["colors"], {"yellow": 8, "green": 1})
        self.assertEqual(found["sleep"]["mid"], 780)
        texts = [n["text"] for n in found["notes"]]
        self.assertEqual(texts, ["Regurgitó un poco después de la toma de las 13", "Lo pesamos en la farmacia: pesó 3,62 kg"])
        self.assertEqual((found["weight"]["value"], found["weight"]["unit"]), ("3.62", "kg"))

    def test_few_days_count_as_they_are(self):
        self.assertEqual(full_days([datetime.date(2026, 10, 20), datetime.date(2026, 10, 21)]),
                         [datetime.date(2026, 10, 20), datetime.date(2026, 10, 21)])


class Visits(unittest.TestCase):
    def test_a_visit_goes_in_the_appointments_and_says_when_the_summary_comes(self):
        fam = family(self, at(28, 9))
        reply = fam.say(GONZA, "Turno con la pediatra el jueves 10:00")
        self.assertIn("jueves 29/10 a las 10:00", reply)
        self.assertIn("Les mando a los dos el resumen para la pediatra el día antes a las 19:00", reply)
        self.assertIn("08:00", reply)
        with fam.agent.memory.lock:
            rows = fam.agent.memory.db.execute("select title, starts_at, cancelled from prep_appointments").fetchall()
        self.assertEqual(rows, [("Control con la pediatra", "2026-10-29T10:00-03:00", 0)])

    def test_who_goes_gets_it_alone(self):
        fam = family(self, at(28, 9))
        reply = fam.say(GONZA, "control con la pediatra el jueves a las 10, va Ceci")
        self.assertIn("va Ceci", reply)
        self.assertEqual(fam.pedi.upcoming()[0]["who"], "ceci")
        fam.say(CECI, "turno con la pediatra el viernes 11:00, voy yo")
        self.assertEqual(fam.pedi.upcoming()[1]["who"], "ceci")

    def test_no_time_asks_for_it_and_a_call_is_left_to_the_agent(self):
        fam = family(self, at(28, 9))
        self.assertIn("¿Qué día y a qué hora", fam.say(GONZA, "tenemos turno con la pediatra el jueves"))
        self.assertIsNone(fam.pedi.take({"person": "gonza"}, "voy a llamar a la pediatra"))
        self.assertEqual(fam.pedi.upcoming(), [])

    def test_next_and_cancel(self):
        fam = family(self, at(28, 9))
        fam.say(GONZA, "turno con la pediatra el jueves 10:00")
        self.assertIn("jueves 29/10 a las 10:00", fam.say(CECI, "¿Cuándo es el turno con la pediatra?"))
        self.assertIn("saqué el control", fam.say(CECI, "cancelá el turno con la pediatra"))
        self.assertEqual(fam.pedi.upcoming(), [])
        with fam.agent.memory.lock:
            self.assertEqual(fam.agent.memory.db.execute("select cancelled from prep_appointments").fetchone(), (1,))


class Questions(unittest.TestCase):
    def test_muse_tidies_the_question_and_its_words_are_checked(self):
        muse = FakeMuse([{"es": "¿Es normal que estornude tanto?", "en": "Is it normal that he sneezes so much?"}])
        fam = family(self, at(28, 9), muse=muse)
        reply = fam.say(CECI, "preguntarle a la pediatra si es normal que estornude tanto")
        self.assertIn("¿Es normal que estornude tanto?", reply)
        self.assertEqual(muse.asked, ["si es normal que estornude tanto"])
        self.assertEqual(fam.pedi.questions()[0]["en"], "Is it normal that he sneezes so much?")

    def test_muse_adding_advice_or_changing_a_number_is_dropped(self):
        muse = FakeMuse([{"es": "¿Es normal que tome 80 ml?", "en": "Should he drink 80 ml?"}])
        fam = family(self, at(28, 9), muse=muse)
        fam.say(GONZA, "preguntarle a la pediatra cuánto tiene que tomar si toma 90 ml")
        question = fam.pedi.questions()[0]
        self.assertEqual(question["es"], "¿Cuánto tiene que tomar si toma 90 ml?")  # the parent's words
        self.assertIsNone(question["en"])
        reasons = [e["why"] for e in fam.agent.bus.history if e.get("action") == "muse_rejected"]
        self.assertEqual(reasons, ["numbers changed", "numbers changed"])

    def test_muse_down_keeps_the_parents_words(self):
        fam = family(self, at(28, 9))
        reply = fam.say(GONZA, "Preguntarle a la pediatra: ¿cuándo le podemos cortar las uñas?")
        self.assertIn("¿Cuándo le podemos cortar las uñas?", reply)
        self.assertIn("Es la primera pregunta", reply)

    def test_list_close_and_close_all(self):
        fam = family(self, at(28, 9))
        fam.say(GONZA, "preguntarle a la pediatra por los gases")
        fam.say(CECI, "preguntarle a la pediatra si puede salir a pasear")
        listed = fam.say(CECI, "¿qué preguntas para la pediatra tenemos?")
        self.assertIn("1. ¿Por los gases?", listed)
        self.assertIn("2. ¿Puede salir a pasear?", listed)
        self.assertIn("cerré la pregunta 1", fam.say(CECI, "cerrar pregunta 1"))
        self.assertEqual(len(fam.pedi.questions()), 1)
        self.assertIn("No hay una pregunta 5", fam.say(CECI, "cerrá pregunta 5"))
        self.assertIn("cerré las 1 preguntas", fam.say(CECI, "cerrar todas las preguntas"))
        self.assertEqual(fam.pedi.questions(), [])

    def test_a_red_flag_is_never_taken_here(self):
        fam = family(self, at(28, 9))
        self.assertIsNone(fam.pedi.take({"person": "ceci"}, "preguntarle a la pediatra si es normal que tenga fiebre"))
        self.assertIsNone(fam.pedi.take({"person": "ceci"}, "la pediatra dijo que si no respira llamemos al 911"))
        reply = fam.say(CECI, "preguntarle a la pediatra si es normal que tenga fiebre")
        self.assertIn("pediatra", reply)
        self.assertEqual(fam.pedi.questions(), [])

    def test_a_code_is_never_kept(self):
        fam = family(self, at(28, 9))
        self.assertIn("código", fam.say(GONZA, "preguntarle a la pediatra, la clave del portal es 448812"))
        self.assertEqual(fam.pedi.questions(), [])


class Summary(unittest.TestCase):
    def test_since_birth_with_the_numbers_notes_weight_and_questions(self):
        fam = family(self, at(28, 9), week())
        fam.say(GONZA, "preguntarle a la pediatra si puede salir a pasear")
        text = fam.say(CECI, "resumen para la pediatra")
        lines = text.splitlines()
        self.assertEqual(lines[0], "Resumen para la pediatra.")
        self.assertEqual(lines[1], "Por día: 8 tomas, 7 pañales, 13 h de sueño.")
        for line in ("Desde el nacimiento (19/10).", "Los números por día son de 6 días completos, del 21/10 al 26/10.",
                     "Tomas: por lo general 8 por día (entre 8 y 8).",
                     "Pecho en esos días: izquierdo 24, derecho 12.",
                     "Mamadera en esos días: 12 (fórmula 12), por lo general 75 ml (entre 60 y 90 ml).",
                     "Pañales: por lo general 7 por día (entre 7 y 8): 6 mojados y 3 sucios por día.",
                     "Un pañal puede estar mojado y sucio a la vez.", "Colores anotados: amarillo 8, verde 1.",
                     "Sueño: por lo general 13 h por día (entre 13 h y 13 h).", "Peso: 3,62 kg el 24/10.",
                     "- 22/10 15:00: «Regurgitó un poco después de la toma de las 13»",
                     "Preguntas para la pediatra (1):", "1. ¿Puede salir a pasear?",
                     "Es solo lo que anotaron, sin interpretar: la pediatra es quien evalúa y decide."):
            self.assertIn(line, lines)
        self.assertNotIn("Night wake-up", text)
        self.assertNotIn("Bath", text)
        self.assertIsNone(ADVICE.search(text.replace("evalúa y decide", "")), text)

    def test_strictly_descriptive_in_both_languages(self):
        fam = family(self, at(28, 9), week())
        for lang in ("es", "en"):
            text = fam.pedi.summary(lang)
            self.assertIsNone(ADVICE.search(text), (lang, ADVICE.search(text)))
        self.assertTrue(fam.pedi.summary("en").endswith("the pediatrician is the one who assesses and decides."))

    def test_each_parent_in_their_language(self):
        people = {**PEOPLE, "ceci": {**PEOPLE["ceci"], "lang": "en"}}
        fam = family(self, at(28, 9), week(), people=people)
        self.assertTrue(fam.say(CECI, "pediatrician summary").startswith("Summary for the pediatrician."))
        self.assertTrue(fam.say(GONZA, "resumen para la pediatra").startswith("Resumen para la pediatra."))

    def test_since_the_last_visit(self):
        fam = family(self, at(24, 9), week())
        fam.say(GONZA, "turno con la pediatra hoy a las 10")
        fam.clock.moment = at(24, 11, 30)
        reply = fam.say(CECI, "la pediatra dijo que lo vemos de nuevo en una semana")
        self.assertIn("Anotado en el registro: «La pediatra dijo que lo vemos de nuevo en una semana»", reply)
        self.assertEqual(fam.log.rows[-1]["details"]["text"], "La pediatra dijo que lo vemos de nuevo en una semana")
        fam.clock.moment = at(28, 9)
        text = fam.pedi.summary("es")
        self.assertIn("Desde el último control (24/10).", text)
        self.assertIn("«La pediatra dijo que lo vemos de nuevo en una semana»", text)
        self.assertNotIn("Regurgitó", text)  # Oct 22, before the visit

    def test_said_lists_what_is_still_open(self):
        fam = family(self, at(24, 9), week())
        fam.say(GONZA, "preguntarle a la pediatra por los gases")
        reply = fam.say(CECI, "La pediatra dijo que los gases van a pasar")
        self.assertIn("Siguen abiertas: 1. ¿Por los gases?", reply)
        self.assertIn("«cerrar pregunta 1»", reply)

    def test_before_the_birth_only_the_questions(self):
        fam = family(self, at(28, 9), week(), extra={"baby": {"born": False, "name": "Theo"}})
        fam.pedi.phase = "prep"
        fam.say(GONZA, "preguntarle a la pediatra qué vacunas le dan al nacer")
        text = fam.pedi.summary("es")
        self.assertIn("Theo todavía no nació", text)
        self.assertNotIn("Tomas", text)
        self.assertIn("1. ¿Qué vacunas le dan al nacer?", text)

    def test_an_unread_log_still_sends_the_questions(self):
        fam = family(self, at(28, 9))
        fam.log.entries = mock.Mock(side_effect=RuntimeError("Baby Buddy unreachable"))
        fam.say(GONZA, "preguntarle a la pediatra por los gases")
        text = fam.pedi.summary("es")
        self.assertIn("No pude leer el registro ahora", text)
        self.assertIn("1. ¿Por los gases?", text)


class Pushes(unittest.TestCase):
    def test_the_evening_before_and_the_morning_of_to_both_once(self):
        fam = family(self, at(28, 9), week())
        fam.say(GONZA, "turno con la pediatra el jueves 10:00")
        self.assertEqual(fam.pedi.tick(at(28, 18, 59)), [])
        sent = fam.pedi.tick(at(28, 19, 0))
        self.assertEqual(sorted(e["person"] for e in sent), ["ceci", "gonza"])
        self.assertEqual(fam.pedi.tick(at(28, 19, 1)), [])
        first = fam.sent_to(CECI)[-1]
        self.assertTrue(first.startswith("Control con la pediatra mañana, jueves 29/10, a las 10:00."), first)
        self.assertIn("Por día: 8 tomas", first)
        morning = fam.pedi.tick(at(29, 8, 0))
        self.assertEqual(len(morning), 2)
        self.assertTrue(fam.sent_to(GONZA)[-1].startswith("Control con la pediatra hoy a las 10:00."))
        self.assertEqual(fam.pedi.tick(at(29, 10, 5)), [])

    def test_a_restart_never_sends_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = Family(tmp, at(28, 9), week())
            try:
                fam.say(GONZA, "turno con la pediatra el jueves 10:00")
                self.assertEqual(len(fam.pedi.tick(at(28, 19, 0))), 2)
                again = Pediatrician(fam.agent, fam.config, clock=fam.clock, muse=fam.muse)
                self.assertEqual(again.tick(at(28, 19, 30)), [])
            finally:
                fam.close()

    def test_only_the_one_going_and_a_late_add_gets_the_morning_only(self):
        fam = family(self, at(28, 20, 0), week())
        reply = fam.say(GONZA, "control con la pediatra mañana a las 9, va Ceci")
        self.assertIn("Le mando a Ceci el resumen para la pediatra el mismo día a las 07:30", reply)  # 90 min before
        self.assertEqual(fam.pedi.tick(at(28, 20, 5)), [])  # the evening slot had passed when it was kept
        before = len(fam.sent_to(GONZA))
        sent = fam.pedi.tick(at(29, 7, 30))
        self.assertEqual([e["person"] for e in sent], ["ceci"])
        self.assertEqual(len(fam.sent_to(GONZA)), before)
        self.assertTrue(fam.sent_to(CECI)[-1].startswith("Control con la pediatra hoy a las 09:00."))

    def test_down_overnight_sends_only_the_morning(self):
        fam = family(self, at(28, 9), week())
        fam.say(GONZA, "turno con la pediatra el jueves 10:00")
        sent = fam.pedi.tick(at(29, 8, 30))
        self.assertEqual({e["slot"] for e in sent}, {"morning"})

    def test_each_parent_reads_it_in_their_language(self):
        people = {**PEOPLE, "ceci": {**PEOPLE["ceci"], "lang": "en"}}
        fam = family(self, at(28, 9), week(), people=people)
        fam.say(GONZA, "turno con la pediatra el jueves 10:00")
        fam.pedi.tick(at(28, 19, 0))
        self.assertTrue(fam.sent_to(CECI)[-1].startswith("Pediatrician checkup tomorrow, Thursday Oct 29, at 10:00."))
        self.assertTrue(fam.sent_to(GONZA)[-1].startswith("Control con la pediatra mañana"))


class GlassesAndEcho(unittest.TestCase):
    def test_the_push_card_is_the_visit_and_the_numbers(self):
        fam = family(self, at(28, 9), week())
        fam.say(GONZA, "turno con la pediatra el jueves 10:00")
        fam.pedi.tick(at(28, 19, 0))
        reply = [e for e in fam.agent.bus.history if e["kind"] == "reply" and e.get("source") == "pediatrician"][-1]
        card = hud_cards.from_push(reply, "es")
        self.assertEqual((card["topic"], card["icon"], card["title"]), ("pediatrician", "calendar", "Pediatra"))
        self.assertTrue(card["status"].startswith("Control con la pediatra mañana"))
        self.assertEqual(card["detail"], "Por día: 8 tomas, 7 pañales, 13 h de sueño.")

    def test_asked_on_the_glasses_it_is_two_short_lines(self):
        fam = family(self, at(28, 9), week())
        fam.say(GONZA, "preguntarle a la pediatra por los gases")
        reply = fam.say(GONZA, "resumen para la pediatra", channel="glasses")
        self.assertEqual(reply, "Por día: 8 tomas, 7 pañales, 13 h de sueño.\n1 pregunta anotada.")
        card = hud_cards.from_reply({"text": reply}, "es")
        self.assertEqual(card["status"], "Por día: 8 tomas, 7 pañales, 13 h de sueño.")

    def test_the_echo_reads_the_numbers_never_the_questions(self):
        fam = family(self, at(28, 9), week())
        fam.say(GONZA, "preguntarle a la pediatra por los gases")
        fam.config["voice_bridge"] = {"port": 0, "host": "127.0.0.1", "timeout_s": 5, "unknown_speaker": "guest",
                                      "token_file": os.path.join(fam.config["data_dir"], "voice-token")}
        bridge = VoiceBridge(fam.agent, fam.config, token="t" * 24)
        fam.agent.plugins.append(bridge)
        reply = bridge.ask("agente del bebé, resumen para la pediatra", "echo", None)["reply"]
        self.assertIn("unas 8 tomas, 7 pañales, 6 mojados y 3 sucios, y 13 horas de sueño", reply)
        self.assertIn("Hay una pregunta anotada.", reply)
        self.assertNotIn("gases", reply)
        self.assertLessEqual(len(reply), 400)


class Config(unittest.TestCase):
    def test_the_family_agent_loads_it(self):
        path = os.path.join(os.path.dirname(__file__), "..", "config", "agent.vostro.json")
        config = json.load(open(path))
        self.assertIn("parenting_agent.pediatrician:Pediatrician", config["plugins"])
        self.assertIs(config["house"]["live"], False)


if __name__ == "__main__":
    unittest.main()
