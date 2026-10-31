"""Tests for the families bot in Spanish: the language pick from Telegram, /idioma and /language, the delete flow with
BORRAR, the brain's language, and that no English fixed text reaches a family in Spanish mode. Fake brain, no network.
"""
import datetime
import re
import string
import unittest

from parenting_agent.agent import rules
from parenting_agent.channels import telegram as telegram_mod
from parenting_agent.channels.messaging import Incoming
from parenting_agent.families import texts
from parenting_agent.families.bot import FamiliesBot
from parenting_agent.families.texts import EN, ES

from test_families import TZ, CountingBrain, FakeTelegram, family_of, make, text

# Words that only English text has. The Spanish texts name English twice on purpose, as the way to switch.
ENGLISH = re.compile(r"\b(the|you|your|please|send|done|feed|feeds|diaper|diapers|logged|today|welcome|nothing|"
                     r"could|not|is|are|and|of|at|here|bath|sleep|deleted|limit|reminders are)\b", re.I)
ALLOWED_ENGLISH = ("For English send /language.", "/language English", rules.FEVER_SOURCE, rules.NEWBORN_SOURCE)


class SpanishBrain(CountingBrain):
    """Stands in for the real brain, which the system prompt tells to answer in Spanish. Only fixed texts are tested."""

    def step(self, system, transcript, tools):
        reply = super().step(system, transcript, tools)
        reply.text = "Acá está lo que dice el registro."
        return reply


def english_in(reply):
    for allowed in ALLOWED_ENGLISH:
        reply = reply.replace(allowed, "")
    return ENGLISH.findall(reply)


def onboard(app, user, lang="es-UY", name="Mia", partner="no", internal=False):
    code = app.store.create_invite(internal=internal)
    return [app.handle(user, user, f"/start {code}", "private", lang), app.handle(user, user, name, "private", lang),
            app.handle(user, user, "12/10/2026", "private", lang), app.handle(user, user, partner, "private", lang)]


class Tables(unittest.TestCase):
    def test_both_languages_have_the_same_texts_and_placeholders(self):
        self.assertEqual(set(EN), set(ES))
        fields = lambda s: sorted(f for _, f, _, _ in string.Formatter().parse(s) if f) if isinstance(s, str) else s
        for key in EN:
            self.assertEqual(fields(EN[key]), fields(ES[key]) if isinstance(EN[key], str) else fields(EN[key]), key)
            if isinstance(ES[key], str):
                self.assertNotIn(";", ES[key], key)
                self.assertNotIn("—", ES[key], key)

    def test_spanish_uses_voseo(self):
        spanish = " ".join(v for v in ES.values() if isinstance(v, str))
        for word in ("mandá", "escribí", "querés", "podés", "revisalo"):
            self.assertIn(word, spanish.lower())
        for tuteo in ("envía", "escribe ", "quieres", "puedes", "tienes"):
            self.assertNotIn(tuteo, spanish.lower())

    def test_language_from_the_telegram_app(self):
        self.assertEqual([texts.lang_for(c) for c in ("es", "es-UY", "ES-ar", "en", "pt-BR", "", None)],
                         ["es", "es", "es", "en", "en", "en", "en"])


class Strangers(unittest.TestCase):
    def test_strangers_get_the_language_of_their_app(self):
        app = make(self)
        self.assertEqual(text(app.handle("1", "1", "hola", "private", "es-UY")), ES["NO_CODE"])
        self.assertEqual(text(app.handle("2", "2", "hi", "private", "en")), EN["NO_CODE"])
        self.assertEqual(text(app.handle("3", "3", "/start AAAAAAAA", "private", "es")), ES["BAD_CODE"])
        self.assertEqual(text(app.handle("4", "4", "hola", "group", "es")), ES["GROUP"])
        self.assertEqual(app.store.family_count(), 0)


