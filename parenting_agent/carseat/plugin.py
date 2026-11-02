"""Car seat coach as a plug-in of the persistent agent.

Add "parenting_agent.carseat.plugin:CarSeatCoach" to the agent config plugins and the three tools to
allowed_tools, with an optional "car_seat" block:
    {"skill": "skills/car-seat.json", "source": "phone" | "0" | "clip.mp4",
     "muse": {"enabled": true, "samples": 3}}
The parent says "help me install the car seat": the brain calls start_car_seat_coach. The coach speaks the language of
the parent who asked (the people block "lang", else the words of the request), and every line it says also goes to that
parent's chat when the request came on a chat channel such as Telegram: the glasses show it as a card and speak it. Its
summary is the last line, said by the coach itself, never rewritten by the brain. Each spoken answer ("yes", "no",
"sí") reaches the coach through answer_car_seat_check, and a spoken "listo" or "ya" tells it a camera step is done. car_seat_outgrow reads weight and height
from Baby Buddy and compares them with the seat's limits. Frames stay on this Mac, the brain gets text only, except
with "muse" enabled: then one zoomed still per camera step goes to Muse Spark Open on Baseten for a second opinion
(parenting_agent/carseat/muse_check.py).
"""
import datetime
import json
import re
import threading
from pathlib import Path

from ..agent import rules
from ..agent.plugins import Plugin
from ..agent.tools import Tool, schema
from ..sources import PhoneSource, open_source
from ..speaker import Speaker
from . import outgrow
from .coach import LINES, Coach, _yes_no, is_ready, load_profiles

# While the coach runs, it says the steps itself: the brain must not write its own install steps (Oct 30 rehearsal: Muse
# told the parent to place a base the Joie i-Snug does not have, over the coach's own step).
COACHING_NOTE = ("The car seat coach is running and speaks each install step itself from the seat's manual. Do not give "
                 "car seat install steps or advice of your own. Answer in one short sentence, and pass a yes or no to "
                 "the coach's question with answer_car_seat_check.")
# "Agente, ayudame a instalar la silla del auto" starts the coach without the brain choosing the tool: in 2 of 4 glasses
# speech runs (Oct 30) Muse answered in its own words ("Vamos paso a paso...") and the coach never started.
INSTALL = re.compile(r"\b(instal\w*|coloc\w*|poner|pone|pongo|install\w*|put in|set up|fit)\b")
SEAT = re.compile(r"\b(car ?seat|infant seat|(silla|sillita|butaca|huevito)( \w+){0,2} (auto|coche|carro))\b")
STARTED = {"es": "Dale, arrancamos con la silla.", "en": "OK, let's start with the car seat."}
ALREADY = {"es": "Ya estamos con la silla, sigo con el paso de ahora.", "en": "We are on the car seat already, on to the current step."}


