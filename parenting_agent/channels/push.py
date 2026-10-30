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

Add "parenting_agent.channels.push:FamilyPush" after the Telegram channel and the night feed. Settings under
"family_push": {"channel": "telegram", "asks_to": "gonza", "night": ["22:00", "06:00"]}. Do not load it with the
router (router.py), which delivers notify events itself.
"""
import datetime

from ..agent.plugins import Plugin
from ..rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from ..agent.people import People

SHARED = {"morning_brief", "supplies", "parents_meals", "tonight", "replan", "morning_explain"}
DEFAULTS = {"channel": "telegram", "asks_to": None, "night": ["22:00", "06:00"]}


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
        return self.deliver(event)

    def deliver(self, event):
        now = self.clock()
        night = is_night(now.astimezone(self.tz), self.s["night"])
        to, reason = recipients(event, self.people, self.on_duty(now) if night else None, night, self.s["asks_to"])
        chats = self.chats()
        if event.get("chat_id") and not self.people.person(event.get("person")):
            # A follow-up asked from a family chat that is tied to no person goes back to that chat only.
            to, reason, chats = ["chat"], "asked for it", {"chat": str(event["chat_id"])}
        sent, missing = [], []
        text = self.people.named(str(event.get("text") or ""))
        for person in to:
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
                                      missing=missing, reason=reason)