class Onboarding(unittest.TestCase):
    def test_spanish_onboarding_from_start_to_logging(self):
        app = make(self)
        replies = [text(r) for r in onboard(app, "111")]
        self.assertEqual(replies, [ES["WELCOME"] + ES["ASK_NAME"], ES["ASK_BORN"].format(name="Mia"), ES["ASK_PARTNER"],
                                   ES["READY"].format(name="Mia")])
        self.assertEqual(app.family(family_of(app, "111")).fact("birth_date"), "2026-10-12")
        self.assertRegex(text(app.handle("111", "111", "mamadera 120 ml")), r"^Anoté la mamadera de 120 ml de las \d\d:\d\d\.$")

    def test_english_app_still_onboards_in_english(self):
        app = make(self)
        replies = [text(r) for r in onboard(app, "111", lang="en")]
        self.assertEqual(replies[1], EN["ASK_BORN"].format(name="Mia"))
        self.assertEqual(replies[3], EN["READY"].format(name="Mia"))

    def test_the_other_parent_joins_in_the_family_language(self):
        app = make(self)
        replies = onboard(app, "111", partner="sí")
        self.assertIn("Acá tenés la invitación", text(replies[3]))
        code = re.search(r"\b([A-Z2-9]{8})\b", text(replies[3])).group(1)
        joined = text(app.handle("222", "222", f"/start {code}", "private", "en"))
        self.assertTrue(joined.startswith(ES["PARTNER_WELCOME"].format(name="Mia")))
        self.assertEqual(english_in(joined), [])


class NoEnglishLeak(unittest.TestCase):
    def test_every_fixed_message_in_spanish_mode(self):
        clock = [datetime.datetime(2026, 10, 28, 9, 0, tzinfo=TZ)]
        brain = SpanishBrain(tokens=(1_000_000, 0))  # $0.10 a call, so the cap below is reached after 2 calls
        app = make(self, brain=brain, clock=lambda: clock[0], PA_FAMILIES_BRAIN="baseten", PA_FAMILIES_PRICE_IN="0.10", PA_FAMILIES_PRICE_OUT="0.50", PA_FAMILIES_FAMILY_USD="0.15",
                   PA_FAMILIES_MAX_MESSAGES="40")
        replies = [text(r) for r in onboard(app, "111", partner="sí")]
        code = re.search(r"\b([A-Z2-9]{8})\b", replies[3]).group(1)
        replies.append(text(app.handle("222", "222", f"/start {code}", "private", "es")))
        say = lambda message: replies.append(text(app.handle("111", "111", message, "private", "es"))) or replies[-1]
        say("/resumen")  # nothing logged yet
        say("/proxima")  # fewer than two feeds
        for message in ("/privacidad", "/ayuda", "/start", "/algo", "/avisos off", "/avisos on", "/invitar", "x" * 501,
                        "¿tiene fiebre, le doy paracetamol?", "le subio la fiebre", "¿es normal que llore tanto?"):
            say(message)
        say("hola")
        say("hola")  # the brain is over the family cap from here, the free rules answer in Spanish
        self.assertRegex(say("mamadera 120 ml"), r"^Anoté la mamadera de 120 ml de las \d\d:\d\d\.$")
        self.assertRegex(say("pañal mojado y sucio"), r"^Anoté el pañal mojado y sucio de las \d\d:\d\d\.$")
        self.assertIn("1 toma", say("¿cuánto tomó hoy?"))
        f = app.family(family_of(app, "111"))
        f.log.add("feeding", {"amount_ml": 100, "start": "2026-10-28T06:00:00-03:00"}, "2026-10-28T06:15:00-03:00")
        f.log.add("feeding", {"amount_ml": 100, "start": "2026-10-28T09:00:00-03:00"}, "2026-10-28T09:15:00-03:00")
        nxt = say("/proxima")
        self.assertIn("la próxima toma de Mia", nxt)
        self.assertIn("Hoy para Mia:", say("/resumen"))
        hour, minute = (int(n) for n in re.search(r"las (\d\d):(\d\d)", nxt).groups())
        clock[0] = datetime.datetime(2026, 10, 28, hour, minute, tzinfo=TZ) - datetime.timedelta(minutes=5)
        reminders = app.tick()
        self.assertEqual([chat for chat, _ in reminders], ["111", "222"])
        clock[0] = datetime.datetime(2026, 10, 28, 20, 30, tzinfo=TZ)
        summaries = app.tick()
        self.assertTrue(summaries and summaries[0][1].startswith("Hoy para Mia:"))
        replies += [t for _, t in reminders + summaries]
        self.assertIn(ES["REFUSAL"], replies)
        say("/borrarmisdatos")
        say("no")
        say("/deletemydata")
        deleted = app.handle("111", "111", "BORRAR", "private", "es")
        replies += [t for _, t in deleted]
        self.assertEqual(deleted, [("111", ES["DELETED"]), ("222", ES["DELETED_OTHER"])])
        for reply in replies:
            self.assertEqual(english_in(reply), [], reply)

    def test_every_reply_after_onboarding_is_one_of_the_spanish_texts_or_built_from_them(self):
        spanish_starts = {v.split("{")[0][:20] for v in ES.values() if isinstance(v, str) and v.split("{")[0][:20].strip()}
        app = make(self)
        onboard(app, "111")
        for message in ("/privacidad", "/ayuda", "/avisos off", "/borrarmisdatos", "no"):
            reply = text(app.handle("111", "111", message, "private", "es"))
            self.assertTrue(any(reply.startswith(s) for s in spanish_starts), reply)