def wants_install(text):
    """True for a request to install the car seat, in Spanish or English: an install word and the car seat. A red flag
    is never one, it goes to the 911 line."""
    from ..glasses_speech import plain
    said = plain(text)
    return bool(INSTALL.search(said) and SEAT.search(said)) and not rules.is_emergency(text)


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
        self.asked = {}  # the channel, chat and person that started the coach, and the language it speaks
        self.lock = threading.Lock()
        self.after_reply = None  # what an answer taken by the coach does once its short reply went out
        agent.bus.subscribe(self.relay, ["voice"])
        agent.bus.subscribe(self.replied, ["reply"])
        if hasattr(agent, "answer_takers"):
            agent.answer_takers.append(self.take_answer)
        agent.tools.add(Tool("start_car_seat_coach", "Coach the parent through installing the infant car seat with the car's seat belt, step by step, with the head camera.",
                             schema({}), self.start_coach))
        agent.tools.add(Tool("answer_car_seat_check", "Pass the parent's yes or no answer to the car seat coach's current question.",
                             schema({"check": {"type": "string", "description": "the check id the coach asked about"},
                                     "answer": {"type": "string"}}, ["check", "answer"]), self.answer))
        agent.tools.add(Tool("car_seat_outgrow", "Compare the baby's latest weight and height in Baby Buddy with the car seat's limits.",
                             schema({}), self.outgrow))

    def start_coach(self, defer=False):
        """defer: the coach's first line waits for the agent's short reply to the request, so the lens shows step 1
        last, not the reply over it."""
        with self.lock:
            if self.coach is not None and self.thread.is_alive():
                return "the car seat coach is already running"
            from .sam3_masks import Sam3Masks
            vision = self._vision or Sam3Masks(self.skill_cfg.get("sam3"))
            self.source = self._source or open_source(self.cfg["source"])
            if isinstance(self.source, PhoneSource):
                self.agent.bus.publish("head_camera", url=self.source.url)
            speaker = Speaker(self.source, quiet=self.quiet or bool(self.cfg.get("quiet")))
            self.agent.bus.subscribe(speaker.on_event, ["voice"])
            self.asked = self.who_asked()
            self.coach = Coach(self.skill_cfg, self.agent.bus, vision, self.source, self.seat, self.car,
                               muse=self.muse_check(), lang=self.asked["lang"])
            notes = getattr(self.agent, "prompt_notes", None)
            if notes is not None and COACHING_NOTE not in notes:
                notes.append(COACHING_NOTE)
            self.thread = threading.Thread(target=self._run, name="car-seat", daemon=True)
            if defer:
                self.after_reply = self.thread.start
            else:
                self.thread.start()
            return f"coaching the {self.seat['seat']} install, one step at a time"

    def who_asked(self):
        """The channel, chat and person of the message that started the coach, and the language to coach in: the
        person's "lang" in the people block, else Spanish for a request in Spanish, else the family's language."""
        event = getattr(self.agent, "current_event", None) or {}
        people = getattr(self.agent, "people", None)
        person = event.get("person")
        lang = people.lang(person) if people is not None and person else None
        if lang is None and event.get("kind") == "message" and event.get("text"):
            lang = "es" if rules.looks_spanish(event["text"]) else "en"
        lang = lang or self.cfg.get("lang") or (people.family_lang() if people is not None else None) or "en"
        channel = event.get("channel") if event.get("kind") == "message" else None
        return {"channel": channel or self.cfg["channel"], "chat_id": event.get("chat_id"), "person": person,
                "lang": lang}

    def relay(self, event):
        """Each coach line to the chat the coach was started from (Telegram), as the agent's own message. On the
        glasses and the console the line is already spoken and shown, so nothing more goes there."""
        channel = self.asked.get("channel")
        if event.get("skill") != "car-seat" or channel in (None, "glasses", "console") or not event.get("text"):
            return
        to = {"chat_id": self.asked["chat_id"]} if self.asked.get("chat_id") else {}
        self.agent.bus.publish("reply", channel=channel, text=event["text"], person=self.asked.get("person"),
                               proactive=True, source="car-seat", routine="car_seat", step=event.get("step"), **to)

    def muse_check(self):
        muse = self.cfg.get("muse") or {}
        if not muse.get("enabled"):
            return None
        from ..muse_senses import MuseSenses
        from .muse_check import MuseSeatCheck
        return MuseSeatCheck(MuseSenses(muse.get("senses")), samples=muse.get("samples", 3))

    def running(self):
        return self.coach is not None and (self.thread is None or self.thread.is_alive() or self.after_reply is not None)

    def replied(self, event):
        """The agent said the coach's short reply ("Anotado: sí."): only now the coach moves on, so its next step comes
        after that reply on the lens and in the voice (Nov 1 proof run: the reply card covered the next step's card)."""
        then, self.after_reply = self.after_reply, None
        if then is not None:
            then()

    def take_answer(self, event, text):
        """A plain yes or no on the coach's channel answers the step it is asking, so the answer never depends on the
        brain choosing the tool (Oct 30 rehearsal: Muse answered "sí" in its own words and the step stayed open, then
        the agent said nothing was waiting for a yes). A request to install the car seat starts the coach the same way.
        Returns the short reply, or None for a message not for the coach."""
        if not self.running():
            if "start_car_seat_coach" not in self.agent.tools.allowed or not wants_install(text):
                return None
            self.start_coach(defer=True)
            return STARTED[self.asked.get("lang") if self.asked.get("lang") in STARTED else "en"]
        coach = self.coach
        if wants_install(text):
            return ALREADY[getattr(coach, "lang", "en")]
        if event.get("channel") not in (self.cfg["channel"], self.asked.get("channel")):
            return None
        waiting = getattr(coach, "waiting", None)
        if waiting is not None and is_ready(text):
            self.after_reply = lambda: (coach.ready(waiting),
                                        self.agent.bus.publish("carseat_heard", check=waiting, answer="ready"))
            return LINES[getattr(coach, "lang", "en")]["ready"]
        said = _yes_no(text)
        if said is None:
            return None
        asking = getattr(coach, "asking", None)
        if asking is None or asking in coach.answers:
            return None
        self.after_reply = lambda: (coach.answer(asking, text),
                                    self.agent.bus.publish("carseat_heard", check=asking, answer=said))
        if getattr(coach, "lang", "en") == "es" or rules.looks_spanish(text) or text.strip().lower().startswith(("sí", "si")):
            return "Anotado: sí." if said == "yes" else "Anotado: no."
        return f"Noted: {said}."

    def _run(self):
        try:
            self.coach.run()
        finally:
            notes = getattr(self.agent, "prompt_notes", None)
            if notes is not None and COACHING_NOTE in notes:
                notes.remove(COACHING_NOTE)
        # The summary is the coach's own last line, already spoken and sent. It is kept in the conversation so a later
        # question about the install has it, and never handed to the brain to say again in its own words.
        summary = next((e for e in reversed(self.agent.bus.history) if e["kind"] == "carseat_summary"), None)
        memory = getattr(self.agent, "memory", None)
        if summary is not None and memory is not None:
            memory.add_message(self.asked.get("channel") or self.cfg["channel"], "assistant", summary["text"],
                               ts=self.agent.now())

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
