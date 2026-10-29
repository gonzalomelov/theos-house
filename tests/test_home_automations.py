"""The 3 AM feed (#110), daily baby laundry (#111) and the Echo and Assist voice bridge (#112).

Offline: the house is the fake Home Assistant from test_house_tools, the warmer and the washer plug are virtual, the
brain is the rule-based fake. house.live stays false everywhere except where a test turns it on against the fake.
"""
import datetime
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.house_sounds import HouseSounds
from parenting_agent.house_tools import ALONE, HouseTools
from parenting_agent.laundry import Laundry, Washer, dirtied
from parenting_agent.laundry import DEFAULTS as LAUNDRY_DEFAULTS
from parenting_agent.night_feed import NightFeed, predict
from parenting_agent.virtual_devices import SHOPPING, VirtualSwitch
from parenting_agent.voice_bridge import VoiceBridge, spoken, strip_wake
from tests.test_house_tools import FakeHA

TZ = datetime.timezone(datetime.timedelta(hours=-3))
ROOT = Path(__file__).resolve().parent.parent


def at(day, hh, mm):
    return datetime.datetime(2026, 10, day, hh, mm, tzinfo=TZ)


class ListLog:
    def __init__(self, rows):
        self.rows = rows

    def entries(self):
        return self.rows

    def add_feed(self, moment):
        self.rows.append({"kind": "feeding", "start": moment.isoformat(), "end": moment.isoformat(),
                          "ref": f"feeding#{len(self.rows)}"})


def night_log():
    """Feeds every 3 h ending 23:00 on Oct 20, so the next one is due 02:00, and two rota notes."""
    rows = []
    for i, (d, h) in enumerate([(20, 14), (20, 17), (20, 20), (20, 23)]):
        rows.append({"kind": "feeding", "start": at(d, h, 0).isoformat(), "method": "bottle", "ref": f"feeding#{i}"})
    rows.append({"kind": "note", "time": at(20, 1, 0).isoformat(), "note": "Night wake-up handled by Parent A", "ref": "note#a"})
    return ListLog(rows)


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


def make_agent(tmp, extra_allowed=()):
    config = config_mod.load()
    config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "house": {}, "plugins": []})
    config["allowed_tools"] = config["allowed_tools"] + list(ALONE) + list(extra_allowed)
    agent = build(config)
    return agent, config


def events(agent, kind, **match):
    return [e for e in agent.bus.history if e["kind"] == kind and all(e.get(k) == v for k, v in match.items())]


class NightFeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.clock = Clock(at(21, 1, 0))
        self.log = night_log()
        self.house = HouseTools(self.agent, self.config, client=FakeHA())
        self.sounds = HouseSounds(self.agent, self.config, log=self.log, clock=self.clock)
        self.feed = NightFeed(self.agent, self.config, log=self.log, clock=self.clock)
        self.agent.plugins = [self.house, self.sounds, self.feed]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_predicts_the_night_feed_from_the_log(self):
        nxt = predict(self.log.entries(), at(21, 1, 0))
        self.assertEqual(nxt["at"], at(21, 2, 0))
        self.assertEqual(nxt["computed_from"][-1], "feeding#3")

    def test_a_top_up_within_30_min_is_the_same_feed(self):
        self.log.rows.append({"kind": "feeding", "start": at(20, 23, 20).isoformat(), "ref": "feeding#topup"})
        self.assertEqual(predict(self.log.entries(), at(21, 1, 0))["at"], at(21, 2, 0))

    def test_ten_minutes_before_the_house_gets_ready_once(self):
        self.assertIsNone(self.feed.tick(at(21, 1, 45)))
        episode = self.feed.tick(at(21, 1, 50))
        self.assertEqual(episode["parent"], "Parent B")  # Parent A took the last wake-up
        self.assertEqual(self.feed.warmer.state, "on")
        light = events(self.agent, "house_call", action="study_light")[-1]
        self.assertEqual(light["status"], "dry")
        self.assertEqual(light["data"], {"brightness_pct": 10, "color_temp_kelvin": 2700})
        push = events(self.agent, "night_feed", step="push")[-1]
        self.assertEqual(push["to"], "Parent B")
        self.assertIn("around 02:00", push["text"])
        self.assertIsNone(self.feed.tick(at(21, 1, 51)))
        self.assertEqual(len(events(self.agent, "night_feed", step="prepare")), 1)

    def test_a_cry_gets_the_house_ready_at_once_when_the_feed_is_close(self):
        self.clock.moment = at(21, 1, 30)
        self.agent.bus.publish("sound", label="cry", phase="start", episode=1, seconds=0)
        prepare = events(self.agent, "night_feed", step="prepare")
        self.assertEqual(len(prepare), 1)
        self.assertEqual(prepare[0]["trigger"], "cry")
        self.assertEqual(self.feed.warmer.state, "on")

    def test_a_cry_long_before_the_feed_does_not_warm_the_milk(self):
        self.clock.moment = at(20, 23, 40)
        self.agent.bus.publish("sound", label="cry", phase="start", episode=1, seconds=0)
        self.assertEqual(self.feed.warmer.state, "off")
        self.assertIn("min away", events(self.agent, "night_feed", step="skip")[0]["reason"])

    def test_crying_again_after_a_skip_gets_the_house_ready(self):
        self.clock.moment = at(20, 23, 40)
        self.agent.bus.publish("sound", label="cry", phase="start", episode=1, seconds=0)
        self.clock.moment = at(20, 23, 50)
        self.agent.bus.publish("sound", label="cry", phase="start", episode=2, seconds=0)
        self.assertEqual(self.feed.warmer.state, "on")
        self.assertIn("crying again", events(self.agent, "night_feed", step="prepare")[0]["reason"])

    def test_a_late_feed_cry_turns_the_warmer_back_on_after_its_auto_off(self):
        self.feed.tick(at(21, 1, 50))
        for minute in range(51, 60):
            self.feed.tick(at(21, 1, minute))
        for minute in range(0, 25):
            self.feed.tick(at(21, 2, minute))
        self.assertEqual(self.feed.warmer.state, "off")  # 30 min auto off
        self.clock.moment = at(21, 2, 40)
        self.agent.bus.publish("sound", label="cry", phase="start", episode=3, seconds=0)
        self.assertEqual(self.feed.warmer.state, "on")
        self.assertEqual(len(events(self.agent, "night_feed", step="rewarm")), 1)

    def test_a_cry_while_warming_restarts_the_auto_off_without_a_second_push(self):
        self.feed.tick(at(21, 1, 50))
        self.clock.moment = at(21, 2, 15)
        self.agent.bus.publish("sound", label="cry", phase="start", episode=4, seconds=0)
        self.assertEqual(self.feed.warmer.off_at, at(21, 2, 45))
        self.assertEqual(len(events(self.agent, "night_feed", step="push")), 1)

    def test_a_day_feed_is_left_alone(self):
        log = ListLog([{"kind": "feeding", "start": at(20, h, 0).isoformat(), "ref": f"f{h}"} for h in (7, 10, 13)])
        feed = NightFeed(self.agent, self.config, log=log, clock=Clock(at(20, 15, 55)))
        self.assertIsNone(feed.tick(at(20, 15, 55)))

    def test_white_noise_goes_down_and_comes_back(self):
        device = self.sounds.device
        device.on("bedtime")
        level = device.state["level"]
        self.feed.tick(at(21, 1, 50))
        self.assertAlmostEqual(device.state["level"], round(level * 0.5, 2))
        self.log.add_feed(at(21, 2, 5))
        self.feed.tick(at(21, 2, 10))
        self.assertAlmostEqual(device.state["level"], round(level * 0.5, 2))
        self.feed.tick(at(21, 2, 35))
        self.assertEqual(device.state["level"], level)

    def test_the_voice_logged_feed_winds_everything_down(self):
        self.feed.tick(at(21, 1, 50))
        self.log.add_feed(at(21, 2, 4))
        self.assertIsNone(self.feed.tick(at(21, 2, 6)))
        self.assertEqual(self.feed.warmer.state, "off")
        self.assertEqual(events(self.agent, "house_call", action="study_light")[-1]["service"], "light.turn_on")
        done = self.feed.tick(at(21, 2, 34))
        self.assertIsNotNone(done)
        self.assertEqual(events(self.agent, "house_call", action="study_light")[-1]["service"], "light.turn_off")
        self.assertIn("feed logged at 02:04", events(self.agent, "night_feed", step="done")[0]["reason"])

    def test_without_a_log_one_reminder_to_log_by_voice(self):
        self.feed.tick(at(21, 1, 50))
        for minute in range(31, 59):
            self.feed.tick(at(21, 2, minute))
        reminders = [e for e in events(self.agent, "night_feed", step="push") if "No feed logged" in e["text"]]
        self.assertEqual(len(reminders), 1)
        self.assertIn("baby agent", reminders[0]["text"])

    def test_the_warmer_has_a_hard_auto_off(self):
        config = {**self.config, "night_feed": {"warmer_max_on_min": 600}}
        feed = NightFeed(self.agent, config, log=self.log, clock=self.clock)
        self.assertEqual(feed.warmer.max_on_min, 45)
        feed.warmer.on(at(21, 1, 0))
        feed.warmer.tick(at(21, 1, 45))
        self.assertEqual(feed.warmer.state, "off")
        with self.assertRaises(ValueError):
            VirtualSwitch(self.agent.bus, "switch.x", "x", 0)

    def test_gonza_on_duty_gets_his_iphone_push_dry(self):
        config = {**self.config, "night_feed": {"push": {"Parent B": "gonza"}}}
        feed = NightFeed(self.agent, config, log=self.log, clock=self.clock)
        self.agent.plugins = [self.house, self.sounds, feed]
        feed.tick(at(21, 1, 50))
        push = events(self.agent, "house_call", action="push_gonza")[-1]
        self.assertEqual(push["status"], "dry")
        self.assertFalse(push["live"])

    def test_no_warmer_on_breast_only_nights(self):
        for row in self.log.rows:
            row["method"] = "left breast"
        self.feed.tick(at(21, 1, 50))
        self.assertEqual(self.feed.warmer.state, "off")
        self.assertNotIn("warmer", events(self.agent, "night_feed", step="push")[-1]["text"])
        self.assertIn("Study light", events(self.agent, "night_feed", step="push")[-1]["text"])

    def test_every_device_change_is_dry(self):
        self.feed.tick(at(21, 1, 50))
        self.assertTrue(all(e["dry"] for e in events(self.agent, "virtual_device")))
        self.assertTrue(all(not e["live"] for e in events(self.agent, "house_call")))