class Switch(unittest.TestCase):
    def test_idioma_and_language_switch_the_whole_family(self):
        app = make(self)
        onboard(app, "111", lang="en", partner="yes")
        self.assertEqual(text(app.handle("111", "111", "/idioma")), ES["LANG_SET"])
        self.assertEqual(text(app.handle("111", "111", "/privacy")), ES["PRIVACY"])
        self.assertEqual(text(app.handle("111", "111", "/reminders off")), ES["REMINDERS_OFF"])
        self.assertEqual(text(app.handle("111", "111", "/language")), EN["LANG_SET"])
        self.assertEqual(text(app.handle("111", "111", "/privacidad")), EN["PRIVACY"])
        self.assertEqual(text(app.handle("111", "111", "/language es")), ES["LANG_SET"])
        self.assertEqual(text(app.handle("111", "111", "/idioma en")), EN["LANG_SET"])
        self.assertEqual(text(app.handle("111", "111", "/idioma español")), ES["LANG_SET"])

    def test_switching_during_onboarding_asks_the_question_again(self):
        app = make(self)
        code = app.store.create_invite()
        app.handle("111", "111", f"/start {code}", "private", "es")
        self.assertEqual(text(app.handle("111", "111", "/language")), EN["LANG_SET"] + "\n\n" + EN["ASK_NAME"])
        self.assertEqual(text(app.handle("111", "111", "Mia")), EN["ASK_BORN"].format(name="Mia"))

    def test_an_existing_family_keeps_its_language_whatever_the_app_says(self):
        app = make(self)
        onboard(app, "111", lang="es")
        self.assertEqual(text(app.handle("111", "111", "/privacy", "private", "en")), ES["PRIVACY"])

    def test_the_brain_is_told_the_family_language(self):
        brain = CountingBrain()
        app = make(self, brain=brain, PA_FAMILIES_BRAIN="baseten", PA_FAMILIES_PRICE_IN="0.10", PA_FAMILIES_PRICE_OUT="0.50")
        onboard(app, "111", lang="es")
        app.handle("111", "111", "hola")
        self.assertIn("Rioplatense Spanish with voseo", brain.last_system)
        app.handle("111", "111", "/language")
        app.handle("111", "111", "hello")
        self.assertIn("Always reply in English", brain.last_system)
        self.assertNotIn("_lang", brain.last_system)


