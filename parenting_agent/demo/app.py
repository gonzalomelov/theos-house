"""The public demo: the real agent core, one isolated demo baby per visitor, spend and abuse caps.

Each visitor gets their own Agent with its own bus, an in-memory memory file and a DemoBabyLog copied from the
simulated week, so visitors never see each other. The brain is the real one (Claude stand-in, Muse Spark Open on
Baseten later). House tools only simulate: they record what the agent would do and touch nothing. There is no
Baby Buddy client, no Home Assistant client and no channel plug-in in here.
"""
import collections
import datetime
import json
import threading
import time

from ..agent import brain as brain_mod
from ..agent import rules
from ..agent.loop import SYSTEM, Agent
from ..agent.memory import Memory
from ..agent.tools import Tool, core_tools, schema
from ..bus import Bus
from ..rhythm import patterns
from .babylog import TZ, DemoBabyLog
from .records import Records

ALLOWED = ["log_baby_event", "read_baby_log", "baby_summary", "next_feed", "remember", "current_time",
           "dim_lights", "hold_notifications", "pause_vacuum", "announce"]
PARENTS = ["Parent A", "Parent B"]
SIMULATED = "Simulated in the demo, nothing ran in a real house"
DEMO_NOTE = """
This is a public demo. The baby is a simulated baby called Demo Baby, a few weeks old, and the log is a simulated week.
The house is simulated too: house tools only show what you would do. When an action in the house would help, for example
dimming the nursery light for a night feed or holding notifications while she sleeps, call the tool and say in a few words
that it is simulated. Calling the partner always waits for the parent's yes. Never ask for or repeat personal details.
"""

RESTING = ("The demo is resting for today, it reached its daily limit. Please come back tomorrow. "
           "Nothing you typed was lost, it simply was not sent.")
BUSY = "The demo is busy with other visitors right now. Please try again in a few seconds."
VISITOR_LIMIT = "That is the end of this demo session, you reached the message limit. Thank you for trying the agent."
TOO_LONG = "Please keep it under {n} characters."
THINK_FAIL = "I could not think that through just now. Please try again."


class SpendCapReached(brain_mod.BrainError):
    pass


class MeteredBrain:
    """The real brain behind the daily spend cap: refuses before a call once today's spend is at the cap,
    and charges each call's tokens (or a fallback estimate when the provider reports none)."""

    def __init__(self, brain, records, settings, fallback_tokens=(4000, 400)):
        self.brain, self.records, self.s, self.fallback = brain, records, settings, fallback_tokens
        self.name, self.model, self.destination = brain.name, brain.model, brain.destination

    def cost(self, usage):
        tokens_in, tokens_out = ((usage or {}).get("input_tokens"), (usage or {}).get("output_tokens"))
        if not tokens_in and not tokens_out:
            tokens_in, tokens_out = self.fallback
        return (tokens_in * self.s["price_in_per_mtok"] + tokens_out * self.s["price_out_per_mtok"]) / 1_000_000

    def resting(self):
        return self.records.spent_today() >= self.s["daily_usd_cap"]

    def step(self, system, transcript, tools):
        if self.resting():
            raise SpendCapReached("daily spend cap reached")
        reply = self.brain.step(system, transcript, tools)
        self.name, self.model, self.destination = self.brain.name, self.brain.model, self.brain.destination
        if self.brain.name == "fake":
            spend = 0.0
        else:
            spend = reply.usd if reply.usd is not None else self.cost(reply.usage)
        self.records.add_spend(spend)
        return reply


class DemoAgent(Agent):
    def system_prompt(self):
        return super().system_prompt() + DEMO_NOTE


