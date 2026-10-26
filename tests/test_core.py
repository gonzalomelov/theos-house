import datetime
import json
import tempfile
import unittest
from pathlib import Path

from parenting_agent import config as config_mod
from parenting_agent.alarm import Alarm
from parenting_agent.bus import Bus
from parenting_agent.house import House
from parenting_agent.reasoning import parse
from parenting_agent.reflex import contact_state
from parenting_agent.skill import Skill
from parenting_agent.tracking import Tracker, parse_voice

CONTACT = config_mod.DEFAULTS["contact"]
ALARM = config_mod.DEFAULTS["alarm"]
BABY = [0.2, 0.2, 0.8, 0.9]


def kinds(bus):
    return [e["kind"] for e in bus.history]


class ContactRule(unittest.TestCase):
    def test_hand_inside_baby_is_on(self):
        self.assertEqual(contact_state([[0.4, 0.4, 0.55, 0.7]], BABY, CONTACT), "on")

    def test_hand_outside_baby_is_off(self):
        self.assertEqual(contact_state([[0.85, 0.1, 0.99, 0.4]], BABY, CONTACT), "off")

    def test_no_baby_is_unknown(self):
        self.assertEqual(contact_state([[0.4, 0.4, 0.55, 0.7]], None, CONTACT), "unknown")

    def test_baby_sized_hand_is_ignored(self):
        tiny = [0.5, 0.5, 0.56, 0.62]  # about 0.007 of the frame, under min_hand_area
        self.assertEqual(contact_state([tiny], BABY, CONTACT), "off")


class AlarmFlow(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.alarm = Alarm(self.bus, CONTACT, ALARM)

    def test_chime_at_once_voice_after_hold(self):
        self.alarm.on_reflex("on", 0.0)
        self.alarm.on_reflex("off", 1.0)
        self.assertEqual(self.bus.count("chime"), 1)
        self.assertEqual(self.bus.count("voice"), 0)
        self.alarm.on_reflex("off", 2.1)
        self.assertEqual(self.bus.count("voice"), 0)
        self.alarm.on_reflex("off", 2.2)
        self.assertEqual(self.bus.count("voice"), 1)

    def test_hand_back_clears_and_drops_voice(self):
        self.alarm.on_reflex("off", 1.0)
        self.alarm.on_reflex("on", 1.2)
        self.alarm.on_reflex("on", 1.8)
        self.assertIn("voice_dropped", kinds(self.bus))
        self.assertEqual(self.bus.count("voice"), 0)

    def test_short_flicker_does_not_hold_voice_back(self):
        self.alarm.on_reflex("off", 1.0)
        self.alarm.on_reflex("on", 1.5)
        self.alarm.on_reflex("off", 1.7)
        self.alarm.on_reflex("off", 2.3)
        self.assertEqual(self.bus.count("chime"), 1)
        self.assertEqual(self.bus.count("voice"), 1)

    def test_confirm_off_speaks_early_and_cancel_drops(self):
        self.alarm.on_reflex("off", 1.0)
        self.alarm.on_confirm(1, "off", 1.3)
        self.assertEqual(self.bus.history[-1]["reason"], "confirm")
        self.alarm.on_reflex("on", 2.0)
        self.alarm.on_reflex("on", 2.6)
        self.alarm.on_reflex("off", 3.0)
        self.alarm.on_confirm(2, "on", 3.2)
        self.alarm.on_reflex("off", 4.5)
        self.assertEqual(self.bus.count("voice"), 1)
        self.assertIn("voice_dropped", kinds(self.bus))

    def test_unknown_alerts_like_off(self):
        self.alarm.on_reflex("unknown", 0.5)
        self.assertEqual(self.bus.count("chime"), 1)


class Config(unittest.TestCase):
    def test_skills_load(self):
        for path in Path("skills").glob("*.json"):
            self.assertTrue(config_mod.load(path)["name"])

    def test_bad_overlap_fails(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"name": "x", "contact": {"min_overlap": 2}}, f)
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(f.name)


class FakeHa:
    def __init__(self):
        self.calls, self.states = [], {}

    def service(self, service, entity_id):
        self.calls.append((service, entity_id))
        self.states[entity_id] = "on" if service.endswith("turn_on") else "off"

    def state(self, entity_id):
        return self.states.get(entity_id)


