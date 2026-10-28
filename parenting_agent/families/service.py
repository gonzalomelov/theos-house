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
from . import texts
from .texts import t
from .store import Store, visitor_id

ALLOWED = ["log_baby_event", "read_baby_log", "baby_summary", "remember", "current_time"]
CHANNEL = "telegram"
MAX_PARENTS = 4
DELETE_WINDOW_S = 600
SEEN_MESSAGES = 1000
YES = {"yes", "y", "si", "sí", "s", "ok", "dale", "sure", "yes please", "claro", "obvio", "sí, dale", "si dale"}
START = re.compile(r"^/start(?:@\w+)?(?:\s+(\S+))?\s*$", re.I)
COMMAND = re.compile(r"^/(\w+)(?:@\w+)?\s*(.*)$", re.S)
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y")

FAMILY_NOTE = """
This is one family's private log on Telegram. The baby is {name}, born {born}. Call the baby by name.
There are no house tools here and you cannot act in the house, never offer to. Never ask for or repeat personal details
such as addresses or phone numbers.
"""
LANGUAGE_NOTE = {
    "en": "Always reply in English, even when the parent writes in another language.\n",
    "es": ("Always reply in Rioplatense Spanish with voseo (vos escribís, mandá, querés), warm, short and in plain words, "
           "even when the parent writes in English. Log entries keep their English field values.\n"),
}

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
        """The core prompt with the family's own facts only, and the family's language. Keys starting with _ are the
        service's bookkeeping."""
        facts = {k: v["value"] for k, v in self.memory.facts().items() if not k.startswith("_")}
        base = SYSTEM.format(today=datetime.date.today().isoformat(), facts=json.dumps(facts or "none yet", ensure_ascii=False))
        lang = self.memory.facts().get("_lang", {}).get("value") or "en"
        return (base + FAMILY_NOTE.format(name=facts.get("baby_name", "the baby"), born=facts.get("birth_date", "recently"))
                + LANGUAGE_NOTE.get(lang, LANGUAGE_NOTE["en"]))

    def saved_before_fail(self, entries):
        lang = self.memory.facts().get("_lang", {}).get("value") or "en"
        words = []
        for entry in entries:
            kind = str(entry.get("kind") or "note").upper()
            ml = (entry.get("details") or {}).get("amount_ml")
            if kind == "FEEDING" and isinstance(ml, (int, float)) and ml > 0:
                words.append(t(lang, "ENTRY_FEEDING_ML", ml=f"{float(ml):g}"))
            else:
                words.append(t(lang, f"ENTRY_{kind}") if f"ENTRY_{kind}" in texts.TEXTS.get(lang, texts.EN) else t(lang, "ENTRY_NOTE"))
        return t(lang, "SAVED_BEFORE_FAIL", entries=", ".join(words))


class FamilyBrain:
    """The real brain behind the caps: once the family's or the whole service's spend for today is at its cap,
    the free rule-based brain takes over so logging and simple questions keep working, in the family's language."""

    def __init__(self, service, family_id, lang=lambda: "en", fallback_tokens=(4000, 400)):
        self.service, self.family_id, self.lang, self.fallback = service, family_id, lang, fallback_tokens
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
            if self.lang() == "es":
                return self.rules_in_spanish(system, transcript, tools)
            return self.rules.step(system, transcript, tools)
        self.name, self.destination = self.real.name, self.real.destination
        reply = self.real.step(system, transcript, tools)
        self.service.store.add_spend(self.family_id, self.cost(reply.usage))
        return reply

    def rules_in_spanish(self, system, transcript, tools):
        """The rule-based brain reads English notes and writes English replies. Here a Spanish note is read through
        its English words and every reply comes back in Spanish, so no English text reaches a Spanish family."""
        last = transcript[-1]
        if last["role"] == "user":
            head, sep, note = last["text"].rpartition("] ")
            transcript = transcript[:-1] + [{**last, "text": head + sep + texts.note_to_english(note)}]
        reply = self.rules.step(system, transcript, tools)
        if reply.tool_calls or last["role"] != "tool":
            if not reply.tool_calls:
                reply.text = t("es", "NOTED")
            return reply
        result = last["result"]
        if isinstance(result, str) and "failed" in result:
            reply.text = t("es", "NOT_DONE")
        elif last["name"] == "baby_summary":
            reply.text = day_summary("es", "", result) or t("es", "NOTHING_YET")
        elif last["name"] == "read_baby_log":
            feeds = [e for e in result if e["kind"] == "feeding"]
            reply.text = (t("es", "LOGGED_FEEDS", feeds=", ".join(t("es", "FEED_AT", ml=e["details"].get("amount_ml", "?"), at=e["ts"][11:16])
                                                                   for e in feeds)) if feeds else t("es", "NOTHING_YET"))
        else:
            reply.text = t("es", "LOGGED")
        return reply


