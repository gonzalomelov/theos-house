"""Muse Spark Open looks at the car seat install, one still frame per install step, strict JSON back (issue #30).

At each camera step the coach sends Muse Spark Open on Baseten one still frame, zoomed on the middle of the view
where the parent frames the carrier, with one focused question for that step and a JSON schema. Muse is never told
what a correct install looks like: it picks a neutral observation ("raised" or "lowered" for the handle), and the
code turns that into pass, fail or unseen. Every schema also carries movement_under_1_inch, fixed to cannot_judge:
a still frame cannot show under 2.5 cm (1 inch) of movement, so the parent is asked.

What we learned on the dev renders (results/carseat/muse/README.md): asked about all checks at once on the full
frame, Muse confirmed whatever the prompt described and called wrong installs correct. One focused question on a
zoomed frame fixed the handle. Belt routing and twist stayed close to chance, so for those Muse's answer is logged
as advisory and does not count. MUSE_VOTES says which checks Muse votes on.

Second-opinion rule, for the checks Muse votes on: SAM 3.1's geometry (checks.py) and Muse read the same frame.
  both pass                      pass
  both fail, or fail + unseen    fail
  pass + fail, or pass + unseen  unsure, never a pass: the coach asks for another view and a check by hand
  both unseen                    unseen
If Muse cannot be reached, the SAM verdict stands and is marked single.

The coach never says the seat is safe, only which checks passed, and always suggests a certified technician.
"""
from ..agent.brain import BrainError
from ..muse_senses import jpeg_data_url

CHECKS = ("lap_guides", "shoulder_guide", "no_twist", "level_line", "handle")
MUSE_VOTES = ("handle", "level_line")
PROMPT_VERSION = "v4-step-zoom"
CROP = (0.08, 0.86, 0.125, 0.875)  # top, bottom, left, right, as shares of the frame
ZOOM = 1.6

SYSTEM = "You describe exactly what one photo shows. Be precise. You never say anything is safe."

STEPS = {
    "handle": ("The carry handle is the curved bar attached to the carrier's two sides. Is it raised, standing up "
               "above the carrier like a basket handle, or lowered, lying down along the side of the carrier?",
               {"raised": "pass", "lowered": "fail"}),
    "level_line": ("Look only at the small black window on the carrier's side with a green bar. Compare the green bar "
                   "with the bottom edge of the photo. Is the bar horizontal, or does it slope?",
                   {"horizontal": "pass", "slopes_up_to_the_right": "fail", "slopes_down_to_the_right": "fail"}),
    "shoulder_guide": ("Find the end of the carrier where the doll's head is. There is a blue plastic clip on the rim "
                       "there. The long dark seat belt runs across the top of the photo. Does that belt pass through "
                       "the blue clip at the head end, or does the clip stand apart from the belt with a gap?",
                       {"belt_through_clip": "pass", "clip_apart_from_belt": "fail"}),
    "lap_guides": ("Find the end of the carrier away from the doll's head (the leg end). There are two blue plastic "
                   "clips there, one on the near side wall and one on the far rim, with a seat belt strap running "
                   "between them. Does the strap pass through the near clip? Does it pass through the far clip?",
                   {"through_both": "pass", "misses_near_clip": "fail", "misses_far_clip": "fail", "misses_both": "fail"}),
    "no_twist": ("Find the seat belt strap that runs between the two blue clips at the end of the carrier away from "
                 "the doll's head. Follow it from one clip to the other. Is it a flat strap of even width the whole "
                 "way, or does it narrow or twist somewhere?",
                 {"even_flat": "pass", "narrows_or_twists": "fail"}),
}


def schema(check):
    values = [*STEPS[check][1], "cannot_see"]
    return {"type": "object", "additionalProperties": False, "required": ["look", "answer", "movement_under_1_inch"],
            "properties": {"look": {"type": "string"}, "answer": {"type": "string", "enum": values},
                           "movement_under_1_inch": {"type": "string", "enum": ["cannot_judge"]}}}


def zoom(frame):
    import cv2
    h, w = frame.shape[:2]
    top, bottom, left, right = CROP
    part = frame[int(h * top):int(h * bottom), int(w * left):int(w * right)]
    return cv2.resize(part, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_CUBIC)


def parse(check, answer):
    """pass, fail or unseen from Muse's answer to one step. Anything unexpected is unseen, never pass."""
    return STEPS[check][1].get(answer.get("answer"), "unseen")


def combine(sam, muse):
    """The second-opinion rule for one check. sam and muse are pass, fail, unseen, or None when Muse was not asked."""
    if muse is None:
        return {"result": sam, "second_opinion": "single"}
    pair = {sam, muse}
    if pair == {"pass"}:
        return {"result": "pass", "second_opinion": "agree"}
    if "pass" in pair:
        return {"result": "unsure", "second_opinion": "disagree"}
    if "fail" in pair:
        return {"result": "fail", "second_opinion": "agree" if sam == muse else "one_failed"}
    return {"result": "unseen", "second_opinion": "agree"}


class MuseSeatCheck:
    """samples > 1 asks the same step question that many times at once and takes the majority: Muse's answers on the
    same frame vary from call to call, and a pass needs more than half of them."""

    def __init__(self, senses, samples=1, retries=1):
        self.senses, self.samples, self.retries = senses, samples, retries

    def _one(self, image, check):
        error = None
        for _ in range(1 + self.retries):
            try:
                return self.senses.ask(SYSTEM, STEPS[check][0], schema(check), image_url=image), None
            except BrainError as err:
                error = str(err)[:200]
        return None, error

    def look(self, frame, check):
        """Muse's verdict for one install step on one frame, with the observations, seconds and price."""
        from concurrent.futures import ThreadPoolExecutor
        image = jpeg_data_url(zoom(frame), 92)
        with ThreadPoolExecutor(self.samples) as pool:
            answers = list(pool.map(lambda _: self._one(image, check), range(self.samples)))
        got = [a for a, _ in answers if a is not None]
        if not got:
            return {"check": check, "result": None, "error": answers[0][1], "votes": check in MUSE_VOTES}
        results = [parse(check, g["answer"]) for g in got]
        majority = next((r for r in ("pass", "fail") if results.count(r) * 2 > self.samples), "unseen")
        return {"check": check, "result": majority, "samples": results,
                "seen": [g["answer"].get("answer") for g in got], "movement_under_1_inch": "cannot_judge",
                "look": str(got[0]["answer"].get("look", ""))[:300],
                "seconds": round(max(g["seconds"] for g in got), 3), "usd": round(sum(g["usd"] for g in got), 6),
                "usage": got[0]["usage"], "host": got[0]["host"], "votes": check in MUSE_VOTES}