class Visitor:
    """One visitor's demo: their own agent, bus, memory and baby log, plus what the simulated house did."""

    def __init__(self, brain, settings, clock):
        self.clock = clock
        self.lock = threading.Lock()
        self.last_seen = time.monotonic()
        self.bus = Bus(None)
        self.memory = Memory(":memory:")
        self.baby_log = DemoBabyLog(clock=clock)
        tools = core_tools(self.memory, self.baby_log, ALLOWED)
        self.add_house_tools(tools)
        tools.add(Tool("next_feed", "When the next feed is expected, from the rhythm of this baby's own log. Use it for "
                       "'when is the next feed?' and answer with its text.", schema({}), self.next_feed_text))
        self.agent = DemoAgent(self.bus, self.memory, self.baby_log, tools, brain,
                               max_steps=settings["max_steps"], history=settings["history"])
        self.memory.remember("baby_name", "Demo Baby (simulated)")
        self.memory.remember("parents", "Parent A and Parent B")
        self.replies = collections.deque()
        self.bus.subscribe(self.replies.append, ["reply"])

    def add_house_tools(self, tools):
        def simulated(action):
            def run(**arguments):
                self.bus.publish("house_dry", action=action, arguments=arguments)
                return SIMULATED
            return run
        tools.add(Tool("dim_lights", "Dim the lights in a room, for night feeds. Simulated in the demo.",
                       schema({"room": {"type": "string"}, "level": {"type": "integer"}}), simulated("dim_lights")))
        tools.add(Tool("hold_notifications", "Hold phone and speaker notifications while the baby sleeps or the parent's hands are busy. "
                       "Simulated in the demo.", schema({}), simulated("hold_notifications")))
        tools.add(Tool("pause_vacuum", "Pause the robot vacuum so it does not wake the baby. Simulated in the demo.",
                       schema({}), simulated("pause_vacuum")))
        tools.add(Tool("announce", "Say something on a house speaker. Simulated in the demo.",
                       schema({"text": {"type": "string"}, "where": {"type": "string"}}, ["text"]), simulated("announce")))
        tools.add(Tool("call_partner", "Ask the other parent to come and help. It always waits for the parent's yes.",
                       schema({"text": {"type": "string"}}, ["text"]), simulated("call_partner")))

    def actions_since(self, index):
        events = list(self.bus.history)[index:]
        out = []
        for e in events:
            if e["kind"] == "house_dry":
                out.append({"action": e["action"], "arguments": e.get("arguments") or {}, "status": "simulated"})
            elif e["kind"] == "ask_parent":
                out.append({"action": e.get("name"), "arguments": e.get("arguments") or {}, "status": "waits for your yes"})
        return out

    def talk(self, text):
        start = len(self.bus.history)
        self.replies.clear()
        if rules.is_medical(text):
            self.memory.add_message("demo", "user", text)
            self.agent.say("demo", rules.REFUSAL)
        else:
            self.agent.handle({"kind": "message", "channel": "demo", "text": text})
        reply = " ".join(e["text"] for e in self.replies) or "OK."
        return reply, self.actions_since(start)

    def proactive(self):
        """What the agent says first today, computed from this visitor's log: next feed, night summary, notes."""
        now = self.clock().astimezone(TZ)
        rows = self.baby_log.rhythm_rows()
        out = {}
        nxt = patterns.next_feed(rows, now)
        if nxt:
            minutes = round((nxt["at"] - now).total_seconds() / 60)
            when = patterns.hhmm(nxt["at"].astimezone(TZ))
            out["next_feed"] = {"at": when, "in_min": minutes, "gap_min": nxt["gap_min"],
                                "text": (f"Next feed around {when}, in about {minutes} min. Feeds have been about {nxt['gap_min']} min apart."
                                         if minutes >= 0 else f"A feed was expected around {when}, {-minutes} min ago."),
                                "house": ("dim_lights" if patterns.is_night(nxt["at"].astimezone(TZ)) else None)}
        summary = patterns.night_summary(rows, now, TZ, PARENTS)
        out["night_summary"] = {"text": summary["text"], "on_duty": summary["on_duty"]}
        notes = patterns.unusual_notes(rows, TZ)
        out["unusual"] = [n["text"] for n in notes[-2:]]
        return out

    def next_feed_text(self):
        nxt = self.proactive().get("next_feed")
        return nxt["text"] if nxt else "Not enough feeds in the log yet to tell when the next one is."

    def recent(self, limit=6):
        return [{"kind": e["kind"], "at": e["ts"][11:16], "day": e["ts"][:10], "details": e["details"]}
                for e in self.baby_log.entries(None, None, limit)][::-1]


