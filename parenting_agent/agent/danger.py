"""Red flags by meaning: Muse reads a parent's message for an emergency the word list does not name.

The gate in rules.py is a word list, and blind round b5 sent a phrasing it does not hold: "face in the pillow and now
very still". The message went to the chat brain, which answered with the 911 line and four numbered first aid steps
after it. Now every message the word list lets through is also read by one short Muse call that answers only
emergency true or false, with no tools and no history. A true puts the message on the fixed emergency line, the same
words as the gate, and nothing else is said.

Conservative fallback: when that reading cannot be had (no model in this run, a Muse error or timeout, an answer that
is not the verdict), rules.maybe_danger decides from signs that a baby may not be breathing (a face in soft bedding,
very still, not moving, no breathing heard), so a missing model never makes the gate narrower than it is. Every
reading is a "danger_screen" event with its source, so the share answered by the fallback is counted.

Only the message itself is sent, to the same brain host as the chat (Muse Spark Open on Baseten).
"""
import time

from . import brain as brain_mod
from . import rules

SYSTEM = """You screen one message a parent sent to a baby log assistant. Decide only one thing: does the message say
or suggest that a baby, or a pregnant parent, may be in danger right now and emergency services should be called?
True for: not breathing or breathing strangely, blue, grey or very pale colour, limp, floppy, unresponsive, very still
or not moving in a way that worries the parent, a face pressed into a pillow, a mattress or soft bedding, something
over the face, choking, a fall, under water, a burn, something swallowed (a battery, a magnet, medicine, poison), a
seizure, heavy bleeding, a dog bite, labour signs that cannot wait. False for everyday logs (feeds, diapers, sleep,
baths), a baby sleeping peacefully, questions about the log, jokes and everyday worries with no danger now.
When you are unsure, answer true. Call danger exactly once."""

TOOL = {"name": "danger", "description": "The verdict for the parent's message.",
        "parameters": {"type": "object", "properties": {"emergency": {"type": "boolean"}}, "required": ["emergency"]}}

# A short call: the verdict is one boolean. Muse reasons before it answers, and the reasoning counts in max_tokens.
SCREEN_BRAIN = {"max_tokens": 1024, "reasoning_effort": "low", "timeout_s": 12}


def verdict(reply):
    """True or False from the model's answer, or None when it holds no verdict."""
    for call in reply.tool_calls or []:
        if call.get("name") == "danger" and isinstance((call.get("arguments") or {}).get("emergency"), bool):
            return call["arguments"]["emergency"]
    text = (reply.text or "").strip().lower()
    if text in ("true", "emergency", "yes", '{"emergency": true}'):
        return True
    if text in ("false", "no", '{"emergency": false}'):
        return False
    return None


class DangerScreen:
    """screen(text) -> (emergency, source): source "muse" when Muse read it, "fallback" when the signs decided."""

    def __init__(self, brain):
        self.brain = brain

    def screen(self, text, bus=None):
        started = time.monotonic()
        found, source, error = None, "fallback", None
        if self.brain is not None:
            try:
                found = verdict(self.brain.step(SYSTEM, [{"role": "user", "text": str(text)[:1000]}], [TOOL]))
                source = "muse" if found is not None else "fallback"
                error = None if found is not None else "no verdict"
            except brain_mod.BrainError as failure:
                error = str(failure)[:200]
        if found is None:
            found = rules.maybe_danger(text)
        if bus is not None:
            bus.publish("danger_screen", source=source, emergency=found, error=error,
                             model=getattr(self.brain, "model", None),
                        destination=getattr(self.brain, "destination", None), seconds=round(time.monotonic() - started, 3))
        return found, source


def build(brain_config):
    """The screen for a configured brain: its own short Muse call when the brain is a model, else the fallback signs
    alone (the fake brain and the fixed rules)."""
    config = dict(brain_config or {})
    config.pop("fallback", None)
    brain = None
    if config.get("provider") == "openai_compatible":
        brain = brain_mod.build_one({**config, **SCREEN_BRAIN})
    return DangerScreen(brain)
