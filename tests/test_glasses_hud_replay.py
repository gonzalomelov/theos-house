"""The glasses HUD replay builder (scripts/glasses_hud_replay.py): recorded detector outputs into HUD events."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("glasses_hud_replay", ROOT / "scripts" / "glasses_hud_replay.py")
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def load(path):
    return json.loads(Path(path).read_text())


class HeroSegmentTest(unittest.TestCase):
    RUN = {"feed_s": 10.0, "events": [
        {"kind": "frame", "stream_s": 1.0, "state": "on", "hands": 1, "lift_cm": None},
        {"kind": "alarm", "action": "raise", "episode": 1, "stream_s": 2.0, "state": "off"},
        {"kind": "chime", "episode": 1, "stream_s": 2.0},
        {"kind": "voice", "episode": 1, "stream_s": 3.2, "text": "hand", "reason": "hold"},
        {"kind": "alarm", "action": "clear", "episode": 1, "stream_s": 4.0},
        {"kind": "frame", "stream_s": 12.5, "state": "lifted", "hands": 2, "lift_cm": 1.8},
        {"kind": "message", "t": 5.0, "text": "changing time"},
    ]}

    def test_keeps_recorded_times_relative_to_the_segment(self):
        events = hud.hero_segment(self.RUN, 1.5, 4.5, loop=0)
        self.assertEqual([(e["t"], e["kind"]) for e in events],
                         [(0.5, "alarm"), (0.5, "chime"), (1.7, "voice"), (2.5, "clear")])
        self.assertEqual(events[0]["state"], "off")
        self.assertEqual(events[2]["text"], "hand")

    def test_picks_the_feed_loop(self):
        events = hud.hero_segment(self.RUN, 2.0, 3.0, loop=1)
        self.assertEqual(events, [{"t": 0.5, "kind": "reflex", "state": "lifted", "hands": 2, "lift_cm": 1.8}])

    def test_end_is_exclusive_and_events_without_stream_time_are_skipped(self):
        self.assertEqual([e["kind"] for e in hud.hero_segment(self.RUN, 0.0, 2.0, loop=0)], ["reflex"])


class HeldSegmentTest(unittest.TestCase):
    def test_cue_and_spoken_latency_from_the_record(self):
        events = hud.held_segment({"object": "diaper", "held_looks": ["on"], "spoken": True, "latency_s": 1.733})
        cue = 2.6 - hud.HELD_MASKED_START_S
        self.assertEqual(events[0]["kind"], "held")
        self.assertEqual(events[0]["verdict"], "on")
        self.assertEqual((events[1]["kind"], events[1]["t"]), ("alarm", round(cue, 3)))
        self.assertEqual((events[2]["kind"], events[2]["t"]), ("voice", round(cue + 1.733, 3)))

    def test_a_missed_hover_speaks_nothing(self):
        events = hud.held_segment({"object": "wipe", "held_looks": ["off"], "spoken": False, "latency_s": None})
        self.assertEqual([e["kind"] for e in events], ["held"])


class RecordedReplayTest(unittest.TestCase):
    """Built from the committed results, so it also checks those files still hold what the HUD shows."""

    @classmethod
    def setUpClass(cls):
        cls.replay = hud.build(load(hud.HERO_RUN), load(hud.HELD_RUN), load(hud.DOG_RUN))
        cls.events = cls.replay["events"]

    def kinds(self, kind):
        return [e for e in self.events if e["kind"] == kind]

    def test_length_and_order(self):
        self.assertTrue(10 <= self.replay["duration_s"] <= 20, self.replay["duration_s"])
        times = [e["t"] for e in self.events]
        self.assertEqual(times, sorted(times))
        self.assertEqual([s["name"] for s in self.replay["scenes"]],
                         ["armed", "hands off", "hover", "held diaper", "logged", "dog"])
        ends = [s["at"] + s["length"] for s in self.replay["scenes"]]
        self.assertEqual([s["at"] for s in self.replay["scenes"][1:]], ends[:-1])

    def test_every_event_falls_inside_its_scene(self):
        scenes = self.replay["scenes"]
        current = None
        for event in self.events:
            if event["kind"] == "scene":
                current = next(s for s in scenes if s["name"] == event["name"])
                continue
            self.assertLess(event["t"], current["at"] + current["length"], event)

    def test_recorded_values(self):
        armed = self.kinds("armed")[0]
        self.assertEqual((armed["by"], armed["tool"], armed["seconds"]), ("brain", "start_changing_table", 3.146))
        self.assertEqual([e["state"] for e in self.kinds("alarm")], ["off", "lifted", "lifted"])
        self.assertEqual(len(self.kinds("voice")), 3)
        logged = self.kinds("logged")[0]
        self.assertEqual((logged["at"], logged["contents"], logged["entry"]), ("04:59", ["dirty"], 174))
        dog = self.kinds("dog")[0]
        self.assertEqual((dog["verdict"], dog["ratio"], dog["alert"]), ("near", 0.134, True))
        self.assertEqual(self.kinds("held")[0]["object"], "diaper")

    def test_the_cc_by_photo_carries_its_credit(self):
        sources = load(ROOT / "results" / "dog-near-baby" / "sources.json")
        photo = next(row for row in sources if row["id"] == hud.DOG_ID)
        dog = next(s for s in self.replay["scenes"] if s["name"] == "dog")
        self.assertIn(photo["license"], dog["credit"])

    def test_hand_spoken_keeps_the_recorded_delay_after_the_tone(self):
        chime = next(e for e in self.events if e["kind"] == "chime")
        voice = self.kinds("voice")[0]
        self.assertAlmostEqual(voice["t"] - chime["t"], 10.224 - 8.721, places=3)

    def test_committed_replay_file_is_current(self):
        path = hud.OUT
        self.assertEqual(load(path), json.loads(json.dumps(self.replay)),
                         "run python scripts/glasses_hud_replay.py and commit the result")


if __name__ == "__main__":
    unittest.main()
