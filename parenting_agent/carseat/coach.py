"""Car seat coach: one step at a time by voice, the camera checks what it can see, the parent answers the rest.

The steps come from the seat profile (the maker's manual) and the car profile. Camera steps run SAM 3.1 on the
newest frame taken after the step was spoken, until a check passes or fails, or the step times out and is
listed as not seen. Ask steps (the seat position in the car and the hand checks a camera cannot see) are
spoken, wait for the parent's answer and are logged. They are never skipped: an unanswered one stays open in
the summary. The coach never calls the install safe. The summary lists which visible checks passed, which
failed or were not seen, which hand checks remain, and suggests one check by a certified technician.

Frames stay in memory on this machine. Only the spoken text and the summary reach the bus and the brain.
"""
import json
import threading
import time
from pathlib import Path

from . import checks as checks_mod

CAMERA_STEPS = {
    "lap_guides": {
        "say": "Slide the lap belt into both side guides of the carrier, then show me the belt path from the door.",
        "prompts": ("belt", "guide"), "manual_step": 0,
        "pass": "I can see the lap belt in both side guides.",
        "fail": "The lap belt is not in the {missed}.",
        "unseen": "I could not see the lap belt and both side guides."},
    "shoulder_guide": {
        "say": "Slide the shoulder belt into the rear guide behind the carrier's head end.",
        "prompts": ("belt", "guide"), "manual_step": 1,
        "pass": "I can see the shoulder belt in the rear guide.",
        "fail": "The shoulder belt is not in the rear guide.",
        "unseen": "I could not see the rear guide."},
    "no_twist": {
        "say": "Pull the shoulder belt tight and keep the belt flat, with no twist.",
        "prompts": ("belt", "guide"), "manual_step": 2,
        "pass": "The lap belt looks flat across the carrier.",
        "fail": "The lap belt looks twisted across the carrier.",
        "unseen": "I could not see the lap belt well enough to check for a twist."},
    "level_line": {
        "say": "Show me the level line on the side of the carrier, with the phone held level.",
        "prompts": ("level",), "manual_step": 3,
        "pass": "The level line looks level.",
        "fail": "The level line is tilted about {angle} degrees. The manual says it must be level to the ground.",
        "unseen": "I could not see the level line."},
    "handle": {
        "say": "Put the handle upright, in position {position}, the car position.",
        "prompts": ("handle", "belt", "guide"), "manual_step": None,
        "pass": "The handle is upright.",
        "fail": "The handle is not upright. Move it to position {position}.",
        "unseen": "I could not see the handle."},
}
FORBIDDEN = ("safe",)
UNSURE = ("My two checks disagree here, so I am not counting it as passed. Show me another view, or check it by hand "
          "against the manual.")


def load_profiles(cfg, root="."):
    root = Path(root)
    seat = json.loads((root / cfg["seat_profile"]).read_text())
    car = json.loads((root / cfg["car_profile"]).read_text())
    return seat, car


def plan(cfg, seat, car):
    """The ordered steps for this seat and car."""
    steps = [{"id": "car_position", "kind": "ask",
              "say": (f"Coaching the {seat['seat']} in the {car['car']}, installed with the seat belt and no base. "
                      "Put the carrier on a rear seat, facing the back of the car. "
                      + " ".join(r["text"] for r in car["rules"] if r["id"] == "no_front_airbag")
                      + " Is the carrier on a rear seat, facing the back? Say yes or no."),
              "pass_answer": "yes"}]
    position = seat.get("handle_car_position") or 1
    for check_id, step in CAMERA_STEPS.items():
        manual = seat["steps"][step["manual_step"]] if step["manual_step"] is not None and step["manual_step"] < len(seat["steps"]) else None
        steps.append({"id": check_id, "kind": "camera", "say": step["say"].format(position=position), "manual": manual})
    for hand in cfg["hand_checks"]:
        steps.append({"id": hand["id"], "kind": "ask", "say": hand["ask"], "pass_answer": hand.get("pass_answer", "yes"),
                      "source": hand.get("source")})
    return steps


def _yes_no(text):
    words = (text or "").strip().lower().replace(",", " ").replace(".", " ").split()
    if not words:
        return None
    if words[0] in ("yes", "yeah", "yep", "si", "sí", "correct"):
        return "yes"
    if words[0] in ("no", "nope", "not"):
        return "no"
    return None


