"""hands "sam3_only": the camera skills watch with SAM 3.1 alone, no MediaPipe and no prior work library.
Offline: a scripted stand-in answers with masks, no model loads."""
import copy
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import numpy as np

from parenting_agent import config as config_mod
from parenting_agent import hands as hands_mod
from parenting_agent.bus import Bus
from parenting_agent.sam_hands import SamAlarm, SamOnlySkill, touching

ROOT = Path(__file__).resolve().parent.parent
SHAPE = (360, 640)


def masks_for(on):
    baby = np.zeros(SHAPE, bool)
    baby[100:260, 200:440] = True
    hand = np.zeros(SHAPE, bool)
    if on:
        hand[150:200, 250:300] = True
    else:
        hand[10:40, 10:40] = True
    return [hand], baby


class ScriptedSam:
    """masks(frame, held) answers on for the first on_looks looks, then off."""
    name = "sam3_local"

    def __init__(self, on_looks):
        self.on_looks, self.looks = on_looks, 0

    def masks(self, frame_bgr, held=False):
        self.looks += 1
        return masks_for(self.looks <= self.on_looks)

    def judge(self, frame_bgr):
        return "unsure"


def config():
    cfg = copy.deepcopy(config_mod.load("skills/changing-table.json"))
    cfg["lift"]["enabled"] = False
    cfg["house"] = {"allowed": {}, "on_armed": [], "on_voice": [], "on_closed": []}
    cfg["tracking"] = {"provider": "none", "on_closed": None}
    return cfg


def run(skill, frames, step=0.1):
    frame = np.zeros((*SHAPE, 3), np.uint8)
    for i in range(frames):
        skill.on_frame(frame, i * step)
        time.sleep(0.01)  # lets the background look land


class SamOnly(unittest.TestCase):
    def test_both_hands_off_is_spoken_at_the_first_look_that_sees_it(self):
        bus = Bus()
        skill = SamOnlySkill(config(), bus, ScriptedSam(on_looks=3))
        skill.arm()
        run(skill, 40)
        skill.close()
        voices = [e for e in bus.history if e["kind"] == "voice"]
        self.assertEqual(len(voices), 1)
        self.assertEqual((voices[0]["reason"], voices[0]["text"]), ("sam3", "hand"))
        self.assertEqual(bus.count("chime"), 1)
        self.assertEqual([e["mode"] for e in bus.history if e["kind"] == "hands_mode"], ["sam3_only"])

    def test_hands_on_stay_silent(self):
        bus = Bus()
        skill = SamOnlySkill(config(), bus, ScriptedSam(on_looks=10_000))
        run(skill, 30)
        skill.close()
        self.assertEqual((bus.count("voice"), bus.count("chime")), (0, 0))

    def test_no_sam_no_watch(self):
        from parenting_agent.confirm import NoConfirm
        with self.assertRaises(RuntimeError):
            SamOnlySkill(config(), Bus(), NoConfirm())

    def test_touching_uses_the_baby_mask(self):
        self.assertTrue(touching(*masks_for(True)))
        self.assertFalse(touching(*masks_for(False)))
        self.assertFalse(touching(masks_for(True)[0], None))


class Alarm(unittest.TestCase):
    CFG = {"voice_hold_s": 1.2, "clear_after_on_s": 0.5, "voice_text": "hand"}

    def test_a_lift_chimes_at_once_and_speaks_after_the_hold(self):
        bus = Bus()
        alarm = SamAlarm(bus, self.CFG)
        alarm.on_state("on", 0.0)
        alarm.on_state("lifted", 1.0)
        self.assertEqual((bus.count("chime"), bus.count("voice")), (1, 0))
        alarm.on_state("lifted", 2.3)
        self.assertEqual(bus.count("voice"), 1)

    def test_back_on_before_the_hold_drops_the_prompt(self):
        bus = Bus()
        alarm = SamAlarm(bus, self.CFG)
        alarm.on_state("lifted", 1.0)
        alarm.on_state("on", 1.3)
        alarm.on_state("on", 1.9)
        self.assertEqual(bus.count("voice"), 0)
        self.assertEqual([e["action"] for e in bus.history if e["kind"] == "alarm"], ["raise", "clear"])
        self.assertEqual(bus.count("voice_dropped"), 1)

    def test_unknown_before_the_first_look_does_nothing(self):
        bus = Bus()
        SamAlarm(bus, self.CFG).on_state(None, 0.0)
        self.assertEqual(len(bus.history), 0)


class Setting(unittest.TestCase):
    def test_one_setting_picks_the_detector(self):
        self.assertEqual(hands_mod.mode("sam3_only", "mediapipe"), "sam3_only")
        self.assertEqual(hands_mod.mode(None, "mediapipe"), "mediapipe")
        with self.assertRaises(ValueError):
            hands_mod.mode("yolo")

    def test_build_gives_the_sam_only_skill(self):
        skill = hands_mod.build(config(), Bus(), "sam3_only", confirm_detector=ScriptedSam(1))
        self.assertIsInstance(skill, SamOnlySkill)
        skill.close()

    def test_the_project_runs_without_the_prior_work_library(self):
        """A clone without a private repo: auto picks SAM 3.1 only and the agent still loads."""
        code = (
            "import sys, importlib.abc\n"
            "class Block(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path, target=None):\n"
            "        if name.split('.')[0] == 'hand_reflex_prior': raise ImportError('blocked')\n"
            "sys.meta_path.insert(0, Block())\n"
            "from parenting_agent import hands, reflex, alarm\n"
            "assert not reflex.AVAILABLE and not alarm.AVAILABLE\n"
            "assert hands.mode(None) == 'sam3_only', hands.mode(None)\n"
            "import parenting_agent.changing_table, parenting_agent.camera_skill, parenting_agent.glasses\n"
            "from parenting_agent.__main__ import main\n"
            "sys.exit(main(['--config', 'config/agent.fake.json', '--check']))\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
                              env={**os.environ, "HOME": os.environ.get("HOME", "")})
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])

    def test_no_prior_work_code_is_in_this_repo(self):
        """The reflex and the alarm of Oct 22 to 23 live in the library, this repo only subclasses them."""
        for name in ("reflex.py", "alarm.py"):
            source = (ROOT / "parenting_agent" / name).read_text()
            self.assertIn("hand_reflex_prior", source)
            self.assertNotIn("def contact_state", source)
            self.assertNotIn("vision.HandLandmarker.create_from_options", source)
            self.assertNotIn("def _speak", source)


if __name__ == "__main__":
    unittest.main()
