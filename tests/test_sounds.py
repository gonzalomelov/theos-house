"""Tests for house sounds (issue #14), why is he crying and white noise (issue #32).

Offline: a fake listener that labels synthetic tones, the fake brain, the simulated-week fixture. The PANNs run on
licensed clips is scripts/sounds_run.py.
"""
import builtins
import datetime
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from parenting_agent import cry_reason, hearing
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.bus import Bus
from parenting_agent.channels.router import Router
from parenting_agent.house_sounds import HouseSounds
from parenting_agent.rhythm.log import FixtureLog
from parenting_agent.white_noise import CRIB_CAP_DB, SimulatedWhiteNoise, WhiteNoisePlan, crib_db, max_level
from simweek import cries

TZ = datetime.timezone(datetime.timedelta(hours=-3))
FIXTURE = Path(__file__).parent / "fixtures/simweek.json"
TONES = {"cry": 440, "doorbell": 1000, "dog": 250}


def tone(label, seconds, level=0.3):
    t = np.arange(int(seconds * hearing.RATE)) / hearing.RATE
    return (level * np.sin(2 * np.pi * TONES[label] * t)).astype(np.float32)


class ToneListener:
    """Stands in for PANNs: the strongest frequency in the last second decides the label."""
    name = "tones"

    def score(self, samples):
        last = samples[-hearing.RATE:]
        if np.abs(last).max() < 0.01:
            return {"scores": {label: 0.0 for label in TONES}}
        peak = int(np.argmax(np.abs(np.fft.rfft(last)))) * hearing.RATE / last.size
        return {"scores": {label: (0.9 if abs(peak - hz) < 30 else 0.0) for label, hz in TONES.items()}}


class FakeSkill:
    kind, name = "skill", "changing-table"

    def __init__(self):
        self.skill = None


def make_agent(tmp):
    config = config_mod.load()
    config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": [],
                   "rhythm": {"source": "fixture", "fixture": str(FIXTURE)}})
    return build(config), config


def events(bus, kind):
    return [e for e in bus.history if e["kind"] == kind]


