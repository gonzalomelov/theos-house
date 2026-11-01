"""The OPOL helper (opol.py): which language the baby hears from each parent, counted from the glasses microphone.

Offline: a fake language ID (the real one, Meta's MMS language ID, runs in scripts/opol_run.py on recorded clips), a
fixed clock, a fake ear and a fake Telegram messenger. Chat ids are made up, nothing is sent.
"""
import datetime
import io
import json
import os
import tempfile
import unittest
import wave
from unittest import mock

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.channels.push import FamilyPush
from parenting_agent.channels.telegram import Telegram
from parenting_agent.glasses import Glasses
from parenting_agent.opol import MmsLid, Opol, Unavailable, length, pick, text_lang, wav_pcm
from tests.test_channels import FakeMessenger
from tests.test_home_automations import Clock

TZ = datetime.timezone(datetime.timedelta(hours=-3))
GONZA, CECI = "5001", "5002"
ENV = {"TELEGRAM_CHAT_ID": GONZA, "TELEGRAM_CECI_CHAT_ID": CECI}
PEOPLE = {"gonza": {"name": "Gonza", "rota": "Parent A", "chat_ids_env": "TELEGRAM_CHAT_ID", "lang": "es"},
          "ceci": {"name": "Ceci", "rota": "Parent B", "chat_ids_env": "TELEGRAM_CECI_CHAT_ID", "lang": "es"}}
OPOL = {"languages": {"gonza": "en", "ceci": "es"}, "not_to_baby": ["Firulais"]}
WORDS = "Look at the little duck Theo"


def at(day, hh, mm=0, month=11):
    return datetime.datetime(2026, month, day, hh, mm, tzinfo=TZ)


def wav(seconds=3.0, rate=16000, channels=1, width=2):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * channels * int(seconds * rate) if width == 2 else b"\x01" * int(seconds * rate))
    return out.getvalue()


class FakeLid:
    """Answers like the worker: probabilities for eng and spa, from a queue of (eng, spa) pairs."""

    name = "fake-lid"

    def __init__(self, *pairs):
        self.pairs, self.seen = list(pairs), []

    def classify(self, pcm):
        self.seen.append(len(pcm))
        en, es = self.pairs.pop(0)
        return {"probs": {"eng": en, "spa": es}, "top": "eng" if en >= es else "spa", "top_p": max(en, es)}


class Family:
    """The family agent: Telegram for both parents, the family push and the OPOL helper, Theo born."""

    def __init__(self, tmp, now, lid=None, opol=None, born=True):
        self.env = mock.patch.dict(os.environ, ENV)
        self.env.start()
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "house": {},
                       "plugins": [], "people": PEOPLE, "telegram": {"allowed_chat_ids_env": "TELEGRAM_CHAT_ID"},
                       "family_push": {"morning": True, "hold_s": 300},
                       "baby": {"born": born, "name": "Theo"}, "opol": {**OPOL, **(opol or {})}})
        self.config = config
        self.agent = build(config)
        self.clock = Clock(now)
        self.messenger = FakeMessenger()
        self.telegram = Telegram(self.agent, config, messenger=self.messenger)
        self.push = FamilyPush(self.agent, config, clock=self.clock)
        self.lid = lid or FakeLid()
        self.opol = Opol(self.agent, config, clock=self.clock, lid=self.lid)
        self.agent.plugins = [self.telegram, self.push, self.opol]

    def say(self, chat, text):
        person = self.telegram.person_of(chat)
        event = self.agent.bus.publish("message", channel="telegram", text=text, chat_id=chat, person=person, voice=False)
        self.agent.current_event = event
        try:
            self.agent.handle(event)
        finally:
            self.agent.current_event = None
        return [e for e in self.agent.bus.history if e["kind"] == "reply"][-1]["text"]

    def events(self, action=None):
        return [e for e in self.agent.bus.history if e["kind"] == "opol" and (action is None or e["action"] == action)]

    def morning(self):
        self.agent.bus.publish("notify", text="Good morning.", channel="telegram", source="day-engine",
                               routine="morning_brief", facts={"night": {}, "low": [], "appointments": [], "meals": []})
        self.push.morning_flush()
        return self.sent_to(GONZA)[-1:], self.sent_to(CECI)[-1:]

    def sent_to(self, chat):
        return [text for c, text in self.messenger.sent if c == chat]

    def close(self):
        self.agent.close()
        self.env.stop()


