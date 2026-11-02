"""Speech on the glasses: the gate that keeps talk to the baby away from the agent, the /hear endpoint, and an utterance
heard by the ear becoming a message only when it was meant for the agent."""
import io
import json
import tempfile
import time
import unittest
import urllib.request
import wave

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent import rules
from parenting_agent.glasses import GlassesHub, with_dropped_words
from parenting_agent.glasses_speech import Gate, plain, race, transcript, word_errors
from tests.test_glasses import Events, call


def wav(seconds=0.5, rate=16000):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))
    return out.getvalue()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class GateRules(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.gate = Gate(clock=self.clock)

    def test_start_phrases_pass_any_time(self):
        for said in ("changing time", "Changing time.", "Hora del cambio", "¡Hora de cambiarlo!"):
            self.assertEqual(self.gate.decide(said, "gonza")["why"], "start phrase", said)

    def test_a_command_is_judged_on_its_first_sentence(self):
        decision = self.gate.decide("Changing time. Please check the audio for the exact instructions.", "gonza")
        self.assertEqual((decision["take"], decision["text"]), (True, "Changing time."))
        self.gate.wait("gonza", "finish")
        self.assertEqual(self.gate.decide("Done. It was dirty.", "gonza")["text"], "Done. It was dirty.", "short: all of it")

    def test_talk_to_the_baby_never_reaches_the_agent(self):
        for said in ("Hola Theo, ¿quién es el bebé más lindo?", "sí", "listo", "ya llamé", "done", "what a big boy", ""):
            self.assertFalse(self.gate.decide(said, "gonza")["take"], said)

    def test_the_wake_word_carries_a_question_without_itself(self):
        decision = self.gate.decide("Agente, ¿cuándo comió por última vez?", "gonza")
        self.assertEqual((decision["take"], decision["text"]), (True, "¿cuándo comió por última vez?"))
        self.assertEqual(self.gate.decide("Hey agent, how many diapers today?", "gonza")["text"], "how many diapers today?")
        self.assertTrue(self.gate.decide("A gente, ayúdame con la silla.", "gonza")["take"], "the ear split Agente")
        self.assertFalse(self.gate.decide("La gente dice que duerme poco.", "gonza")["take"], "la gente is just people")

    def test_the_wake_word_alone_opens_a_short_window(self):
        self.assertFalse(self.gate.decide("Agente.", "gonza")["take"])
        self.assertTrue(self.gate.decide("¿Cuándo comió?", "gonza")["take"])
        self.assertFalse(self.gate.decide("¿Y ahora?", "gonza")["take"], "one utterance per wake word")
        self.gate.decide("Agent", "gonza")
        self.clock.now += 9
        self.assertFalse(self.gate.decide("When did she eat?", "gonza")["take"], "the window closes")

    def test_short_answers_pass_only_while_the_agent_waits_for_them(self):
        self.gate.wait("gonza", "finish")
        self.assertTrue(self.gate.decide("Done, it was dirty.", "gonza")["take"])
        self.assertTrue(self.gate.decide("Listo, solo pis.", "gonza")["take"])
        self.assertFalse(self.gate.decide("sí", "gonza")["take"], "finish waits for done, not yes")
        self.assertFalse(self.gate.decide("listo", "ceci")["take"], "waits are per wearer")
        self.gate.wait("gonza", "answer")
        self.assertTrue(self.gate.decide("Sí.", "gonza")["take"])
        self.assertFalse(self.gate.decide("Sí, pero mirá qué lindo está hoy el bebé", "gonza")["take"], "an answer is short")
        self.gate.wait("gonza", "ack")
        self.assertTrue(self.gate.decide("Ya llame", "gonza")["take"], "the ear may drop the accent")
        self.gate.wait("gonza", "ack", False)
        self.assertFalse(self.gate.decide("Ya llamé", "gonza")["take"])
        self.clock.now += 31 * 60
        self.assertFalse(self.gate.decide("Listo", "gonza")["take"], "a wait runs out")

    def test_plain_words_and_word_errors(self):
        self.assertEqual(plain("¡Sí! ¿Cuándo comió?"), "si cuando comio")
        self.assertEqual(word_errors("Done, it was dirty.", "done it was dirty"), (0, 4))
        self.assertEqual(word_errors("¿Cuándo comió por última vez?", "cuando comio por ultima"), (1, 5))
        self.assertEqual(word_errors("ya llamé", "ya llame al 911"), (2, 2))


class HearEndpoint(unittest.TestCase):
    def setUp(self):
        self.heard = []
        self.hub = GlassesHub(port=0, host="127.0.0.1", token="t", person="gonza")
        self.hub.on_hear = lambda audio, person, meta: self.heard.append((audio, person, meta))

    def tearDown(self):
        self.hub.close()

    def wait(self, count=1):
        deadline = time.monotonic() + 5
        while len(self.heard) < count and time.monotonic() < deadline:
            time.sleep(0.01)

    def test_a_wav_utterance_reaches_the_ear_with_its_end_time(self):
        audio = wav()
        request = urllib.request.Request(
            self.hub.url + "hear", data=audio, method="POST",
            headers={"Authorization": "Bearer t", "Content-Type": "audio/wav", "X-Speech-End-Unix": "1761870000.25"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 202)
        self.wait()
        got, person, meta = self.heard[0]
        self.assertEqual((got, person, meta["speech_end_unix"], meta["source"]), (audio, "gonza", 1761870000.25, "glasses mic"))

    def test_text_from_glasses_that_transcribe(self):
        body = json.dumps({"text": "listo"}).encode()
        self.assertEqual(call(self.hub, "hear", body, token="t", kind="application/json")[0], 202)
        self.wait()
        self.assertEqual((self.heard[0][0], self.heard[0][2]["text"]), (None, "listo"))

    def test_refused_without_token_or_with_neither_audio_nor_text(self):
        self.assertEqual(call(self.hub, "hear", wav())[0], 401)
        self.assertEqual(call(self.hub, "hear", b"not audio", token="t", kind="audio/wav")[0], 400)
        self.hub.on_hear = None
        self.assertEqual(call(self.hub, "hear", wav(), token="t", kind="audio/wav")[0], 503)
        self.assertEqual(self.heard, [])


class FakeEar:
    def __init__(self, words):
        self.words = list(words)

    def hear(self, audio):
        word = self.words.pop(0)
        if isinstance(word, Exception):
            raise word
        return word


class Racing(unittest.TestCase):
    """Several ear calls at once, the first real transcript wins: Muse sometimes answers with nothing or as an assistant."""

    def ears(self, answers):
        answers = list(answers)

        class One:
            def hear(self, audio):
                word, delay = answers.pop(0)
                time.sleep(delay)
                if isinstance(word, Exception):
                    raise word
                return word
        return One

    def test_the_first_transcript_wins_over_nothing_and_assistant_talk(self):
        make = self.ears([("", 0.0), ("¿En qué puedo ayudarte?", 0.01), ("Listo", 0.05)])
        text, info = race(make, b"wav", calls=3, rounds=1)
        self.assertEqual((text, info["calls"]), ("Listo", 3))
        advice = "Agente, el bebé está azul y no respira.\n\nEmergencia médica: llamá ya a emergencias."
        self.assertEqual(race(self.ears([(advice, 0)]), b"wav", calls=1, rounds=1)[0], "Agente, el bebé está azul y no respira.")
        self.assertFalse(transcript("Hola, ¿en qué puedo ayudarte?"))
        self.assertTrue(transcript("Ya llamé"))

    def test_a_silent_round_is_asked_again_then_gives_up(self):
        text, info = race(self.ears([("", 0), ("", 0), ("Sí", 0)]), b"wav", calls=2, rounds=2)
        self.assertEqual((text, info["round"]), ("Sí", 2))
        self.assertEqual(race(self.ears([("", 0)] * 4), b"wav", calls=2, rounds=2)[0], "")

    def test_slower_calls_reach_late_after_the_race(self):
        late = []
        make = self.ears([("Hola Theo", 0.0), ("el bebé no respira", 0.15), (RuntimeError("503"), 0.1)])
        text, info = race(make, b"wav", calls=3, rounds=1, late=late.append)
        self.assertEqual(text, "Hola Theo")
        self.assertEqual(info["candidates"], ["Hola Theo"])
        deadline = time.monotonic() + 2
        while not late and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.1)
        self.assertEqual(late, ["el bebé no respira"])

    def test_errors_only_when_every_call_failed(self):
        self.assertEqual(race(self.ears([(RuntimeError("503"), 0), ("Done", 0.02)]), b"wav", calls=2, rounds=1)[0], "Done")
        with self.assertRaises(RuntimeError):
            race(self.ears([(RuntimeError("503"), 0)] * 2), b"wav", calls=2, rounds=1)


class HeardByTheAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = config_mod.load(None)
        config.update({"data_dir": self.tmp.name, "env_file": f"{self.tmp.name}/none.env",
                       "glasses": {"port": 0, "host": "127.0.0.1", "token": "t", "person": "gonza"},
                       "plugins": ["parenting_agent.glasses:Glasses"]})
        self.agent = build(config)
        self.channel = self.agent.plugins[0]
        self.channel.race_cfg = {"calls": 1, "rounds": 1}
        self.messages = []
        self.agent.bus.subscribe(lambda e: self.messages.append(e["text"]), ["message"])

    def tearDown(self):
        self.channel.stop()
        self.agent.close()
        self.tmp.cleanup()

    def use_ear(self, words):
        ear = FakeEar(words)
        self.channel._make_ear = lambda: ear

    def speech(self):
        return [e for e in self.agent.bus.history if e["kind"] == "speech"]

    def test_only_words_meant_for_the_agent_become_messages(self):
        self.use_ear(["Hola Theo, qué lindo", "Changing time", "Agente, ¿cuándo comió?", RuntimeError("down")])
        for _ in range(4):
            self.channel.hear(wav(), "gonza", {"speech_end_unix": 1.0})
        self.assertEqual(self.messages, ["Changing time", "¿cuándo comió?"])
        took = [(e.get("text"), e["took"], e["why"]) for e in self.speech()]
        self.assertEqual(took[:3], [(None, False, "not for the agent"), ("Changing time", True, "start phrase"),
                                    ("Agente, ¿cuándo comió?", True, "wake word")])
        self.assertEqual((took[3][1], took[3][2]), (False, "ear failed"))
        self.assertIn("down", self.speech()[3]["error"])
        self.assertEqual(self.speech()[1]["speech_end_unix"], 1.0)

    def test_a_dropped_utterance_keeps_no_words_in_the_log(self):
        self.use_ear(["Hola Theo, qué lindo", "agente", "Agente, ¿cuándo comió?"])
        words = []
        self.channel.on_dropped_words = words.append
        for _ in range(3):
            self.channel.hear(wav(), "gonza", {"speech_end_unix": 1.0, "speech_s": 2.5})
        dropped, wake, kept = self.speech()
        for event in (dropped, wake):
            self.assertFalse(event["took"])
            self.assertNotIn("text", event)
            self.assertNotIn("ear_answers", event)
            self.assertEqual((event["person"], event["speech_s"], event["speech_end_unix"]), ("gonza", 2.5, 1.0))
            self.assertIn("heard_unix", event)
        self.assertEqual((dropped["why"], wake["why"]), ("not for the agent", "wake word, listening"))
        self.assertNotIn("Theo", json.dumps(self.speech(), ensure_ascii=False))
        self.assertEqual((kept["text"], kept["ear_answers"]), ("Agente, ¿cuándo comió?", ["Agente, ¿cuándo comió?"]))
        self.assertEqual([(w["text"], w["why"]) for w in words],
                         [("Hola Theo, qué lindo", "not for the agent"), ("agente", "wake word, listening")])
        restored = [e.get("text") for e in with_dropped_words(self.speech(), words)]
        self.assertEqual(restored, ["Hola Theo, qué lindo", "agente", "Agente, ¿cuándo comió?"])

    def test_the_changing_table_and_a_red_flag_open_their_short_answers(self):
        events = Events(self.channel.hub)
        self.assertTrue(events.wait(lambda e: e["kind"] == "hello"))
        self.use_ear(["done, it was dirty", "done, it was dirty", "ya llame"])
        self.channel.hear(wav(), "gonza")
        self.agent.bus.publish("changing_armed", via="brain", since_words_s=1.0)
        self.channel.hear(wav(), "gonza")
        self.assertEqual(self.messages, ["done, it was dirty"])
        self.channel.send_card({"topic": "red_flag", "title": "Llamá al 911 ya", "status": "", "alert": True, "sticky": True},
                               "gonza", "red flag", "telegram")
        self.channel.hear(wav(), "gonza")
        self.assertEqual(self.messages[-1], "ya llame")
        self.assertTrue(events.wait(lambda e: e["kind"] == "red_flag_clear"))
        self.assertTrue(events.wait(lambda e: e["kind"] == "heard" and e["text"] == "ya llame" and e["took"]))

    def test_a_question_the_agent_asks_on_the_glasses_opens_a_yes(self):
        self.use_ear(["Sí.", "Sí."])
        self.channel.hear(wav(), "gonza")
        self.agent.bus.publish("reply", channel="glasses", chat_id="gonza", text="¿Empezamos con la silla?")
        self.channel.hear(wav(), "gonza")
        self.assertEqual(self.messages, ["Sí."])

    def red_flags(self):
        """The messages the agent's gate answers with the 911 line."""
        return [text for text in self.messages if rules.is_emergency(text)]

    def test_a_red_flag_said_without_the_wake_word_still_reaches_the_agent(self):
        self.use_ear(["El bebé está azul y no respira", "Theo no respira, está morado", "Respira tranquilo, ya se durmió",
                      "Le puse el body azul"])
        decisions = [self.channel.hear(wav(), "gonza") for _ in range(4)]
        self.assertEqual([d["why"] for d in decisions], ["red flag", "red flag", "not for the agent", "not for the agent"])
        self.assertEqual(self.messages, ["El bebé está azul y no respira", "Theo no respira, está morado"])
        self.assertEqual(self.speech()[0]["red_flag"], "El bebé está azul y no respira")

    def test_a_misheard_red_flag_still_brings_the_911_line(self):
        # Oct 30, rehearsal 1 of results/glasses-speech: "está azul y no respira bien" heard as "está azulino respira bien"
        self.use_ear(["Agente, está azulino respira bien.", "He is not breating, agent"])
        first = self.channel.hear(wav(), "gonza")
        self.assertEqual(first, {"take": True, "text": "esta azul y no respira bien", "why": "red flag"})
        self.channel.hear(wav(), "gonza")
        self.assertEqual(self.red_flags(), ["esta azul y no respira bien", "he is not breathing agent"])

    def test_a_red_flag_in_a_slower_call_reaches_the_agent_once(self):
        delays = iter([(0.0, "Hola mi amor"), (0.2, "el bebé no respira"), (0.3, "el bebé no respira")])

        class Slow:
            def hear(self, audio):
                delay, words = next(delays)
                time.sleep(delay)
                return words
        self.channel._make_ear = Slow
        self.channel.race_cfg = {"calls": 3, "rounds": 1}
        decision = self.channel.hear(wav(), "gonza")
        self.assertEqual(decision["why"], "not for the agent")
        deadline = time.monotonic() + 3
        while not self.messages and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.4)
        self.assertEqual(self.messages, ["el bebé no respira"])
        self.assertEqual([e["why"] for e in self.agent.bus.history if e["kind"] == "speech_red_flag"],
                         ["red flag in a later ear call"])

    def test_the_car_seat_question_opens_one_yes(self):
        self.channel.hub.camera_person = "gonza"
        self.use_ear(["Sí.", "Sí."])
        self.agent.bus.publish("carseat_step", step="car_position", step_kind="ask")
        self.channel.hear(wav(), "gonza")
        self.channel.hear(wav(), "gonza")
        self.assertEqual(self.messages, ["Sí."])

    def test_a_car_seat_camera_step_hears_listo_and_ya_until_the_summary(self):
        self.channel.hub.camera_person = "gonza"
        self.use_ear(["Listo.", "Ya.", "Ya comió hace un rato.", "Listo."])
        self.agent.bus.publish("carseat_step", step="lap_guides", step_kind="camera")
        self.channel.hear(wav(), "gonza")
        self.channel.hear(wav(), "gonza")
        self.channel.hear(wav(), "gonza")
        self.assertEqual(self.messages, ["Listo.", "Ya."], "only the short done words while a camera step waits")
        self.agent.bus.publish("carseat_summary", text="fin", results={})
        self.channel.hear(wav(), "gonza")
        self.assertEqual(self.messages, ["Listo.", "Ya."], "after the summary nothing waits")


if __name__ == "__main__":
    unittest.main()
