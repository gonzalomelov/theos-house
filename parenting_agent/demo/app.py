"""The public demo: the real agent core, one isolated demo baby per visitor, spend and abuse caps.

Each visitor gets their own Agent with its own bus, an in-memory memory file and a DemoBabyLog copied from the
simulated week, so visitors never see each other. The brain is the real one (Muse Spark Open on
Baseten, Claude only as a logged fallback). House tools only simulate: they record what the agent would do and touch nothing. There is no
Baby Buddy client, no Home Assistant client and no channel plug-in in here.
"""
import collections
import datetime
import hashlib
import hmac
import ipaddress
import json
import secrets
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

ALLOWED = ["log_baby_event", "edit_baby_event", "delete_baby_event", "read_baby_log", "baby_summary", "next_feed", "current_time",
           "dim_lights", "hold_notifications", "pause_vacuum", "announce"]
# The only sentences the simulated speakers can say. Free text never reaches a speaker, so no code or name is read aloud.
ANNOUNCEMENTS = rules.ANNOUNCEMENTS
ROOMS = ["nursery", "kitchen", "living room", "bedroom", "every room"]
PARENTS = ["Parent A", "Parent B"]
SIMULATED = "Simulated in the demo, nothing ran in a real house"
DEMO_NOTE = """
This is a public demo. The baby is a simulated baby called Demo Baby, a few weeks old, and the log is a simulated week.
The house is simulated too: house tools only show what you would do. When an action in the house would help, for example
dimming the nursery light for a night feed or holding notifications while she sleeps, call the tool and say in a few words
that it is simulated. dim_lights, hold_notifications, pause_vacuum and announce run alone, simulated. announce says only
one of its fixed sentences, never free text. Calling the partner always waits for the parent's yes. Never ask for, keep or
repeat personal details: no real names, codes, addresses or phone numbers. If a visitor gives one, say you do not keep it.
"""

