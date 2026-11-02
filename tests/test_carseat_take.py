"""The car seat coach driven by voice on the glasses path: the request starts it without the brain, the close-up card
names the guide, and the take script's own pieces (the utterance cutter, the mock feed, the frame splitter)."""
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from parenting_agent import hud_cards as cards
from parenting_agent.carseat.plugin import STARTED, CarSeatCoach, wants_install
from tests.test_carseat import ROOT, FakeVision, FrameFeed

sys.path.insert(0, str(ROOT / "scripts"))
import carseat_glasses_take as take  # noqa: E402


class InstallRequest(unittest.TestCase):
    def test_install_requests_in_both_languages_and_what_is_not_one(self):
        for text in ("Agente, ayúdame a instalar la silla de la auto.", "ayudame a instalar la silla del auto",
                     "poné la sillita en el auto", "Help me install the car seat.", "let's set up the car seat"):
            self.assertTrue(wants_install(text), text)
        for text in ("¿se puede dormir en la silla del auto?", "instalé la silla alta", "help me with the car seat",
                     "se cayó instalando la silla del auto y no respira"):
            self.assertFalse(wants_install(text), text)

    def agent(self, tmp, allowed=True):
        from parenting_agent.agent import build
        from parenting_agent.agent import config as config_mod
        config = config_mod.load()
        tools = ["start_car_seat_coach", "answer_car_seat_check"] if allowed else []
        config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                       "plugins": [], "allowed_tools": config["allowed_tools"] + tools,
                       "people": {"gonza": {"name": "Gonza", "lang": "es"}},
                       "car_seat": {"skill": str(ROOT / "skills/car-seat.json"), "channel": "glasses"}})
        agent = build(config)
        cwd = Path.cwd()
        try:
            os.chdir(ROOT)
            plugin = CarSeatCoach(agent, config, vision=FakeVision({}), source=FrameFeed(frames=2000), quiet=True)
        finally:
            os.chdir(cwd)
        return agent, plugin

    def hear(self, agent, text):
        message = agent.bus.publish("message", channel="glasses", text=text, person="gonza", chat_id="gonza")
        agent.current_event = message
        agent.handle(message)
        agent.current_event = None

    def test_the_request_starts_the_coach_without_the_brain_in_the_parents_language(self):
        """Oct 30 speech runs: Muse answered "Vamos paso a paso" in 2 of 4 takes and the coach never started."""
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = self.agent(tmp)
            try:
                self.hear(agent, "ayúdame a instalar la silla del auto.")
                self.assertTrue(plugin.running())
                replies = [e["text"] for e in agent.bus.history if e["kind"] == "reply"]
                self.assertEqual(replies, [STARTED["es"]])
                self.assertFalse(any(e["kind"] == "brain_call" for e in agent.bus.history))
                deadline = time.monotonic() + 3
                while not any(e["kind"] == "carseat_step" for e in agent.bus.history) and time.monotonic() < deadline:
                    time.sleep(0.02)
                first = next(e for e in agent.bus.history if e["kind"] == "voice" and e.get("skill") == "car-seat")
                self.assertEqual(first["lang"], "es")
                reply = next(e for e in agent.bus.history if e["kind"] == "reply")
                self.assertLess(agent.bus.history.index(reply), agent.bus.history.index(first),
                                "the short reply first, then step 1, so the lens ends on the step")
                self.assertEqual(plugin.asked["channel"], "glasses")
                self.hear(agent, "ayudame a instalar la silla del auto")
                self.assertEqual(sum(e["kind"] == "skill_armed" for e in agent.bus.history), 1, "never a second coach")
            finally:
                plugin.stop()
                plugin.thread.join(timeout=5)
                agent.close()

    def test_without_the_tool_allowed_the_words_go_to_the_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = self.agent(tmp, allowed=False)
            try:
                self.assertIsNone(plugin.take_answer({"channel": "glasses"}, "ayudame a instalar la silla del auto"))
                self.assertFalse(plugin.running())
            finally:
                agent.close()