class Delete(unittest.TestCase):
    def test_borrar_confirms_in_spanish_and_delete_does_not(self):
        app = make(self)
        onboard(app, "111", lang="es")
        self.assertIn("Mandá BORRAR para confirmar", text(app.handle("111", "111", "/borrarmisdatos")))
        self.assertEqual(text(app.handle("111", "111", "DELETE")), ES["DELETE_CANCELLED"])
        app.handle("111", "111", "/deletemydata")
        self.assertEqual(text(app.handle("111", "111", "borrar")), ES["DELETED"])
        self.assertEqual(app.store.family_count(), 0)

    def test_delete_confirms_in_english_and_borrar_does_not(self):
        app = make(self)
        onboard(app, "111", lang="en")
        self.assertIn("Send DELETE to confirm", text(app.handle("111", "111", "/borrarmisdatos")))
        self.assertEqual(text(app.handle("111", "111", "BORRAR")), EN["DELETE_CANCELLED"])
        app.handle("111", "111", "/deletemydata")
        self.assertEqual(text(app.handle("111", "111", "DELETE")), EN["DELETED"])
        self.assertEqual(app.store.family_count(), 0)


class Medical(unittest.TestCase):
    def test_spanish_health_questions_are_refused_without_the_brain(self):
        brain = CountingBrain()
        app = make(self, brain=brain, PA_FAMILIES_BRAIN="baseten", PA_FAMILIES_PRICE_IN="0.10", PA_FAMILIES_PRICE_OUT="0.50")
        onboard(app, "111", lang="es")
        for question in ("¿le doy ibuprofeno?", "¿es normal este sarpullido?", "tiene tos, ¿le doy algo?"):
            self.assertEqual(text(app.handle("111", "111", question)), ES["REFUSAL"])
        # What the parent saw, with no question, is noted in their words. They asked nothing, so no advice line follows
        # (round 4: "No puedo darte consejo médico" after "tomo 70 y vomito un poco" read as noise at 3 AM).
        for seen in ("tiene sarpullido", "vomitó dos veces", "tiene tos", "vomito un poquito dsp de la toma"):
            reply = text(app.handle("111", "111", seen))
            self.assertRegex(reply, r"^Anoté una nota a las \d\d:\d\d: \"" + seen + r"\"\.$")
            self.assertNotIn(rules.NO_ADVICE["es"], reply)
        notes = [e["details"]["text"] for e in app.family(family_of(app, "111")).log.entries("note")]
        self.assertEqual(notes, ["tiene sarpullido", "vomitó dos veces", "tiene tos", "vomito un poquito dsp de la toma"])
        self.assertEqual(brain.calls, 0)

    def test_spanish_advice_words_stop_a_reminder(self):
        self.assertFalse(texts.no_advice_es("Deberías llamar al pediatra."))
        self.assertTrue(texts.no_advice_es(ES["NEXT_FEED"].format(name="Mia", when="12:00", minutes=8, gap="3 h 00 min")))


class Bot(unittest.TestCase):
    def test_telegram_adapter_reads_the_language_code(self):
        messenger = telegram_mod.TelegramMessenger("t")
        messenger._call = lambda method, params, timeout: [
            {"update_id": 5, "message": {"text": "hola", "chat": {"id": 42, "type": "private"},
                                         "from": {"id": 42, "first_name": "A", "language_code": "es"}}}]
        self.assertEqual(messenger.poll(0, 0)[0].language_code, "es")

    def test_the_bot_passes_the_language_on(self):
        app = make(self)
        fake = FakeTelegram([[Incoming(1, "555", "hola", "x", "555", "private", "es-UY")]])
        FamiliesBot(app, fake, poll_timeout_s=0).poll_once()
        self.assertEqual(fake.sent, [("555", ES["NO_CODE"])])


if __name__ == "__main__":
    unittest.main()
