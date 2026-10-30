"""Proactive pushes to the right parent: everything the agent starts on its own reaches the person it is for.

The routines publish "notify" events (night feed, house brain, day engine, reminders). This plug-in sends each one over
Telegram to the people it is for, in their own chat, with rota labels replaced by names ("Parent A" becomes "Gonza"):

| The notify event | Goes to |
|---|---|
| has a person (a reminder or a follow-up someone asked for) | that person |
| has a parent or a to that names one parent (the night feed push, a parent's line in tonight's plan) | that parent |
| is a shared routine: morning brief, supplies, meals, tonight's plan, a re-plan, the morning explanation | both |
| waits for a yes ("Reply yes to start it") | one parent: the one on duty at night, else settings "asks_to" |
| anything else at night (22:00 to 06:00) | the parent on duty, from the night rota (night_feed.py) |
| anything else | both |

An event with quiet true stays in the event log only. A yes to a pushed question is bound to the people it was sent to
(Agent.bind_ask), so the other parent's yes runs nothing. Every delivery is a "pushed" event with who got it and why,
and each message is a "reply" event with proactive true and the person, so the log shows who was told what.

A scheduled push (ONCE_A_DAY: tonight's plan, the parents' meals, the morning message and its parts) reaches each
parent at most once a day, across restarts (morning.Sent, data/scheduled-pushes.json). A repeat is a "pushed" event
with nobody in to and the reason, never a message.

With "morning": true the morning brief and the night explanation are not sent on their own: they wait (up to hold_s
seconds for the other one) and go out with the prep lines as one short message per parent with only what is theirs
(channels/morning.py). The prep plug-in hands its nudge to the same message.

Add "parenting_agent.channels.push:FamilyPush" after the Telegram channel and the night feed. Settings under
"family_push": {"channel": "telegram", "asks_to": "gonza", "night": ["22:00", "06:00"], "morning": true}. Do not
load it with the router (router.py), which delivers notify events itself.
"""
import datetime
import threading
from pathlib import Path

from ..agent.plugins import Plugin
from ..rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from ..agent.people import People
from . import morning as morning_mod

SHARED = {"morning_brief", "supplies", "parents_meals", "tonight", "replan", "morning_explain"}
ONCE_A_DAY = {"morning_brief", "morning_explain", "morning", "tonight", "parents_meals"}
MORNING_PARTS = {"morning_brief": "day-engine", "morning_explain": "house-brain"}
DEFAULTS = {"channel": "telegram", "asks_to": None, "night": ["22:00", "06:00"], "morning": False, "hold_s": 300}


def find_plugin(agent, name):
    return next((p for p in getattr(agent, "plugins", []) if getattr(p, "name", "") == name), None)


def is_night(local, night):
    start, end = (datetime.time.fromisoformat(t) for t in night)
    t = local.time()
    return t >= start or t < end if start > end else start <= t < end


def recipients(event, people, on_duty=None, night=False, asks_to=None):
    """(people keys, reason) for one notify event. Pure, so the routing table is tested without a channel."""
    keys = people.keys()
    if not keys:
        return [], "no people in the config"
    person = people.person(event.get("person"))
    if person:
        return [person], "asked for it"
    for field in ("parent", "to"):
        who = event.get(field)
        if who and who != "both" and people.person(who):
            return [people.person(who)], f"for {people.display(who)}"
    if event.get("routine") in SHARED:
        return keys, "shared"
    duty = people.person(on_duty) if night and on_duty else None
    if event.get("ask"):
        if duty:
            return [duty], "a question for one yes, the parent on duty tonight"
        return [people.person(asks_to) or keys[0]], "a question for one yes"
    if duty:
        return [duty], "on duty tonight"
    return keys, "shared"