class Coach:
    def __init__(self, cfg, bus, vision, source, seat, car, recheck=False, answer_timeout_s=None, clock=time.monotonic,
                 muse=None):
        self.cfg, self.bus, self.vision, self.source = cfg, bus, vision, source
        self.muse = muse  # a MuseSeatCheck: Muse Spark Open's second opinion on the same frame
        self.seat, self.car = seat, car
        self.recheck, self.answer_timeout_s, self.clock = recheck, answer_timeout_s, clock
        self.steps = plan(cfg, seat, car)
        self.results = {}
        self.answers, self.answer_ready = {}, threading.Condition()
        self.stop_flag = False
        self.asking = None  # the ask step waiting for the parent's yes or no

    # ---------- speech and logging ----------

    def say(self, text, **fields):
        lowered = text.lower()
        for word in FORBIDDEN:
            if f" {word} " in f" {lowered.replace('.', ' ').replace(',', ' ')} ":
                raise ValueError(f"the coach must never say '{word}': {text}")
        self.bus.publish("voice", text=text, skill="car-seat", stream_s=self.stream_now(), **fields)

    def stream_now(self):
        started = getattr(self.source, "started", None)
        return round(self.clock() - started, 3) if started else 0.0

    # ---------- answers from the parent ----------

    def answer(self, check_id, text):
        """The parent's reply to an ask step, from voice, chat or a tool call."""
        with self.answer_ready:
            self.answers[check_id] = text
            self.answer_ready.notify_all()
        return f"noted for {check_id}"

    def _wait_answer(self, check_id):
        deadline = None if self.answer_timeout_s is None else self.clock() + self.answer_timeout_s
        with self.answer_ready:
            while check_id not in self.answers and not self.stop_flag:
                remaining = None if deadline is None else deadline - self.clock()
                if remaining is not None and remaining <= 0:
                    return None
                self.answer_ready.wait(timeout=0.2 if remaining is None else min(remaining, 0.2))
            return self.answers.get(check_id)

    # ---------- steps ----------

    def run_ask(self, step):
        self.asking = step["id"]
        self.say(step["say"], step=step["id"])
        reply = self._wait_answer(step["id"])
        self.asking = None
        said = _yes_no(reply)
        if said is None:
            result = "open"
        else:
            result = "pass" if said == step["pass_answer"] else "fail"
        self.results[step["id"]] = {"kind": "hand", "result": result, "answer": reply}
        self.bus.publish("carseat_check", check=step["id"], check_kind="hand", result=result, answer=reply)
        if result == "fail":
            self.say("Noted. Please fix this before driving, and ask me to check again.", step=step["id"], result="fail")
        elif result == "open":
            self.say("I will keep this check open in the summary.", step=step["id"], result="open")

    def run_camera(self, step):
        spec = CAMERA_STEPS[step["id"]]
        position = self.seat.get("handle_car_position") or 1
        started_at = self.stream_now()
        _, start_seq, _ = self._latest(0) or (None, 0, 0.0)
        self.say(step["say"], step=step["id"])
        prompts_cfg = self.cfg["prompts"]
        prompts = [prompts_cfg[k] for k in spec["prompts"]]
        deadline = self.clock() + self.cfg.get("step_timeout_s", 8.0)
        seq, first, last_frame = start_seq, None, None
        while self.clock() < deadline and not self.stop_flag:
            got = self._latest(seq)
            if got is None:
                if getattr(self.source, "stopped", False):
                    break
                time.sleep(0.005)
                continue
            frame, seq, frame_s = got
            last_frame = frame
            found, seconds = self.vision.masks(frame, prompts)
            verdict = checks_mod.analyze(found, prompts_cfg, frame.shape[:2], self.cfg.get("checks"))[step["id"]]
            self.bus.publish("carseat_frame", step=step["id"], frame_s=round(frame_s, 3), sam_s=seconds,
                             result=verdict["result"])
            if verdict["result"] == "unseen":
                continue
            if first is None:
                verdict = self.second_opinion(step["id"], frame, verdict)
                first = verdict
                missed = verdict.get("missed") or []
                missed = "near and far side guides" if len(missed) == 2 else f"{missed[0] if missed else 'side'} side guide"
                text = (spec[verdict["result"]] if verdict["result"] in spec else UNSURE).format(missed=missed,
                                                      angle=round(abs(verdict.get("angle_deg", 0))), position=position)
                spoken_at = self.stream_now()
                self.say(text, step=step["id"], result=verdict["result"])
                self._record(step, verdict, started_at, frame_s, spoken_at)
            if verdict["result"] == "pass" or not self.recheck:
                return
            if first["result"] == "fail" and verdict["result"] == "pass":
                return
        if first is None:
            verdict = self.second_opinion(step["id"], last_frame, {"result": "unseen"}) if last_frame is not None else {"result": "unseen"}
            if verdict["result"] == "unseen":
                self.say(spec["unseen"] + " I am listing it as not checked.", step=step["id"], result="unseen")
            else:
                text = spec["fail"].format(missed="side guide", angle="a few", position=position) \
                    if verdict["result"] == "fail" else UNSURE
                self.say(text, step=step["id"], result=verdict["result"])
            self._record(step, verdict, started_at, None, self.stream_now())

    def second_opinion(self, check_id, frame, verdict):
        """SAM's verdict combined with Muse's on the same frame, for the checks Muse votes on (muse_check.py)."""
        from . import muse_check
        if self.muse is None or check_id not in muse_check.MUSE_VOTES:
            return verdict
        muse = self.muse.look(frame, check_id)
        both = muse_check.combine(verdict["result"], muse.get("result"))
        self.bus.publish("carseat_muse", step=check_id, sam=verdict["result"], muse=muse.get("result"),
                         result=both["result"], second_opinion=both["second_opinion"], muse_s=muse.get("seconds"),
                         usd=muse.get("usd"), host=muse.get("host"), error=muse.get("error"))
        return {**verdict, "result": both["result"], "sam_result": verdict["result"], "muse_result": muse.get("result"),
                "second_opinion": both["second_opinion"]}

    def _record(self, step, verdict, started_at, frame_s, spoken_at):
        detail = {k: v for k, v in verdict.items() if k not in ("widths",)}
        self.results[step["id"]] = {"kind": "camera", **detail, "step_started_s": started_at,
                                    "frame_s": None if frame_s is None else round(frame_s, 3), "spoken_s": spoken_at}
        self.bus.publish("carseat_check", check=step["id"], **{("check_kind" if k == "kind" else k): v for k, v in self.results[step["id"]].items()})

    def _latest(self, seq):
        return self.source.latest(seq)

    # ---------- whole run ----------

    def run(self):
        self.bus.publish("skill_armed", skill="car-seat")
        for step in self.steps:
            if self.stop_flag:
                break
            self.bus.publish("carseat_step", step=step["id"], step_kind=step["kind"])
            (self.run_camera if step["kind"] == "camera" else self.run_ask)(step)
        text = self.summary()
        self.say(text, step="summary")
        self.bus.publish("carseat_summary", text=text, results=self.results)
        return self.results

    def summary(self):
        names = {"lap_guides": "lap belt in both side guides", "shoulder_guide": "shoulder belt in the rear guide",
                 "no_twist": "no twist in the lap belt", "level_line": "level line level", "handle": "handle upright",
                 "car_position": "carrier on a rear seat facing back", "belt_path_movement": "less than 2.5 centimeters of movement at the belt path",
                 "harness_pinch": "no slack in the harness pinch test"}
        group = lambda kind, result: [names.get(k, k) for k, v in self.results.items() if v["kind"] == kind and v["result"] == result]
        parts = []
        for label, items in (("Visible checks that passed", group("camera", "pass")),
                             ("Visible checks that failed", group("camera", "fail")),
                             ("Visible checks I could not see", group("camera", "unseen")),
                             ("Visible checks my two checks disagree on, check them by hand", group("camera", "unsure")),
                             ("Hand checks you confirmed", group("hand", "pass")),
                             ("Hand checks that need fixing", group("hand", "fail")),
                             ("Hand checks still open", group("hand", "open"))):
            if items:
                parts.append(f"{label}: {', '.join(items)}.")
        missing = [s["id"] for s in self.steps if s["id"] not in self.results]
        if missing:
            parts.append(f"Not done yet: {', '.join(names.get(m, m) for m in missing)}.")
        parts.append("This is not a verdict on the install. " + self.cfg["technician"])
        return " ".join(parts)

    def stop(self):
        self.stop_flag = True
        with self.answer_ready:
            self.answer_ready.notify_all()
