"""Tests for voice notes (issue #58): the ear, the spoken words, the Telegram voice calls, and the voice path in the
agent's channel and in the families bot. Offline: a fake ear, a fake voice backend and a fake messenger.
The real run with Muse and MMS-TTS is scripts/voice_notes_run.py.
"""
import datetime
import io
import json
import shutil
import tempfile
import unittest
import zoneinfo
from unittest import mock

from parenting_agent.agent import rules
from parenting_agent.agent.brain import BrainError
from parenting_agent.channels.messaging import Incoming, Messenger
from parenting_agent.channels.telegram import Telegram, TelegramMessenger
from parenting_agent.families.bot import FamiliesBot
from parenting_agent.voice import audio, client, ear, words

from test_channels import FAMILY, make_agent
from test_families import make, onboard

TZ = zoneinfo.ZoneInfo("America/Montevideo")


class FakeEar:
    model = "fake-ear"

    def __init__(self, heard):
        self.heard, self.usage, self.calls = list(heard), {"input_tokens": 200, "output_tokens": 50}, 0

    def hear(self, wav):
        self.calls += 1
        if not self.heard:
            raise BrainError("HTTP 500")
        return self.heard.pop(0)


class FakeBackend:
    def __init__(self):
        self.spoken = []

    def to_wav(self, data):
        if data == b"broken":
            raise client.VoiceError("ffmpeg failed")
        return b"RIFF" + data

    def speak(self, text, lang, fmt="ogg"):
        self.spoken.append((text, lang))
        return b"OggS" + text.encode()


class VoiceMessenger(Messenger):
    def __init__(self, items=()):
        self.items, self.sent, self.voices = list(items), [], []

    def poll(self, offset, timeout):
        return [i for i in self.items if i.update_id >= offset]

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        return len(self.sent)

    def download(self, file_id):
        return file_id.encode()

    def send_voice(self, chat_id, ogg):
        self.voices.append((chat_id, ogg))
        return len(self.voices)


def voice_note(update_id, chat, file_id="note", lang="es-UY"):
    return Incoming(update_id, chat, "", "parent", chat, "private", lang, file_id)