class EarTest(unittest.TestCase):
    def test_a_doorbell_in_a_test_clip_becomes_a_doorbell_event(self):
        bus = Bus()
        ear = hearing.Ear(ToneListener(), bus)
        clip = np.concatenate([np.zeros(2 * hearing.RATE, np.float32), tone("doorbell", 2), np.zeros(hearing.RATE, np.float32)])
        published = hearing.play(ear, clip)
        doorbells = [e for e in published if e["label"] == "doorbell"]
        print("doorbell event:", json.dumps(doorbells[0]))
        self.assertEqual(len(doorbells), 1)
        self.assertEqual(doorbells[0]["phase"], "start")
        self.assertEqual(doorbells[0]["peak"], 0.9)

    def test_a_cry_is_reported_once_with_its_length_and_pitch(self):
        bus = Bus()
        ear = hearing.Ear(ToneListener(), bus)
        published = hearing.play(ear, np.concatenate([np.zeros(hearing.RATE, np.float32), tone("cry", 12)]))
        cry = [e for e in published if e["label"] == "cry"]
        self.assertEqual(len(cry), 1)
        self.assertEqual(cry[0]["phase"], "end")
        self.assertGreaterEqual(cry[0]["seconds"], 11)
        self.assertAlmostEqual(cry[0]["features"]["pitch_hz"], 440, delta=15)

    def test_a_long_cry_is_reported_while_it_still_goes_on(self):
        bus = Bus()
        ear = hearing.Ear(ToneListener(), bus, {"cry_report_s": 10})
        published = hearing.play(ear, tone("cry", 25))
        self.assertEqual([e["phase"] for e in published if e["label"] == "cry"], ["ongoing"])

    def test_audio_is_never_saved(self):
        writes = []
        real_open, real_os_open = builtins.open, os.open

        def watch_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                writes.append(str(file))
            return real_open(file, mode, *args, **kwargs)

        def watch_os_open(path, flags, *args, **kwargs):
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
                writes.append(str(path))
            return real_os_open(path, flags, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            agent, config = make_agent(tmp)
            sounds = HouseSounds(agent, config, listener=ToneListener(), clock=lambda: datetime.datetime(2026, 10, 24, 15, 0, tzinfo=TZ))
            agent.plugins = [sounds]
            before = {p for p in Path(tmp).rglob("*")}
            with mock.patch("builtins.open", watch_open), mock.patch("io.open", watch_open), mock.patch("os.open", watch_os_open):
                clip = np.concatenate([tone("cry", 8), np.zeros(4 * hearing.RATE, np.float32), tone("doorbell", 2)])
                hearing.play(sounds.listen(), clip)
            after = {p for p in Path(tmp).rglob("*")}
            log = (Path(tmp) / "events.jsonl").read_text()
            agent.close()
        self.assertEqual(writes, [], "nothing opens a file for writing while audio is processed")
        self.assertEqual(after - before, set())
        audio_suffixes = (".wav", ".pcm", ".raw", ".ogg", ".mp3", ".flac", ".aiff", ".npy")
        self.assertFalse([p for p in after if p.suffix in audio_suffixes])
        # The event log only holds labels and numbers: no event carries a long list of samples.
        for line in log.splitlines():
            for value in json.loads(line).values():
                self.assertFalse(isinstance(value, list) and len(value) > 50)
        self.assertIn('"label": "doorbell"', log)

    def test_files_are_decoded_on_a_pipe(self):
        command = hearing.decode_command("x.wav", 0, 5)
        self.assertEqual(command[-3:], ["-f", "s16le", "pipe:1"])

    def test_camera_url_is_masked_in_errors(self):
        url = hearing.camera_url({"TAPO_USER": "u", "TAPO_PASS": "secret", "TAPO_HOST": "192.0.2.10"})
        self.assertNotIn("secret", hearing.mask(f"failed to open {url}"))


class DoorbellTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, config = make_agent(self.tmp.name)
        self.ear_out = []
        self.router = Router(self.agent, config, presence=lambda: "home",
                             outputs={"ear": lambda text: self.ear_out.append(text) or {"played": True}})
        self.skill = FakeSkill()
        self.sounds = HouseSounds(self.agent, config, listener=ToneListener())
        self.agent.plugins = [self.router, self.skill, self.sounds]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def ring(self):
        hearing.play(self.sounds.listen(), tone("doorbell", 2))

    def test_doorbell_during_a_skill_goes_to_the_ear_and_tells_the_agent(self):
        self.skill.skill = object()
        self.ring()
        routed = events(self.agent.bus, "routed")
        print("doorbell during the change:", routed[-1]["channel"], "|", self.ear_out[-1])
        self.assertEqual(routed[-1]["channel"], "ear")
        self.assertIn("Doorbell", self.ear_out[-1])
        observed = events(self.agent.bus, "observation")
        self.assertTrue(observed and "changing-table" in observed[-1]["text"])
        self.assertTrue(events(self.agent.bus, "house_sound")[-1]["skill_active"])

    def test_doorbell_with_hands_free_goes_to_the_home_speaker(self):
        self.ring()
        self.assertEqual(events(self.agent.bus, "routed")[-1]["channel"], "home_speaker")
        self.assertFalse(events(self.agent.bus, "observation"))


class CryReasonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = FixtureLog(FIXTURE).entries()
        cls.cases = cries.candidates(cls.entries)

    def test_top_guess_right_in_at_least_7_of_10_simulated_cries(self):
        picked = cries.sample(self.cases)
        right = 0
        for case in picked:
            result = cry_reason.explain(self.entries, case["at"], TZ)
            right += result["top"] == case["truth"]
            print(f"{case['at']:%a %H:%M} truth={case['truth']:<6} guess={result['top']:<7} {result['text']}")
        print(f"top guess right in {right} of {len(picked)}")
        self.assertEqual(len(picked), 10)
        self.assertGreaterEqual(right, 7)

    def test_whole_week_accuracy(self):
        right = sum(cry_reason.explain(self.entries, c["at"], TZ)["top"] == c["truth"] for c in self.cases)
        print(f"whole simulated week: {right} of {len(self.cases)}")
        self.assertGreaterEqual(right / len(self.cases), 0.7)

    def test_example_reason_reads_like_the_issue(self):
        case = next(c for c in cries.sample(self.cases) if c["truth"] == "hungry")
        result = cry_reason.explain(self.entries, case["at"], TZ)
        self.assertRegex(result["text"], r"^Probably hungry: last feed \d+ h( \d+ min)? ago, he eats about every ")
        self.assertTrue(result["computed_from"])
        self.assertEqual([r["reason"] for r in result["ranked"]][0], "hungry")

    def test_never_pain_illness_or_a_medical_cause(self):
        texts = []
        for case in self.cases:
            result = cry_reason.explain(self.entries, case["at"], TZ, {"length_s": 90, "voiced_share": 0.9})
            self.assertTrue(set(r["reason"] for r in result["ranked"]) <= set(cry_reason.REASONS))
            texts += [result["text"]] + [r["evidence"] for r in result["ranked"]]
        for entries in ([], self.entries[:3], [e for e in self.entries if e["kind"] == "feeding"]):
            texts.append(cry_reason.explain(entries, datetime.datetime(2026, 10, 26, 3, 0, tzinfo=TZ), TZ)["text"])
        for text in texts:
            self.assertTrue(cry_reason.no_medical(text), text)
        for word in ("pain", "illness", "colic", "fever", "teething", "sick"):
            self.assertFalse(cry_reason.no_medical(f"probably {word}"))

    def test_sound_features_are_a_weak_signal_only(self):
        case = self.cases[10]
        plain = cry_reason.explain(self.entries, case["at"], TZ)["ranked"]
        loud = cry_reason.explain(self.entries, case["at"], TZ, {"length_s": 120, "voiced_share": 1.0})["ranked"]
        for a in plain:
            b = next(r for r in loud if r["reason"] == a["reason"])
            self.assertLessEqual(abs(a["score"] - b["score"]), cry_reason.SOUND_WEIGHT + 1e-9)

    def test_only_the_past_is_read(self):
        case = self.cases[20]
        future_only = [e for e in self.entries if cry_reason.when(e) > case["at"]]
        past = [e for e in self.entries if cry_reason.when(e) <= case["at"]]
        self.assertEqual(cry_reason.explain(past, case["at"], TZ)["text"],
                         cry_reason.explain(past + future_only, case["at"], TZ)["text"])


class WhiteNoiseTest(unittest.TestCase):
    def test_volume_never_above_50_db_at_the_crib(self):
        bus = Bus()
        device = SimulatedWhiteNoise(bus)
        self.assertLessEqual(crib_db(device.max_level, device.calibration), CRIB_CAP_DB)
        self.assertGreater(crib_db(device.max_level + 0.01, device.calibration), CRIB_CAP_DB)
        for asked in (0.05, 0.5, 1.0, 7.0):
            device.on("test", level=asked)
            device.level(asked)
            self.assertLessEqual(device.state["level"], device.max_level)
        for event in events(bus, "white_noise"):
            self.assertLessEqual(event["crib_db"], CRIB_CAP_DB)
        self.assertTrue(events(bus, "white_noise")[-1]["capped"])

    def test_measured_calibration_moves_the_cap(self):
        measured = [[0.2, 41.0], [0.5, 49.0], [0.8, 56.0]]
        level = max_level(measured)
        self.assertLessEqual(crib_db(level, measured), CRIB_CAP_DB)
        self.assertGreater(level, 0.5)
        self.assertLess(level, 0.8)
        with self.assertRaises(ValueError):
            SimulatedWhiteNoise(Bus(), [[0.01, 80.0]])

    def test_on_before_naps_and_bedtime_timer_down_once_asleep(self):
        entries = FixtureLog(FIXTURE).entries()
        bus = Bus()
        plan = WhiteNoisePlan(SimulatedWhiteNoise(bus), {"timer_min": 30})
        now = datetime.datetime(2026, 10, 24, 6, 0, tzinfo=TZ)
        while now < datetime.datetime(2026, 10, 25, 6, 0, tzinfo=TZ):
            plan.tick(entries, now)
            now += datetime.timedelta(minutes=1)
        noise = events(bus, "white_noise")
        ons = [e for e in noise if e["action"] == "on"]
        timers = [e for e in noise if e["action"] == "timer"]
        offs = [e for e in noise if e["action"] == "off"]
        print(f"one simulated day: {len(ons)} on, {len(timers)} timers, {len(offs)} off, max {max(e['crib_db'] for e in noise)} dB")
        self.assertTrue(any("nap expected" in e["reason"] for e in ons))
        self.assertTrue(any("bedtime" in e["reason"] for e in ons))
        self.assertTrue(timers and all("asleep since" in e["reason"] for e in timers))
        self.assertTrue(offs and all(e["reason"] == "sleep timer ran out" for e in offs))
        self.assertTrue(all(e["dry"] for e in noise))
        self.assertLessEqual(max(e["crib_db"] for e in noise), CRIB_CAP_DB)


class NightCryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, config = make_agent(self.tmp.name)
        self.now = datetime.datetime(2026, 10, 24, 2, 0, tzinfo=TZ)
        self.sounds = HouseSounds(self.agent, config, listener=ToneListener(), clock=lambda: self.now)
        self.agent.plugins = [self.sounds]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def cry(self, seconds):
        hearing.play(self.sounds.listen(), tone("cry", seconds))

    def test_short_night_fuss_gets_white_noise_before_a_parent(self):
        self.cry(8)
        self.assertRegex(events(self.agent.bus, "white_noise")[0]["reason"], r"^short night fuss, [78] s$")
        self.assertFalse(events(self.agent.bus, "notify"))
        self.assertEqual(len(events(self.agent.bus, "cry_reason")), 1)
        self.now += datetime.timedelta(seconds=60)
        self.cry(8)
        notify = events(self.agent.bus, "notify")
        print("fuss came back:", notify[-1]["text"])
        self.assertEqual(len(notify), 1)
        self.assertRegex(notify[0]["text"], r"Parent [AB] is on duty\.$")

    def test_fuss_that_settles_wakes_nobody(self):
        self.cry(8)
        self.now += datetime.timedelta(seconds=200)
        self.sounds.tick(self.now)
        self.assertTrue(events(self.agent.bus, "fuss_settled"))
        self.assertFalse(events(self.agent.bus, "notify"))

    def test_long_night_cry_tells_the_parent_on_duty_with_the_reason(self):
        self.cry(40)
        notify = events(self.agent.bus, "notify")
        self.assertEqual(len(notify), 1)
        self.assertEqual(notify[0]["reason"], events(self.agent.bus, "cry_reason")[0]["top"])

    def test_day_cry_says_the_reason_and_the_tool_answers(self):
        self.now = datetime.datetime(2026, 10, 24, 14, 0, tzinfo=TZ)
        self.cry(8)
        notify = events(self.agent.bus, "notify")
        self.assertEqual(len(notify), 1)
        self.assertNotIn("on duty", notify[0]["text"])
        status, text = self.agent.tools.run("why_crying", {})
        self.assertEqual(status, "ask_parent")  # not on the allowed list in this config
        self.assertTrue(self.agent.tools.items["why_crying"].handler().startswith(("Probably", "Crying")))


if __name__ == "__main__":
    unittest.main()