def day_summary(lang, name, s):
    """Today's feeds, diapers, sleep and baths from a baby_summary result, or "" when nothing was logged."""
    feeds, diapers, sleep, baths = s["feedings"], s["diapers"], s["sleep"], s["baths"]
    if not (feeds["count"] or diapers["count"] or sleep["count"] or baths["count"]):
        return ""
    parts = [t(lang, "TODAY", name=name)] if name else []
    if feeds["count"]:
        total = t(lang, "FEEDS_TOTAL", ml=feeds["total_ml"]) if feeds["total_ml"] else ""
        parts.append(t(lang, "FEEDS", feeds=texts.plural(lang, feeds["count"], "FEED"), total=total, last=feeds["last_at"]))
    if diapers["count"]:
        parts.append(t(lang, "DIAPERS", diapers=texts.plural(lang, diapers["count"], "DIAPER"), wet=diapers["wet"], dirty=diapers["dirty"]))
    if sleep["count"]:
        parts.append(t(lang, "SLEEP", time=_hm(sleep["total_min"]), sleeps=texts.plural(lang, sleep["count"], "SLEEP_ONE")))
    if baths["count"]:
        parts.append(t(lang, "BATH", last=baths["last_at"]))
    return " ".join(parts)


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
        self.agent = FamilyAgent(self.bus, self.memory, self.log, tools, FamilyBrain(service, family_id, lambda: self.lang),
                                 max_steps=service.s["max_steps"], history=service.s["history"])
        self.replies = collections.deque()
        self.bus.subscribe(self.replies.append, ["reply"])

    def fact(self, key, default=""):
        return self.memory.facts().get(key, {}).get("value") or default

    @property
    def lang(self):
        lang = self.fact("_lang", "en")
        return lang if lang in texts.LANGS else "en"

    def t(self, key, **values):
        return t(self.lang, key, **values)

    @property
    def name(self):
        return self.fact("baby_name", "tu bebé" if self.lang == "es" else "your baby")

    def talk(self, text):
        self.replies.clear()
        if texts.is_medical(text):
            self.memory.add_message(CHANNEL, "user", text)
            self.agent.say(CHANNEL, self.t("REFUSAL"))
        else:
            self.agent.handle({"kind": "message", "channel": CHANNEL, "text": text})
        return " ".join(e["text"] for e in self.replies) or self.t("OK")

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
        self.seen = collections.OrderedDict()

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

    def first_time(self, user_id, message_id):
        """False when this incoming message was already handled, for example Telegram delivering one update twice."""
        if message_id is None:
            return True
        key = (str(user_id), str(message_id))
        with self.lock:
            if key in self.seen:
                return False
            self.seen[key] = True
            while len(self.seen) > SEEN_MESSAGES:
                self.seen.popitem(last=False)
        return True

    def handle(self, user_id, chat_id, text, chat_type="private", language_code="", message_id=None):
        """language_code is the sender's Telegram app language. It picks the language for strangers and for a new
        family. A family that exists keeps its own language until a parent sends /idioma or /language. message_id is
        the Telegram update id: the same id twice is handled once, so one message never logs twice."""
        if not self.first_time(user_id, message_id):
            return []
        text = (text or "").strip()
        app_lang = texts.lang_for(language_code)
        if chat_type and chat_type != "private":
            return [(chat_id, t(app_lang, "GROUP"))]
        if not user_id or not text:
            return []
        vid = visitor_id(user_id)
        parent = self.store.parent(vid)
        if parent is None:
            return [(chat_id, self.gate(vid, str(user_id), chat_id, text, app_lang))]
        family_id = parent["family_id"]
        f = self.family(family_id)
        if len(text) > self.s["max_input_chars"]:
            return [(chat_id, f.t("TOO_LONG", n=self.s["max_input_chars"]))]
        if self.store.family_messages_today(family_id) >= self.s["max_messages_per_family_day"]:
            return [(chat_id, f.t("FAMILY_LIMIT"))]
        self.store.add_message(vid, family_id, parent["internal"])
        with f.lock:
            pending_delete = f.fact("_delete_asked")
            if pending_delete:
                f.memory.remember("_delete_asked", "")
                if text.strip(" .!¡").upper() == f.t("DELETE_WORD") and time.time() - float(pending_delete) <= DELETE_WINDOW_S:
                    return self.delete(family_id, chat_id)
                return [(chat_id, f.t("DELETE_CANCELLED"))]
            command = COMMAND.match(text)
            if command:
                return [(chat_id, self.command(f, parent, command.group(1).lower(), command.group(2).strip()))]
            if parent["step"] != "ready":
                return [(chat_id, self.onboard(f, parent, text))]
            try:
                return [(chat_id, f.talk(text))]
            except brain_mod.BrainError as error:
                # Kept in the conversation, so the next turn sees this message was answered and does not log it then.
                f.bus.publish("agent_error", error=str(error)[:300])
                f.memory.add_message(CHANNEL, "assistant", f.t("THINK_FAIL"))
                return [(chat_id, f.t("THINK_FAIL"))]

    def gate(self, vid, user_id, chat_id, text, lang="en"):
        """Strangers: only a valid invite code gets in. Nothing about a stranger is stored on disk."""
        start = START.match(text)
        if not start or not start.group(1):
            return t(lang, "NO_CODE")
        day = self.store.today()
        if self.bad_codes[(vid, day)] >= self.s["max_bad_codes_per_day"]:
            return t(lang, "TOO_MANY")
        code = start.group(1)
        invite = self.store.invite(code)
        if invite is None:
            self.bad_codes[(vid, day)] += 1
            return t(lang, "BAD_CODE")
        family_id = invite["family_id"]
        if family_id is None and self.store.family_count() >= self.s["max_families"]:
            return t(lang, "FULL")
        if family_id is not None and len(self.store.parents_of(family_id)) >= MAX_PARENTS:
            return t(lang, "BAD_CODE")
        if not self.store.use_invite(code, vid):
            return t(lang, "BAD_CODE")
        internal = invite["internal"] or user_id in self.s["internal_user_ids"]
        if family_id is None:
            family_id = self.store.create_family()
            self.store.add_parent(vid, chat_id, family_id, "baby_name", internal)
            self.store.add_message(vid, family_id, internal)
            self.family(family_id).memory.remember("_lang", lang)
            return t(lang, "WELCOME") + t(lang, "ASK_NAME")
        self.store.add_parent(vid, chat_id, family_id, "ready", internal)
        self.store.add_message(vid, family_id, internal)
        f = self.family(family_id)
        return f.t("PARTNER_WELCOME", name=f.name) + f.t("READY", name=f.name)

    def onboard(self, f, parent, text):
        step, vid = parent["step"], parent["visitor_id"]
        if step == "baby_name":
            name = " ".join(text.split())[:40].strip(" .!")
            if not name:
                return f.t("ASK_NAME")
            f.memory.remember("baby_name", name)
            self.store.set_step(vid, "birth_date")
            return f.t("ASK_BORN", name=name)
        if step == "birth_date":
            born = parse_birth(text, self.now().date())
            if born is None:
                return f.t("BAD_BORN")
            f.memory.remember("birth_date", born.isoformat())
            self.store.set_step(vid, "partner")
            return f.t("ASK_PARTNER")
        self.store.set_step(vid, "ready")
        ready = f.t("READY", name=f.name)
        if text.lower().strip(" .!¡") in YES:
            return self.partner_invite(f, parent) + "\n\n" + ready
        return ready

    def partner_invite(self, f, parent):
        if len(self.store.parents_of(f.family_id)) >= MAX_PARENTS:
            return f.t("PARTNER_MAX", name=f.name, n=MAX_PARENTS)
        code = self.store.create_invite(f.family_id, self.s["invite_days"], internal=parent["internal"])
        return f.t("PARTNER_CODE", code=code, link=self.invite_link(code), days=self.s["invite_days"], name=f.name)

    def command(self, f, parent, typed, arg):
        """typed is the command as sent, in either language: /resumen and /summary are the same command."""
        name, ready = texts.COMMANDS.get(typed, typed), parent["step"] == "ready"
        if name == "start":
            return f.t("ALREADY") if ready else self.onboard_prompt(f, parent)
        if name == "privacy":
            return f.t("PRIVACY")
        if name == "deletemydata":
            f.memory.remember("_delete_asked", str(time.time()))
            return f.t("DELETE_ASK", name=f.name)
        if name == "language":
            # /idioma alone means Spanish, /language alone means English, or name one: /idioma en, /language es.
            wanted = texts.LANGUAGE_ARGS.get(arg.lower().split(" ")[0] if arg else "")
            f.memory.remember("_lang", wanted or ("es" if typed == "idioma" else "en"))
            note = f.t("LANG_SET")
            return note if ready else note + "\n\n" + self.onboard_prompt(f, parent)
        if not ready:
            return self.onboard_prompt(f, parent)
        if name == "summary":
            return self.summary_text(f)
        if name == "next":
            return self.next_feed(f)["text"]
        if name == "invite":
            return self.partner_invite(f, parent)
        if name == "reminders":
            off = arg.lower() in ("off", "apagar", "no")
            f.memory.remember("_reminders", "off" if off else "on")
            return f.t("REMINDERS_OFF") if off else f.t("REMINDERS_ON")
        return f.t("READY", name=f.name)

    def onboard_prompt(self, f, parent):
        step = parent["step"]
        if step == "baby_name":
            return f.t("ASK_NAME")
        if step == "birth_date":
            return f.t("ASK_BORN", name=f.name)
        return f.t("ASK_PARTNER")

    def delete(self, family_id, chat_id):
        f = self.family(family_id)
        done, other_done = f.t("DELETED"), f.t("DELETED_OTHER")
        others = [p["chat_id"] for p in self.store.parents_of(family_id) if p["chat_id"] != str(chat_id)]
        self.forget(family_id)
        babylog.wipe(self.s["data_dir"], family_id)
        self.store.delete_family(family_id)
        return [(chat_id, done)] + [(other, other_done) for other in others]

    # What the agent says first

    def next_feed(self, f, now=None):
        now = now or self.now()
        nxt = patterns.next_feed(f.log.rhythm_rows(), now)
        if not nxt:
            return {"text": f.t("NEED_TWO_FEEDS", name=f.name), "at": None}
        minutes = round((nxt["at"] - now).total_seconds() / 60)
        when = patterns.hhmm(nxt["at"].astimezone(self.tz))
        text = (f.t("NEXT_FEED", name=f.name, when=when, minutes=minutes, gap=_hm(nxt["gap_min"]))
                if minutes >= 0 else f.t("FEED_LATE", name=f.name, when=when, ago=_hm(-minutes)))
        return {"text": text, "at": nxt["at"], "last": nxt["computed_from"][-1]}

    def summary_text(self, f, now=None, quiet=False):
        """Today so far for the family. With quiet, "" when nothing was logged instead of saying so."""
        now = now or self.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        text = day_summary(f.lang, f.name, f.log.summary(midnight.isoformat(timespec="seconds")))
        if not text:
            return "" if quiet else f.t("NOTHING_TODAY", name=f.name)
        nxt = self.next_feed(f, now)
        return text + (" " + nxt["text"] if nxt["at"] is not None else "")

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
                    if patterns.no_advice(text) and texts.no_advice_es(text):
                        out += [(chat, text) for chat in chats]
        return out

    def due(self, f, now):
        texts_due = []
        if f.fact("_reminders", "on") != "off":
            nxt = self.next_feed(f, now)
            if nxt["at"] is not None:
                lead = datetime.timedelta(minutes=self.s["reminder_lead_min"])
                recent = now - self.last_feed_start(f) <= datetime.timedelta(hours=self.s["reminder_max_gap_h"])
                in_window = nxt["at"] - lead <= now <= nxt["at"] + datetime.timedelta(minutes=30)
                if recent and in_window and f.fact("_reminded_for") != nxt["last"]:
                    f.memory.remember("_reminded_for", nxt["last"])
                    texts_due.append(nxt["text"])
        day = now.date().isoformat()
        if now.hour >= self.s["summary_hour"] and f.fact("_summary_day") != day:
            text = self.summary_text(f, now, quiet=True)
            if text:
                f.memory.remember("_summary_day", day)
                texts_due.append(text)
        return texts_due

    def last_feed_start(self, f):
        rows = patterns.feeds(f.log.rhythm_rows())
        return patterns.when(rows[-1]) if rows else datetime.datetime.min.replace(tzinfo=self.tz)

    def close(self):
        with self.lock:
            for f in self.families.values():
                f.close()
            self.families.clear()
        self.store.close()