class FamilyPush(Plugin):
    name = "family-push"
    kind = "channel"

    def __init__(self, agent, config, clock=None):
        super().__init__(agent, config)
        self.s = {**DEFAULTS, **(config.get("family_push") or {})}
        rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self.people = getattr(agent, "people", None) or People(config.get("people"))
        self.sent = morning_mod.Sent(Path(config.get("data_dir", "data")) / "scheduled-pushes.json")
        self.parts, self.timer = {}, None
        self.lock = threading.RLock()
        agent.bus.subscribe(self.on_notify, ["notify"])

    def chats(self):
        """{person: chat id} from the channel plug-in's people, the first chat of each person."""
        channel = find_plugin(self.agent, self.s["channel"])
        people = getattr(channel, "people", {}) or {}
        return {person: sorted(ids)[0] for person, ids in people.items() if ids}

    def on_duty(self, now):
        rota = getattr(self.agent, "rota", None)
        if rota is None:
            return None
        try:
            return rota.on_duty(now)
        except Exception as error:  # a bad log read leaves the push to both parents, never to nobody
            self.agent.bus.publish("push_error", error=f"night rota: {str(error)[:180]}")
            return None

    def on_notify(self, event):
        if event.get("quiet") or event.get("channel") not in (None, self.s["channel"]):
            return None
        if self.merging() and event.get("routine") in MORNING_PARTS:
            return self.morning_part(event)
        return self.deliver(event)

    def day(self, now):
        """The day a scheduled push belongs to: a night that runs past midnight is still the evening's day."""
        return (now.astimezone(self.tz) - datetime.timedelta(hours=6)).date().isoformat()

    def deliver(self, event, texts=None):
        """texts, when given, is {person: text}: a message written for each parent (the morning message)."""
        now = self.clock()
        night = is_night(now.astimezone(self.tz), self.s["night"])
        to, reason = recipients(event, self.people, self.on_duty(now) if night else None, night, self.s["asks_to"])
        if texts is not None:
            to, reason = list(texts), "one morning message each"
        chats = self.chats()
        if event.get("chat_id") and not self.people.person(event.get("person")):
            # A follow-up asked from a family chat that is tied to no person goes back to that chat only.
            to, reason, chats = ["chat"], "asked for it", {"chat": str(event["chat_id"])}
        routine, day, repeats = event.get("routine"), self.day(now), []
        if routine in ONCE_A_DAY:
            with self.lock:
                repeats = [p for p in to if self.sent.sent(routine, p, day)]
                to = [p for p in to if p not in repeats]
                self.sent.mark(routine, to, day)
            if repeats and not to:
                return self.agent.bus.publish("pushed", source=event.get("source"), routine=routine, to=[], missing=[],
                                              repeats=repeats, reason=f"already sent today ({day}), a restart repeat")
        sent, missing = [], []
        text = self.people.named(str(event.get("text") or ""))
        for person in to:
            if texts is not None:
                text = texts[person]
            chat = chats.get(person)
            if chat is None:
                missing.append(person)
                continue
            self.agent.bus.publish("reply", channel=self.s["channel"], chat_id=chat, text=text,
                                   person=None if person == "chat" else person, proactive=True, source=event.get("source"))
            sent.append(person)
        if event.get("ask") and sent and hasattr(self.agent, "bind_ask"):
            self.agent.bind_ask(sent)
        return self.agent.bus.publish("pushed", source=event.get("source"), routine=event.get("routine"), to=sent,
                                      missing=missing, reason=reason, **({"repeats": repeats} if repeats else {}))

    # The one morning message

    def merging(self):
        return self.s["morning"] is True and bool(self.people)

    def morning_part(self, event):
        """Holds the brief or the explanation until the other one is in (or hold_s passes), then sends one message."""
        with self.lock:
            if self.morning_sent():
                return self.agent.bus.publish("pushed", source=event.get("source"), routine=event.get("routine"), to=[],
                                              missing=[], reason="already in today's morning message, a restart repeat")
            self.parts[event["routine"]] = event
            expected = {r for r, plugin in MORNING_PARTS.items() if find_plugin(self.agent, plugin) is not None}
            if expected <= set(self.parts):
                return self.morning_flush()
            if self.timer is None:
                self.timer = threading.Timer(self.s["hold_s"], self.morning_flush)
                self.timer.daemon = True
                self.timer.start()
            return self.agent.bus.publish("pushed", source=event.get("source"), routine=event.get("routine"), to=[],
                                          missing=[], reason="held for the morning message")

    def morning_sent(self):
        day = self.day(self.clock())
        return all(self.sent.sent("morning", p, day) for p in self.people.keys())

    def morning_from_prep(self):
        """The prep nudge is due: it goes in the morning message, or is already in today's."""
        with self.lock:
            prep = find_plugin(self.agent, "prep")
            if self.morning_sent():
                if prep is not None:
                    prep.record_nudge("in the morning message")
                return None
            return self.morning_flush()

    def morning_lang(self, prep):
        try:
            return prep.nudge_lang() if prep is not None else "en"
        except Exception:  # noqa: BLE001 a bad memory read keeps the message in English, never unsent
            return "en"

    def morning_flush(self):
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            parts, self.parts = self.parts, {}
            if self.morning_sent():
                return None
            now = self.clock()
            prep = find_plugin(self.agent, "prep")
            lang = self.morning_lang(prep)
            lines = []
            if prep is not None and prep.cfg["nudge"]["enabled"] and prep.last_nudge() != now.date().isoformat():
                try:
                    lines = prep.nudge_lines(lang)
                    prep.record_nudge("in the morning message")
                except Exception as error:  # noqa: BLE001 the rest of the message still goes out
                    self.agent.bus.publish("push_error", error=f"prep lines: {str(error)[:180]}")
            brief = (parts.get("morning_brief") or {}).get("facts")
            explain = parts.get("morning_explain")
            rota = getattr(self.agent, "rota", None)
            tonight = last_night = None
            if rota is not None:
                try:
                    tonight = rota.rota_only(now)
                    yesterday = now.astimezone(self.tz).replace(hour=22, minute=0, second=0, microsecond=0) \
                        - datetime.timedelta(days=1)
                    last_night = ((explain or {}).get("facts") or {}).get("on_duty") or rota.rota_only(yesterday)
                except Exception as error:  # noqa: BLE001 no duty lines rather than no message
                    self.agent.bus.publish("push_error", error=f"night rota: {str(error)[:180]}")
            texts = {}
            for person in self.people.keys():
                label = self.people.label(person)
                texts[person] = self.people.named(morning_mod.compose(
                    lang, self.people.name(person), label, brief, explain, lines,
                    self.people.rota_label(tonight) if tonight else None,
                    self.people.rota_label(last_night) if last_night else None))
            self.agent.bus.publish("morning_message", parts=sorted(parts), facts=brief, explain=(explain or {}).get("text"),
                                   explain_facts=(explain or {}).get("facts"), prep=lines, tonight=tonight,
                                   last_night=last_night, texts=texts, lang=lang)
            return self.deliver({"routine": "morning", "source": "family-push"}, texts)