def family(test, now=None, **kw):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    fam = Family(tmp.name, now or at(4, 9, 0), **kw)
    test.addCleanup(fam.close)
    return fam


class Pieces(unittest.TestCase):
    def test_pick_counts_only_a_sure_english_or_spanish(self):
        self.assertEqual(pick({"probs": {"eng": 0.9, "spa": 0.05}}, 0.8, 0.5), ("en", 0.947))
        self.assertEqual(pick({"probs": {"eng": 0.1, "spa": 0.85}}, 0.8, 0.5), ("es", 0.895))
        self.assertEqual(pick({"probs": {"eng": 0.45, "spa": 0.4}}, 0.8, 0.5)[0], None, "a mix is not sure")
        self.assertEqual(pick({"probs": {"eng": 0.2, "spa": 0.02}}, 0.8, 0.5)[0], None, "mostly another language")
        self.assertEqual(pick({"probs": {}}, 0.8, 0.5), (None, 0.0))

    def test_wav_in_memory(self):
        pcm, seconds = wav_pcm(wav(2.5))
        self.assertEqual((len(pcm), seconds), (2 * 40000, 2.5))
        pcm, seconds = wav_pcm(wav(1.0, channels=2))
        self.assertEqual((len(pcm), seconds), (32000, 1.0), "the first channel only")
        with self.assertRaises(ValueError):
            wav_pcm(wav(1.0, rate=8000))
        with self.assertRaises(ValueError):
            wav_pcm(wav(1.0, width=1))

    def test_length_and_text_language(self):
        self.assertEqual([length(s, "es") for s in (0.4, 20.4, 59.6, 45 * 60, 3600, 2 * 3600 + 600)],
                         ["1 s", "20 s", "1 min", "45 min", "1 h", "2 h 10 min"])
        self.assertEqual(text_lang("mirá qué lindo el patito", 3), "es")
        self.assertEqual(text_lang("look at the little duck", 3), "en")
        self.assertIsNone(text_lang("hola Theo", 3), "too short to tell")

    def test_the_real_language_id_says_why_it_cannot_start(self):
        with self.assertRaises(Unavailable):
            MmsLid({"python": "/nonexistent/python"})
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(Unavailable):
            MmsLid({"python": os.sys.executable, "model_dir": tmp})


