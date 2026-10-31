"""Tests for the local cry reason from the sound (issue #161): the head, the guess, the blend with the log, the wiring.

Offline: a fake listener whose embedding is chosen by the test, the tone listener from test_sounds, the simulated-week
fixture. The PANNs run on the held-out Donate-a-Cry test is scripts/cry_reason_train.py, the live run
scripts/cry_reason_live.py.
"""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from parenting_agent import cry_reason, cry_sound, hearing, hud_cards
from parenting_agent.agent import rules
from parenting_agent.house_sounds import HouseSounds
from tests.test_sounds import ToneListener, events, make_agent, tone

TZ = datetime.timezone(datetime.timedelta(hours=-3))
REPO = Path(__file__).resolve().parent.parent
NOW = datetime.datetime(2026, 10, 24, 14, 0, tzinfo=TZ)


def one_hot_head(speak=()):
    """A head that reads the class straight off the first five embedding numbers."""
    w = np.zeros((8, 5), np.float32)
    w[:5, :5] = 10 * np.eye(5)
    return cry_sound.Head(np.zeros(8), np.ones(8), w, np.zeros(5), meta={"speak": list(speak)})


class FakeEmbedder(ToneListener):
    def __init__(self, label="hungry", fail=False):
        self.label, self.fail, self.calls = label, fail, []

    def embed(self, samples):
        self.calls.append(samples.size)
        if self.fail:
            raise hearing.Unavailable("worker gone")
        x = np.zeros(8, np.float32)
        x[cry_sound.CLASSES.index(self.label)] = 1
        return x


def log_result(top="hungry", likely=True, text="Probably hungry: last feed 2 h 51 min ago, he eats about every 2 h 26 min."):
    return {"top": top, "likely": likely, "text": text, "ranked": [], "computed_from": []}


def guess(label, speak=True, confidence=0.9):
    return {"label": label, "confidence": confidence, "speak": speak}


class HeadTest(unittest.TestCase):
    def test_fit_learns_separable_classes_and_round_trips(self):
        rng = np.random.default_rng(0)
        y = np.repeat(np.arange(5), 20)
        x = rng.normal(size=(100, 16)).astype(np.float32)
        x[np.arange(100), y] += 4
        head = cry_sound.Head.fit(x, y, l2=0.1, balanced=True, steps=300)
        self.assertGreater(np.mean(head.probs(x).argmax(axis=1) == y), 0.95)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "head.json"
            path.write_text(json.dumps(head.to_json({"speak": ["hungry"]})))
            again = cry_sound.Head.load(path)
        self.assertEqual(again.meta["speak"], ["hungry"])
        np.testing.assert_allclose(again.probs(x[:3]), head.probs(x[:3]), atol=1e-3)
        np.testing.assert_allclose(head.probs(x).sum(axis=1), 1, atol=1e-5)

    def test_shipped_head_matches_the_held_out_test(self):
        head = cry_sound.Head.load()
        evaluation = json.loads((REPO / "results/cry-reason/eval.json").read_text())
        self.assertEqual(head.w.shape, (2048, 5))
        self.assertEqual(head.meta["speak"], evaluation["speak"])
        self.assertEqual(head.meta["test"]["gate_passed"], evaluation["gate_passed"])
        self.assertIn("ODbL", head.meta["data"])

    def test_split_was_committed_with_a_protocol_and_no_device_on_both_sides(self):
        split = json.loads((REPO / "results/cry-reason/split.json").read_text())
        train = {c["device"] for c in split["clips"] if c["split"] == "train"}
        test = {c["device"] for c in split["clips"] if c["split"] == "test"}
        self.assertFalse(train & test)
        self.assertIn("decision_rule", split["protocol"])


class GuessTest(unittest.TestCase):
    def test_guess_reads_the_embedding_and_says_only_cleared_classes(self):
        listener = FakeEmbedder("tired")
        ears = cry_sound.CrySound(listener, {"enabled": True, "clip_s": 2}, head=one_hot_head(speak=["hungry"]))
        got = ears.guess(np.zeros(5 * hearing.RATE, np.float32))
        self.assertEqual((got["label"], got["speak"], got["host"]), ("tired", False, "local"))
        self.assertEqual(listener.calls, [2 * hearing.RATE])
        listener.label = "hungry"
        self.assertTrue(ears.guess(np.zeros(hearing.RATE, np.float32))["speak"])

    def test_off_or_a_broken_worker_skips_without_raising(self):
        head = one_hot_head()
        self.assertIn("skipped", cry_sound.CrySound(FakeEmbedder(), {"enabled": False}, head=head).guess(np.zeros(10)))
        got = cry_sound.CrySound(FakeEmbedder(fail=True), {"enabled": True}, head=head).guess(np.zeros(10))
        self.assertIn("worker gone", got["skipped"])


