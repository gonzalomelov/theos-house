"""The hand detector a camera skill runs: Meta's SAM 3.1 alone (sam_hands.py)."""
from . import confirm as confirm_mod

MODES = ("auto", "sam3_only")


def mode(*settings):
    """The first setting given, from the agent config then the skill file. Every valid setting runs SAM 3.1."""
    chosen = next((s for s in settings if s), "auto")
    if chosen not in MODES:
        raise ValueError(f"hands must be one of {', '.join(MODES)}, got {chosen}")
    return "sam3_only"


def build(cfg, bus, chosen, reflex=None, confirm_detector=None, tracker=None):
    """A SAM 3.1 skill for cfg."""
    from .sam_hands import SamOnlySkill
    detector = confirm_detector or confirm_mod.build(cfg["confirm"])
    return SamOnlySkill(cfg, bus, detector, tracker=tracker)