class Counting(unittest.TestCase):
    def test_minutes_per_parent_per_language_per_day(self):
        fam = family(self, lid=FakeLid((0.95, 0.01), (0.02, 0.9), (0.03, 0.93), (0.9, 0.02)))
        fam.opol.overheard(wav(4.0), "gonza", WORDS, {"speech_s": 3.6})
        fam.opol.overheard(wav(5.0), "ceci", "Mirá el patito, Theo")
        fam.opol.overheard(wav(2.0), "gonza", "Mirá el patito")  # Gonza in Spanish: counted as Spanish, his
        fam.clock.moment = at(5, 8, 0)
        fam.opol.overheard(wav(3.0), "gonza", WORDS)
        rows = fam.opol.totals(at(4, 0).date(), at(4, 0).date())
        self.assertEqual(rows, {"gonza": {"en": 3.6, "es": 2.0}, "ceci": {"es": 5.0}})
        self.assertEqual(fam.opol.totals(at(5, 0).date(), at(5, 0).date()), {"gonza": {"en": 3.0}})
        counted = fam.events("counted")
        self.assertEqual([(e["person"], e["lang"], e["by"]) for e in counted],
                         [("gonza", "en", "mms-lid"), ("ceci", "es", "mms-lid"), ("gonza", "es", "mms-lid"),
                          ("gonza", "en", "mms-lid")])

    def test_no_words_and_no_audio_are_kept(self):
        fam = family(self, lid=FakeLid((0.95, 0.01)))
        fam.opol.overheard(wav(4.0), "gonza", WORDS)
        with fam.agent.memory.lock:
            tables = [r[0] for r in fam.agent.memory.db.execute(
                "select name from sqlite_master where type = 'table' and name like 'opol%'")]
            stored = json.dumps([fam.agent.memory.db.execute(f"select * from {t}").fetchall() for t in tables])
        self.assertNotIn("duck", stored)
        self.assertNotIn("duck", json.dumps(fam.events()), "the opol events carry no words")
        with fam.agent.memory.lock:
            messages = fam.agent.memory.db.execute("select text from messages").fetchall()
        self.assertEqual(messages, [], "the overheard words never become a message")
        self.assertEqual(fam.lid.seen, [2 * 64000], "the audio went only to the local language ID, in memory")

    def test_what_is_not_counted(self):
        fam = family(self, lid=FakeLid((0.45, 0.4), (0.95, 0.01)))
        fam.opol.overheard(wav(3.0), "gonza", "Ceci, ¿me pasás el pañal?")
        fam.opol.overheard(wav(3.0), "ceci", "Firulais, salí de acá")
        fam.opol.overheard(wav(0.6), "gonza", "Hi")
        fam.opol.overheard(wav(3.0), "gonza", WORDS)  # the model is not sure: nothing
        fam.opol.overheard(wav(3.0), "abuela", WORDS)
        fam.opol.overheard(wav(3.0), "gonza", WORDS)  # counted
        reasons = [e["reason"] for e in fam.events("skipped")]
        self.assertEqual(reasons, ["to someone else", "to someone else", "too short", "language not sure",
                                   "unknown speaker"])
        self.assertEqual(fam.opol.totals(at(4, 0).date(), at(4, 0).date()), {"gonza": {"en": 3.0}})

    def test_glasses_that_send_text_get_the_words_language(self):
        fam = family(self)
        fam.opol.overheard(None, "ceci", "Mirá qué lindo el patito, Theo", {"speech_s": 2.5})
        fam.opol.overheard(None, "ceci", "Hola Theo", {"speech_s": 1.5})
        fam.opol.overheard(None, "ceci", "Mirá qué lindo el patito")  # no length: nothing to count
        self.assertEqual(fam.opol.totals(at(4, 0).date(), at(4, 0).date()), {"ceci": {"es": 2.5}})
        self.assertEqual(fam.events("counted")[0]["by"], "words")

    def test_no_language_id_falls_back_to_the_words_and_says_so(self):
        fam = family(self, opol={"lid": {"python": "/nonexistent/python"}})
        fam.opol._lid = None
        fam.opol.overheard(wav(3.0), "gonza", WORDS)
        self.assertEqual(len(fam.events("lid_unavailable")), 1)
        self.assertEqual([(e["lang"], e["by"]) for e in fam.events("counted")], [("en", "words")])

    def test_a_failing_language_id_is_reported_and_replaced(self):
        fam = family(self, lid=FakeLid(), opol={"lid": {"python": "/nonexistent/python"}})
        fam.opol.overheard(wav(3.0), "gonza", WORDS)  # the fake has no answer left: IndexError, like a dead worker
        self.assertIn("IndexError", fam.events("failed")[0]["error"])
        self.assertIsNone(fam.opol._lid)
        fam.opol.overheard(wav(3.0), "gonza", WORDS)
        self.assertEqual([(e["lang"], e["by"]) for e in fam.events("counted")], [("en", "words")])

    def test_before_the_birth_and_when_turned_off_nothing_is_counted(self):
        prep = family(self, born=False, lid=FakeLid((0.95, 0.01)))
        prep.opol.overheard(wav(3.0), "gonza", WORDS)
        self.assertEqual(prep.events("skipped")[0]["reason"], "not born yet")
        self.assertIn("todavía no nació", prep.say(GONZA, "¿cuánto inglés escuchó Theo esta semana?"))
        off = family(self, opol={"enabled": False})
        off.opol.overheard(wav(3.0), "gonza", WORDS)
        self.assertEqual(off.events("skipped")[0]["reason"], "off in the config")
        self.assertIn("apagado en la configuración", off.say(GONZA, "prendé el conteo de idiomas"))

    def test_the_counting_thread(self):
        fam = family(self, lid=FakeLid((0.95, 0.01), (0.01, 0.95)))
        fam.opol.start()
        fam.opol.overheard(wav(3.0), "gonza", WORDS)
        fam.opol.overheard(wav(2.0), "ceci", "Mirá el patito")
        fam.opol.queue.join()
        fam.opol.stop()
        self.assertEqual(fam.opol.totals(at(4, 0).date(), at(4, 0).date()), {"gonza": {"en": 3.0}, "ceci": {"es": 2.0}})


