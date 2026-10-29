"""Dog near the baby (issue #109): the gap rule, never a dog alone, the rate limit, Telegram to Gonza only, the
Echo announce in dry run, and frames kept in a short in-memory buffer. Offline: fake masks, fake Home Assistant,
fake Telegram."""
import os
import unittest
from unittest import mock

import numpy as np

from parenting_agent import dog_watch
from parenting_agent.bus import Bus
from parenting_agent.dog_watch import DEFAULTS, Alerter, DogWatch, Gate, RateLimit, Watch, decide, measure

H, W = 480, 640


def box(x0, y0, x1, y1):
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = True
    return m


BABY = box(100, 200, 200, 300)  # 100 x 100, baby size 100 px


def found(dog=None, baby=BABY, area=None, dog_score=0.9, baby_score=0.9):
    out = {"dog": [], "baby": [], "bassinet": [], "play mat": []}
    if dog is not None:
        out["dog"].append((dog_score, dog))
    if baby is not None:
        out["baby"].append((baby_score, baby))
    if area is not None:
        out["play mat"].append((0.9, area))
    return out


class FakeSegmenter:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def masks(self, frame, prompts):
        self.calls += 1
        return self.result, 0.5


class FakeMessenger:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        return 1


class FakeHA:
    def __init__(self, states=None):
        self.states, self.calls = states or {}, []

    def state(self, entity_id):
        return self.states.get(entity_id, "off")

    def attributes(self, entity_id):
        return {"volume_level": 0.4}

    def service(self, *args):
        self.calls.append(args)

    def camera_image(self, entity_id):
        import cv2
        return cv2.imencode(".jpg", np.zeros((H, W, 3), np.uint8))[1].tobytes()


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class MeasureTest(unittest.TestCase):
    def test_gap_in_baby_sizes(self):
        m = measure(found(dog=box(230, 200, 330, 300)), DEFAULTS)  # 30 px to the right of the baby
        self.assertTrue(m["dog"] and m["baby"])
        self.assertAlmostEqual(m["gap_px"], 30, delta=3)
        self.assertAlmostEqual(m["ratio"], 0.3, delta=0.03)
        self.assertEqual(decide(m, DEFAULTS), "near")

    def test_far_dog(self):
        m = measure(found(dog=box(500, 200, 600, 300)), DEFAULTS)
        self.assertGreater(m["ratio"], 2.5)
        self.assertEqual(decide(m, DEFAULTS), "far")

    def test_touching(self):
        m = measure(found(dog=box(150, 250, 260, 330)), DEFAULTS)  # overlaps the baby
        self.assertTrue(m["touching"])
        self.assertEqual(decide(m, DEFAULTS), "near")

    def test_dog_alone_never_alerts(self):
        m = measure(found(dog=box(150, 250, 260, 330), baby=None), DEFAULTS)
        self.assertEqual(decide(m, DEFAULTS), "no_baby")

    def test_low_score_baby_is_no_baby(self):
        m = measure(found(dog=box(210, 200, 260, 300), baby_score=0.2), DEFAULTS)
        self.assertEqual(decide(m, DEFAULTS), "no_baby")

    def test_baby_without_dog(self):
        self.assertEqual(decide(measure(found(), DEFAULTS), DEFAULTS), "no_dog")
        self.assertEqual(decide(measure({}, DEFAULTS), DEFAULTS), "no_baby")

    def test_play_mat_under_the_baby_is_the_babys_area(self):
        mat = box(50, 150, 400, 350)
        dog = box(420, 200, 500, 300)  # 220 px from the baby, 20 px from the mat
        self.assertEqual(decide(measure(found(dog=dog), DEFAULTS), DEFAULTS), "far")
        m = measure(found(dog=dog, area=mat), DEFAULTS)
        self.assertTrue(m["area_has_furniture"])
        self.assertEqual(decide(m, DEFAULTS), "near")

    def test_play_mat_away_from_the_baby_is_ignored(self):
        mat = box(450, 0, 640, 100)
        m = measure(found(dog=box(500, 20, 600, 90), area=mat), DEFAULTS)
        self.assertEqual(decide(m, DEFAULTS), "far")


class RateLimitTest(unittest.TestCase):
    def test_one_alert_per_window_per_room(self):
        clock = Clock()
        limit = RateLimit(300, clock)
        self.assertTrue(limit.allow("living room"))
        clock.t = 299
        self.assertFalse(limit.allow("living room"))
        self.assertTrue(limit.allow("kitchen"))
        clock.t = 301
        self.assertTrue(limit.allow("living room"))


