"""The families service: the invite gate, 3 onboarding questions, one private log per family, caps.

handle() takes one Telegram message and returns the messages to send as (chat_id, text) pairs. tick() returns
the next feed reminders and daily summaries that are due. Neither sends anything itself, the bot does.

Walled off: each family gets its own agent with its own bus, its own SQLite file and only the log tools. There is
no Baby Buddy client, no Home Assistant client, no house tool and no channel plug-in in here.
"""
import collections
import datetime
import json
import re
import threading
import time
import zoneinfo

from ..agent import brain as brain_mod
from ..agent import rules
from ..agent.loop import SYSTEM, Agent
from ..agent.tools import core_tools
from ..bus import Bus
from ..rhythm import patterns
from . import babylog
from .store import Store, visitor_id

ALLOWED = ["log_baby_event", "read_baby_log", "baby_summary", "remember", "current_time"]
CHANNEL = "telegram"
MAX_PARENTS = 4
DELETE_WINDOW_S = 600
YES = {"yes", "y", "si", "sí", "s", "ok", "dale", "sure", "yes please"}
START = re.compile(r"^/start(?:@\w+)?(?:\s+(\S+))?\s*$", re.I)
COMMAND = re.compile(r"^/(\w+)(?:@\w+)?\s*(.*)$", re.S)
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y")

FAMILY_NOTE = """
This is one family's private log on Telegram. The baby is {name}, born {born}. Call the baby by name.
There are no house tools here and you cannot act in the house, never offer to. Never ask for or repeat personal details
such as addresses or phone numbers.
"""

NO_CODE = ("Hi. This bot is a private beta for invited families. If someone gave you an invite code, "
           "send /start followed by the code, for example /start K7QM3XPA.")
BAD_CODE = "That invite code is not valid or was already used. Please check it, or ask the person who invited you for a new one."
TOO_MANY = "Too many codes tried today. Please try again tomorrow."
FULL = "The beta is full right now. Thank you for your interest."
GROUP = "I only work in a private chat. Please message me directly."
ALREADY = "You are already set up. Send /help to see what I can do."
TOO_LONG = "Please keep it under {n} characters."
FAMILY_LIMIT = "Your family reached today's message limit. I will be back tomorrow. Nothing was logged from this message."
THINK_FAIL = "I could not think that through just now. Please try again."

WELCOME = ("Welcome. I keep a private log of your baby's feeds, diapers, sleep and baths, answer questions from it, "
           "remind you of the next feed and send a short summary each evening. I never give medical advice. "
           "Three quick questions and you are logging. Send /privacy to read what I store.\n\n"
           "1 of 3. What is your baby's name or nickname?")
ASK_BORN = "2 of 3. When was {name} born? For example 2026-10-12 or 12/10/2026."
BAD_BORN = "I could not read that date. Please write it like 2026-10-12 or 12/10/2026. It cannot be in the future."
ASK_PARTNER = ("3 of 3. Should the other parent log too? Reply yes and I will make an invite code for them, "
               "or no. You can also send /invite later.")
READY = ("All set for {name}. Just write what happened, for example:\n"
         "bottle 120 ml\nleft breast 15 min\nwet and dirty diaper\n{name} fell asleep\n{name} woke up\nbath done\n\n"
         "Or ask: when did {name} last eat? How much did {name} drink today?\n\n"
         "/summary today so far, /next next feed, /invite the other parent, /reminders off or on, "
         "/privacy what I store, /deletemydata delete everything.")
PARTNER_CODE = ("Here is the invite for the other parent, valid for {days} days and for one person:\n{code}\n{link}"
                "They send /start {code} to this bot and join {name}'s log.")
PARTNER_WELCOME = ("Welcome. You joined {name}'s log. You and the other parent see and add to the same private log. "
                   "I never give medical advice. Send /privacy to read what I store.\n\n")