class CombineTest(unittest.TestCase):
    def test_a_guess_that_did_not_clear_the_test_is_logged_not_said(self):
        out = cry_sound.combine(log_result(), guess("tired", speak=False), [], NOW)
        self.assertEqual(out["text"], log_result()["text"])
        self.assertEqual(out["sound"]["label"], "tired")

    def test_agreeing_and_disagreeing_sound(self):
        self.assertTrue(cry_sound.combine(log_result(), guess("hungry"), [], NOW)["text"].endswith("The sound agrees."))
        out = cry_sound.combine(log_result(), guess("discomfort"), [], NOW)
        self.assertIn("From the sound alone, a guess: uncomfortable", out["text"])
        self.assertEqual(out["top"], "hungry")  # the log's ranking stays

    def test_belly_pain_is_check_on_him_now_never_pain(self):
        out = cry_sound.combine(log_result(), guess("belly_pain"), [], NOW)
        self.assertTrue(out["text"].startswith("The cry sounds like ones parents tagged as hard crying. Check on him now."))
        self.assertTrue(cry_reason.no_medical(out["text"]))
        self.assertFalse(out["safety_line"])
        self.assertNotIn("pain", out["text"].lower())

    def test_belly_pain_with_a_red_flag_in_the_log_adds_the_fixed_line(self):
        entries = [{"kind": "note", "time": (NOW - datetime.timedelta(hours=2)).isoformat(),
                    "note": "He threw up green after the feed", "ref": "note@1"}]
        out = cry_sound.combine(log_result(), guess("belly_pain"), entries, NOW)
        self.assertTrue(out["text"].endswith(rules.URGENT_REPLY["red_flag"]["en"]))
        old = [{**entries[0], "time": (NOW - datetime.timedelta(hours=30)).isoformat()}]
        self.assertFalse(cry_sound.combine(log_result(), guess("belly_pain"), old, NOW)["safety_line"])

    def test_every_spoken_class_passes_the_no_medical_guard(self):
        for label in ("hungry", "tired", "discomfort", "burping"):
            text = cry_sound.combine(log_result(top="tired"), guess(label), [], NOW)["text"]
            self.assertTrue(cry_reason.no_medical(text), text)


class WiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def sounds(self, now, label, speak):
        listener = FakeEmbedder(label)
        local = cry_sound.CrySound(listener, {"enabled": True}, head=one_hot_head(speak=speak))
        sounds = HouseSounds(self.agent, self.config, listener=listener, clock=lambda: now, local=local)
        self.agent.plugins = [sounds]
        return sounds

    def test_day_cry_runs_the_local_model_and_tells_with_source_and_routine(self):
        sounds = self.sounds(NOW, "hungry", speak=["hungry"])
        hearing.play(sounds.listen(), tone("cry", 8))
        guessed = events(self.agent.bus, "cry_sound_guess")
        self.assertEqual([(g["listener"], g["label"], g["host"]) for g in guessed], [("local", "hungry", "local")])
        notify = events(self.agent.bus, "notify")[-1]
        self.assertEqual((notify["source"], notify["routine"]), ("house-sounds", "cry"))
        self.assertEqual(events(self.agent.bus, "cry_reason")[0]["sound"]["label"], "hungry")
        self.assertEqual(sounds.clips, {})

    def test_night_check_now_skips_the_white_noise_and_goes_to_the_parent_on_duty(self):
        sounds = self.sounds(datetime.datetime(2026, 10, 24, 2, 0, tzinfo=TZ), "belly_pain", speak=["belly_pain"])
        hearing.play(sounds.listen(), tone("cry", 8))
        self.assertFalse(events(self.agent.bus, "white_noise"))
        notify = events(self.agent.bus, "notify")[-1]
        self.assertTrue(notify["check_now"])
        self.assertRegex(notify["parent"], r"^Parent [AB]$")
        self.assertIn("Check on him now.", notify["text"])

    def test_the_glasses_show_a_cry_card(self):
        event = {"text": "Probably hungry: last feed 2 h 51 min ago. Gonza is on duty.", "proactive": True,
                 "source": "house-sounds", "routine": "cry", "check_now": True}
        card = hud_cards.from_push(event, "en")
        self.assertEqual(card["title"], "He is crying")
        self.assertTrue(card.get("alert"))


if __name__ == "__main__":
    unittest.main()
