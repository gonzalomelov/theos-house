"""Which hand detector a camera skill runs: one setting, "hands", in the agent config or the skill file.

- "mediapipe": the MediaPipe reflex in under a second, the alarm, and SAM 3.1 confirming or cancelling (skill.py). The
  reflex and the alarm are prior work from Oct 22 to 23 2026 in the private library,
  with this repo's event-time changes in reflex.py and alarm.py.
- "sam3_only": Meta's SAM 3.1 alone, no MediaPipe and no prior code (sam_hands.py).
- "auto" (the default): mediapipe when the prior work library is installed, else sam3_only. A clean clone without it
  runs SAM 3.1 only.
"""
from . import alarm as alarm_mod
from . import confirm as confirm_mod
from . import reflex as reflex_mod

MODES = ("auto", "mediapipe", "sam3_only")


def mode(*settings):
    """The first setting given, from the agent config then the skill file, resolved: mediapipe or sam3_only."""
    chosen = next((s for s in settings if s), "auto")
    if chosen not in MODES:
        raise ValueError(f"hands must be one of {', '.join(MODES)}, got {chosen}")
    if chosen == "auto":
        return "mediapipe" if reflex_mod.AVAILABLE and alarm_mod.AVAILABLE else "sam3_only"
    return chosen


def build(cfg, bus, chosen, reflex=None, confirm_detector=None, tracker=None):
    """A skill for cfg with the chosen hand detector. reflex is used by the mediapipe mode only."""
    if chosen == "sam3_only":
        from .sam_hands import SamOnlySkill
        detector = confirm_detector or confirm_mod.build(cfg["confirm"])
        return SamOnlySkill(cfg, bus, detector, tracker=tracker)
    from .skill import Skill
    return Skill(cfg, bus, reflex or reflex_mod.MediaPipeReflex(cfg["contact"]), confirm_detector=confirm_detector,
                 tracker=tracker)