PRIVACY = ("What I store: your baby's name and birth date, what you log (feeds, diapers, sleep, baths, notes), "
           "our conversation, and your Telegram chat id so I can answer you. For counting real use I keep one row per "
           "message with the time and a scrambled id, never the text.\n"
           "Where: one private file for your family on a small server in Gonza's home in Uruguay. Other families "
           "cannot see it. To answer, the text of the conversation goes to an AI model (Anthropic Claude now, "
           "Meta's Muse Spark later), which does not keep it or train on it. Telegram carries the messages.\n"
           "Delete: send /deletemydata. It removes your family's file, the conversation, the rows and both parents' access, at once.")
DELETE_ASK = ("This deletes {name}'s whole log, our conversation and access for everyone in your family. It cannot be undone. "
              "Send DELETE to confirm. Anything else cancels.")
DELETE_CANCELLED = "Not deleted. Everything is still here."
DELETED = "Done. Everything about your family is deleted. Send /start with a new invite code if you ever want to come back."
DELETED_OTHER = "The other parent deleted your family's data. Everything is gone. Thank you for trying the agent."
HELP = READY


def _n(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def _hm(minutes):
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def parse_birth(text, today):
    words = text.strip().lower()
    if words in ("today", "hoy"):
        return today
    if words in ("yesterday", "ayer"):
        return today - datetime.timedelta(days=1)
    for fmt in DATE_FORMATS:
        try:
            day = datetime.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
        if today - datetime.timedelta(days=3 * 366) <= day <= today:
            return day
        return None
    return None


class FamilyAgent(Agent):
    def system_prompt(self):
        """The core prompt with the family's own facts only. Keys starting with _ are the service's bookkeeping."""
        facts = {k: v["value"] for k, v in self.memory.facts().items() if not k.startswith("_")}
        base = SYSTEM.format(today=datetime.date.today().isoformat(), facts=json.dumps(facts or "none yet", ensure_ascii=False))
        return base + FAMILY_NOTE.format(name=facts.get("baby_name", "the baby"), born=facts.get("birth_date", "recently"))


class FamilyBrain:
    """The real brain behind the caps: once the family's or the whole service's spend for today is at its cap,
    the free rule-based brain takes over so logging and simple questions keep working."""

    def __init__(self, service, family_id, fallback_tokens=(4000, 400)):
        self.service, self.family_id, self.fallback = service, family_id, fallback_tokens
        self.real, self.rules = service.brain, brain_mod.FakeBrain()
        self.name, self.model, self.destination = self.real.name, self.real.model, self.real.destination

    def capped(self):
        store, s = self.service.store, self.service.s
        return store.spent_today() >= s["daily_usd_cap"] or store.spent_today(self.family_id) >= s["family_daily_usd"]

    def cost(self, usage):
        tokens_in, tokens_out = (usage or {}).get("input_tokens"), (usage or {}).get("output_tokens")
        if not tokens_in and not tokens_out:
            tokens_in, tokens_out = self.fallback
        s = self.service.s
        return (tokens_in * s["price_in_per_mtok"] + tokens_out * s["price_out_per_mtok"]) / 1_000_000

    def step(self, system, transcript, tools):
        if self.real.name == "fake" or self.capped():
            self.name, self.destination = "fake", self.rules.destination
            return self.rules.step(system, transcript, tools)
        self.name, self.destination = self.real.name, self.real.destination
        reply = self.real.step(system, transcript, tools)
        self.service.store.add_spend(self.family_id, self.cost(reply.usage))
        return reply


class Family:
    """One family's agent, bus, memory file and log. Nothing here is shared with another family."""

    def __init__(self, service, family_id):
        self.family_id = family_id
        self.lock = threading.Lock()
        self.last_seen = time.monotonic()
        self.memory = babylog.open_memory(service.s["data_dir"], family_id)
        self.log = babylog.FamilyBabyLog(self.memory, service.now)
        self.bus = Bus(None)
        tools = core_tools(self.memory, self.log, ALLOWED)
        self.agent = FamilyAgent(self.bus, self.memory, self.log, tools, FamilyBrain(service, family_id),
                                 max_steps=service.s["max_steps"], history=service.s["history"])
        self.replies = collections.deque()
        self.bus.subscribe(self.replies.append, ["reply"])

    def fact(self, key, default=""):
        return self.memory.facts().get(key, {}).get("value") or default

    @property
    def name(self):
        return self.fact("baby_name", "your baby")

    def talk(self, text):
        self.replies.clear()
        if rules.is_medical(text):
            self.memory.add_message(CHANNEL, "user", text)
            self.agent.say(CHANNEL, rules.REFUSAL)
        else:
            self.agent.handle({"kind": "message", "channel": CHANNEL, "text": text})
        return " ".join(e["text"] for e in self.replies) or "OK."

    def close(self):
        self.memory.close()
        self.bus.close()


class Families:
    def __init__(self, settings, brain=None, clock=None):
        self.s = settings
        self.tz = zoneinfo.ZoneInfo(settings["tz"])
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self.store = Store(settings["data_dir"], clock=lambda: self.clock())
        self.brain = brain or brain_mod.build(settings["brain"])
        self.families = collections.OrderedDict()
        self.lock = threading.Lock()
        self.bad_codes = collections.Counter()

    def now(self):
        return self.clock().astimezone(self.tz)

    # Families in memory

    def family(self, family_id):
        with self.lock:
            idle_before = time.monotonic() - 3600
            for fid in [k for k, f in self.families.items() if f.last_seen < idle_before and k != family_id]:
                self.families.pop(fid).close()
            if family_id not in self.families:
                self.families[family_id] = Family(self, family_id)
            f = self.families[family_id]
            f.last_seen = time.monotonic()
            return f

    def forget(self, family_id):
        with self.lock:
            f = self.families.pop(family_id, None)
        if f:
            f.close()

    def invite_link(self, code):
        user = self.s.get("bot_username")
        return f"https://t.me/{user}?start={code}\n" if user else ""

    # One message in

    def handle(self, user_id, chat_id, text, chat_type="private"):
        text = (text or "").strip()
        if chat_type and chat_type != "private":
            return [(chat_id, GROUP)]
        if not user_id or not text:
            return []
        vid = visitor_id(user_id)
        parent = self.store.parent(vid)
        if parent is None:
            return [(chat_id, self.gate(vid, str(user_id), chat_id, text))]
        if len(text) > self.s["max_input_chars"]:
            return [(chat_id, TOO_LONG.format(n=self.s["max_input_chars"]))]
        family_id = parent["family_id"]
        if self.store.family_messages_today(family_id) >= self.s["max_messages_per_family_day"]:
            return [(chat_id, FAMILY_LIMIT)]
        self.store.add_message(vid, family_id, parent["internal"])
        f = self.family(family_id)
        with f.lock:
            pending_delete = f.fact("_delete_asked")
            if pending_delete:
                f.memory.remember("_delete_asked", "")
                if text.strip(" .!").upper() == "DELETE" and time.time() - float(pending_delete) <= DELETE_WINDOW_S:
                    return self.delete(family_id, chat_id)
                return [(chat_id, DELETE_CANCELLED)]
            command = COMMAND.match(text)
            if command:
                return [(chat_id, self.command(f, parent, command.group(1).lower(), command.group(2).strip()))]
            if parent["step"] != "ready":
                return [(chat_id, self.onboard(f, parent, text))]
            try:
                return [(chat_id, f.talk(text))]
            except brain_mod.BrainError as error:
                f.bus.publish("agent_error", error=str(error)[:300])
                return [(chat_id, THINK_FAIL)]

    def gate(self, vid, user_id, chat_id, text):
        """Strangers: only a valid invite code gets in. Nothing about a stranger is stored on disk."""
        start = START.match(text)
        if not start or not start.group(1):
            return NO_CODE
        day = self.store.today()
        if self.bad_codes[(vid, day)] >= self.s["max_bad_codes_per_day"]:
            return TOO_MANY
        code = start.group(1)
        invite = self.store.invite(code)
        if invite is None:
            self.bad_codes[(vid, day)] += 1
            return BAD_CODE
        family_id = invite["family_id"]
        if family_id is None and self.store.family_count() >= self.s["max_families"]:
            return FULL
        if family_id is not None and len(self.store.parents_of(family_id)) >= MAX_PARENTS:
            return BAD_CODE
        if not self.store.use_invite(code, vid):
            return BAD_CODE
        internal = invite["internal"] or user_id in self.s["internal_user_ids"]
        if family_id is None:
            family_id = self.store.create_family()
            self.store.add_parent(vid, chat_id, family_id, "baby_name", internal)
            self.store.add_message(vid, family_id, internal)
            self.family(family_id)
            return WELCOME
        self.store.add_parent(vid, chat_id, family_id, "ready", internal)
        self.store.add_message(vid, family_id, internal)
        name = self.family(family_id).name
        return PARTNER_WELCOME.format(name=name) + READY.format(name=name)

    def onboard(self, f, parent, text):
        step, vid = parent["step"], parent["visitor_id"]
        if step == "baby_name":
            name = " ".join(text.split())[:40].strip(" .!")
            if not name:
                return WELCOME.rsplit("\n\n", 1)[-1]
            f.memory.remember("baby_name", name)
            self.store.set_step(vid, "birth_date")
            return ASK_BORN.format(name=name)
        if step == "birth_date":
            born = parse_birth(text, self.now().date())
            if born is None:
                return BAD_BORN
            f.memory.remember("birth_date", born.isoformat())
            self.store.set_step(vid, "partner")
            return ASK_PARTNER
        self.store.set_step(vid, "ready")
        ready = READY.format(name=f.name)
        if text.lower().strip(" .!") in YES:
            return self.partner_invite(f, parent) + "\n\n" + ready
        return ready

    def partner_invite(self, f, parent):
        if len(self.store.parents_of(f.family_id)) >= MAX_PARENTS:
            return f"{f.name}'s log already has {MAX_PARENTS} people, the most it can have."
        code = self.store.create_invite(f.family_id, self.s["invite_days"], internal=parent["internal"])
        return PARTNER_CODE.format(code=code, link=self.invite_link(code), days=self.s["invite_days"], name=f.name)

    def command(self, f, parent, name, arg):
        ready = parent["step"] == "ready"
        if name == "start":
            return ALREADY if ready else self.onboard_prompt(f, parent)
        if name == "privacy":
            return PRIVACY
        if name == "deletemydata":
            f.memory.remember("_delete_asked", str(time.time()))
            return DELETE_ASK.format(name=f.name)
        if not ready:
            return self.onboard_prompt(f, parent)
        if name == "summary":
            return self.summary_text(f)
        if name == "next":
            return self.next_feed(f)["text"]
        if name == "invite":
            return self.partner_invite(f, parent)
        if name == "reminders":
            off = arg.lower() == "off"
            f.memory.remember("_reminders", "off" if off else "on")
            return "Feed reminders are off. Send /reminders on to turn them back on." if off else "Feed reminders are on."
        return HELP.format(name=f.name)

    def onboard_prompt(self, f, parent):
        step = parent["step"]
        if step == "baby_name":
            return WELCOME.rsplit("\n\n", 1)[-1]
        if step == "birth_date":
            return ASK_BORN.format(name=f.name)
        return ASK_PARTNER

    def delete(self, family_id, chat_id):
        others = [p["chat_id"] for p in self.store.parents_of(family_id) if p["chat_id"] != str(chat_id)]
        self.forget(family_id)
        babylog.wipe(self.s["data_dir"], family_id)
        self.store.delete_family(family_id)
        return [(chat_id, DELETED)] + [(other, DELETED_OTHER) for other in others]

    # What the agent says first

    def next_feed(self, f, now=None):
        now = now or self.now()
        nxt = patterns.next_feed(f.log.rhythm_rows(), now)
        if not nxt:
            return {"text": f"I need two feeds in {f.name}'s log before I can tell the next one.", "at": None}
        minutes = round((nxt["at"] - now).total_seconds() / 60)
        when = patterns.hhmm(nxt["at"].astimezone(self.tz))
        text = (f"Next feed for {f.name} around {when}, in about {minutes} min. Feeds have been about {_hm(nxt['gap_min'])} apart."
                if minutes >= 0 else f"A feed for {f.name} was expected around {when}, {_hm(-minutes)} ago.")
        return {"text": text, "at": nxt["at"], "last": nxt["computed_from"][-1]}

    def summary_text(self, f, now=None):
        now = now or self.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        s = f.log.summary(midnight.isoformat(timespec="seconds"))
        feeds, diapers, sleep, baths = s["feedings"], s["diapers"], s["sleep"], s["baths"]
        if not (feeds["count"] or diapers["count"] or sleep["count"] or baths["count"]):
            return f"Nothing logged for {f.name} today yet."
        parts = [f"Today for {f.name}:"]
        if feeds["count"]:
            parts.append(_n(feeds["count"], "feed") + (f", {feeds['total_ml']} ml in total" if feeds["total_ml"] else "")
                         + f", the last at {feeds['last_at']}.")
        if diapers["count"]:
            parts.append(f"{_n(diapers['count'], 'diaper')}, {diapers['wet']} wet and {diapers['dirty']} dirty.")
        if sleep["count"]:
            parts.append(f"{_hm(sleep['total_min'])} of sleep over {_n(sleep['count'], 'sleep')}.")
        if baths["count"]:
            parts.append(f"Bath at {baths['last_at']}.")
        nxt = self.next_feed(f, now)
        if nxt["at"] is not None:
            parts.append(nxt["text"])
        return " ".join(parts)

    def tick(self, now=None):
        """Reminders and summaries due now, as (chat_id, text). Each is sent once."""
        now = (now or self.now()).astimezone(self.tz)
        out = []
        for family_id in self.store.family_ids():
            chats = [p["chat_id"] for p in self.store.parents_of(family_id) if p["step"] == "ready"]
            if not chats:
                continue
            f = self.family(family_id)
            with f.lock:
                for text in self.due(f, now):
                    if patterns.no_advice(text):
                        out += [(chat, text) for chat in chats]
        return out

    def due(self, f, now):
        texts = []
        if f.fact("_reminders", "on") != "off":
            nxt = self.next_feed(f, now)
            if nxt["at"] is not None:
                lead = datetime.timedelta(minutes=self.s["reminder_lead_min"])
                recent = now - self.last_feed_start(f) <= datetime.timedelta(hours=self.s["reminder_max_gap_h"])
                in_window = nxt["at"] - lead <= now <= nxt["at"] + datetime.timedelta(minutes=30)
                if recent and in_window and f.fact("_reminded_for") != nxt["last"]:
                    f.memory.remember("_reminded_for", nxt["last"])
                    texts.append(nxt["text"])
        day = now.date().isoformat()
        if now.hour >= self.s["summary_hour"] and f.fact("_summary_day") != day:
            text = self.summary_text(f, now)
            if not text.startswith("Nothing logged"):
                f.memory.remember("_summary_day", day)
                texts.append(text)
        return texts

    def last_feed_start(self, f):
        rows = patterns.feeds(f.log.rhythm_rows())
        return patterns.when(rows[-1]) if rows else datetime.datetime.min.replace(tzinfo=self.tz)

    def close(self):
        with self.lock:
            for f in self.families.values():
                f.close()
            self.families.clear()
        self.store.close()