class Ear(unittest.TestCase):
    def reply(self, text):
        return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 260, "completion_tokens": 90}}

    def test_sends_wav_as_input_audio_to_muse(self):
        sent = []
        with mock.patch.dict("os.environ", {"BASETEN_API_KEY": "k"}), \
                mock.patch.object(ear, "post_json", lambda url, headers, body, timeout: (sent.append(body), self.reply("Le di 90 ml"))[1]):
            self.assertEqual(ear.Ear().hear(b"RIFFdata"), "Le di 90 ml")
        part = sent[0]["messages"][0]["content"][1]
        self.assertEqual(part["type"], "input_audio")
        self.assertEqual(part["input_audio"]["format"], "wav")
        self.assertEqual(sent[0]["model"], "meta-models/muse-spark-open-1026")

    def test_an_answer_about_the_audio_is_never_the_parents_words(self):
        answers = [self.reply("No tengo acceso al audio para transcribirlo."),
                   self.reply("Listo para transcribir. Enviá el audio y lo escribo."), self.reply("Wet and dirty diaper")]
        with mock.patch.dict("os.environ", {"BASETEN_API_KEY": "k"}), \
                mock.patch.object(ear, "post_json", lambda *a: answers.pop(0)):
            listener = ear.Ear()
            self.assertEqual(listener.hear(b"RIFF"), "Wet and dirty diaper")
        self.assertEqual(listener.tries, 3)
        self.assertEqual(listener.usage["input_tokens"], 780)

    def test_three_refusals_hear_nothing(self):
        with mock.patch.dict("os.environ", {"BASETEN_API_KEY": "k"}), \
                mock.patch.object(ear, "post_json", lambda *a: self.reply("I don't have access to audio files.")):
            self.assertEqual(ear.Ear().hear(b"RIFF"), "")

    def test_refusal_words(self):
        for said in ("Le di 90 ml de mamadera a las 3", "Wet and dirty diaper", "Se despertó recién", "Perdón, eran 100"):
            self.assertFalse(ear.refused(said), said)
        for answer in ("No se pudo acceder al contenido de audio", "To help with transcription I would need an audio file"):
            self.assertTrue(ear.refused(answer), answer)

    def test_no_key_is_a_brain_error(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(BrainError):
                ear.Ear().hear(b"RIFF")

    def test_clean(self):
        self.assertEqual(ear.clean('Transcription: "le di 90 ml"'), "le di 90 ml")


class Spoken(unittest.TestCase):
    def test_only_the_first_sentences_are_spoken(self):
        backend = FakeBackend()
        client.Voice(backend, FakeEar([])).speak("Uno. Dos. Tres. Cuatro. Cinco.", "es")
        self.assertEqual(backend.spoken, [("Uno. Dos. Tres.", "es")])


class Words(unittest.TestCase):
    def test_numbers_and_times_in_spanish(self):
        self.assertEqual(words.spoken("Anoté 90 ml a las 15:30.", "es"), "Anoté noventa mililitros a las tres y media.")
        self.assertEqual(words.spoken("Hoy tomó 210 ml", "es"), "Hoy tomó doscientos diez mililitros")
        self.assertEqual(words.es(121), "ciento veintiuno")
        self.assertEqual(words.es(100), "cien")

    def test_numbers_and_times_in_english(self):
        self.assertEqual(words.spoken("Logged 150 ml at 06:05.", "en"), "Logged one hundred fifty milliliters at six oh five.")
        self.assertEqual(words.spoken("**Bottles: 210ml** — 2 bottles", "en"), "Bottles: two hundred ten milliliters, two bottles")

    def test_sentences(self):
        self.assertEqual(words.sentences("Listo. ¿Algo más?\nChau"), ["Listo.", "¿Algo más?", "Chau"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
class Audio(unittest.TestCase):
    def wav(self):
        import wave
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(b"\x00\x01" * 8000)
        return buffer.getvalue()

    def test_round_trip_ogg_opus_and_wav(self):
        ogg = audio.to_ogg_opus(self.wav())
        self.assertEqual(ogg[:4], b"OggS")
        self.assertIn(b"OpusHead", ogg[:200])
        back = audio.to_wav(ogg)
        self.assertEqual(back[:4], b"RIFF")

    def test_garbage_is_an_audio_error(self):
        with self.assertRaises(audio.AudioError):
            audio.to_wav(b"not audio")


class TelegramVoice(unittest.TestCase):
    def test_poll_reads_the_voice_file_id(self):
        messenger = TelegramMessenger("t")
        update = {"update_id": 5, "message": {"chat": {"id": 111, "type": "private"}, "from": {"id": 111},
                                              "voice": {"file_id": "VOICE1", "duration": 2}}}
        with mock.patch.object(messenger, "_call", return_value=[update]):
            item = messenger.poll(0, 0)[0]
        self.assertEqual((item.text, item.voice_file_id), ("", "VOICE1"))

    def test_send_voice_is_multipart_with_the_ogg(self):
        messenger = TelegramMessenger("t")
        seen = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(request, timeout):
            seen.update(url=request.full_url, kind=request.headers["Content-type"], body=request.data)
            return Response(json.dumps({"ok": True, "result": {"message_id": 9}}).encode())

        with mock.patch("urllib.request.urlopen", urlopen):
            self.assertEqual(messenger.send_voice("111", b"OggSdata"), 9)
        self.assertTrue(seen["url"].endswith("/sendVoice"))
        self.assertTrue(seen["kind"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="voice"; filename="reply.ogg"', seen["body"])
        self.assertIn(b"OggSdata", seen["body"])


class AgentChannel(unittest.TestCase):
    def channel(self, heard, items):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        agent, config = make_agent(tmp)
        self.addCleanup(agent.close)
        messenger = VoiceMessenger(items)
        channel = Telegram(agent, config, messenger)
        backend = FakeBackend()
        channel.voice = client.Voice(backend, FakeEar(heard))
        return agent, channel, messenger, backend

    def test_a_voice_note_is_logged_and_answered_in_text_and_voice(self):
        agent, channel, messenger, backend = self.channel(["bottle, 120 ml"], [voice_note(1, FAMILY, lang="en")])
        accepted = channel.poll_once(timeout=0)
        self.assertEqual(len(accepted), 1)
        message = [e for e in agent.bus.history if e["kind"] == "message"][0]
        self.assertEqual((message["text"], message["voice"]), ("bottle, 120 ml", True))
        agent.handle(message)
        channel.spoken_thread.join(5)
        self.assertEqual(agent.baby_log.entries("feeding")[0]["details"]["amount_ml"], 120)
        self.assertTrue(messenger.sent[0][1].startswith("«bottle, 120 ml»\n"))
        self.assertEqual(len(messenger.voices), 1)
        self.assertEqual(backend.spoken[0][1], "en")

    def test_a_typed_message_gets_no_voice_note(self):
        agent, channel, messenger, backend = self.channel([], [Incoming(1, FAMILY, "wet diaper", "parent")])
        channel.poll_once(timeout=0)
        agent.handle([e for e in agent.bus.history if e["kind"] == "message"][0])
        self.assertEqual(messenger.voices, [])
        self.assertFalse(messenger.sent[0][1].startswith("«"))

    def test_a_voice_note_that_cannot_be_heard_asks_to_type_it(self):
        agent, channel, messenger, backend = self.channel([], [voice_note(1, FAMILY, "broken")])
        self.assertEqual(channel.poll_once(timeout=0), [])
        self.assertIn("No pude escuchar", messenger.sent[0][1])
        self.assertEqual(agent.bus.count("message"), 0)

    def test_voice_off_says_so(self):
        agent, channel, messenger, backend = self.channel([], [voice_note(1, FAMILY, lang="en")])
        channel.voice = None
        channel.poll_once(timeout=0)
        self.assertIn("only read text", messenger.sent[0][1])

    def test_strangers_are_never_heard(self):
        agent, channel, messenger, backend = self.channel(["bottle"], [voice_note(1, "999")])
        channel.poll_once(timeout=0)
        self.assertEqual(channel.voice.ear.calls, 0)
        self.assertEqual(messenger.sent, [])


class FamiliesVoice(unittest.TestCase):
    def bot(self, heard, **extra):
        app = make(self, **extra)
        onboard(app, "111")
        messenger = VoiceMessenger()
        backend = FakeBackend()
        listener = FakeEar(heard)
        return app, FamiliesBot(app, messenger, poll_timeout_s=0, voice=client.Voice(backend, listener)), messenger, backend, listener

    def test_a_parents_voice_note_logs_and_is_answered_twice(self):
        app, bot, messenger, backend, listener = self.bot(["bottle 90 ml"])
        bot.poll_once_items([voice_note(50, "111", lang="en")])
        bot.spoken_thread.join(5)
        family = app.family(app.store.parent(__import__("parenting_agent.families.store", fromlist=["visitor_id"]).visitor_id("111"))["family_id"])
        self.assertEqual(family.log.entries("feeding")[0]["details"]["amount_ml"], 90)
        self.assertTrue(messenger.sent[0][1].startswith("«bottle 90 ml»\n"))
        self.assertEqual(len(messenger.voices), 1)
        self.assertGreater(app.store.spent_today(), 0)

    def test_strangers_are_not_heard_and_cost_nothing(self):
        app, bot, messenger, backend, listener = self.bot(["bottle"])
        bot.poll_once_items([voice_note(51, "999", lang="en")])
        self.assertEqual(listener.calls, 0)
        self.assertEqual(app.store.spent_today(), 0)
        self.assertIn("only read text", messenger.sent[0][1])

    def test_over_the_cap_a_voice_note_is_not_heard(self):
        app, bot, messenger, backend, listener = self.bot(["bottle"], PA_FAMILIES_FAMILY_USD="0")
        bot.poll_once_items([voice_note(52, "111", lang="en")])
        self.assertEqual(listener.calls, 0)

    def test_a_failed_hearing_asks_to_type_it(self):
        app, bot, messenger, backend, listener = self.bot([])
        bot.poll_once_items([voice_note(53, "111", lang="en")])
        self.assertIn("could not hear", messenger.sent[0][1])
        self.assertEqual(messenger.voices, [])


class Rules(unittest.TestCase):
    now = datetime.datetime(2026, 10, 29, 4, 50, tzinfo=TZ)

    def test_a_named_clock_time_is_the_latest_one(self):
        self.assertEqual(rules.latest_time("2026-10-28T04:30:00", self.now, "se durmió a las 4 y media"), "2026-10-29T04:30:00-03:00")
        self.assertEqual(rules.latest_time("2026-10-29T23:00:00-03:00", self.now, "a las 11"), "2026-10-28T23:00:00-03:00")
        self.assertEqual(rules.latest_time("2026-10-27T23:00:00", self.now, "anoche a las 11"), "2026-10-27T23:00:00")

    def test_the_time_the_parent_named(self):
        self.assertEqual(rules.named_time("le di 90 ml a las 3", self.now), "2026-10-29T03:00:00-03:00")
        self.assertEqual(rules.named_time("le di 90 ml a las 3", self.now.replace(hour=15, minute=20)), "2026-10-29T15:00:00-03:00")
        self.assertEqual(rules.named_time("se durmió a las 4 y media", self.now), "2026-10-29T04:30:00-03:00")
        self.assertEqual(rules.named_time("She fell asleep at 3:15", self.now), "2026-10-29T03:15:00-03:00")
        self.assertIsNone(rules.named_time("teta 10 minutos", self.now))
        self.assertIsNone(rules.named_time("de las 2 a las 3", self.now))
        self.assertIsNone(rules.named_time("ayer a las 3", self.now))

    def test_kinds_said(self):
        self.assertEqual(rules.kinds_said("She fell asleep at 3:15"), {"sleep"})
        self.assertEqual(rules.kinds_said("mamadera 120 y pañal mojado"), {"feeding", "diaper"})
        self.assertEqual(rules.kinds_said("Breastfed on the right side for 12 minutes"), {"feeding"})

    def test_one_diaper_is_one_entry(self):
        calls = [{"id": "a", "name": "log_baby_event", "arguments": {"kind": "diaper", "details": {"wet": True}}},
                 {"id": "b", "name": "log_baby_event", "arguments": {"kind": "diaper", "details": {"solid": True}}}]
        merged = rules.one_diaper(calls, "She just pooped, dirty diaper")
        self.assertEqual(len(merged), 1)
        self.assertEqual(rules.said_only("She just pooped, dirty diaper", "diaper", merged[0]["arguments"]["details"])[0], {"solid": True})
        self.assertEqual(len(rules.one_diaper(calls, "dos pañales, uno con pis y otro con caca")), 2)

    def test_wet_and_dirty_only_when_said(self):
        self.assertEqual(rules.said_only("pañal mojado y con caca", "diaper", {"wet": True, "solid": True})[0], {"wet": True, "solid": True})
        self.assertEqual(rules.said_only("wet diaper", "diaper", {"wet": True, "solid": True})[0], {"wet": True})


class ScriptedBrain:
    name, model, destination = "scripted", "test", "none"

    def __init__(self, replies):
        self.replies = list(replies)

    def step(self, system, transcript, tools):
        from parenting_agent.agent.brain import Reply
        return self.replies.pop(0) if self.replies else Reply("Done.")


class Guards(unittest.TestCase):
    def agent(self, replies):
        from parenting_agent.agent.brain import Reply  # noqa: F401
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        agent, _ = make_agent(tmp)
        self.addCleanup(agent.close)
        agent.brain = ScriptedBrain(replies)
        return agent

    def test_a_sleep_note_never_logs_an_earlier_bottle_again(self):
        from parenting_agent.agent.brain import Reply
        calls = [{"id": "1", "name": "log_baby_event", "arguments": {"kind": "feeding", "details": {"amount_ml": 60}}},
                 {"id": "2", "name": "log_baby_event", "arguments": {"kind": "sleep", "details": {"action": "start"}}}]
        agent = self.agent([Reply(tool_calls=calls), Reply("Logged.")])
        agent.handle({"kind": "message", "channel": "console", "text": "She fell asleep"})
        self.assertEqual([e["kind"] for e in agent.baby_log.entries()], ["sleep"])

    def test_the_named_time_wins_over_the_time_of_the_message(self):
        from parenting_agent.agent.brain import Reply
        calls = [{"id": "1", "name": "log_baby_event", "arguments": {"kind": "feeding", "details": {"amount_ml": 90}}}]
        agent = self.agent([Reply(tool_calls=calls), Reply("Logged.")])
        agent.handle({"kind": "message", "channel": "console", "text": "le di 90 ml de mamadera a las 3"})
        self.assertIn(agent.baby_log.entries("feeding")[0]["ts"][11:16], ("03:00", "15:00"))


class Image(unittest.TestCase):
    def test_the_image_bakes_the_revisions_the_code_loads(self):
        from pathlib import Path
        from parenting_agent.voice.tts import MODELS
        dockerfile = (Path(__file__).resolve().parent.parent / "deploy" / "voice" / "Dockerfile").read_text()
        for repo, revision in MODELS.values():
            self.assertIn(f"get('{repo}', revision='{revision}')", dockerfile)
        self.assertIn("HF_HUB_OFFLINE=1", dockerfile)

    def test_the_image_exports_the_int8_decoder_and_points_the_voice_at_it(self):
        from pathlib import Path
        dockerfile = (Path(__file__).resolve().parent.parent / "deploy" / "voice" / "Dockerfile").read_text()
        self.assertIn("python -m parenting_agent.voice.onnx_decoder /opt/mms-onnx", dockerfile)
        self.assertIn("ENV PA_VOICE_ONNX=/opt/mms-onnx", dockerfile)
        self.assertLess(dockerfile.index("HF_HUB_OFFLINE=1"), dockerfile.index("onnx_decoder /opt/mms-onnx"))


class OnnxDecoder(unittest.TestCase):
    class Model:
        decoder = "torch decoder"

    def test_without_a_folder_the_decoder_stays_in_torch(self):
        from parenting_agent.voice.tts import MmsVoice
        voice, model = MmsVoice(onnx_dir=""), self.Model()
        voice.use_onnx_decoder("es", model)
        self.assertEqual((voice.decoders, model.decoder), ({"es": "torch"}, "torch decoder"))

    def test_a_folder_without_the_file_fails_loudly(self):
        import tempfile
        from parenting_agent.voice.tts import MmsVoice
        voice = MmsVoice(onnx_dir=tempfile.mkdtemp())
        with self.assertRaises(FileNotFoundError):
            voice.use_onnx_decoder("es", self.Model())

    def test_the_file_names(self):
        from parenting_agent.voice import onnx_decoder
        self.assertEqual(onnx_decoder.path("/x", "es").name, "mms-es-decoder-int8.onnx")
        self.assertEqual(onnx_decoder.path("/x", "en", int8=False).name, "mms-en-decoder.onnx")
        self.assertEqual(sorted(onnx_decoder.CALIBRATION), ["en", "es"])


class Build(unittest.TestCase):
    def test_none_is_off_and_a_url_is_the_service(self):
        self.assertIsNone(client.build(None))
        self.assertIsNone(client.build({"service": "none"}))
        voice = client.build({"service": "http://voice:8800"})
        self.assertIsInstance(voice.backend, client.RemoteVoice)
        self.assertEqual(voice.ear.model, "meta-models/muse-spark-open-1026")

    def test_the_service_is_never_reached_through_a_proxy(self):
        remote = client.RemoteVoice("http://voice:8800")
        self.assertFalse(any(isinstance(h, __import__("urllib.request").request.ProxyHandler) and h.proxies
                             for h in remote.opener.handlers))


if __name__ == "__main__":
    unittest.main()