def washer_profile(start, heat_min=15, pauses=(2, 3, 4), seed_watts=(5, 2100, 300, 450)):
    """Minute readings of one wash: fill, heat, turns with pauses, spin, then standby. Synthetic, not measured."""
    fill, heat, turn, spin = seed_watts
    rows = [(start - datetime.timedelta(minutes=5 - i), 1.0) for i in range(5)]
    t = start
    def run(watts, minutes):
        nonlocal t
        for _ in range(minutes):
            rows.append((t, watts))
            t += datetime.timedelta(minutes=1)
    run(fill + 5, 4)
    run(heat, heat_min)
    for pause in pauses:
        run(turn, 8)
        run(2.0, pause)
    run(spin, 10)
    end = t
    run(1.0, 20)
    return rows, end


class LaundryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name, ("laundry_status", "mark_baby_load", "set_clean_bodysuits"))
        self.clock = Clock(at(21, 8, 0))
        self.log = ListLog([])
        self.house = HouseTools(self.agent, self.config, client=FakeHA())
        self.laundry = Laundry(self.agent, self.config, log=self.log, clock=self.clock)
        self.agent.plugins = [self.house, self.laundry]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def feed_profile(self, rows):
        changes = []
        for moment, watts in rows:
            self.clock.moment = moment
            change = self.laundry.reading(watts, moment)
            if change:
                changes.append((change, moment))
        return changes

    def test_one_cycle_with_pauses_is_one_start_and_one_finish(self):
        rows, end = washer_profile(at(21, 9, 0))
        changes = self.feed_profile(rows)
        self.assertEqual([c for c, _ in changes], ["started", "finished"])
        self.assertEqual(self.laundry.cycles[0]["end"], end)
        texts = [e["text"] for e in events(self.agent, "laundry", step="push")]
        self.assertIn("move the laundry to the dryer", texts[-1])

    def test_a_short_blip_is_not_a_cycle(self):
        rows = [(at(21, 9, m), 40.0) for m in range(3)] + [(at(21, 9, m), 1.0) for m in range(3, 15)]
        changes = self.feed_profile(rows)
        self.assertEqual([c for c, _ in changes], ["started", "blip"])
        self.assertEqual(self.laundry.cycles, [])

    def test_daily_reminder_once_when_no_baby_load(self):
        self.clock.moment = at(21, 18, 59)
        self.assertIsNone(self.laundry.tick(at(21, 18, 59)))
        text = self.laundry.tick(at(21, 19, 0))
        self.assertIn("No baby load today yet", text)
        self.assertIsNone(self.laundry.tick(at(21, 19, 30)))
        self.assertEqual(events(self.agent, "house_call", action="push_gonza")[-1]["status"], "dry")

    def test_no_reminder_after_a_baby_load(self):
        rows, _ = washer_profile(at(21, 9, 0))
        self.feed_profile(rows[:12])
        self.assertIn("running load", self.laundry.mark_baby_load())
        self.feed_profile(rows[12:])
        self.assertIsNone(self.laundry.tick(at(21, 19, 0)))
        self.assertEqual(events(self.agent, "laundry", step="reminder_skipped")[0]["reason"], "a baby load ran today")

    def test_bodysuits_count_down_from_the_log_and_back_after_a_baby_load(self):
        self.laundry.set_clean_bodysuits(10)
        self.log.rows += [
            {"kind": "note", "time": at(21, 8, 30).isoformat(), "note": "Spit up after the feed", "ref": "n1"},
            {"kind": "change", "time": at(21, 10, 0).isoformat(), "wet": True, "solid": True, "notes": "blowout", "ref": "c1"},
            {"kind": "change", "time": at(21, 11, 0).isoformat(), "wet": True, "solid": False, "notes": "", "ref": "c2"},
        ]
        self.clock.moment = at(21, 12, 0)
        clean = self.laundry.clean_bodysuits(at(21, 12, 0))
        self.assertEqual(clean["count"], 8)
        self.assertEqual(clean["from"], ["n1", "c1"])
        self.assertEqual(self.laundry.clean_bodysuits(at(22, 9, 0))["count"], 7)  # a new day uses one
        rows, _ = washer_profile(at(22, 10, 0))
        self.feed_profile(rows)
        self.clock.moment = at(22, 12, 0)
        self.laundry.mark_baby_load()
        self.assertEqual(self.laundry.clean_bodysuits(at(22, 12, 0))["count"], LAUNDRY_DEFAULTS["stock"])

    def test_parents_correct_the_count_through_the_agent(self):
        self.agent.tools.items["set_clean_bodysuits"].handler(count=4)
        self.assertIn("about 4.", self.laundry.status_text())
        self.agent.tools.items["set_clean_bodysuits"].handler(count=3)
        self.assertIn("about 3. That is low.", self.agent.tools.items["laundry_status"].handler())

    def test_dirtied_words(self):
        self.assertTrue(dirtied({"note": "Changed his bodysuit"}))
        self.assertTrue(dirtied({"notes": "small leak"}))
        self.assertFalse(dirtied({"note": "Night wake-up handled by Parent A"}))

    def test_reads_watts_from_home_assistant_read_only(self):
        ha = FakeHA()
        ha.states["sensor.washer_plug_power"] = "1234.5"
        laundry = Laundry(self.agent, {**self.config, "laundry": {"source": "home_assistant"}}, log=self.log,
                          clock=self.clock, reader=ha)
        self.assertEqual(laundry.read_watts(), 1234.5)
        self.assertEqual(ha.calls, [])

    def test_washer_needs_the_quiet_to_last(self):
        washer = Washer(LAUNDRY_DEFAULTS)
        self.assertIsNone(washer.feed(500, at(21, 9, 0)))
        self.assertEqual(washer.feed(500, at(21, 9, 1)), "started")
        for m in range(2, 7):
            self.assertIsNone(washer.feed(1, at(21, 9, m)))
        self.assertIsNone(washer.feed(300, at(21, 9, 7)))  # the drum turns again, the quiet starts over
        self.assertEqual(washer.state, "running")

    def test_shopping_list_names_a_plug_with_a_price(self):
        for item in ("bottle_warmer", "washer"):
            self.assertIn("Shelly Plus Plug IT", SHOPPING[item]["plug"])
            self.assertIn("EUR", SHOPPING[item]["price"])


class VoiceBridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.config["voice_bridge"] = {"port": 0, "host": "127.0.0.1", "timeout_s": 10,
                                       "token_file": str(Path(self.tmp.name) / "voice-token")}
        self.bridge = VoiceBridge(self.agent, self.config, token="t" * 24)
        self.agent.plugins = [self.bridge]
        self.agent.start()
        self.bridge.start()
        self.url = f"http://127.0.0.1:{self.bridge.port}"

    def tearDown(self):
        self.bridge.stop()
        self.agent.stop()
        self.agent.close()
        self.tmp.cleanup()

    def post(self, body, token="t" * 24, path="/ask"):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read())

    def test_a_fake_utterance_logs_a_feed_and_says_so(self):
        status, body = self.post({"text": "baby agent, fed 90 ml", "source": "echo", "person": "Gonza"})
        self.assertEqual(status, 200)
        self.assertEqual(body["reply"], "Done, logged.")
        feeds = self.agent.baby_log.entries("feeding")
        self.assertEqual(feeds[-1]["details"]["amount_ml"], 90.0)
        message = events(self.agent, "message", channel="voice")[-1]
        self.assertEqual((message["text"], message["chat_id"]), ("fed 90 ml", "echo:gonza"))

    def test_a_question_is_answered_from_the_log(self):
        self.post({"text": "fed 120 ml", "source": "assist"})
        _, body = self.post({"text": "ask the baby agent how much did he drink today?", "source": "assist"})
        self.assertIn("120", body["reply"])

    def test_wrong_token_is_refused_and_nothing_reaches_the_agent(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"text": "fed 90 ml"}, token="wrong")
        self.assertEqual(caught.exception.code, 401)
        self.assertEqual(events(self.agent, "message"), [])

    def test_a_bad_source_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"text": "fed 90 ml", "source": "telegram"})
        self.assertEqual(caught.exception.code, 400)

    def test_a_yes_on_the_voice_chat_runs_only_what_was_asked_there(self):
        self.agent.wait_for_yes({"id": "x", "name": "remember", "arguments": {"key": "baby_name", "value": "Theo"}},
                                channel="telegram")
        _, body = self.post({"text": "baby agent yes", "source": "echo"})
        self.assertNotIn("Done", body["reply"])
        self.assertEqual(len(self.agent.pending), 1)

    def test_not_on_every_interface(self):
        with self.assertRaises(ValueError):
            VoiceBridge(self.agent, {**self.config, "voice_bridge": {"host": "0.0.0.0"}})
        with self.assertRaises(ValueError):
            VoiceBridge(self.agent, {**self.config, "voice_bridge": {"host": "8.8.8.8"}})


class WordsTest(unittest.TestCase):
    def test_strip_wake(self):
        self.assertEqual(strip_wake("Alexa, tell the baby agent that he slept 2 hours"), "he slept 2 hours")
        self.assertEqual(strip_wake("baby agent when is the next feed"), "when is the next feed")
        self.assertEqual(strip_wake("agente del bebé tomó 90 ml"), "tomó 90 ml")
        self.assertEqual(strip_wake("fed 90 ml"), "fed 90 ml")

    def test_spoken_is_short_and_plain(self):
        self.assertEqual(spoken("**Done**, see https://x.y/z now"), "Done, see now")
        self.assertLessEqual(len(spoken("word " * 200)), 401)


if __name__ == "__main__":
    unittest.main()
