"""Muse Spark Open's eyes and ears (issues #30 and #14), offline: a fake post stands in for Baseten.

The real runs are scripts/carseat_muse_eval.py and the earlier sounds run, results in results/carseat/muse/ and
results/sounds/muse/.
"""
import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from parenting_agent import cry_muse, hearing, muse_senses
from parenting_agent.agent.brain import BrainError
from parenting_agent.bus import Bus
from parenting_agent.carseat import muse_check
from parenting_agent.carseat.coach import Coach
from parenting_agent.house_sounds import HouseSounds
from parenting_agent.muse_senses import MuseSenses, beeps, wav_bytes
from tests.test_carseat import CAR, SEAT, SKILL, FakeVision, FrameFeed, scene
from tests.test_sounds import ToneListener, events, make_agent, tone

TZ = datetime.timezone(datetime.timedelta(hours=-3))


def reply(answer, prompt_tokens=1000, completion_tokens=500):
    return {"choices": [{"message": {"content": json.dumps(answer) if not isinstance(answer, str) else answer},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}


class FakePost:
    def __init__(self, answers):
        self.answers, self.bodies = list(answers), []

    def __call__(self, url, headers, body, timeout):
        self.bodies.append(body)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return reply(answer)


def senses(answers):
    post = FakePost(answers)
    return MuseSenses({"key_env": "MUSE_TEST_KEY"}, post=post), post


@mock.patch.dict(os.environ, {"MUSE_TEST_KEY": "test-key-not-real"})
class MuseSensesTest(unittest.TestCase):
    def test_one_image_then_the_question_with_a_strict_schema(self):
        s, post = senses([{"a": 1}])
        got = s.ask("sys", "question", {"type": "object"}, image_url="data:image/jpeg;base64,AAAA")
        body = post.bodies[0]
        self.assertEqual(body["model"], "meta-models/muse-spark-open-1026")
        self.assertEqual([p["type"] for p in body["messages"][1]["content"]], ["image_url", "text"])
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(got["answer"], {"a": 1})
        self.assertEqual(got["host"], "inference.baseten.co")
        self.assertAlmostEqual(got["usd"], (1000 * 1.25 + 500 * 4.25) / 1e6)

    def test_audio_goes_after_the_instruction_in_one_user_message(self):
        """With a system message, or the audio before the instruction, Muse answers that it heard nothing (Oct 29)."""
        s, post = senses([{"a": 1}])
        s.ask("sys", "q", {"type": "object"}, audio_wav=b"RIFFwav")
        messages = post.bodies[0]["messages"]
        self.assertEqual([m["role"] for m in messages], ["user"])
        self.assertEqual([p["type"] for p in messages[0]["content"]], ["text", "input_audio"])
        self.assertEqual(messages[0]["content"][0]["text"], "sys\n\nq")
        self.assertEqual(messages[0]["content"][1]["input_audio"], {"data": "UklGRndhdg==", "format": "wav"})

    def test_no_audio_prompt_offers_a_way_out_of_hearing(self):
        """'If no audio reaches you' made Muse say it heard nothing even for speech it otherwise wrote down (Oct 29)."""
        for text in (cry_muse.SYSTEM, cry_muse.TEXT, muse_senses.CANARY_SYSTEM, muse_senses.CANARY_TEXT):
            self.assertNotIn("no audio", text.lower())
            self.assertNotIn("attached", text.lower())

    def test_an_answer_that_is_not_json_is_an_error_never_a_verdict(self):
        s, _ = senses(["the seat looks fine"])
        with self.assertRaises(BrainError):
            s.ask("sys", "q", {"type": "object"})

    def test_canary_needs_muse_to_hear_and_count_the_beeps(self):
        self.assertFalse(senses([{"heard_sound": False, "beeps": 0}])[0].canary())
        self.assertFalse(senses([{"heard_sound": True, "beeps": 2}])[0].canary())
        self.assertTrue(senses([{"heard_sound": True, "beeps": 3}])[0].canary())
        self.assertFalse(senses([BrainError("HTTP 500")])[0].canary())

    def test_wav_is_made_in_memory(self):
        wav = wav_bytes(np.zeros(1600))
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertGreater(len(beeps(3)), 16000)


class MuseSeatCheckTest(unittest.TestCase):
    def test_every_step_schema_fixes_movement_to_cannot_judge(self):
        for check in muse_check.STEPS:
            prop = muse_check.schema(check)["properties"]["movement_under_1_inch"]
            self.assertEqual(prop["enum"], ["cannot_judge"])
            self.assertIn("cannot_see", muse_check.schema(check)["properties"]["answer"]["enum"])

    def test_no_step_question_says_what_correct_looks_like_or_says_safe(self):
        for text, mapping in muse_check.STEPS.values():
            self.assertNotIn("correct", text.lower())
            self.assertNotIn("safe", text.lower())
            self.assertIn("pass", mapping.values())
            self.assertIn("fail", mapping.values())

    def test_anything_unexpected_is_unseen_never_pass(self):
        self.assertEqual(muse_check.parse("handle", {"answer": "raised"}), "pass")
        self.assertEqual(muse_check.parse("handle", {"answer": "lowered"}), "fail")
        for odd in ({"answer": "cannot_see"}, {"answer": "upright"}, {}, {"answer": None}):
            self.assertEqual(muse_check.parse("handle", odd), "unseen")

    def test_second_opinion_rule(self):
        c = lambda s, m: muse_check.combine(s, m)["result"]
        self.assertEqual(c("pass", "pass"), "pass")
        self.assertEqual(c("pass", "fail"), "unsure")
        self.assertEqual(c("fail", "pass"), "unsure")
        self.assertEqual(c("pass", "unseen"), "unsure")
        self.assertEqual(c("unseen", "pass"), "unsure")
        self.assertEqual(c("fail", "fail"), "fail")
        self.assertEqual(c("unseen", "fail"), "fail")
        self.assertEqual(c("unseen", "unseen"), "unseen")
        self.assertEqual(muse_check.combine("pass", None), {"result": "pass", "second_opinion": "single"})

    @mock.patch.dict(os.environ, {"MUSE_TEST_KEY": "test-key-not-real"})
    def test_majority_of_samples_and_a_split_is_never_a_pass(self):
        frame = np.zeros((720, 960, 3), np.uint8)
        s, _ = senses([{"look": "", "answer": "raised", "movement_under_1_inch": "cannot_judge"}])
        self.assertEqual(muse_check.MuseSeatCheck(s, samples=3).look(frame, "handle")["result"], "pass")
        s, _ = senses([{"look": "", "answer": "raised", "movement_under_1_inch": "cannot_judge"},
                       {"look": "", "answer": "lowered", "movement_under_1_inch": "cannot_judge"},
                       {"look": "", "answer": "cannot_see", "movement_under_1_inch": "cannot_judge"}])
        got = muse_check.MuseSeatCheck(s, samples=3).look(frame, "handle")
        self.assertEqual(sorted(got["samples"]), ["fail", "pass", "unseen"])
        self.assertEqual(got["result"], "unseen")

    @mock.patch.dict(os.environ, {"MUSE_TEST_KEY": "test-key-not-real"})
    def test_muse_down_gives_no_result(self):
        s, _ = senses([BrainError("HTTP 503")])
        got = muse_check.MuseSeatCheck(s).look(np.zeros((100, 100, 3), np.uint8), "handle")
        self.assertIsNone(got["result"])


class FakeMuse:
    def __init__(self, results):
        self.results, self.asked = results, []

    def look(self, frame, check):
        self.asked.append(check)
        return {"result": self.results.get(check, "pass"), "seconds": 0.01, "usd": 0.001, "host": "fake"}


def run(found, muse):
    bus = Bus()
    coach = Coach({**SKILL, "closeup": False, "ready_timeout_s": 0.0, "step_timeout_s": 1.0}, bus, FakeVision(found),
                  FrameFeed(), SEAT, CAR, answer_timeout_s=0.3, muse=muse)
    for check, text in {"harness_pinch": "no", "car_position": "yes", "buckle": "yes", "tension": "yes",
                        "belt_path_movement": "yes"}.items():
        coach.answer(check, text)
    return bus, coach.run()


class CoachWithMuseTest(unittest.TestCase):
    def test_muse_is_asked_only_on_the_checks_it_votes_on(self):
        found, _ = scene()
        muse = FakeMuse({})
        bus, results = run(found, muse)
        self.assertEqual(sorted(muse.asked), sorted(muse_check.MUSE_VOTES))
        self.assertTrue(all(r["result"] == "pass" for r in results.values()))
        self.assertEqual(len(events(bus, "carseat_muse")), len(muse_check.MUSE_VOTES))

    def test_muse_disagreeing_keeps_the_check_from_passing_and_never_says_safe(self):
        found, _ = scene()
        bus, results = run(found, FakeMuse({"handle": "fail"}))
        self.assertEqual(results["handle"]["result"], "unsure")
        self.assertEqual(results["handle"]["muse_result"], "fail")
        spoken = [e["text"] for e in bus.history if e["kind"] == "voice"]
        self.assertTrue(any("disagree" in t for t in spoken))
        self.assertIn("check them by hand", spoken[-1])
        self.assertIn("certified child passenger safety technician", spoken[-1])
        self.assertTrue(all(" safe " not in f" {t.lower()} " for t in spoken))

    def test_muse_catches_what_sam_could_not_see(self):
        found, _ = scene(handle_upright=False)
        found[SKILL["prompts"]["handle"]] = []  # SAM finds no handle at all
        _, results = run(found, FakeMuse({"handle": "fail"}))
        self.assertEqual(results["handle"]["result"], "fail")

    def test_muse_down_leaves_the_sam_verdict_marked_single(self):
        found, _ = scene()
        _, results = run(found, FakeMuse({"handle": None, "level_line": None}))
        self.assertEqual(results["handle"]["result"], "pass")
        self.assertEqual(results["handle"]["second_opinion"], "single")


class FakeEars:
    def __init__(self, guess):
        self.guess_value, self.got = guess, []

    def guess(self, samples, rate):
        self.got.append(samples.size)
        return dict(self.guess_value)


@mock.patch.dict(os.environ, {"MUSE_TEST_KEY": "test-key-not-real"})
class CryMuseTest(unittest.TestCase):
    def test_off_by_default_and_nothing_is_sent(self):
        s, post = senses([{"heard_sound": True}])
        self.assertIn("off", cry_muse.CryEars(s).guess(np.zeros(16000))["skipped"])
        self.assertEqual(post.bodies, [])

    def test_a_failed_canary_sends_no_cry_audio(self):
        s, post = senses([{"heard_sound": False, "beeps": 0}])
        got = cry_muse.CryEars(s, {"enabled": True}).guess(np.zeros(5 * 16000))
        self.assertIn("canary failed", got["skipped"])
        self.assertEqual(len(post.bodies), 1)  # the synthetic canary only
        self.assertIn("beeps", post.bodies[0]["messages"][0]["content"][0]["text"])

    def test_only_the_first_clip_seconds_are_sent_and_the_guess_is_read(self):
        s, post = senses([{"heard_sound": True, "beeps": 3},
                          {"heard_sound": True, "sound": "baby_crying", "reason_guess": "hungry", "confidence": 0.7}])
        got = cry_muse.CryEars(s, {"enabled": True, "clip_s": 2.0}).guess(np.zeros(20 * 16000))
        self.assertEqual((got["reason"], got["confidence"], got["heard"]), ("hungry", 0.7, True))
        sent = post.bodies[1]["messages"][0]["content"][1]["input_audio"]["data"]
        self.assertLess(len(sent), 2.5 * 16000 * 2 * 4 / 3 + 200)  # about 2 s of 16-bit audio in base64

    def test_a_claim_without_hearing_a_cry_gives_no_reason(self):
        got = cry_muse.read({"answer": {"heard_sound": False, "sound": "baby_crying", "reason_guess": "hungry",
                                        "confidence": 0.9}, "seconds": 1, "usd": 0, "usage": {}, "host": "x"})
        self.assertIsNone(got["reason"])

    def test_blend_adds_one_sentence_and_keeps_the_log_ranking(self):
        result = {"top": "tired", "text": "Probably tired: awake 54 min.", "ranked": [{"reason": "tired", "score": 0.9}]}
        out = cry_muse.blend(result, {"reason": "hungry", "confidence": 0.8})
        self.assertEqual(out["top"], "tired")
        self.assertTrue(out["text"].endswith("From the sound alone, a guess: hungry."))
        self.assertIs(cry_muse.blend(result, {"reason": "hungry", "confidence": 0.2}), result)
        self.assertIs(cry_muse.blend(result, None), result)

    def test_the_schema_has_no_medical_reason(self):
        for value in cry_muse.SCHEMA["properties"]["reason_guess"]["enum"]:
            self.assertTrue(cry_muse.no_medical(value))


class HouseSoundsMuseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.now = datetime.datetime(2026, 10, 24, 14, 0, tzinfo=TZ)

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_the_cry_clip_reaches_muse_once_and_is_dropped(self):
        ears = FakeEars({"heard": True, "reason": "hungry", "confidence": 0.8, "seconds": 1.0, "usd": 0.001,
                         "usage": {}, "host": "fake"})
        sounds = HouseSounds(self.agent, self.config, listener=ToneListener(), clock=lambda: self.now, ears=ears)
        hearing.play(sounds.listen(), tone("cry", 8))
        self.assertEqual(len(ears.got), 1)
        self.assertEqual(sounds.clips, {})
        guess = events(self.agent.bus, "cry_sound_guess")[0]
        self.assertNotIn("samples", guess)
        self.assertTrue(all(not isinstance(v, np.ndarray) for v in guess.values()))
        self.assertIn("From the sound alone, a guess: hungry.", events(self.agent.bus, "notify")[0]["text"])

    def test_without_muse_the_cry_flow_is_unchanged(self):
        sounds = HouseSounds(self.agent, self.config, listener=ToneListener(), clock=lambda: self.now)
        hearing.play(sounds.listen(), tone("cry", 8))
        self.assertFalse(events(self.agent.bus, "cry_sound_guess"))
        self.assertIsNone(sounds.listen().on_cry_clip)
        self.assertNotIn("sound alone", events(self.agent.bus, "notify")[0]["text"])


if __name__ == "__main__":
    unittest.main()