FULL = "The demo is full right now. Please try again in a few minutes."
CLIENT_LIMIT = "That is the end of the demo for today from this connection. Thank you for trying the agent."
NEVER_SENT = "not sent: a code, a password, a phone number or an address is never passed on, ask the parent to share it themselves"
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
    health_gate = True

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
        tools = core_tools(self.memory, self.baby_log, ALLOWED, remember_keys=())  # the demo keeps no facts from visitors
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
        announce = simulated("announce")

        def say_fixed(message, where="nursery"):
            if message not in ANNOUNCEMENTS or where not in ROOMS:
                raise ValueError(f"announce says only one of: {', '.join(ANNOUNCEMENTS)}, in one of: {', '.join(ROOMS)}")
            return announce(message=message, text=ANNOUNCEMENTS[message], where=where)
        tools.add(Tool("announce", "Say one fixed sentence on a house speaker, never free text. Simulated in the demo. "
                       + " ".join(f"{k}: {v}" for k, v in ANNOUNCEMENTS.items()),
                       schema({"message": {"type": "string", "enum": list(ANNOUNCEMENTS)},
                               "where": {"type": "string", "enum": ROOMS}}, ["message"]), say_fixed))
        partner = simulated("call_partner")

        def call_partner(text):
            if rules.personal_detail(text):
                raise ValueError(NEVER_SENT)
            return partner(text=str(text)[:200])
        tools.add(Tool("call_partner", "Ask the other parent to come and help, in a short sentence with no codes or personal "
                       "details. It always waits for the parent's yes.", schema({"text": {"type": "string"}}, ["text"]), call_partner))

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
        # Health advice is refused inside the agent before any brain call, and a dose given or a milestone is logged.
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
        self.clients = Clients(settings)
        self.preview = (0.0, None)

    def visitor(self, vid, fresh=False):
        """The visitor's own demo, made on their first message or reset. None when the demo is full: a visitor who
        is still talking is never dropped to make room for a new one."""
        with self.lock:
            self._evict()
            if fresh or vid not in self.visitors:
                if vid not in self.visitors and len(self.visitors) >= self.s["max_visitors_in_memory"]:
                    return None
                if vid in self.visitors:
                    self.visitors.pop(vid).memory.close()
                self.visitors[vid] = Visitor(self.brain, self.s, self.clock)
            self.visitors.move_to_end(vid)
            v = self.visitors[vid]
            v.last_seen = time.monotonic()
            return v

    def known(self, vid):
        with self.lock:
            return self.visitors.get(vid)

    def _evict(self):
        """Drop visitors idle for visitor_idle_s. When the demo is full, drop the longest idle one only if it has
        been quiet for protect_s: an active conversation is never evicted."""
        now = time.monotonic()
        for vid in [k for k, v in self.visitors.items() if v.last_seen < now - self.s["visitor_idle_s"]]:
            self.visitors.pop(vid).memory.close()
        while len(self.visitors) >= self.s["max_visitors_in_memory"]:
            vid, oldest = next(iter(self.visitors.items()))
            if oldest.last_seen > now - self.s["protect_s"]:
                break
            self.visitors.pop(vid).memory.close()

    def fresh_state(self):
        """What a visitor with no demo yet sees, built at most once a minute and never kept as a visitor, so page
        loads and cookie-less requests cannot fill the demo or push anyone out."""
        made, v = self.preview
        if v is None or time.monotonic() - made > 60:
            if v is not None:
                v.memory.close()
            v = Visitor(self.brain, self.s, self.clock)
            self.preview = (time.monotonic(), v)
        return v

    def remaining(self, vid, internal):
        if internal:
            return None
        return max(0, self.s["max_messages_per_visitor"] - self.records.messages_from(vid))

    def state(self, vid, internal):
        v = self.known(vid) or self.fresh_state()
        return {"proactive": v.proactive(), "recent": v.recent(), "remaining": self.remaining(vid, internal),
                "resting": self.brain.resting(), "max_input": self.s["max_input_chars"]}

    def message(self, vid, internal, text, client=None):
        """Returns (http status, body). Records one session row for each message the demo takes in. client is the
        connection the request came from (Cloudflare's CF-Connecting-IP behind the tunnel), which a visitor cannot
        reset the way they drop a cookie. It is kept only as a keyed hash in memory, never stored or logged."""
        text = (text or "").strip()
        if not text:
            return 400, {"error": "empty"}
        if len(text) > self.s["max_input_chars"]:
            return 413, {"error": "too_long", "reply": TOO_LONG.format(n=self.s["max_input_chars"])}
        if not internal and self.records.messages_from(vid) >= self.s["max_messages_per_visitor"]:
            return 429, {"error": "visitor_limit", "reply": VISITOR_LIMIT, "remaining": 0}
        new = self.known(vid) is None
        if not internal and not self.clients.allow(client, new_visitor=new):
            return 429, {"error": "client_limit", "reply": CLIENT_LIMIT, "remaining": 0}
        if new and self.visitor(vid) is None:
            return 503, {"error": "full", "reply": FULL, "remaining": self.remaining(vid, internal)}
        self.records.add_message(vid, internal)
        if self.brain.resting() or (not internal and self.records.messages_today() > self.s["max_messages_per_day"]):
            return 503, {"error": "resting", "reply": RESTING, "remaining": self.remaining(vid, internal)}
        if not self.thinking.acquire(timeout=20):
            return 503, {"error": "busy", "reply": BUSY, "remaining": self.remaining(vid, internal)}
        try:
            v = self.visitor(vid)
            if v is None:
                return 503, {"error": "full", "reply": FULL, "remaining": self.remaining(vid, internal)}
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

    def reset(self, vid, internal, client=None):
        """A fresh demo baby. It counts as a new visitor for the connection's limit, so resets cannot fill the demo."""
        if not internal and not self.clients.allow(client, new_visitor=True, message=False):
            return 429, {"error": "client_limit", "reply": CLIENT_LIMIT, "remaining": 0}
        if self.visitor(vid, fresh=True) is None:
            return 503, {"error": "full", "reply": FULL}
        return 200, self.state(vid, internal)

    def close(self):
        with self.lock:
            for v in self.visitors.values():
                v.memory.close()
            self.visitors.clear()
            if self.preview[1] is not None:
                self.preview[1].memory.close()
        self.records.close()


class Clients:
    """Limits per connection, which a visitor cannot reset by dropping the cookie: messages per day and new demo
    babies per hour. A connection is kept as an HMAC under a key made at start and held only in memory, so no IP is
    ever stored or logged, and a restart forgets them all."""

    def __init__(self, settings, clock=time.time):
        self.s, self.clock = settings, clock
        self.key = secrets.token_bytes(32)
        self.seen = collections.OrderedDict()
        self.lock = threading.Lock()

    def name(self, client):
        """An IPv6 client counts by its /64, which one home or one phone holds, so rotating addresses inside it does
        not reset the limits."""
        value = str(client or "unknown").strip()
        try:
            address = ipaddress.ip_address(value.split("%")[0])
            if address.version == 6 and not address.ipv4_mapped:
                value = str(ipaddress.ip_network(f"{address}/64", strict=False))
            elif address.version == 6:
                value = str(address.ipv4_mapped)
        except ValueError:
            pass
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()[:32]

    def allow(self, client, new_visitor=False, message=True):
        now = self.clock()
        with self.lock:
            name = self.name(client)
            messages, babies = self.seen.pop(name, ([], []))
            messages = [t for t in messages if t > now - 86400]
            babies = [t for t in babies if t > now - 3600]
            ok = ((not message or len(messages) < self.s["max_messages_per_client"])
                  and (not new_visitor or len(babies) < self.s["max_new_visitors_per_client"]))
            if ok:
                if message:
                    messages.append(now)
                if new_visitor:
                    babies.append(now)
            self.seen[name] = (messages, babies)
            while len(self.seen) > 20000:
                self.seen.popitem(last=False)
            return ok


def dumps(body):
    return json.dumps(body, ensure_ascii=False, default=str).encode()
