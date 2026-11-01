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
from parenting_agent.agent.brain import Reply
from parenting_agent import voice_bridge as voice_bridge_mod
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

    def cry(self, moment, episode=1):
        self.clock.moment = moment
        self.agent.bus.publish("sound", label="cry", phase="start", episode=episode, seconds=0)

    def say(self, moment, text):
        self.clock.moment = moment
        self.agent.bus.publish("message", channel="telegram", text=text)

    def run_ticks(self, start, end):
        t = start
        while t < end:
            self.feed.tick(t)
            t += datetime.timedelta(minutes=1)

    def test_the_guess_only_prewarms_the_warmer_silently(self):
        device = self.sounds.device
        device.on("bedtime")
        level = device.state["level"]
        self.assertIsNone(self.feed.tick(at(21, 1, 45)))
        episode = self.feed.tick(at(21, 1, 50))
        self.assertFalse(episode["awake"])
        self.assertEqual(self.feed.warmer.state, "on")
        self.assertEqual(events(self.agent, "house_call", action="study_light"), [])
        self.assertEqual(events(self.agent, "night_feed", step="push"), [])
        self.assertEqual(events(self.agent, "night_feed", step="prepare"), [])
        self.assertEqual(device.state["level"], level)
        self.assertIsNone(self.feed.tick(at(21, 1, 51)))
        self.assertEqual(len(events(self.agent, "night_feed", step="prewarm")), 1)

    def test_a_guess_never_pushes_or_nags_and_closes_quietly(self):
        device = self.sounds.device
        device.on("bedtime")
        level = device.state["level"]
        self.run_ticks(at(21, 1, 40), at(21, 4, 30))
        self.assertEqual(events(self.agent, "night_feed", step="push"), [])
        self.assertEqual(events(self.agent, "notify"), [])
        self.assertEqual(device.state["level"], level)
        self.assertEqual(self.feed.warmer.state, "off")
        self.assertIn("no awake signal", events(self.agent, "night_feed", step="done")[0]["reason"])

    def test_a_cry_while_prewarming_gets_the_house_ready(self):
        self.feed.tick(at(21, 1, 50))
        self.cry(at(21, 1, 58))
        prepare = events(self.agent, "night_feed", step="prepare")
        self.assertEqual((len(prepare), prepare[0]["trigger"]), (1, "cry"))
        light = events(self.agent, "house_call", action="study_light")[-1]
        self.assertEqual(light["status"], "dry")
        self.assertEqual(light["data"], {"brightness_pct": 10, "color_temp_kelvin": 2700})
        push = events(self.agent, "night_feed", step="push")[-1]
        self.assertEqual(push["to"], "Parent B")  # Parent A took the last wake-up
        self.assertIn("awake", push["text"])

    def test_a_cry_gets_the_house_ready_at_once_when_the_feed_is_close(self):
        self.cry(at(21, 1, 30))
        prepare = events(self.agent, "night_feed", step="prepare")
        self.assertEqual(len(prepare), 1)
        self.assertEqual(prepare[0]["trigger"], "cry")
        self.assertEqual(self.feed.warmer.state, "on")

    def test_a_cry_long_before_the_feed_does_not_warm_the_milk(self):
        self.cry(at(20, 23, 40))
        self.assertEqual(self.feed.warmer.state, "off")
        self.assertIn("min away", events(self.agent, "night_feed", step="skip")[0]["reason"])

    def test_crying_again_after_a_skip_gets_the_house_ready(self):
        self.cry(at(20, 23, 40))
        self.cry(at(20, 23, 50), episode=2)
        self.assertEqual(self.feed.warmer.state, "on")
        self.assertIn("crying again", events(self.agent, "night_feed", step="prepare")[0]["reason"])

    def test_a_parent_saying_he_is_up_gets_the_house_ready(self):
        for text in ("is he up?", "he's still asleep", "when is the next feed", "good night"):
            self.say(at(21, 1, 20), text)
        self.assertEqual(events(self.agent, "night_feed", step="prepare"), [])
        self.say(at(21, 1, 25), "he's up")
        prepare = events(self.agent, "night_feed", step="prepare")
        self.assertEqual((len(prepare), prepare[0]["trigger"]), (1, "parent"))
        self.assertEqual(len(events(self.agent, "night_feed", step="push")), 1)

    def test_a_parent_starting_a_bottle_needs_no_push(self):
        self.say(at(21, 1, 25), "starting a bottle")
        self.assertEqual(len(events(self.agent, "night_feed", step="prepare")), 1)
        self.assertEqual(events(self.agent, "night_feed", step="push"), [])
        self.assertEqual(self.feed.warmer.state, "on")

    def test_the_he_is_up_button(self):
        self.clock.moment = at(21, 1, 25)
        self.agent.bus.publish("baby_awake", by="Parent A")
        self.assertEqual(events(self.agent, "night_feed", step="prepare")[0]["trigger"], "button")

    def test_a_day_message_or_cry_is_left_alone(self):
        self.say(at(21, 10, 0), "he's up")
        self.cry(at(21, 10, 5))
        self.assertEqual(events(self.agent, "night_feed", step="prepare"), [])

    def test_a_logged_feed_is_an_awake_signal_without_a_push(self):
        self.feed.tick(at(21, 1, 50))
        self.log.add_feed(at(21, 2, 4))
        self.assertIsNone(self.feed.tick(at(21, 2, 6)))
        self.assertEqual(events(self.agent, "night_feed", step="prepare")[0]["trigger"], "log")
        self.assertEqual(self.feed.warmer.state, "off")
        self.assertEqual(events(self.agent, "house_call", action="study_light")[-1]["service"], "light.turn_on")
        self.assertEqual(events(self.agent, "night_feed", step="push"), [])
        done = self.feed.tick(at(21, 2, 34))
        self.assertIsNotNone(done)
        self.assertEqual(events(self.agent, "house_call", action="study_light")[-1]["service"], "light.turn_off")
        self.assertIn("feed logged at 02:04", events(self.agent, "night_feed", step="done")[0]["reason"])

    def test_a_logged_wake_up_note_is_an_awake_signal(self):
        self.feed.tick(at(21, 1, 0))
        self.log.rows.append({"kind": "note", "time": at(21, 1, 10).isoformat(), "note": "He woke up", "ref": "note#w"})
        self.feed.tick(at(21, 1, 11))
        self.assertEqual(events(self.agent, "night_feed", step="prepare")[0]["trigger"], "log")

    def test_what_was_in_the_log_before_is_not_a_signal(self):
        self.log.rows.append({"kind": "note", "time": at(21, 0, 55).isoformat(), "note": "He woke up", "ref": "note#old"})
        self.feed.tick(at(21, 1, 0))
        self.assertEqual(events(self.agent, "night_feed", step="prepare"), [])

    def test_white_noise_goes_down_only_once_he_is_awake_and_comes_back(self):
        device = self.sounds.device
        device.on("bedtime")
        level = device.state["level"]
        self.feed.tick(at(21, 1, 50))
        self.assertEqual(device.state["level"], level)
        self.cry(at(21, 1, 56))
        self.assertAlmostEqual(device.state["level"], round(level * 0.5, 2))
        self.log.add_feed(at(21, 2, 5))
        self.feed.tick(at(21, 2, 10))
        self.assertAlmostEqual(device.state["level"], round(level * 0.5, 2))
        self.feed.tick(at(21, 2, 35))
        self.assertEqual(device.state["level"], level)

    def test_a_late_feed_cry_turns_the_warmer_back_on_after_its_auto_off(self):
        self.cry(at(21, 1, 50))
        self.run_ticks(at(21, 1, 51), at(21, 2, 25))
        self.assertEqual(self.feed.warmer.state, "off")  # 30 min auto off
        self.cry(at(21, 2, 40), episode=3)
        self.assertEqual(self.feed.warmer.state, "on")
        self.assertEqual(len(events(self.agent, "night_feed", step="rewarm")), 1)

    def test_a_cry_while_warming_restarts_the_auto_off_without_a_second_push(self):
        self.cry(at(21, 1, 50))
        self.cry(at(21, 2, 15), episode=4)
        self.assertEqual(self.feed.warmer.off_at, at(21, 2, 45))
        self.assertEqual(len(events(self.agent, "night_feed", step="push")), 1)

    def test_the_no_feed_logged_reminder_only_once_he_is_awake(self):
        self.cry(at(21, 1, 50))
        self.run_ticks(at(21, 1, 51), at(21, 3, 0))
        reminders = [e for e in events(self.agent, "night_feed", step="push") if "No feed logged" in e["text"]]
        self.assertEqual(len(reminders), 1)
        self.assertIn("baby agent", reminders[0]["text"])

    def test_the_warmer_has_a_per_night_cap_across_switch_ons(self):
        self.cry(at(21, 0, 30))
        for i, minute in enumerate(range(20, 300, 20)):  # a cry every 20 min would restart a per-switch auto off forever
            moment = at(21, 0, 30) + datetime.timedelta(minutes=minute)
            self.run_ticks(moment - datetime.timedelta(minutes=20), moment)
            self.cry(moment, episode=10 + i)
        self.run_ticks(at(21, 5, 30), at(21, 5, 50))
        night_min = self.feed.warmer.used_min(at(21, 5, 50))
        self.assertLessEqual(night_min, 90)
        self.assertGreaterEqual(night_min, 89)
        self.assertEqual(self.feed.warmer.state, "off")
        self.assertTrue(events(self.agent, "night_feed", step="warmer", action="night cap")
                        or events(self.agent, "night_feed", step="warmer", action="left off"))
        self.assertEqual(self.feed.night_cap(at(21, 23, 0)), 90)  # the next night starts fresh

    def test_the_warmer_has_a_hard_auto_off_and_a_hard_night_cap(self):
        config = {**self.config, "night_feed": {"warmer_max_on_min": 600, "warmer_night_max_min": 6000}}
        feed = NightFeed(self.agent, config, log=self.log, clock=self.clock)
        self.assertEqual(feed.warmer.max_on_min, 45)
        self.assertEqual(feed.night_cap_min, 120)
        feed.warmer.on(at(21, 1, 0))
        feed.warmer.tick(at(21, 1, 45))
        self.assertEqual(feed.warmer.state, "off")
        with self.assertRaises(ValueError):
            VirtualSwitch(self.agent.bus, "switch.x", "x", 0)

    def test_gonza_on_duty_gets_his_iphone_push_dry(self):
        config = {**self.config, "night_feed": {"push": {"Parent B": "gonza"}}}
        self.feed.stop()
        feed = NightFeed(self.agent, config, log=self.log, clock=self.clock)
        self.agent.plugins = [self.house, self.sounds, feed]
        feed.awake(at(21, 1, 50), "cry", "cry heard")
        push = events(self.agent, "house_call", action="push_gonza")[-1]
        self.assertEqual(push["status"], "dry")
        self.assertFalse(push["live"])

    def test_no_warmer_on_breast_only_nights(self):
        for row in self.log.rows:
            row["method"] = "left breast"
        self.feed.tick(at(21, 1, 50))
        self.assertEqual(self.feed.warmer.state, "off")
        self.cry(at(21, 1, 55))
        self.assertEqual(self.feed.warmer.state, "off")
        self.assertNotIn("warmer", events(self.agent, "night_feed", step="push")[-1]["text"])
        self.assertIn("Study light", events(self.agent, "night_feed", step="push")[-1]["text"])

    def test_every_device_change_is_dry(self):
        self.feed.tick(at(21, 1, 50))
        self.cry(at(21, 1, 55))
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