class HouseActions(unittest.TestCase):
    def test_allowed_runs_and_reads_back_unknown_asks_parent(self):
        bus, ha = Bus(), FakeHa()
        cfg = {"allowed": {"hold": {"service": "input_boolean.turn_on", "entity_id": "input_boolean.focus", "expect": "on"}},
               "on_armed": ["hold", "unlock_door"]}
        house = House(cfg, bus, client=ha)
        house.on_event("armed")
        house.close()
        self.assertEqual(ha.calls, [("input_boolean.turn_on", "input_boolean.focus")])
        done = [e for e in bus.history if e["kind"] == "house_done"]
        self.assertTrue(done[0]["confirmed"])
        asked = [e for e in bus.history if e["kind"] == "ask_parent"]
        self.assertEqual(asked[0]["action"], "unlock_door")

    def test_no_client_runs_dry(self):
        bus = Bus()
        House({"allowed": {"hold": {"service": "light.turn_on", "entity_id": "light.x"}}, "on_armed": ["hold"]}, bus).on_event("armed")
        self.assertEqual(bus.count("house_dry"), 1)


class Reasoning(unittest.TestCase):
    def test_action_outside_list_becomes_ask_parent(self):
        self.assertEqual(parse('{"action": "unlock_door", "ask_parent": false}', {"hold"}),
                         {"action": None, "ask_parent": True, "why": "unlock_door is not allowed"})

    def test_allowed_action_passes(self):
        self.assertEqual(parse('ok {"action": "hold", "ask_parent": false, "why": "bath"}', {"hold"})["action"], "hold")


class FakeBabyBuddy:
    def __init__(self):
        self.posts = []

    def post(self, path, data):
        self.posts.append((path, data))
        return {"id": len(self.posts)}


class Tracking(unittest.TestCase):
    def test_voice_parsing(self):
        self.assertEqual(parse_voice("bottle, 120 ml")[1]["amount"], 120.0)
        self.assertEqual(parse_voice("dirty"), ("changes", {"wet": False, "solid": True}))
        self.assertEqual(parse_voice("asleep")[0], "sleep_start")
        self.assertIsNone(parse_voice("hello"))

    def test_closed_change_is_logged(self):
        bus, bb = Bus(), FakeBabyBuddy()
        start = datetime.datetime(2026, 10, 26, 18, 0, tzinfo=datetime.timezone.utc)
        Tracker({"on_closed": "change"}, bus, client=bb).skill_closed("changing-table", start, start + datetime.timedelta(minutes=4))
        self.assertEqual(bb.posts[0][0], "changes")
        self.assertEqual(bus.count("tracked"), 1)


class FakeReflex:
    def __init__(self, states):
        self.states = iter(states)

    def state(self, frame):
        return next(self.states), 1, 0.001


class SkillLifecycle(unittest.TestCase):
    def test_arm_watch_close(self):
        import numpy as np
        bus = Bus()
        cfg = config_mod.load("skills/changing-table.json")
        skill = Skill(cfg, bus, FakeReflex(["on", "off", "off", "off"]), tracker=Tracker({"on_closed": "change"}, bus))
        skill.arm()
        frame = np.zeros((360, 640, 3), np.uint8)
        for t in (0.0, 0.5, 1.0, 1.8):
            skill.on_frame(frame, t)
        skill.close()
        k = kinds(bus)
        self.assertEqual(k[0], "skill_armed")
        self.assertEqual(k[-1], "skill_closed")
        self.assertEqual(bus.count("chime"), 1)
        self.assertEqual(bus.count("voice"), 1)
        self.assertEqual(bus.count("ask_parent"), 3)  # house actions not mapped to real devices yet
        self.assertEqual(bus.count("track_dry"), 1)


if __name__ == "__main__":
    unittest.main()


class HeadCameraPage(unittest.TestCase):
    def test_frame_post_reaches_the_latest_slot_and_events_flow(self):
        import urllib.request

        import cv2
        import numpy as np

        from parenting_agent.sources import PhoneSource
        source = PhoneSource(port=0, host="127.0.0.1")
        try:
            page = urllib.request.urlopen(source.url, timeout=5).read()
            self.assertIn(b"getUserMedia", page)
            ok, jpeg = cv2.imencode(".jpg", np.zeros((360, 640, 3), np.uint8))
            request = urllib.request.Request(source.url + "frame", data=jpeg.tobytes(), method="POST",
                                             headers={"Content-Type": "image/jpeg"})
            self.assertEqual(urllib.request.urlopen(request, timeout=5).status, 204)
            frame, seq, _ = source.latest(0)
            self.assertEqual((seq, frame.shape), (1, (360, 640, 3)))
        finally:
            source.close()