class AnswerOrder(unittest.TestCase):
    def test_the_coach_moves_on_only_after_its_short_reply(self):
        from parenting_agent.carseat.coach import Coach
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin = InstallRequest.agent(None, tmp)
            try:
                coach = Coach(plugin.skill_cfg, agent.bus, None, None, plugin.seat, plugin.car, lang="es")
                plugin.coach, coach.asking = coach, "car_position"
                self.assertEqual(plugin.take_answer({"channel": "glasses"}, "Sí, está atrás."), "Anotado: sí.")
                self.assertNotIn("car_position", coach.answers, "not before the reply is said")
                agent.bus.publish("reply", channel="glasses", text="Anotado: sí.")
                self.assertEqual(coach.answers["car_position"], "Sí, está atrás.")
            finally:
                agent.close()


class CloseUpCard(unittest.TestCase):
    def test_the_close_up_card_names_the_guide(self):
        near = cards.car_seat("lap_guides", "es", 3, 10, view="near")
        self.assertEqual(near["detail"], "Acercá el teléfono a la guía de la puerta")
        self.assertEqual(cards.car_seat("lap_guides", "es", 3, 10, view="far")["detail"],
                         "Acercá el teléfono a la guía del otro lado")
        self.assertEqual(cards.car_seat("shoulder_guide", "en", 5, 10, view="rear")["detail"],
                         "Bring the phone to the rear guide")
        self.assertEqual(cards.car_seat("lap_guides", "es", 3, 10)["detail"], "Decí listo cuando termines")
        summary = cards.car_seat("summary", "es")
        self.assertIn("No es un veredicto", summary["detail"])


class TakePieces(unittest.TestCase):
    def test_the_cutter_cuts_one_utterance_and_hears_nothing_while_muted(self):
        rate = 16000
        quiet = np.random.default_rng(0).normal(0, 0.001, rate).astype(np.float32)
        t = np.arange(int(0.6 * rate)) / rate
        voice = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        audio = np.concatenate([quiet, voice, quiet, quiet])
        cutter = take.Cutter()
        got = []
        for n in range(0, len(audio), 1600):
            got += cutter.feed(audio[n:n + 1600], 1000.0 + n / rate)
        self.assertEqual(len(got), 1)
        samples, start, end = got[0]
        self.assertAlmostEqual(start, 1001.0, delta=0.1)
        self.assertAlmostEqual(end, 1001.6, delta=0.1)
        self.assertGreater(len(samples), 0.6 * rate)
        self.assertTrue(take.wav_bytes(samples).startswith(b"RIFF"))
        muted = take.Cutter()
        muted.muted = True
        self.assertEqual(muted.feed(audio, 0.0), [])

    def test_the_feed_plays_the_step_then_loops_the_hold_until_the_next_step(self):
        cursor = take.Cursor(480.0, fps=10)
        cursor.play((484, 485), hold=(485, 486))
        shown = [cursor.step(1000) for _ in range(40)]
        self.assertEqual(shown[:11], list(range(40, 51)))
        self.assertTrue(cursor.played())
        self.assertTrue(all(50 <= i <= 60 for i in shown[11:]), "the hold stays inside its span")
        self.assertLess(shown[-1], max(shown), "and turns back")
        cursor.play((490, 491))
        self.assertFalse(cursor.played())
        self.assertEqual(cursor.step(1000), 100)

    def test_jpegs_are_split_from_one_stream(self):
        stream = io.BytesIO(b"junk\xff\xd8one\xff\xd9\xff\xd8two\xff\xd9")
        self.assertEqual(list(take.jpegs(stream)), [b"\xff\xd8one\xff\xd9", b"\xff\xd8two\xff\xd9"])

    def test_the_take_runs_the_agent_dry_and_quiet(self):
        config = take.agent_config()
        self.assertFalse(config["house"]["live"])
        self.assertTrue(config["car_seat"]["quiet"])
        self.assertEqual(config["car_seat"]["source"], f"glasses:{take.PORT}")
        self.assertIn("start_car_seat_coach", config["allowed_tools"])
        self.assertNotIn("log_baby_event", config["allowed_tools"])


if __name__ == "__main__":
    unittest.main()