class ScriptedBrain:
    """A brain that plays fixed steps: each step is a tool call (name, arguments) or a final text."""
    name, model, destination = "scripted", "scripted", "nowhere"

    def __init__(self, steps):
        self.steps, self.seen = list(steps), []

    def step(self, system, transcript, tools):
        self.seen.append({"system": system, "tools": [t["name"] for t in tools], "last": transcript[-1]})
        step = self.steps.pop(0)
        if isinstance(step, tuple):
            return Reply("", [{"id": f"c{len(self.seen)}", "name": step[0], "arguments": step[1]}])
        return Reply(step)


class VoiceGuestTest(unittest.TestCase):
    """Grandma at the Echo: a guest who only reads the log, answered by the brain with read tools alone (goals video v9)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.config["people"] = {"gonza": {"name": "Gonza", "lang": "es"}, "ceci": {"name": "Ceci", "lang": "es"}}
        self.config["baby"] = {"born": False, "name": "Theo"}
        self.config["voice_bridge"] = {"port": 0, "host": "127.0.0.1", "timeout_s": 10, "guests": ["abuela"],
                                       "unknown_speaker": "guest", "token_file": str(Path(self.tmp.name) / "voice-token")}
        self.agent.people = config_mod_people(self.config["people"])
        self.bridge = VoiceBridge(self.agent, self.config, token="t" * 24)
        self.agent.plugins = [self.bridge]
        self.agent.start()
        self.agent.baby_log.add("feeding", {"amount_ml": 90.0, "method": "bottle", "type": "formula"},
                                "2026-10-30T07:55:00-03:00")

    def tearDown(self):
        self.agent.stop()
        self.agent.close()
        self.tmp.cleanup()

    def guest_brain(self, *steps):
        brain = ScriptedBrain(steps)
        self.agent.brain = brain
        return brain

    def test_grandma_hears_the_last_feed_from_the_log_and_nothing_is_written(self):
        brain = self.guest_brain(("read_baby_log", {"kind": "feeding", "limit": 1}),
                                 "Theo comió por última vez ayer a las 07:55, una mamadera de 90 ml.")
        before = len(self.agent.baby_log.entries())
        result = self.bridge.ask("agente del bebé, ¿cuándo comió Theo por última vez?", "echo", "abuela")
        self.assertEqual(result["role"], "guest")
        self.assertIn("a las 7:55", result["reply"])  # said as a person says it, never "07:55"
        self.assertEqual(sorted(brain.seen[0]["tools"]), ["baby_summary", "current_time", "read_baby_log"])
        self.assertIn("abuela", brain.seen[0]["system"])
        self.assertEqual(len(self.agent.baby_log.entries()), before)
        self.assertEqual(events(self.agent, "message"), [])
        guest = events(self.agent, "voice_guest")[-1]
        self.assertEqual((guest["person"], guest["tools"], guest["guard"]), ("abuela", ["read_baby_log"], None))
        self.assertTrue(events(self.agent, "brain_call", guest=True))

    def test_a_wrong_time_from_the_brain_is_replaced_by_the_log(self):
        self.guest_brain("Comió hace una hora.")
        reply = self.bridge.ask("¿cuándo comió Theo por última vez?", "echo", "abuela")["reply"]
        self.assertIn("de las 7:55", reply)
        self.assertNotRegex(reply, r"\d+/\d+|\d{4}-\d{2}")
        self.assertEqual(events(self.agent, "voice_guest")[-1]["guard"], "last_feed_time")

    def test_a_guest_cannot_log_and_a_write_tool_is_refused(self):
        self.guest_brain(("log_baby_event", {"kind": "feeding", "details": {"amount_ml": 90}}), "Anoté 90 ml.")
        before = len(self.agent.baby_log.entries())
        reply = self.bridge.ask("agente del bebé tomó 90 ml", "echo", "abuela")["reply"]
        self.assertEqual(len(self.agent.baby_log.entries()), before)
        self.assertIn("Solo los padres", reply)
        self.assertEqual(events(self.agent, "guest_denied")[-1]["name"], "log_baby_event")

    def test_a_house_tool_never_reaches_a_guest(self):
        brain = self.guest_brain("No puedo prender luces, solo los padres pueden.")
        self.bridge.ask("agente del bebé prendé la luz del estudio", "echo", "abuela")
        self.assertNotIn("light_on", brain.seen[0]["tools"])
        self.assertEqual(len(brain.seen[0]["tools"]), 3)

    def test_red_flag_health_and_safe_sleep_get_fixed_lines_with_no_brain_call(self):
        brain = self.guest_brain()
        self.assertIn("911", self.bridge.ask("agente del bebé no respira", "echo", "abuela")["reply"])
        self.assertIn("pediatra", self.bridge.ask("¿le puedo dar paracetamol?", "echo", "abuela")["reply"])
        self.assertIn("911", self.bridge.ask("está azulino respira bien", "echo", "abuela")["reply"])
        self.assertEqual(brain.seen, [])
        self.assertEqual([e["guard"] for e in events(self.agent, "voice_guest")], ["emergency", "health", "emergency"])

    def test_a_guest_yes_runs_nothing_waiting(self):
        self.agent.wait_for_yes({"id": "x", "name": "remember", "arguments": {"key": "baby_name", "value": "Theo"}},
                                channel="voice")
        self.guest_brain("No tengo nada para confirmar.")
        self.bridge.ask("agente del bebé sí", "echo", "abuela")
        self.assertEqual(len(self.agent.pending), 1)

    def test_who_is_a_guest(self):
        self.assertEqual(self.bridge.role("Gonza"), "parent")
        self.assertEqual(self.bridge.role("ceci"), "parent")
        self.assertEqual(self.bridge.role("Abuela"), "guest")
        self.assertEqual(self.bridge.role(""), "guest")
        self.assertEqual(self.bridge.role("someone"), "guest")
        open_house = VoiceBridge(self.agent, {**self.config, "voice_bridge": {"host": "127.0.0.1", "guests": ["abuela"]}},
                                 token="t" * 24)
        self.assertEqual(open_house.role(""), "parent")
        self.assertEqual(open_house.role("abuela"), "guest")


class VoiceSkillDoorTest(unittest.TestCase):
    """The Alexa skill's own door (#177): its own token, its role capped by config, an asked-again id never runs twice."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.config["people"] = {"gonza": {"name": "Gonza", "lang": "es"}}
        self.agent.people = config_mod_people(self.config["people"])
        self.agent.baby_log.add("feeding", {"amount_ml": 90.0, "method": "bottle", "type": "formula"},
                                "2026-10-30T07:55:00-03:00")
        self.bridges = []

    def tearDown(self):
        for bridge in self.bridges:
            bridge.stop()
        self.agent.stop()
        self.agent.close()
        self.tmp.cleanup()

    def bridge(self, role):
        self.config["voice_bridge"] = {"port": 0, "host": "127.0.0.1", "timeout_s": 10, "unknown_speaker": "guest",
                                       "token_file": str(Path(self.tmp.name) / "voice-token"),
                                       "skill": {"role": role, "token_file": str(Path(self.tmp.name) / "skill-token")}}
        bridge = VoiceBridge(self.agent, self.config, token="h" * 24, skill_token="s" * 24)
        self.agent.plugins = [bridge]
        self.agent.start()
        bridge.start()
        self.bridges.append(bridge)
        self.url = f"http://127.0.0.1:{bridge.port}"
        return bridge

    def post(self, body, token):
        request = urllib.request.Request(self.url + "/ask", data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())

    def test_the_skill_has_its_own_token_and_home_assistant_keeps_its_own(self):
        bridge = self.bridge("guest")
        self.assertEqual(bridge.authorized({"Authorization": "Bearer " + "s" * 24}), "skill")
        self.assertEqual(bridge.authorized({"Authorization": "Bearer " + "h" * 24}), "home-assistant")
        self.assertIsNone(bridge.authorized({"Authorization": "Bearer " + "x" * 24}))
        self.assertIsNone(bridge.authorized({}))
        self.assertEqual((Path(self.tmp.name) / "skill-token").stat().st_mode & 0o777, 0o600)

    def test_a_guest_skill_stays_a_guest_even_when_it_names_a_parent(self):
        self.bridge("guest")
        self.agent.brain = ScriptedBrain(["Theo comió por última vez ayer a las 07:55."])
        before = len(self.agent.baby_log.entries())
        body = self.post({"text": "tomó 90 ml", "source": "echo", "person": "gonza"}, "s" * 24)
        self.assertEqual(body["role"], "guest")
        self.assertEqual(len(self.agent.baby_log.entries()), before)
        self.assertEqual(events(self.agent, "message"), [])
        self.assertEqual(events(self.agent, "voice_bridge", status="answered")[-1]["via"], "skill")

    def test_a_parent_skill_logs_for_a_named_parent_and_reads_for_anyone_else(self):
        self.bridge("parent")
        body = self.post({"text": "fed 90 ml", "source": "echo", "person": "gonza"}, "s" * 24)
        self.assertEqual((body["role"], body["reply"]), ("parent", "Done, logged."))
        self.agent.brain = ScriptedBrain(["Ayer a las 07:55."])
        self.assertEqual(self.post({"text": "¿cuándo comió?", "source": "echo"}, "s" * 24)["role"], "guest")

    def test_the_same_request_id_asked_again_returns_the_first_answer_and_runs_once(self):
        self.bridge("guest")
        brain = ScriptedBrain(["Ayer a las 07:55."])
        self.agent.brain = brain
        first = self.post({"text": "¿cuándo comió Theo?", "source": "echo", "request_id": "r1"}, "s" * 24)
        again = self.post({"text": "¿cuándo comió Theo?", "source": "echo", "request_id": "r1"}, "s" * 24)
        self.assertEqual(first, again)
        self.assertEqual(len(brain.seen), 1)
        self.assertEqual(len(events(self.agent, "voice_guest")), 1)
        self.assertEqual([e["repeat"] for e in events(self.agent, "voice_bridge", status="answered")], [False, True])

    def test_a_repeat_while_the_first_still_runs_waits_for_it(self):
        import threading
        bridge = self.bridge("guest")
        gate, calls, out = threading.Event(), [], {}

        def slow():
            calls.append(1)
            gate.wait(5)
            return {"reply": "done"}

        first = threading.Thread(target=lambda: out.setdefault("first", bridge.once(("skill", "r2"), slow)))
        first.start()
        time.sleep(0.1)
        second = threading.Thread(target=lambda: out.setdefault("second", bridge.once(("skill", "r2"), slow)))
        second.start()
        time.sleep(0.1)
        gate.set()
        first.join(5)
        second.join(5)
        self.assertEqual(calls, [1])
        self.assertEqual((out["first"], out["second"]), (({"reply": "done"}, False), ({"reply": "done"}, True)))

    def test_a_skill_role_must_be_guest_or_parent(self):
        self.config["voice_bridge"] = {"host": "127.0.0.1", "skill": {"role": "admin"}}
        with self.assertRaises(ValueError):
            VoiceBridge(self.agent, self.config, token="h" * 24)