class FromTheGlasses(unittest.TestCase):
    """The real glasses path: Muse's ear (faked here) writes it down, the gate drops it, the helper counts it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = config_mod.load(None)
        config.update({"data_dir": self.tmp.name, "env_file": f"{self.tmp.name}/none.env", "people": PEOPLE,
                       "glasses": {"port": 0, "host": "127.0.0.1", "token": "t", "person": "gonza"},
                       "baby": {"born": True, "name": "Theo"}, "opol": OPOL, "plugins": []})
        self.agent = build(config)
        self.addCleanup(self.agent.close)
        self.glasses = Glasses(self.agent, config)
        self.addCleanup(self.glasses.stop)
        self.glasses.race_cfg = {"calls": 1, "rounds": 1}
        self.lid = FakeLid((0.97, 0.01))
        self.opol = Opol(self.agent, config, clock=lambda: at(4, 10, 0), lid=self.lid)
        self.agent.plugins = [self.glasses, self.opol]
        self.messages = []
        self.agent.bus.subscribe(lambda e: self.messages.append(e["text"]), ["message"])

    def test_talk_to_the_baby_is_counted_and_the_agent_stays_quiet(self):
        words = [WORDS, "Agente, ¿cuándo comió?", "Agente", "El bebé está azul y no respira"]
        self.glasses._make_ear = lambda: type("Ear", (), {"hear": lambda _, audio: words.pop(0)})()
        for _ in range(4):
            self.glasses.hear(wav(3.0), "gonza", {"speech_s": 2.8})
        self.assertEqual(self.messages, ["¿cuándo comió?", "El bebé está azul y no respira"],
                         "only the agent's words and the red flag reach it")
        self.assertEqual(self.opol.totals(at(4, 0).date(), at(4, 0).date()), {"gonza": {"en": 2.8}})
        self.assertEqual(len(self.lid.seen), 1, "the wake word, the command and the red flag are not counted")
        replies = [e for e in self.agent.bus.history if e["kind"] == "reply"]
        self.assertFalse(any("Theo" in str(e.get("text")) and "duck" in str(e.get("text")) for e in replies))


class Asking(unittest.TestCase):
    def setUp(self):
        self.fam = family(self, now=at(4, 20, 0))  # Wednesday Nov 4: the week is Mon 2 to Wed 4
        o = self.fam.opol
        o.add("2026-11-02", "gonza", "en", 3600 + 50 * 60)
        o.add("2026-11-03", "gonza", "es", 15 * 60)
        o.add("2026-11-03", "ceci", "es", 2 * 3600 + 45 * 60)
        o.add("2026-11-04", "ceci", "en", 20 * 60)
        o.add("2026-11-01", "gonza", "en", 5 * 3600)  # last week, Sunday

    def test_how_much_english_this_week(self):
        reply = self.fam.say(GONZA, "¿cuánto inglés escuchó Theo esta semana?")
        self.assertIn("Esta semana (desde el lunes 2/11) Theo escuchó 2 h 10 min en inglés (Gonza 1 h 50 min, "
                      "Ceci 20 min) y 3 h en español (Ceci 2 h 45 min, Gonza 15 min).", reply)
        self.assertIn("nunca lo que dicen", reply)

    def test_spanish_first_when_asked_and_in_english_when_asked_in_english(self):
        reply = self.fam.say(CECI, "¿cuánto español le hablamos hoy?")
        self.assertTrue(reply.startswith("Hoy Theo escuchó 20 min en inglés (Ceci 20 min)."), reply)
        reply = self.fam.say(GONZA, "How much Spanish did Theo hear this week?")
        self.assertTrue(reply.startswith("Esta semana (desde el lunes 2/11) Theo escuchó 3 h en español"), reply)
        self.fam.opol.people().spec["gonza"]["lang"] = "en"
        reply = self.fam.say(GONZA, "how much English did Theo hear last week?")
        self.assertTrue(reply.startswith("Last week (26/10 to 1/11) Theo heard 5 h of English (Gonza 5 h). I count"), reply)
        del self.fam.opol.people().spec["gonza"]["lang"]
        reply = self.fam.say(GONZA, "How much Spanish did Theo hear this week?")
        self.assertTrue(reply.startswith("This week (since Monday 2/11) Theo heard 3 h of Spanish"), reply)

    def test_nothing_counted_yesterday(self):
        self.fam.clock.moment = at(6, 9, 0)
        self.assertIn("Ayer no conté nada", self.fam.say(CECI, "¿cuánto inglés escuchó ayer?"))

    def test_off_on_and_delete(self):
        self.assertIn("apagué el conteo de idiomas", self.fam.say(CECI, "apagá el conteo de idiomas"))
        self.assertIn("está apagado", self.fam.say(GONZA, "¿cuánto inglés escuchó Theo esta semana?"))
        self.fam.opol.overheard(wav(3.0), "gonza", WORDS)
        self.assertEqual(self.fam.events("skipped")[-1]["reason"], "turned off by a parent")
        self.assertIn("prendí", self.fam.say(CECI, "prendé el conteo de idiomas"))
        self.assertIn("borré todo el conteo de idiomas (4 días)", self.fam.say(CECI, "borrá el conteo de idiomas"))
        self.assertIn("no conté nada", self.fam.say(GONZA, "¿cuánto inglés escuchó Theo esta semana?"))

    def test_other_messages_are_left_to_the_agent(self):
        for text in ("¿cómo se dice pañal en inglés?", "le di 90 ml", "Theo no respira"):
            self.assertIsNone(self.fam.opol.take({"person": "gonza"}, text), text)


class MorningLine(unittest.TestCase):
    def week(self, fam, first, per_day):
        """per_day: {person: {lang: minutes}} on each of 7 days from first."""
        for i in range(7):
            day = (first + datetime.timedelta(days=i)).date().isoformat()
            for person, langs in per_day.items():
                for lang, minutes in langs.items():
                    fam.opol.add(day, person, lang, minutes * 60)

    def test_monday_line_once_for_each_parent_with_their_language(self):
        fam = family(self, now=at(9, 7, 30))  # Monday Nov 9
        self.week(fam, at(2, 0), {"gonza": {"en": 30, "es": 5}, "ceci": {"es": 40}})
        gonza, ceci = fam.morning()
        self.assertIn("Idiomas: la semana pasada Theo te escuchó 3 h 30 min en inglés (tu idioma con él) y 35 min en "
                      "español.", gonza[0])
        self.assertIn("Idiomas: la semana pasada Theo te escuchó 4 h 40 min en español (tu idioma con él).", ceci[0])
        fam.clock.moment = at(10, 7, 30)
        fam.push.sent.path.unlink()
        gonza, ceci = fam.morning()
        self.assertNotIn("Idiomas", gonza[0] + ceci[0], "at most weekly")

    def test_a_drift_gets_a_line_midweek_at_most_every_3_days(self):
        fam = family(self, now=at(12, 7, 30))  # Thursday Nov 12, the weekly line already went on Monday
        fam.opol.mark(at(9, 0).date(), "gonza", "weekly", at(9, 0).date())
        self.week(fam, at(2, 0), {"gonza": {"en": 30, "es": 5}})  # Nov 2 to 8: 86 % English
        for day in (9, 10, 11):
            fam.opol.add(f"2026-11-{day:02d}", "gonza", "es", 20 * 60)
            fam.opol.add(f"2026-11-{day:02d}", "gonza", "en", 10 * 60)  # 33 % English
        line = fam.opol.morning_line("gonza", "es")
        self.assertEqual(line, "Idiomas: en los últimos 3 días el 33 % de lo que Theo te escuchó fue en inglés (tu idioma "
                               "con él), la semana anterior el 86 %.")
        self.assertIsNone(fam.opol.morning_line("gonza", "es", at(13, 7, 30)))
        self.assertIsNone(fam.opol.morning_line("gonza", "es", at(14, 7, 30)))

    def test_no_line_with_little_counted_no_goal_or_turned_off(self):
        fam = family(self, now=at(9, 7, 30))
        self.week(fam, at(2, 0), {"gonza": {"en": 1}, "ceci": {"es": 40}})
        self.assertIsNone(fam.opol.morning_line("gonza", "es"), "7 min in a week is under the floor")
        fam.opol.cfg["languages"] = {"gonza": "en"}
        self.assertIsNone(fam.opol.morning_line("ceci", "es"), "no language set for her")
        fam.opol.cfg["languages"] = OPOL["languages"]
        fam.opol.set_state("off")
        self.assertIsNone(fam.opol.morning_line("ceci", "es"))
        fam.opol.set_state("on")
        self.assertIn("4 h 40 min en español", fam.opol.morning_line("ceci", "es"))
        english = family(self, now=at(9, 7, 30))
        self.week(english, at(2, 0), {"ceci": {"es": 40}})
        self.assertEqual(english.opol.morning_line("ceci", "en"),
                         "Languages: last week Theo heard you for 4 h 40 min in Spanish (your language with him).")

    def test_a_broken_read_never_stops_the_morning_message(self):
        fam = family(self, now=at(9, 7, 30))
        with mock.patch.object(fam.opol, "totals", side_effect=RuntimeError("disk")):
            gonza, ceci = fam.morning()
        self.assertEqual((len(gonza), len(ceci)), (1, 1))
        self.assertEqual(len(fam.events("line_failed")), 2)


if __name__ == "__main__":
    unittest.main()
