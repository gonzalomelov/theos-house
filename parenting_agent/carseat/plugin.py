"""Car seat coach as a plug-in of the persistent agent.

Add "parenting_agent.carseat.plugin:CarSeatCoach" to the agent config plugins and the three tools to
allowed_tools, with an optional "car_seat" block:
    {"skill": "skills/car-seat.json", "source": "phone" | "0" | "clip.mp4",
     "muse": {"enabled": true, "samples": 3}}
The parent says "help me install the car seat": the brain calls start_car_seat_coach. Each spoken answer
("yes", "no") reaches the coach through answer_car_seat_check. car_seat_outgrow reads weight and height
from Baby Buddy and compares them with the seat's limits. Frames stay on this Mac, the brain gets text only, except
with "muse" enabled: then one zoomed still per camera step goes to Muse Spark Open on Baseten for a second opinion
(parenting_agent/carseat/muse_check.py).
"""
import datetime
import json
import threading
from pathlib import Path

from ..agent import rules
from ..agent.plugins import Plugin
from ..agent.tools import Tool, schema
from ..sources import PhoneSource, open_source
from ..speaker import Speaker
from . import outgrow
from .coach import Coach, _yes_no, load_profiles

# While the coach runs, it says the steps itself: the brain must not write its own install steps (Oct 30 rehearsal: Muse
# told the parent to place a base the Joie i-Snug does not have, over the coach's own step).
COACHING_NOTE = ("The car seat coach is running and speaks each install step itself from the seat's manual. Do not give "
                 "car seat install steps or advice of your own. Answer in one short sentence, and pass a yes or no to "
                 "the coach's question with answer_car_seat_check.")


class CarSeatCoach(Plugin):
    name = "car-seat"
    kind = "skill"

    def __init__(self, agent, config, vision=None, source=None, quiet=False):
        super().__init__(agent, config)
        self.cfg = {"skill": "skills/car-seat.json", "source": "phone", "channel": "console", **config.get("car_seat", {})}
        self.skill_cfg = json.loads(Path(self.cfg["skill"]).read_text())
        self.seat, self.car = load_profiles(self.skill_cfg)
        self._vision, self._source, self.quiet = vision, source, quiet
        self.coach, self.thread, self.source = None, None, None
        self.lock = threading.Lock()
        if hasattr(agent, "answer_takers"):
            agent.answer_takers.append(self.take_answer)
        agent.tools.add(Tool("start_car_seat_coach", "Coach the parent through installing the infant car seat with the car's seat belt, step by step, with the head camera.",
                             schema({}), self.start_coach))
        agent.tools.add(Tool("answer_car_seat_check", "Pass the parent's yes or no answer to the car seat coach's current question.",
                             schema({"check": {"type": "string", "description": "the check id the coach asked about"},
                                     "answer": {"type": "string"}}, ["check", "answer"]), self.answer))
        agent.tools.add(Tool("car_seat_outgrow", "Compare the baby's latest weight and height in Baby Buddy with the car seat's limits.",
                             schema({}), self.outgrow))

    def start_coach(self):
        with self.lock:
            if self.coach is not None and self.thread.is_alive():
                return "the car seat coach is already running"
            from .sam3_masks import Sam3Masks
            vision = self._vision or Sam3Masks(self.skill_cfg.get("sam3"))
            self.source = self._source or open_source(self.cfg["source"])
            if isinstance(self.source, PhoneSource):
                self.agent.bus.publish("head_camera", url=self.source.url)
            speaker = Speaker(self.source, quiet=self.quiet)
            self.agent.bus.subscribe(speaker.on_event, ["voice"])
            self.coach = Coach(self.skill_cfg, self.agent.bus, vision, self.source, self.seat, self.car, recheck=True,
                               muse=self.muse_check())
            notes = getattr(self.agent, "prompt_notes", None)
            if notes is not None and COACHING_NOTE not in notes:
                notes.append(COACHING_NOTE)
            self.thread = threading.Thread(target=self._run, name="car-seat", daemon=True)
            self.thread.start()
            return f"coaching the {self.seat['seat']} install, one step at a time"

    def muse_check(self):
        muse = self.cfg.get("muse") or {}
        if not muse.get("enabled"):
            return None
        from ..muse_senses import MuseSenses
        from .muse_check import MuseSeatCheck
        return MuseSeatCheck(MuseSenses(muse.get("senses")), samples=muse.get("samples", 3))

    def take_answer(self, event, text):
        """A plain yes or no on the coach's channel answers the step it is asking, so the answer never depends on the
        brain choosing the tool (Oct 30 rehearsal: Muse answered "sí" in its own words and the step stayed open, then
        the agent said nothing was waiting for a yes). Returns the short reply, or None for a message not for the coach."""
        coach = self.coach
        said = _yes_no(text)
        if coach is None or event.get("channel") != self.cfg["channel"] or said is None:
            return None
        asking = getattr(coach, "asking", None)
        if asking is None or asking in coach.answers:
            return None
        coach.answer(asking, text)
        self.agent.bus.publish("carseat_heard", check=asking, answer=said)
        spanish = rules.looks_spanish(text) or text.strip().lower().startswith(("sí", "si"))
        return ("Anotado: sí." if said == "yes" else "Anotado: no.") if spanish else f"Noted: {said}."

    def _run(self):
        try:
            self.coach.run()
        finally:
            notes = getattr(self.agent, "prompt_notes", None)
            if notes is not None and COACHING_NOTE in notes:
                notes.remove(COACHING_NOTE)
        summary = next(e for e in reversed(self.agent.bus.history) if e["kind"] == "carseat_summary")
        self.agent.bus.publish("observation", source=self.name, channel=self.cfg["channel"], text="Car seat coach finished. " + summary["text"])

    def answer(self, check, answer):
        if self.coach is None:
            return "the car seat coach is not running"
        return self.coach.answer(check, answer)

    def outgrow(self):
        log = self.agent.baby_log
        if not hasattr(log, "request"):
            return "the outgrow watch needs Baby Buddy as the baby log"
        weights, heights = outgrow.from_babybuddy(log.request, log.child())
        result = outgrow.watch(weights, heights, self.seat["limits"], datetime.date.today(), seat=self.seat["seat"])
        self.agent.bus.publish("carseat_outgrow", **{k: v for k, v in result.items() if k != "text"})
        return result["text"]

    def stop(self):
        if self.coach is not None:
            self.coach.stop()
        if self.source is not None and self._source is None:
            self.source.close()