class VoiceBridgeSetupTest(unittest.TestCase):
    def test_the_token_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, config = make_agent(tmp)
            config["voice_bridge"] = {"port": 0, "host": "127.0.0.1", "token_file": str(Path(tmp) / "voice-token")}
            first = VoiceBridge(agent, config)
            first.start()
            first.stop()
            second = VoiceBridge(agent, config)
            self.assertEqual(second.token, first.token)
            self.assertEqual((Path(tmp) / "voice-token").stat().st_mode & 0o777, 0o600)
            agent.close()

    def test_container_listens_on_its_own_private_address(self):
        real = voice_bridge_mod.socket.gethostbyname
        voice_bridge_mod.socket.gethostbyname = lambda name: "192.0.2.10"
        try:
            self.assertEqual(voice_bridge_mod.own_address("container"), "192.0.2.10")
        finally:
            voice_bridge_mod.socket.gethostbyname = real
        self.assertEqual(voice_bridge_mod.own_address("127.0.0.1"), "127.0.0.1")


class HomeAssistantAskScriptTest(unittest.TestCase):
    """deploy/home-assistant/shell/parenting_agent_ask.py, the script Home Assistant runs, against a real bridge."""

    def setUp(self):
        import base64
        import importlib.util
        spec = importlib.util.spec_from_file_location("ha_ask", ROOT / "deploy/home-assistant/shell/parenting_agent_ask.py")
        self.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.script)
        self.b64 = lambda text: base64.b64encode(text.encode()).decode()
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.config["voice_bridge"] = {"port": 0, "host": "127.0.0.1", "timeout_s": 10, "unknown_speaker": "guest",
                                       "token_file": str(Path(self.tmp.name) / "voice-token")}
        self.bridge = VoiceBridge(self.agent, self.config, token="t" * 24)
        self.agent.plugins = [self.bridge]
        self.agent.start()
        self.bridge.start()
        self.url = f"http://127.0.0.1:{self.bridge.port}/ask"
        self.secrets = Path(self.tmp.name) / "secrets.yaml"
        self.secrets.write_text(f'some_password: x\nparenting_agent_voice_url: "{self.url}"\n'
                                f'parenting_agent_voice_token: "{"t" * 24}"\n')

    def tearDown(self):
        self.bridge.stop()
        self.agent.stop()
        self.agent.close()
        self.tmp.cleanup()

    def test_a_question_comes_back_as_json_on_stdout(self):
        import contextlib
        import io
        self.agent.brain = ScriptedBrain(["Hoy no hay tomas en el registro."])
        self.script.SECRETS = str(self.secrets)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.script.main(["x", self.b64("echo"), self.b64("abuela"), self.b64("agente del bebé, ¿cómo está el registro hoy?")])
        answer = json.loads(out.getvalue())
        self.assertEqual((answer["status"], answer["role"]), (200, "guest"))
        self.assertEqual(answer["reply"], "Hoy no hay tomas en el registro.")

    def test_a_wrong_token_says_no_answer_and_never_prints_the_token(self):
        answer = self.script.ask("echo", "abuela", "agente del bebé hola", self.url, "wrong-token")
        self.assertEqual((answer["status"], answer["reply"]), (401, self.script.NO_ANSWER))
        self.assertNotIn("t" * 24, json.dumps(answer))

    def test_secrets_are_read_by_name(self):
        self.assertEqual(self.script.secret("parenting_agent_voice_url", self.secrets), self.url)
        with self.assertRaises(KeyError):
            self.script.secret("missing", self.secrets)


def config_mod_people(spec):
    from parenting_agent.agent.people import People
    return People(spec)


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