class AlertTest(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.events = []
        self.bus.subscribe(self.events.append)

    def test_telegram_to_gonza_and_echo_dry_run(self):
        messenger, ha = FakeMessenger(), FakeHA()
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "42"}):
            alert = Alerter({**DEFAULTS}, self.bus, ha, messenger)
        alert({"ratio": 0.2, "touching": False})
        self.assertEqual(messenger.sent, [("42", "Dog close to Theo in the living room")])
        self.assertEqual(ha.calls, [], "house.live is false, so the Echo is never called")
        self.assertTrue(any(e["kind"] == "house_dry" and e["action"] == "announce" for e in self.events))
        self.assertTrue(any(e["kind"] == "dog_alert" and e["telegram"] for e in self.events))

    def test_live_house_announces(self):
        ha = FakeHA()
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "42"}):
            alert = Alerter({**DEFAULTS, "house": {"live": True}}, self.bus, ha, FakeMessenger())
        alert({})
        self.assertIn(("notify.send_message", "notify.gonza_s_echo_dot_announce",
                       {"message": "Dog close to Theo in the living room."}), ha.calls)

    def test_no_chat_id_sends_nothing(self):
        messenger = FakeMessenger()
        with mock.patch.dict(os.environ, {}, clear=True):
            alert = Alerter({**DEFAULTS}, self.bus, None, messenger)
        self.assertFalse(alert({}))
        self.assertEqual(messenger.sent, [])


class WatchTest(unittest.TestCase):
    def make(self, result, clock=None):
        self.bus, self.alerts = Bus(), []
        return Watch({**DEFAULTS}, self.bus, FakeSegmenter(result), self.alerts.append, clock=clock or Clock())

    def test_near_alerts_once_in_the_window(self):
        clock = Clock()
        watch = self.make(found(dog=box(210, 200, 260, 300)), clock)
        frame = np.zeros((H, W, 3), np.uint8)
        self.assertEqual(watch.look(frame)[:2], ("near", True))
        clock.t = 60
        self.assertEqual(watch.look(frame)[:2], ("near", False))
        clock.t = 400
        self.assertEqual(watch.look(frame)[:2], ("near", True))
        self.assertEqual(len(self.alerts), 2)

    def test_dog_alone_and_far_never_alert(self):
        frame = np.zeros((H, W, 3), np.uint8)
        for result in (found(dog=box(150, 250, 260, 330), baby=None), found(dog=box(500, 200, 600, 300))):
            watch = self.make(result)
            for _ in range(3):
                watch.look(frame)
            self.assertEqual(self.alerts, [])

    def test_frames_kept_only_in_a_short_buffer(self):
        watch = self.make(found())
        for i in range(10):
            watch.look(np.full((4, 4, 3), i, np.uint8))
        self.assertEqual(len(watch.buffer), DEFAULTS["buffer_frames"])
        self.assertEqual(int(watch.buffer[-1][0, 0, 0]), 9)


class GateTest(unittest.TestCase):
    def test_sensor_or_low_rate_snapshot(self):
        clock, ha = Clock(), FakeHA()
        gate = Gate(ha, DEFAULTS["gate_sensors"], 30, clock)
        self.assertEqual(gate.why(), "snapshot")
        gate.looked()
        clock.t = 10
        self.assertIsNone(gate.why())
        ha.states[DEFAULTS["gate_sensors"][0]] = "on"
        self.assertEqual(gate.why(), DEFAULTS["gate_sensors"][0])
        ha.states.clear()
        clock.t = 31
        self.assertEqual(gate.why(), "snapshot")


class PluginTest(unittest.TestCase):
    def test_step_reads_the_camera_in_memory_and_alerts(self):
        class Agent:
            bus = Bus()
        ha, messenger = FakeHA(), FakeMessenger()
        seg = FakeSegmenter(found(dog=box(210, 200, 260, 300)))
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "42"}):
            plugin = DogWatch(Agent(), {}, client=ha, segmenter=seg, messenger=messenger)
        plugin.watch = Watch(plugin.cfg, Agent.bus, seg, plugin.alert)
        with mock.patch("builtins.open", side_effect=AssertionError("a frame must never be written")):
            verdict, alerted, _ = plugin.step()
        self.assertEqual((verdict, alerted), ("near", True))
        self.assertEqual(len(messenger.sent), 1)
        self.assertFalse(plugin.cfg["house"]["live"])

    def test_no_token_stays_off(self):
        class Agent:
            bus = Bus()
        with mock.patch.dict(os.environ, {}, clear=True):
            plugin = DogWatch(Agent(), {})
        plugin.start()
        self.assertIsNone(plugin.thread)
        self.assertEqual(dog_watch.prompts(DEFAULTS), ["dog", "baby", "bassinet", "play mat"])


if __name__ == "__main__":
    unittest.main()