class DemoApp:
    def __init__(self, settings, brain=None, clock=None):
        self.s = settings
        self.clock = clock or (lambda: datetime.datetime.now(TZ))
        self.records = Records(settings["data_dir"])
        raw = brain or brain_mod.build(settings["brain"])
        self.brain = MeteredBrain(raw, self.records, settings)
        self.visitors = collections.OrderedDict()
        self.lock = threading.Lock()
        self.thinking = threading.BoundedSemaphore(settings["max_parallel_brain"])

    def visitor(self, vid, fresh=False):
        with self.lock:
            self._evict()
            if fresh or vid not in self.visitors:
                self.visitors[vid] = Visitor(self.brain, self.s, self.clock)
            self.visitors.move_to_end(vid)
            v = self.visitors[vid]
            v.last_seen = time.monotonic()
            return v

    def _evict(self):
        idle_before = time.monotonic() - self.s["visitor_idle_s"]
        for vid in [k for k, v in self.visitors.items() if v.last_seen < idle_before]:
            self.visitors.pop(vid).memory.close()
        while len(self.visitors) >= self.s["max_visitors_in_memory"]:
            self.visitors.popitem(last=False)[1].memory.close()

    def remaining(self, vid, internal):
        if internal:
            return None
        return max(0, self.s["max_messages_per_visitor"] - self.records.messages_from(vid))

    def state(self, vid, internal):
        v = self.visitor(vid)
        return {"proactive": v.proactive(), "recent": v.recent(), "remaining": self.remaining(vid, internal),
                "resting": self.brain.resting(), "max_input": self.s["max_input_chars"]}

    def message(self, vid, internal, text):
        """Returns (http status, body). Records one session row for each message the demo takes in."""
        text = (text or "").strip()
        if not text:
            return 400, {"error": "empty"}
        if len(text) > self.s["max_input_chars"]:
            return 413, {"error": "too_long", "reply": TOO_LONG.format(n=self.s["max_input_chars"])}
        if not internal and self.records.messages_from(vid) >= self.s["max_messages_per_visitor"]:
            return 429, {"error": "visitor_limit", "reply": VISITOR_LIMIT, "remaining": 0}
        self.records.add_message(vid, internal)
        if self.brain.resting() or (not internal and self.records.messages_today() > self.s["max_messages_per_day"]):
            return 503, {"error": "resting", "reply": RESTING, "remaining": self.remaining(vid, internal)}
        if not self.thinking.acquire(timeout=20):
            return 503, {"error": "busy", "reply": BUSY, "remaining": self.remaining(vid, internal)}
        try:
            v = self.visitor(vid)
            with v.lock:
                try:
                    reply, actions = v.talk(text)
                except SpendCapReached:
                    v.memory.add_message("demo", "assistant", RESTING)
                    return 503, {"error": "resting", "reply": RESTING, "remaining": self.remaining(vid, internal)}
                except brain_mod.BrainError as error:
                    v.bus.publish("agent_error", error=str(error)[:300])
                    v.memory.add_message("demo", "assistant", THINK_FAIL)
                    return 502, {"error": "brain", "reply": THINK_FAIL, "remaining": self.remaining(vid, internal)}
            return 200, {"reply": reply, "actions": actions, "proactive": v.proactive(), "recent": v.recent(),
                         "remaining": self.remaining(vid, internal)}
        finally:
            self.thinking.release()

    def reset(self, vid, internal):
        self.visitor(vid, fresh=True)
        return self.state(vid, internal)

    def close(self):
        with self.lock:
            for v in self.visitors.values():
                v.memory.close()
            self.visitors.clear()
        self.records.close()


def dumps(body):
    return json.dumps(body, ensure_ascii=False, default=str).encode()
