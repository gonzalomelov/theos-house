"""One path for every event, real or simulated: recorded, gated, given to Muse, and every step recorded and streamed.

Events run one at a time, so the home's one thread never has two runs. Tables: events and actions. What the agent does is
published as it happens, for the HTTP stream.
"""
import asyncio
import collections
import datetime
import json
import re
import time
import zoneinfo

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..agent import rules
from . import agent as agent_mod
from . import safety, tools as tools_mod
from .mock_home import MockHome
from .settings import HAND, Settings, part

TZ = zoneinfo.ZoneInfo("America/Montevideo")
RECURSION_LIMIT = 60  # each tool round takes 3 graph steps, so this is about 20 rounds in one event. 24 ended a run after 8 rounds (Nov 3)
RETRY_WAITS = (5, 30)
RECOVER_WITHIN = "15 minutes"
PRUNE_EVERY = 25
STALE_WAKE_MIN, END_LATE_MIN = 30, 60
HAND_HOLD_H = 2
ALARM_HOURS = 36  # long enough to reach the next morning check from any hour
OWN_MOVE_S = 60
# A wake to get something ready means nothing after its moment has passed, unlike a reminder.
PREPARES = re.compile(r"warm|bottle|feed|mamadera|calent|toma|dehumid|deshumid|humid", re.I)
ABOUT_THE_AIR = safety.ABOUT_THE_AIR
OPEN_ALARM = "open_alarm_"  # an alarm that reached the morning check and still has no answer: known, but no check says it again
ANSWERED = "alarm_answered"
ENDED = {"warmer_off_at": {"es": "El calentador de mamaderas se apagó solo a las {at}.", "en": "The bottle warmer turned itself off at {at}."},
         "vacuum_off_at": {"es": "La aspiradora terminó y volvió a su base a las {at}.", "en": "The vacuum finished and went back to its base at {at}."}}
GAP_TOLD = re.compile(r"\d+\s*(?:h|hs|hours?|horas?)\b|\bfeeds?\b|\btomas?\b|comi[oó]", re.I)
FOLLOW_UP = "alarm_follow_up"
FOLLOW_UP_MIN = 40
FOLLOW_UP_WRITER = re.compile(r"\d\d:\d\d (\S+) wrote")
REMINDER, UNANSWERED = tools_mod.REMINDER, "reminder_unanswered"
ESCALATE_MIN = 15
NEAR_SAME_MIN, CRY_TOLD_MIN, SAME_WAKE_MIN = 10, 10, 5
SAME_TOPIC_MIN = 45  # two wakes about the same thing this close are one wake
# Muse's words refused: the first try and 2 more, or less once a parent has waited this long. Then a plain line, and Muse stops.
MAX_REFUSED, STALL_S, MAX_REFUSALS_IN_EVENT = 3, 15, 6
# A slow Muse with nothing refused: past this the parent who wrote hears one holding line, and Muse carries on.
HOLD_S = 30
HOLDING = {"es": "Sigo con esto, ya te contesto.", "en": "Still on this, I'll answer you in a moment."}
READ_LINE = {"es": "Te leí. Ahora no tengo una buena respuesta para esto.", "en": "I read your message. I don't have a good answer for it right now."}
DONE_LINE = {"es": "Ya lo tengo.", "en": "Got that."}
ASK_HOW = {"es": "¿Cómo está Theo ahora?", "en": "How is Theo now?"}
CALL_FIRST = {"es": "Llamá a su pediatra, o al 911 si no puede esperar.", "en": "Please call his pediatrician, or 911 if it can't wait."}
TONIGHT_YOU = {"es": "Esta noche te toca a vos.", "en": "You're on tonight."}
TONIGHT_OTHER = {"es": "Esta noche le toca a {who}.", "en": "{who} is on tonight."}
ALARM_SAID = {"es": 'A las {at}: "{sign}". {ask}', "en": 'At {at}: "{sign}". {ask}'}
ALARM_FACT = re.compile(r'^At \w+ (\d\d:\d\d) \S+.*? (?:wrote|heard) "(.+)"')
RECIPE_HEADS = {"es": ("Ingredientes", "Pasos"), "en": ("Ingredients", "Steps")}
RECHECK_SOON_MIN = 10
RECHECK_ROOM_H = 1
CRY_LINE = {"es": "Theo está llorando.", "en": "Theo is crying."}
REMINDED = {"es": "Recordatorio que me pediste: {why}", "en": "The reminder you asked for: {why}"}
NO_COOKIDOO = {"es": "No puedo enviarla a Cookidoo desde acá. Eso se hace desde la app Muse de Meta.", "en": "I can't send it to Cookidoo from here. That is done from Meta's Muse app."}
PLAN_LINE = {"es": '{who} escribió: "{plan}"', "en": '{who} wrote: "{plan}"'}
HANDED_OVER = {"es": "{who} me dijo que esta noche te toca a vos. Si no es así, avisame.", "en": "{who} told me you're on tonight. If that's not right, tell me."}
RECHECK_ROOM = "check Theo's room temperature again: read it, and tell the parent on duty the reading if it is still far out of range. If it is, ask to be woken again in an hour"
SAID_AT = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
EARLIER_ASKED = re.compile(r"\b(?:before|earlier|ahead|antes|previo)\b|\bevery\b|\bcada\b", re.I)
CAMERA_OFF = {"es": "Un aviso nomás: la cámara del cambiador no vio ninguna mano sobre Theo. Una mano sobre él, por favor.", "en": "Just a nudge: the changing table camera saw no hand on Theo. A hand on him, please."}
WARMER = "Tapo P110 - Bottle Warmer"
WARMER_ENDS = {"es": "El calentador de mamaderas está prendido y se apaga solo a las {at}.", "en": "The bottle warmer is on, and it turns itself off at {at}."}
RECIPE_LATER = {"es": "Theo es recién nacido, así que esta queda para ustedes por ahora, o para más adelante. Su pediatra les va a decir cuándo.", "en": "Theo is a newborn, so this one is for you two for now, or for later on. His pediatrician can say when."}
FRIGHT_TOLD = {"es": '{who} escribió: "{words}". Andá a ver a Theo, y llamen a su pediatra.', "en": '{who} wrote: "{words}". Please go to Theo, and call his pediatrician.'}
# The warmer ends after 30 minutes, so a warmer started long before a feed is a warmer gone cold when he wakes.
PREWARM_MIN = 30
ALARM = re.compile(r"alarm|smoke|humo|fire|fuego|\bgas\b", re.I)
NO_BRAIN = {"es": {"cry": "Theo está llorando. Te aviso sin más detalle porque ahora no puedo pensar bien, se me cortó la conexión.",
                   "alarm": "Se escuchó: {kind}. Ahora no puedo pensar bien porque se me cortó la conexión, revisá por favor.",
                   "message": "Se me cortó la conexión y no pude hacer lo que me pediste. Probá de nuevo en un rato."},
            "en": {"cry": "Theo is crying. I can't say more, I've lost my connection.",
                   "alarm": "Heard: {kind}. I've lost my connection, please check.",
                   "message": "I lost my connection and couldn't do what you asked. Please try again in a while."}}
SCHEMA = ("""create table if not exists events (id bigserial primary key, home text not null, at timestamptz not null default now(),
    happened_at timestamptz not null, type text not null, source text not null, payload jsonb not null,
    status text not null default 'queued', outcome text)""",
          """create table if not exists actions (id bigserial primary key, event_id bigint references events(id), at timestamptz not null default now(),
    tool text not null, arguments jsonb not null, result text)""",
          """create table if not exists wakes (id bigserial primary key, home text not null, at timestamptz not null, why text not null,
    fired boolean not null default false)""")


def on_duty(moment):
    """Who the rota gives this night: nights alternate, and the hours before 7 belong to the night that began the evening before."""
    night = (moment - datetime.timedelta(hours=7)).date()
    return "gonza" if night.toordinal() % 2 == 0 else "ceci"


def is_night(moment):
    return moment.hour >= 22 or moment.hour < 7


def night_of(moment):
    return (moment - datetime.timedelta(hours=7)).date()


def who_is_on(moment, facts):
    """The rota, or the parent set_on_duty named for that night."""
    return facts.get(tools_mod.duty_key(night_of(moment))) or on_duty(moment)


def duty_line(moment, facts, last_night_known=True):
    """The one record of who is on duty, as Muse reads it at the top of every event. Everything else asks who_is_on too."""
    day = datetime.timedelta(days=1)
    if is_night(moment):
        return (f"The night that belongs to this moment began on the evening of {night_of(moment)}. On duty that night: {who_is_on(moment, facts)}. "
                f"The next night ({night_of(moment) + day}): {who_is_on(moment + day, facts)}")
    last = f"last night {who_is_on(moment - day, facts)}, " if last_night_known else "last night isn't on record, so never say who was on, "
    return f"On duty: {last}tonight ({night_of(moment)}) {who_is_on(moment, facts)}"


def timed_lines(moment, facts):
    """What Muse started and how it stands now, from the clock, so it never has to guess."""
    lines = []
    for key, name, ended in (("warmer_off_at", "The bottle warmer", "so nothing is warm now"), ("vacuum_off_at", "The vacuum", "it is docked")):
        if key in facts:
            until = datetime.datetime.fromisoformat(facts[key])
            lines.append(f"{name} is on until {until:%H:%M}." if moment < until else f"{name} ended by itself at {until:%A %H:%M}, {ended}.")
    return lines


def feed_line(moment, feed):
    if not feed:
        return None
    day = {0: "today", 1: "yesterday"}.get((moment.date() - feed.date()).days, f"{feed:%A %Y-%m-%d}")
    return f"Last feed in the log: {day} at {feed:%H:%M}, {(moment - feed).total_seconds() / 3600:.1f} hours ago."


def a_said_alarm(key):
    return key.startswith("alarm_") and key != ANSWERED


def vital_alarm(facts):
    """An alarm about his breathing or his colour is still open, so the next check isn't routine."""
    return any(a_said_alarm(k) and safety.BLUE_OR_BREATH.search(str(v)) for k, v in facts.items())


def rota_note(event, moment, facts):
    """Who really covered last night, from the record, for a check after a night changed by hand. Muse says it this way."""
    last_night = night_of(moment) - datetime.timedelta(days=1)
    if event["type"] != "schedule" or tools_mod.duty_key(last_night) not in facts or vital_alarm(facts):
        return None
    last, usual = facts[tools_mod.duty_key(last_night)], on_duty(moment - datetime.timedelta(days=1))
    said = f"Last night {last} was on duty" + (", for that night only" if last != usual else "")
    if event["payload"].get("name") == "evening":  # the evening is about tonight: last night said again read as a ledger, and "changed to you" went to the wrong parent (Nov 4)
        said = "Tonight's plan"
    if tools_mod.duty_key(night_of(moment)) in facts:
        return f"{said}. Tonight {who_is_on(moment, facts)} is on, a parent already said so: don't ask again."
    return f"{said}. The rota alone gives tonight to {who_is_on(moment, facts)}: ask simply if the plan for tonight stays."


def today_note(event, moment, facts):
    """What was remembered for today, so a morning check can't skip an appointment."""
    if event["type"] != "schedule" or event["payload"].get("name") != "morning":
        return None
    names = [str(moment.date()), moment.strftime("%A").lower(), {"Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles", "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo"}[moment.strftime("%A")]]
    found = [f"{k}: {v}" for k, v in facts.items() if not k.startswith(("on_duty", "duty_note", "hand_", "feed_gap", "fever", "alarm_", OPEN_ALARM, "plan_")) and any(n in str(v).lower() for n in names)]
    return "Remembered for today, name it with its time: " + "; ".join(found) + "." if found else None


def alarm_note(event, facts):
    """What the gate or an emergency set off since the last check, so a check can't read as if the night was quiet."""
    if event["type"] != "schedule":
        return None
    found = [v for k, v in sorted(facts.items()) if a_said_alarm(k)]
    if not found:
        return None
    ask = " One of these was about his breathing or his colour, so the first thing you ask each parent is how Theo is now, not about tonight's plan." if vital_alarm(facts) else ""
    return "Since the last check, these happened, say them plainly in one line to each parent, with the time and the words in quotes, and no advice: " + " ".join(found) + ask


def plans_of(facts):
    return [(k, v) for k, v in sorted(facts.items()) if k.startswith("plan_")]


def plan_note(event, facts):
    """A plan a parent reported from a doctor reaches the morning report, in their words."""
    if event["type"] != "schedule" or event["payload"].get("name") != "morning" or not plans_of(facts):
        return None
    return "A parent reported this plan. Name it to each parent, in their words, with no advice: " + " ".join(v for _, v in plans_of(facts))


def describe(event, moment, facts, feed=None, lang="es", extra=(), last_night_known=True):
    """The event as Muse reads it. A parent's words pass through rules.parent_text so they can't pose as the system."""
    payload = event["payload"]
    when = moment.strftime("%A %Y-%m-%d %H:%M")
    night = is_night(moment)
    notes = [f"Write for people in {'English' if lang == 'en' else 'Rioplatense Spanish'}.", *timed_lines(moment, facts), feed_line(moment, feed), rota_note(event, moment, facts), today_note(event, moment, facts), alarm_note(event, facts), plan_note(event, facts), *extra]
    rota = duty_line(moment, facts, last_night_known)
    facts = {k: v for k, v in facts.items() if k not in ("warmer_off_at", "vacuum_off_at", "feed_gap_told", "language", ANSWERED) and not k.startswith(("hand_", "plan_", "on_duty_", OPEN_ALARM))}
    head = f"[{when}, {'night' if night else 'day'}. {rota}.]\n" + " ".join(n for n in notes if n)
    remembered = "\n".join(f"- {k}: {v}" for k, v in facts.items()) or "- nothing yet"
    if event["type"] == "message":
        body = f"{payload.get('from', 'A parent')} wrote to you on {payload.get('channel', 'the phone')}: {rules.parent_text(payload.get('text', ''))}"
    elif event["type"] == "state_changed":
        body = f"Home sensor: {payload.get('entity_id')} changed to {payload.get('state')}."
    elif event["type"] == "sound":
        body = f"Sound heard in the {payload.get('room', 'house')}: {payload.get('kind')}."
    elif event["type"] == "wake":
        late = f" This was due at {payload['due']}, so it is late and may no longer apply." if payload.get("due") else ""
        why = str(payload.get("why"))
        if why.startswith(f"{REMINDER}:"):
            parent, what = why[len(REMINDER) + 1:].split(":", 1)
            body = f"{parent.capitalize()} asked you for this reminder: {what.strip()}.{late} Send it to {parent} now with notify, saying what it is. Whatever else is going on, it isn't replaced by anything else."
        elif why.startswith(f"{UNANSWERED}:"):
            parent, what = why[len(UNANSWERED) + 1:].split(":", 1)
            body = f"{parent.capitalize()} was asked a while ago and hasn't answered: {what.strip()}. It is day, so tell the other parent once, in one short line, that {parent} hasn't answered. Don't message {parent} again."
        else:
            body = f"You asked to be woken now, to: {why}.{late} Nobody else knows about this. Look at how things are now and decide."
    elif event["type"] == "schedule":
        body = f"Scheduled check: {payload.get('name')}. Nobody asked for anything. Decide if anything is worth doing now."
    elif event["type"] == "camera":
        body = f"{payload.get('model', 'A camera model')} at {payload.get('camera')}: {payload.get('saw')}."
        if payload.get("verdict") == "off":
            body += " No hand on the baby at the changing table is the danger this camera is there for. Tell the parent on duty now, in one short line, like a friend's nudge: what the camera saw, and a hand on him, please. No blame, and never as if you were watching them. Say the same on the kitchen Echo."
    else:
        body = f"Event {event['type']}: {json.dumps(payload, ensure_ascii=False)}"
    return f"{head}\nWhat you remember:\n{remembered}\n\n{body}"


def unanswered(event, calls):
    """A parent wrote on a phone and no message reached them. The glasses are left out: their yes and no belong to the coach."""
    payload = event["payload"]
    if event["type"] != "message" or payload.get("from") not in tools_mod.PARENTS or payload.get("channel") == "the glasses":
        return False
    return not any(tool == "start_car_seat_coach" or (tool == "notify" and arguments.get("parent") == payload["from"] and (result or "").startswith("Sent"))
                   for tool, arguments, result in calls)


def a_cry(event):
    return event["type"] == "sound" and "cry" in str(event["payload"].get("kind", "")).lower()


def unheard_cry(event, calls):
    """A cry nobody was told about. A question about something else, sent instead, doesn't count as telling."""
    return a_cry(event) and not any(tool == "notify" and (result or "").startswith("Sent") and safety.CRY_SAID.search(str(arguments.get("text", ""))) for tool, arguments, result in calls)


def a_real_danger(event, heard):
    """What can wake the parent who isn't on duty: a parent's own words now, or an alarm in the house. Never a wake, a check or a reading,
    and never a feed nobody can drink. Muse's words aren't a new emergency."""
    if event["type"] == "sound":
        return bool(ALARM.search(str(event["payload"].get("kind", ""))))
    return event["type"] == "message" and not safety.IMPOSSIBLE_ML.search(heard) and safety.worth_waking(heard)


STARTS = {"Tapo P110 - Bottle Warmer": ("warmer_off_at", "It turns itself off", 30), "vacuum": ("vacuum_off_at", "It finishes and docks", 60)}


def sent_words(calls):
    return " ".join(str(arguments.get("text", "")) for tool, arguments, result in calls if tool == "notify" and (result or "").startswith("Sent"))


def sent_to(calls):
    return {arguments.get("parent") for tool, arguments, result in calls if tool == "notify" and (result or "").startswith("Sent")}


def told_out_loud(calls):
    """A danger isn't told with a message that makes no sound."""
    return any(tool == "notify" and not arguments.get("quiet") and (result or "").startswith("Sent") for tool, arguments, result in calls)


def warmer_started(calls):
    return any(tool == "HassTurnOn" and arguments.get("name") == WARMER and not tools_mod.FAILED.match(result or "") for tool, arguments, result in calls)


def previewed(calls):
    return any(tool == "preview_family_recipe" and not tools_mod.FAILED.match(result or "") for tool, _, result in calls)


def preview_of(calls):
    return next((arguments for tool, arguments, result in reversed(calls) if tool == "preview_family_recipe" and not tools_mod.FAILED.match(result or "")), None)


def recipe_shown(arguments, words):
    """The phone has the recipe when most of its ingredients are in what went out."""
    items = [re.findall(r"[^\W\d_]{4,}", str(item).lower()) for item in arguments.get("ingredients") or []]
    words = words.lower()
    return sum(any(w in words for w in item) for item in items) * 2 >= len(items)


def recipe_card(arguments, lang):
    """The recipe as a message, from what Muse gave the preview."""
    ingredients, steps = RECIPE_HEADS[lang]
    lines = [str(arguments.get("name", "")).strip(), "", f"{ingredients}:", *(f"- {item}" for item in arguments.get("ingredients") or []), "", f"{steps}:"]
    lines += [f"{i}. {step.get('text', step) if isinstance(step, dict) else step}" for i, step in enumerate(arguments.get("steps") or [], 1)]
    return "\n".join(lines).strip()


def started(calls):
    """What this event turned on, and whether anyone was told."""
    told = any(tool == "notify" and (result or "").startswith("Sent") for tool, _, result in calls)
    return not told and any((tool == "HassTurnOn" and arguments.get("name") in STARTS or tool == "HassVacuumStart") and not tools_mod.FAILED.match(result or "")
                            for tool, arguments, result in calls)


MEMORY_SAID = re.compile(r"\b(?:remember\w*|asked|request\w*|per|wish\w*|because of|as told)\b", re.I)


def memory_named(note, facts):
    """Which of Muse's own remembered facts its closing line says changed what it did. The home's own notes don't count."""
    words = re.sub(r"[\W_]+", " ", note or "").lower()
    own = [k for k in facts if not k.startswith(("alarm_", OPEN_ALARM, "on_duty_", "duty_note_", "plan_", "hand_", "fever_", "feed_gap")) and k not in ("language", "warmer_off_at", "vacuum_off_at", ANSWERED)]
    named = [k for k in own if re.sub(r"[\W_]+", " ", k).lower().strip() in words]
    if named or not MEMORY_SAID.search(words):
        return named
    said = set(words.split())
    return [k for k in own if any(len(w) >= 6 and w in said for w in re.sub(r"[\W_]+", " ", k).lower().split())]  # "as Ceci asked, the dehumidifier stays off" names the fact by its subject


class Core:
    def __init__(self, settings=None, model=None, channel=None, log=None):
        self.settings = settings or Settings()
        self.model = model
        self.given_channel, self.given_log = channel, log
        self.queue = asyncio.Queue()
        self.subscribers = set()
        self.recent = collections.deque(maxlen=500)
        self.seq = 0
        self.mock = None
        self.channel = None
        self.moment = None
        self.heard = ""
        self.sender = None
        self.feed = None
        self.warm_until = None
        self.current = None
        self.checked_today = {}
        self.running = {}
        self.own = {}
        self.readings = {}
        self.closed_signs = set()
        self.sent_lately = {}
        self.cry_told_at = None
        self.pinged = {}
        self.pinged_then = {}
        self.refusals = {}
        self.told_now = set()
        self.calls = []
        self.capped = False
        self.began = time.monotonic()

    def now(self):
        """The moment the agent is living: the current event's, which a simulated event sets."""
        return self.moment or datetime.datetime.now(TZ)

    async def __aenter__(self):
        s = self.settings
        self.pool = AsyncConnectionPool(s.db_url, min_size=1, max_size=s.pool_max, open=False,
                                        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0}, check=AsyncConnectionPool.check_connection)  # a connection PostgreSQL dropped is replaced, never handed out
        await self.pool.open()
        saver, self.store = AsyncPostgresSaver(self.pool), AsyncPostgresStore(self.pool)
        await saver.setup()
        await self.store.setup()
        async with self.pool.connection() as db:
            for statement in SCHEMA:
                await db.execute(statement)
        if part("home") != "real":
            self.mock = MockHome(s.mock_port).start()
        self.channel = self.given_channel or (tools_mod.RealChannel(s) if part("channel") == "real" else tools_mod.MockChannel())
        memory, self.log = self.given_log or tools_mod.baby_log(s, self.now)
        if self.mock:
            self.mock.clock = self.now
        self.tools = [*await tools_mod.home_tools(s, self.mock, lambda: self.current, self.moved, self.water_or_held),
                      *tools_mod.channel_tools(self.channel, s, self.log, lambda: self.heard, self.night_check, self.claims, self.note_said, self.repeats, self.hushed, self.must_be_heard, self.refused),
                      *tools_mod.log_tools(self.log, memory, lambda: self.heard), *tools_mod.memory_tools(self.store, s.home, lambda: self.heard), *tools_mod.duty_tool(self.store, s.home, self.duty_set),
                      *tools_mod.next_feed_tool(self.log, self.now), *tools_mod.coach_tool(), *tools_mod.recipe_tool(lambda: self.heard, lambda: self.settings.lang), *tools_mod.vacuum_tool(s, self.mock), *tools_mod.wake_tool(self)]
        self.saver = saver
        self.agent = agent_mod.build(self.model or agent_mod.muse(), self.tools, saver, self.store)
        self.config = {"configurable": {"thread_id": f"home-{s.home}"}, "recursion_limit": RECURSION_LIMIT}
        await self.recover()
        self.worker = asyncio.create_task(self.work())
        return self

    async def __aexit__(self, *exc):
        self.worker.cancel()
        if self.mock:
            self.mock.stop()
        await self.pool.close()

    async def forget(self):
        """Removes this home from PostgreSQL: its events, actions, thread and facts."""
        home = self.settings.home
        await self.saver.adelete_thread(self.config["configurable"]["thread_id"])
        for item in await self.store.asearch((*tools_mod.FACTS, home), limit=1000):
            await self.store.adelete(item.namespace, item.key)
        async with self.pool.connection() as db:
            await db.execute("delete from actions where event_id in (select id from events where home = %s)", (home,))
            await db.execute("delete from events where home = %s", (home,))
            await db.execute("delete from wakes where home = %s", (home,))

    def publish(self, kind, **fields):
        self.seq += 1
        item = {"seq": self.seq, "kind": kind, "at": time.time(), **fields}
        self.recent.append(item)
        for subscriber in self.subscribers:
            subscriber.put_nowait(item)
        return item

    def note_said(self, parent, asked, out):
        """What really went out, for the record and the trace, by what Muse asked: a turn can send two messages at once."""
        self.said_out[(parent, asked)] = out
        self.told_now.add(parent)
        self.sent_lately.setdefault(parent, []).append((self.now(), out))
        self.sent_lately[parent] = self.sent_lately[parent][-8:]
        if self.ping_topic:
            self.pinged.setdefault(parent, set()).add(self.ping_topic)

    def nagging(self, why):
        """This wake already told someone about this, nobody answered, and now it wants another one."""
        return bool(self.ping_topic) and self.ping_topic == (safety.topic_of(why) or "other") and any(self.ping_topic in topics for topics in self.pinged_then.values())

    def plain_line(self, parent):
        """What goes out when the checks refused Muse's words too many times, or None when nobody is owed a message. Only what the home knows for sure."""
        lang = "en" if self.settings.lang == "en" else "es"
        preview = preview_of(self.calls)
        if parent == self.sender:
            if self.frightened:
                return CALL_FIRST[lang]
            if preview:
                out, _ = safety.outbound(recipe_card(preview, lang), lang)
                if out:
                    return out
            return (READ_LINE if tools_mod.record_line(self.calls).startswith("Nothing done.") else DONE_LINE)[lang]
        if self.follow_up:
            return ASK_HOW[lang]
        if self.a_cry:
            return CRY_LINE[lang]
        if self.in_check:
            return None  # the check's own line goes out at its end, from code
        return None

    async def refused(self, parent, text, why, wording):
        """Every refusal goes through here. Muse gets 2 more tries at a message, and a parent never waits on it past STALL_S: then the home sends a plain line, and Muse stops.
        A refusal that isn't about the words, like a parent asleep, sends nothing."""
        self.refusals[parent] = self.refusals.get(parent, 0) + 1
        if self.refusals[parent] < MAX_REFUSED and not (wording and parent == self.sender and time.monotonic() - self.began > STALL_S):
            return why
        self.capped = True
        line = self.plain_line(parent) if wording and parent not in self.told_now and parent in tools_mod.PARENTS else None
        if not line:
            return f"{why} Enough tries on this: leave it, and end now."
        await asyncio.to_thread(self.channel.send, parent, line)
        self.note_said(parent, text, line)
        return f"Sent to {parent}. It wasn't your words: the home sent a plain line of its own, after they were refused. End now."

    def repeats(self, parent, text):
        """Why this message would be a repeat, or None. A parent writing gets their answer however often they ask. A cry already told isn't told again in the same minutes."""
        moment = self.now()
        if parent == self.sender:
            return None
        if self.ping_topic and self.ping_topic in self.pinged_then.get(parent, ()):
            other = next(p for p in tools_mod.PARENTS if p != parent)
            then = f"It is day, so it is enough to tell {other} once." if not is_night(moment) and self.ping_topic not in self.pinged_then.get(other, ()) else "Leave it for now."
            return f"Refused, nothing was sent: {parent} didn't answer the last time you wrote about this, so don't ask again. {then}"
        if self.a_cry and self.cry_told_at and abs(moment - self.cry_told_at) < datetime.timedelta(minutes=CRY_TOLD_MIN):
            return f"Refused, nothing was sent: the parent on duty was told Theo is crying at {self.cry_told_at:%H:%M}, and this is the same crying. Don't send another message about it."
        for at, before in self.sent_lately.get(parent, []):
            if abs(moment - at) < datetime.timedelta(minutes=NEAR_SAME_MIN) and safety.near_same(text, before):
                other = next(p for p in tools_mod.PARENTS if p != parent)
                then = f"If they haven't answered it is enough to tell {other} once." if not is_night(moment) else "It is night, so wait for them."
                return f"Refused, nothing was sent: you told {parent} nearly the same at {at:%H:%M}. {then}"
        return None

    def hushed(self):
        """At night only what someone must act on makes a sound. A device moving or a reading that isn't a danger still reaches the parent on duty, without one."""
        return self.routine and is_night(self.now())

    def must_be_heard(self):
        """A cry, a room far out of range and no hand on Theo make a sound, whatever else the message is about."""
        return self.a_cry or self.camera_off or self.room_reading is not None

    def too_early_for_warmer(self, moment):
        """Why the warmer can't go on by itself now: it ends after 30 minutes, and the next feed is further away than that."""
        try:
            _, estimate = tools_mod.feed_estimate(self.log, moment)
        except Exception:
            return None
        if not estimate or estimate["at"] - moment <= datetime.timedelta(minutes=PREWARM_MIN):
            return None
        at = estimate["at"].astimezone(TZ)
        return f"Refused, the warmer stayed off: the next feed is expected around {at:%H:%M}, and the warmer ends by itself after {PREWARM_MIN} minutes, so it would be cold by then. Ask to be woken about 15 minutes before that feed."

    def early_reminder(self, moment, why):
        """Why a wake can't be set this early: it names a later time, and nobody asked to hear before it. Getting a bottle ready ahead is another thing."""
        named = [moment.replace(hour=int(h), minute=int(m), second=0, microsecond=0) for h, m in SAID_AT.findall(why)]
        if PREPARES.search(why) or EARLIER_ASKED.search(f"{why} {self.heard}") or safety.APPOINTMENT.search(why) or not named or min(named) <= moment:
            return None
        return f"Refused: this reminder is for {min(named):%H:%M}, so its one wake is at {min(named):%H:%M}, not {moment:%H:%M}. Ask for that time."

    async def say_fixed(self, event, parent, line, quiet=False):
        """A line from code, when Muse left it unsaid. It goes on record and in the trace like any other message, so the trace and the phones agree."""
        arguments = {"parent": parent, "text": line, **({"quiet": True} if quiet else {})}
        await asyncio.to_thread(self.channel.send, parent, line, *([True] if quiet else []))
        await self.record(event["id"], "notify", arguments, f"Sent to {parent}.")
        self.publish("tool_result", event_id=event["id"], tool="notify", arguments=arguments, result=f"Sent to {parent}.")

    async def night_check(self, parent, emergency):
        """Why this message can't wake this parent, or None. At night only the parent on duty, whoever wrote to the agent, or an emergency."""
        moment = self.now()
        real = emergency and self.real_danger
        if real or not is_night(moment) or parent == self.sender or parent in (self.duty_told, self.alarm_writer, self.reminder_for):
            return None
        duty = who_is_on(moment, await tools_mod.facts(self.store, self.settings.home))
        if parent == duty:
            return None
        if emergency:
            return f"Refused, nothing was sent: it is the night and {duty} is on duty, so {parent} sleeps. emergency is only for a new danger a parent just wrote about, or an alarm in the house, and this is neither."
        return (f"Refused, nothing was sent: it is the night and {duty} is on duty, so {parent} sleeps. If the plan changed, call set_on_duty first. "
                "If this is a danger to someone's life or the house, send it with emergency true.")

    async def duty_set(self, day, parent):
        """Nobody gets a night on someone else's word without hearing it, even at 3: they are the one the next cry reaches, and they can say no.
        A parent taking a night themself is told to the other, or at night kept for the morning so the other can sleep."""
        moment = self.now()
        other = next(p for p in tools_mod.PARENTS if p != self.sender) if self.sender in tools_mod.PARENTS else None
        if not self.sender:
            return ""
        if parent == other or not other:  # not a parent's word at all: still only a claim
            self.duty_told = parent
            return f" {parent} doesn't know yet and the next cry reaches them. Tell {parent} now, in one line, that {self.sender} passed them this night, so they can say no."
        if is_night(moment):
            await self.store.aput((*tools_mod.FACTS, self.settings.home), f"duty_note_{day}",
                                  {"value": f"{self.sender} took the night of {day}: tell {other} in the morning check."})
            return ""
        self.duty_told = other
        return f" Tell {other} now, in one line, that {self.sender} changed this, so they can say if it's wrong."

    async def moved(self, short, arguments, result):
        """Nothing Muse starts runs forever: the end is on record, and Muse hears when it is."""
        if tools_mod.FAILED.match(result or ""):
            return ""
        name = "vacuum" if short == "HassVacuumStart" else arguments.get("name")
        namespace = (*tools_mod.FACTS, self.settings.home)
        self.own[name] = time.monotonic()
        if short == "HassTurnOn" and "Dehumidifier" in str(name):
            await self.add_wake(self.now() + datetime.timedelta(hours=1), "check the dehumidifier is working: read the humidity and compare with when it went on")
        if short in ("HassTurnOn", "HassVacuumStart") and name in STARTS:
            key, how, minutes = STARTS[name]
            until = self.now() + datetime.timedelta(minutes=minutes)
            await self.store.aput(namespace, key, {"value": until.isoformat()})
            if key == "warmer_off_at":
                self.warm_until = until
            await self.add_wake(until, f"device_end:{key}:{until.isoformat()}")
            return f" {how} at {until:%H:%M}. The parent on duty hears from you that it is on, the time it ends, and that it ends by itself."
        if short in ("HassTurnOff", "HassVacuumReturnToBase") and (name in STARTS or short == "HassVacuumReturnToBase"):
            key = STARTS[name][0] if name in STARTS else "vacuum_off_at"
            await self.store.adelete(namespace, key)
            if key == "warmer_off_at":
                self.warm_until = None
        return ""

    def by_hand(self, entity, state, moment=None):
        """A plug that changed with no call from the agent, and not because it ended by itself. A source asks with the clock on the wall,
        since self.moment is still the last event's."""
        name = HAND.get(entity)
        if not name or state not in ("on", "off") or time.monotonic() - self.own.get(name, -OWN_MOVE_S * 2) < OWN_MOVE_S:
            return False
        ended = "Warmer" in name and state == "off" and self.warm_until and (moment or self.now()) >= self.warm_until - datetime.timedelta(minutes=2)
        return not ended

    @staticmethod
    def hand_key(name):
        return "hand_" + re.sub(r"\W+", "_", name)[:50]

    async def note_hand(self, event):
        """Someone switched a plug: it is held for a while, and Muse hears it as a person's choice."""
        payload, moment = event["payload"], event["moment"]
        if not self.by_hand(payload.get("entity_id"), payload.get("state"), moment):
            return
        name = HAND[payload["entity_id"]]
        until = moment + datetime.timedelta(hours=HAND_HOLD_H)
        await self.store.aput((*tools_mod.FACTS, self.settings.home), self.hand_key(name),
                              {"value": f"A person switched {name} {payload['state']} by hand at {moment:%H:%M}, held until {until.isoformat()}"})
        ends = ""
        if name in STARTS and payload["state"] == "on":  # a plug a person started still ends by itself, and someone hears it
            key, _, minutes = STARTS[name]
            end = moment + datetime.timedelta(minutes=minutes)
            await self.store.aput((*tools_mod.FACTS, self.settings.home), key, {"value": end.isoformat()})
            if key == "warmer_off_at":
                self.warm_until = end
            await self.add_wake(end, f"device_end:{key}:{end.isoformat()}")
            ends = f" It turns itself off at {end:%H:%M}."
        elif name in STARTS:  # switched off by hand: there is no end left to announce
            await self.store.adelete((*tools_mod.FACTS, self.settings.home), STARTS[name][0])
        event["hand"] = name
        event["note"] = (f"A person switched {name} {payload['state']} by hand just now.{ends} It stays that way for {HAND_HOLD_H} hours unless a parent asks. "
                         "Tell the parent on duty in one short line, or ask them. At night, set quiet.")

    async def held_by_hand(self, short, arguments):
        """A plug a person just switched isn't switched back by Muse on its own. The vacuum cleans by itself only with nobody home."""
        why = tools_mod.night_refusal(short, arguments, self.sender)
        if why:
            return why
        if short == "HassVacuumStart" and self.sender not in tools_mod.PARENTS:
            try:
                empty = await asyncio.to_thread(tools_mod.nobody_home, self.settings)
            except Exception:
                empty = False
            if not empty:
                return "Refused, the vacuum stayed docked: someone may be home. It starts by itself only when nobody is home, or when a parent asks."
        name = arguments.get("name")
        if short not in tools_mod.NAMED or self.sender or not name:
            return None
        if short == "HassTurnOn" and name == WARMER and not self.a_cry:
            early = await asyncio.to_thread(self.too_early_for_warmer, self.now())
            if early:
                return early
        found = await self.store.aget((*tools_mod.FACTS, self.settings.home), self.hand_key(name))
        if not found:
            return None
        until = datetime.datetime.fromisoformat(found.value["value"].rsplit(" ", 1)[-1])
        if self.now() >= until:
            await self.store.adelete((*tools_mod.FACTS, self.settings.home), self.hand_key(name))
            return None
        return f"Refused: a person switched {name} by hand, so it stays until {until:%H:%M} unless a parent asks. Tell the parent on duty or ask them."

    async def water_or_held(self, short, arguments):
        """The list refuses water, and every other move goes through the hand's hold."""
        if short == "HassListAddItem" and safety.water_only(arguments.get("item")):
            return "Refused, nothing was added: water comes from the tap, so it stays off the shopping list. Add the other ingredients one at a time."
        return await self.held_by_hand(short, arguments)

    def gap_hours(self):
        return (self.now() - self.feed).total_seconds() / 3600 if self.feed else 0

    def quiet_start(self, event):
        """The first reading after a start is for the room. A restart must never read to the parents as a check-in, unless the room is dangerous."""
        payload = event["payload"]
        return event["type"] == "state_changed" and bool(payload.get("first_after_start")) and safety.unsafe_room(payload) is None

    def claims(self, text):
        """What a message can't say, from the clock: a warm bottle with the warmer off, or calm about a long gap between feeds."""
        if self.after_start:
            return "Refused, nothing was sent: the agent just restarted and this is only its first reading. Handle the room and message nobody."
        if self.in_check and any(sign in text.lower() for sign in self.closed_signs):
            return "Refused, nothing was sent: you already reported that alarm in an earlier check, so it is closed. Leave it out, or ask once how Theo is now."
        if safety.WAITS_FOR_YES.search(text):
            return "Refused, nothing was sent: nothing waits for a yes here. A night passed is set at once, and the other parent can say no. Say that."
        if safety.SAID_DUTY.search(text) and not self.last_night_known:
            return "Refused, nothing was sent: there is no record of who was on last night, so don't say. Say only who is on tonight."
        if safety.GLITCH.search(text) and self.room_reading is not None:
            return f"Refused, nothing was sent: you don't know it is the sensor. The room reads {self.room_reading:g} degrees until another reading says otherwise. Say the reading, and that someone should go and check the room."
        if safety.NAMES_CHECK.search(text):
            return "Refused, nothing was sent: nobody needs to hear which check this is. Just say what matters, like a friend would."
        if safety.SCOREKEEP.search(text):
            return "Refused, nothing was sent: nobody owes anybody a night, and this reads like scorekeeping. Ask simply if the plan for tonight stays the same."
        if self.frightened and safety.MILLILITERS.search(text):
            return "Refused, nothing was sent: this parent is scared about how Theo is now, so no amounts. Say who to call first, in one or two short lines."
        if self.frightened and not safety.DOCTOR_STEP.search(text):
            return "Refused, nothing was sent: this parent is scared about how Theo is now. The first words are who to call: his pediatrician, or 911 if it can't wait. Don't give any advice beyond that."
        if safety.LOG_LIKE.search(text) and not safety.ASKS_NUMBERS.search(self.heard):
            return "Refused, nothing was sent: that reads like a log. Nobody asked for totals or counts, so write it like a friend would: what happened and when, in plain words."
        if self.camera_off and safety.WATCHING.search(text):
            return "Refused, nothing was sent: this reads as if someone was watching and blaming them. Say what the camera saw, lightly, and ask for a hand on him."
        if safety.SAME_PLAN.search(text) and self.vital_check:
            return "Refused, nothing was sent: there was an alarm about his breathing or his colour. Ask how Theo is now, and leave tonight's plan for later."
        if self.about_recipe and safety.says_suits(text):
            return "Refused, nothing was sent: don't call a recipe good for Theo or a baby. Say this one is for them for now, or for later on, and that his pediatrician can say when."
        if safety.unasked_tip(text, self.heard):
            return "Refused, nothing was sent: nobody asked how to do that. Answer in one short line that you have it, with no tip."
        if safety.DIDNT_CATCH.search(text):
            return f'Refused, nothing was sent: you have what they wrote: "{rules.parent_text(self.heard)[:200]}". Answer that.' if self.heard else "Refused, nothing was sent: there is nothing to ask them to repeat. Say what you know."
        if safety.SENT_THERE.search(text) and not safety.CANT_SEND.search(text):
            return "Refused, nothing was sent: this home can't send anything to Cookidoo or the Thermomix. Say plainly that you can't send it from here."
        wrong_clock = safety.DAY_WORDS.search(text) if is_night(self.now()) else safety.NIGHT_WORDS.search(text)
        if wrong_clock:
            return f"Refused, nothing was sent: it is {self.now():%H:%M}, so \"{wrong_clock.group(0)}\" is wrong. Leave it out."
        if safety.CANT_SEE.search(text):
            return "Refused, nothing was sent: you can't see Theo, so you can't check on him. Say who should go and look."
        if safety.CANT_KEEP.search(text):
            return "Refused, nothing was sent: that isn't yours to promise. Checks still go out, and at night only the parent on duty is woken. Say what will happen."
        if safety.WRONG_NUMBER.search(text):
            return "Refused, nothing was sent: the home is in Uruguay and the emergency number is 911."
        jargon = safety.JARGON.search(text)
        if jargon:
            return f'Refused, nothing was sent: "{jargon.group(0)}" isn\'t how a friend writes. Say it in plain words.'
        if safety.READY_AT.search(text):
            return "Refused, nothing was sent: the time you have is when the warmer switches off, not when a bottle is ready. Say it is warming, without a ready time."
        if safety.PROMISE.search(text) and not self.reminder_set:
            return "Refused, nothing was sent: you have no reminder set, so don't promise one. Call wake_me_at first, or leave the promise out."
        if safety.WARM_CLAIM.search(text) and not (self.warm_until and self.now() < self.warm_until):
            return "Refused, nothing was sent: the bottle warmer is off, so no bottle is warm. Say it isn't, or turn it on."
        if self.gap_hours() >= safety.FEED_GAP_H and safety.REASSURE.search(text):
            return f"Refused, nothing was sent: the log shows no feed for {self.gap_hours():.0f} hours, so don't reassure. Say the fact, and ask if feeds went unlogged."
        return None

    def last_feed(self, moment):
        """The newest feed in the log that isn't after this moment. A log that can't be read tells nothing."""
        try:
            entries = self.log.entries("feeding", None, 50)
        except Exception:
            return None
        times = []
        for entry in entries:
            at = datetime.datetime.fromisoformat(entry["ts"])
            times.append(at if at.tzinfo else at.replace(tzinfo=TZ))
        times = [t for t in times if t <= moment]
        return max(times) if times else None

    async def tidy_facts(self, moment):
        """A duty change holds for its night, so old ones and their notes go. Returns what is left."""
        facts = await tools_mod.facts(self.store, self.settings.home)
        for key in list(facts):
            found = re.match(r"(?:on_duty|duty_note)_(\d{4}-\d{2}-\d{2})$", key)
            if found and datetime.date.fromisoformat(found.group(1)) < night_of(moment) - datetime.timedelta(days=1):
                await self.store.adelete((*tools_mod.FACTS, self.settings.home), key)
                del facts[key]
            alarm = re.match(r"(?:open_)?alarm_(\d{12})$", key)
            if alarm and datetime.datetime.strptime(alarm.group(1), "%Y%m%d%H%M").replace(tzinfo=TZ) < moment - datetime.timedelta(hours=ALARM_HOURS):
                await self.store.adelete((*tools_mod.FACTS, self.settings.home), key)
                del facts[key]
        return facts

    async def add_wake(self, moment, why):
        """Returns the moment of the wake this one was merged into, or None if it was added."""
        if not why.startswith("device_end:"):
            self.reminder_set = True
        kept = why.startswith(("device_end:", REMINDER, UNANSWERED, FOLLOW_UP))
        async with self.pool.connection() as db:
            if not why.startswith("device_end:"):  # the same reminder asked for three times is one reminder
                near = await (await db.execute("select why, at from wakes where home = %s and not fired and at between %s and %s",
                                               (self.settings.home, moment - datetime.timedelta(minutes=SAME_TOPIC_MIN), moment + datetime.timedelta(minutes=SAME_TOPIC_MIN)))).fetchall()
                topic = safety.topic_of(why)
                for row in near:
                    same = abs(row["at"] - moment) <= datetime.timedelta(minutes=SAME_WAKE_MIN) and safety.near_same(why, row["why"])
                    chain = not kept and topic and not row["why"].startswith(("device_end:", REMINDER, UNANSWERED, FOLLOW_UP)) and safety.topic_of(row["why"]) == topic  # two chains about one thing, like "check again in an hour" twice (Nov 4)
                    if same or chain:
                        return row["at"].astimezone(TZ)
            await db.execute("insert into wakes (home, at, why) values (%s, %s, %s)", (self.settings.home, moment, why))
        return None

    async def wakes(self):
        async with self.pool.connection() as db:
            return await (await db.execute("select * from wakes where home = %s and not fired order by at", (self.settings.home,))).fetchall()

    async def fire_wakes(self, moment=None):
        """Dispatch every wake that is due at this moment, once each. A wake to get something ready goes if it is too late to matter, a reminder still
        comes, saying it is late. Nothing is ever acted on as if it were still its old moment."""
        moment = moment or datetime.datetime.now(TZ)
        async with self.pool.connection() as db:
            due = await (await db.execute("update wakes set fired = true where home = %s and not fired and at <= %s returning why, at",
                                          (self.settings.home, moment))).fetchall()
        fired = []
        for row in sorted(due, key=lambda r: r["at"]):
            late = (moment - row["at"]).total_seconds() / 60
            if row["why"].startswith("device_end:"):
                _, key, until = row["why"].split(":", 2)
                fired.append(await self.dispatch("device_ended", {"key": key, "until": until, "late": late > END_LATE_MIN}, source="wake", at=row["at"].isoformat() if late <= END_LATE_MIN else moment.isoformat()))
            elif late <= STALE_WAKE_MIN:
                fired.append(await self.dispatch("wake", {"why": row["why"]}, source="wake", at=row["at"].isoformat()))
            elif PREPARES.search(row["why"]) and not row["why"].startswith((FOLLOW_UP, REMINDER)):
                self.publish("source", name="wake", status=f"dropped, {late:.0f} minutes late: {row['why'][:120]}")
            else:
                fired.append(await self.dispatch("wake", {"why": row["why"], "due": row["at"].astimezone(TZ).strftime("%A %H:%M")}, source="wake", at=moment.isoformat()))
        return fired

    async def dispatch(self, type, payload=None, source="simulator", at=None, ask=False):
        """The one way in. at is an ISO time for a simulated moment, the agent then lives that moment. ask holds what is
        said on the Echo, for the one waiting there."""
        moment = datetime.datetime.fromisoformat(at).astimezone(TZ) if at else datetime.datetime.now(TZ)
        key = (type, json.dumps(payload or {}, sort_keys=True))
        same = self.running.get(key) if type not in ("schedule", "wake", "device_ended") else None
        if same and not same[1].done():  # the same event pressed again while the first still runs is one event
            return same
        event = {"type": type, "payload": payload or {}, "source": source, "moment": moment, "ask": ask}
        async with self.pool.connection() as db:
            row = await (await db.execute("insert into events (home, happened_at, type, source, payload) values (%s, %s, %s, %s, %s) returning id",
                                          (self.settings.home, moment, type, source, Jsonb(event["payload"])))).fetchone()
        event["id"] = row["id"]
        if type == "state_changed" and self.mock:
            entity = str(event["payload"].get("entity_id"))
            if entity.startswith("sensor.") and entity not in self.readings:  # the first reading has a room to compare with, or 35 degrees in a minute reads as real and 10 as a fault
                try:
                    self.readings[entity] = (float(self.mock.state(entity)), moment)
                except (TypeError, ValueError):
                    pass
            self.mock.set_state(event["payload"].get("entity_id"), event["payload"].get("state"), moment)
        self.publish("event", event_id=event["id"], type=type, source=source, payload=event["payload"], happened_at=moment.isoformat())
        done = asyncio.get_running_loop().create_future()
        event["done"] = done
        self.running = {k: v for k, v in self.running.items() if not v[1].done()}
        self.running[key] = (event["id"], done)
        await self.queue.put(event)
        return event["id"], done

    async def recover(self):
        """What a power cut left unfinished runs now, a night cry can't be lost. Too old to matter is on record as missed."""
        async with self.pool.connection() as db:
            await db.execute("update events set status = 'missed', outcome = 'The agent was down when this came.' where home = %s and status = 'queued' and at < now() - %s::interval",
                             (self.settings.home, RECOVER_WITHIN))
            rows = await (await db.execute("select * from events where home = %s and status = 'queued' order by id", (self.settings.home,))).fetchall()
        for row in rows:
            event = {"id": row["id"], "type": row["type"], "payload": row["payload"], "source": row["source"], "moment": row["happened_at"].astimezone(TZ), "ask": False,
                     "again": True, "done": asyncio.get_running_loop().create_future()}
            await self.queue.put(event)
        return len(rows)

    async def prune(self):
        """Every step of a thread is a full checkpoint, so this keeps only the latest, and rota entries for nights long gone."""
        await self.saver.aprune([self.config["configurable"]["thread_id"]], strategy="keep_latest")
        known = await tools_mod.facts(self.store, self.settings.home)
        limit = self.now().date() - datetime.timedelta(days=2)
        for key in known:
            if key.startswith("on_duty_") and key[8:] < str(limit):
                await self.store.adelete((*tools_mod.FACTS, self.settings.home), key)

    async def work(self):
        ran = 0
        while True:
            event = await self.queue.get()
            try:
                outcome = await self.run(event)
                ran += 1
                if ran % PRUNE_EVERY == 0:
                    await self.prune()
            except Exception as failure:  # PostgreSQL gone while recording a failure: the worker still lives for the next event
                outcome = {"status": "failed", "outcome": f"{type(failure).__name__}: {str(failure)[:300]}"}
                self.publish("error", event_id=event["id"], error=outcome["outcome"])
            if event["ask"]:
                outcome = {**outcome, "said": self.channel.hold or []}
            if not event["done"].done():
                event["done"].set_result(outcome)

    async def finish(self, event, status, outcome):
        async with self.pool.connection() as db:
            await db.execute("update events set status = %s, outcome = %s where id = %s", (status, outcome, event["id"]))
        self.publish("done", event_id=event["id"], status=status, outcome=outcome)
        return {"status": status, "outcome": outcome}

    async def record(self, event_id, tool, arguments, result):
        async with self.pool.connection() as db:
            await db.execute("insert into actions (event_id, tool, arguments, result) values (%s, %s, %s, %s)",
                             (event_id, tool, Jsonb(arguments), result))

    async def run(self, event):
        started = time.monotonic()
        self.moment = event["moment"]
        self.heard = str(event["payload"].get("text", "")) if event["type"] == "message" else ""
        self.sender = event["payload"].get("from") if event["type"] == "message" else None
        self.channel.hold = [] if event["ask"] else None
        why = str(event["payload"].get("why", "")) if event["type"] == "wake" else ""
        self.follow_up = why.startswith(FOLLOW_UP)
        writer = FOLLOW_UP_WRITER.search(why) if self.follow_up else None
        self.alarm_writer = writer.group(1) if writer else None
        self.reminder_for = why[len(REMINDER) + 1:].split(":", 1)[0] if why.startswith(f"{REMINDER}:") else None
        self.real_danger = a_real_danger(event, self.heard)
        self.a_cry = a_cry(event)
        self.duty_told = None
        self.room_reading = safety.unsafe_room(event["payload"]) if event["type"] == "state_changed" else None
        self.about_recipe = event["type"] == "recipe" or bool(safety.RECIPE_WORDS.search(self.heard))
        self.frightened = self.sender in tools_mod.PARENTS and safety.frightened(self.heard)
        self.camera_off = event["type"] == "camera" and event["payload"].get("verdict") == "off"
        self.routine = (event["type"] in ("state_changed", "device_ended") and self.room_reading is None) or (event["type"] == "wake" and why != RECHECK_ROOM and not why.startswith((REMINDER, UNANSWERED, FOLLOW_UP)))
        self.ping_topic = (safety.topic_of(why) or "other") if event["type"] == "wake" and not why.startswith((REMINDER, UNANSWERED, FOLLOW_UP)) else None
        self.pinged_then = {k: set(v) for k, v in self.pinged.items()}
        self.refusals, self.told_now, self.calls, self.capped, self.began = {}, set(), [], False, time.monotonic()
        self.vital_check = False
        self.in_check = event["type"] == "schedule"
        self.said_out = {}
        self.current = event["id"]
        if self.mock:
            self.mock.tick(event["moment"])
        try:
            if event["type"] == "device_ended":
                return await self.ended(event)
            if event["type"] == "gap_check":
                return await self.gap_only(event)
            if event["type"] == "state_changed":
                await self.note_hand(event)
            if why.startswith(f"{UNANSWERED}:") and await self.reminder_answered(event, why):
                return await self.finish(event, "done", "Nothing done.")
            if event["type"] == "message":
                self.pinged.pop(self.sender, None)  # they're here, so the next one is news again
                await self.keep_plan(event)
                stopped = await self.gated(event)
                if stopped:
                    return stopped
                if self.sender in tools_mod.PARENTS and safety.FALSE_ALARM.search(self.heard) and not safety.VITAL.search(safety.NOT_A_SIGN.sub(" ", self.heard)):
                    event["note"] = await self.close_alarms(event)
                elif self.sender in tools_mod.PARENTS and not event.get("note") and (not safety.ERRAND.search(self.heard) or safety.HOW_HE_IS.search(self.heard)):
                    await self.answered()  # they said how things are, so nobody asks
            return await self.attempts(event, started)
        except Exception as failure:  # one bad event never stops the agent: it is on record, and the next one runs
            self.publish("error", event_id=event["id"], error=f"{type(failure).__name__}: {str(failure)[:300]}")
            return await self.finish(event, "failed", f"{type(failure).__name__}: {str(failure)[:300]}")

    retry_waits = RETRY_WAITS
    hold_s = HOLD_S

    async def hold_line(self, event):
        """A parent never sits in silence on a slow Muse. One line, only if nothing has reached them yet, and it answers nothing, so Muse's answer still goes."""
        await asyncio.sleep(self.hold_s)
        if self.sender in self.told_now:
            return
        line = HOLDING["en" if self.settings.lang == "en" else "es"]
        await asyncio.to_thread(self.channel.send, self.sender, line)
        await self.record(event["id"], "holding_line", {"parent": self.sender}, line)
        self.publish("tool_result", event_id=event["id"], tool="notify", arguments={"parent": self.sender, "text": line}, result=f"Sent to {self.sender}.")

    async def attempts(self, event, started):
        """The brain can be away for a moment. It gets asked again, and if it stays away, what can't wait goes out without it."""
        hold = asyncio.create_task(self.hold_line(event)) if event["type"] == "message" and self.sender in tools_mod.PARENTS and not event["ask"] else None
        try:
            return await self.brain_or_fixed(event, started)
        finally:
            if hold:
                hold.cancel()

    async def brain_or_fixed(self, event, started):
        for wait in (*self.retry_waits, None):
            try:
                return await self.decide(event, started)
            except Exception as failure:
                why = f"{type(failure).__name__}: {str(failure)[:300]}"
                self.publish("error", event_id=event["id"], error=why)
                if wait is None:
                    told = await self.without_brain(event)
                    return await self.finish(event, "failed", why + (f" Told without Muse: {', '.join(told)}." if told else ""))
                event["again"] = True
                await asyncio.sleep(wait)

    async def without_brain(self, event):
        """Fixed lines for when Muse is unreachable: a cry to the parent on duty, an alarm to both, a parent's message gets told to retry."""
        payload, lang = event["payload"], self.settings.lang if self.settings.lang in NO_BRAIN else "es"
        kind = str(payload.get("kind", "")).lower()
        if event["type"] == "sound" and "cry" in kind:
            to, line = [who_is_on(event["moment"], await tools_mod.facts(self.store, self.settings.home))], NO_BRAIN[lang]["cry"]
        elif event["type"] == "sound" and ALARM.search(kind):
            to, line = list(tools_mod.PARENTS), NO_BRAIN[lang]["alarm"].format(kind=payload.get("kind"))
        elif event["type"] == "message" and payload.get("from") in tools_mod.PARENTS:
            to, line = [payload["from"]], NO_BRAIN[lang]["message"]
        elif event["type"] == "schedule" and payload.get("name") == "morning":  # a plan a parent reported can't wait for the brain
            plans = [v for _, v in plans_of(await tools_mod.facts(self.store, self.settings.home))]
            to, line = list(tools_mod.PARENTS) if plans else [], " ".join(plans)
        else:
            return []
        told = []
        for parent in to:
            try:
                await asyncio.to_thread(self.channel.send, parent, line)
                await self.record(event["id"], "no_brain_message", {"to": parent}, line)
                self.publish("tool_result", event_id=event["id"], tool="notify", arguments={"parent": parent, "text": line}, result=f"Sent to {parent}.")
                told.append(parent)
            except Exception as failure:
                self.publish("error", event_id=event["id"], error=f"{type(failure).__name__}: {str(failure)[:300]}")
        return told

    async def gated(self, event):
        """Red flags and medical questions never reach Muse. The fixed line goes out and the thread learns it happened."""
        text = event["payload"].get("text", "")
        verdict = await asyncio.to_thread(safety.gate, text, self.screen, self.settings.lang)
        if not verdict:
            return None
        kind, line = verdict
        lang = safety.lang_of(text, self.settings.lang)
        sender = event["payload"].get("from")
        to = list(tools_mod.PARENTS) if kind != "medical" or sender not in tools_mod.PARENTS else [sender]
        duty = who_is_on(event["moment"], await tools_mod.facts(self.store, self.settings.home))
        if kind == "medical" and duty not in to:  # the one on duty knows what was asked, without being woken for it
            quietly = safety.because(sender, text, line, lang)
            await asyncio.to_thread(self.channel.send, duty, quietly, True)
            await self.record(event["id"], "gate_message", {"to": duty, "kind": kind, "quiet": True}, "Told quietly.")
            self.publish("tool_result", event_id=event["id"], tool="notify", arguments={"parent": duty, "text": quietly, "quiet": True}, result=f"Sent to {duty}.")
        for parent in to:  # one phone failing never keeps the line from the other, and it is tried once more
            words = safety.because(sender or "A parent", text, line, lang) if kind != "medical" and parent != sender else line
            for attempt in range(2):
                try:
                    await asyncio.to_thread(self.channel.send, parent, words)
                    await self.record(event["id"], "gate_message", {"to": parent, "kind": kind}, words)
                    break
                except Exception as failure:
                    await self.record(event["id"], "gate_message", {"to": parent, "kind": kind, "attempt": attempt + 1}, f"Failed: {type(failure).__name__}")
        if self.channel.hold is not None:
            self.channel.hold.append(line)
        self.publish("gate", event_id=event["id"], gate=kind, to=to, text=line)
        if kind == "urgent" and rules.names_fever(text):  # it stays known across the night, whoever is on duty
            await self.keep_fever(event, sender, text)
        if kind != "medical":
            await self.keep_alarm(event, sender, text)
        await self.agent.aupdate_state(self.config, {"messages": [
            HumanMessage(f"{sender or 'A parent'} wrote: {rules.parent_text(text)}"),
            AIMessage(f"The safety gate answered this with its fixed {kind} line to {', '.join(to)}. I did not answer it.")]}, as_node="model")
        rest = safety.rest_of(text) if kind != "emergency" else ""  # a life in danger gets the fixed line and nothing else from the house
        if rest:  # the rest of the message still gets done
            event["payload"] = {**event["payload"], "text": rest}
            self.heard = rest
            event["note"] = "The safety gate already answered the worrying part of this message. Do only what these words ask, and don't bring that part up."
            return None
        return await self.finish(event, "gated", kind)

    async def keep_fever(self, event, sender, text):
        moment = event["moment"]
        await self.record(event["id"], "fever_logged", {"by": sender}, "In the alarm's note.")
        await self.store.aput((*tools_mod.FACTS, self.settings.home), "fever_reported", {"value": f'{sender} reported at {moment:%A %H:%M}: "{safety.sign_of(text)}". Both parents were told to call.'})

    async def keep_plan(self, event):
        """A plan from a doctor is kept in the parent's words, whatever Muse chooses to remember, and even when the gate answers the rest of the message."""
        who, plan = event["payload"].get("from"), safety.plan_of(event["payload"].get("text", ""))
        if who in tools_mod.PARENTS and plan:
            await self.store.aput((*tools_mod.FACTS, self.settings.home), f"plan_{event['moment']:%Y%m%d%H%M}", {"value": f'{who.capitalize()} at {event["moment"]:%H:%M}: "{plan}"'})

    async def close_follow_up(self):
        async with self.pool.connection() as db:
            await db.execute(f"update wakes set fired = true where home = %s and not fired and (why like '{FOLLOW_UP}%%' or why like '{UNANSWERED}:%%: how Theo is%%')", (self.settings.home,))

    async def answered(self):
        """A parent said how things are: nobody asks again, and the next check says what happened one last time."""
        await self.close_follow_up()
        namespace = (*tools_mod.FACTS, self.settings.home)
        facts = await tools_mod.facts(self.store, self.settings.home)
        if any(a_said_alarm(k) for k in facts):
            await self.store.aput(namespace, ANSWERED, {"value": "yes"})
        for key in [k for k in facts if k.startswith(OPEN_ALARM)]:
            await self.store.adelete(namespace, key)

    async def close_alarms(self, event):
        """A parent said it was a false alarm: it is over now, for the checks, the questions and the home's own wakes about it."""
        await self.close_follow_up()
        namespace = (*tools_mod.FACTS, self.settings.home)
        facts = await tools_mod.facts(self.store, self.settings.home)
        for key, value in facts.items():
            if a_said_alarm(key) or key.startswith(OPEN_ALARM) or key in (ANSWERED, "fever_reported"):
                found = re.search(r'"(.+)"', str(value))
                if found:
                    self.closed_signs.add(found.group(1).lower())
                await self.store.adelete(namespace, key)
        for wake in await self.wakes():
            if safety.ABOUT_HOW_HE_IS.search(wake["why"]) or re.search(r"\bfever\b|\bfiebre\b", wake["why"], re.I):
                async with self.pool.connection() as db:
                    await db.execute("update wakes set fired = true where id = %s", (wake["id"],))
        return f"{self.sender.capitalize()} says it was a false alarm, so it is closed. Answer in one short line, with no question about it and no advice."

    async def reminder_answered(self, event, why):
        """The escalation is for a parent who stayed silent, and only by day."""
        parent = why[len(UNANSWERED) + 1:].split(":", 1)[0]
        if is_night(event["moment"]):
            return True
        async with self.pool.connection() as db:
            row = await (await db.execute("select 1 from events where home = %s and type = 'message' and payload->>'from' = %s and happened_at >= %s limit 1",
                                          (self.settings.home, parent, event["moment"] - datetime.timedelta(minutes=ESCALATE_MIN)))).fetchone()
        return bool(row)

    async def keep_alarm(self, event, who, text, ask=True, verb="wrote"):
        """An alarm goes in the log and in memory with the words that raised it, nothing else from the message. The next check says it once, and
        before that Muse asks how Theo is, once. Only people and the house's own alarms open one: never what the agent itself wrote."""
        moment, sign = event["moment"], safety.sign_of(text)
        try:
            await asyncio.to_thread(self.log.add, "note", {"text": f'Alarm at {moment:%H:%M}, {who}: "{sign}"'}, moment.isoformat())
        except Exception as failure:
            self.publish("error", event_id=event["id"], error=f"{type(failure).__name__}: {str(failure)[:300]}")
        await self.store.aput((*tools_mod.FACTS, self.settings.home), f"alarm_{moment:%Y%m%d%H%M}", {"value": f'At {moment:%A %H:%M} {who} {verb} "{sign}", and both parents were told.'})
        await self.store.adelete((*tools_mod.FACTS, self.settings.home), ANSWERED)  # a new danger: nobody has answered this one
        self.closed_signs.discard(sign.lower())
        if ask and not any(w["why"].startswith(FOLLOW_UP) for w in await self.wakes()):  # two alarms close together get one question
            await self.add_wake(moment + datetime.timedelta(minutes=FOLLOW_UP_MIN), f'{FOLLOW_UP}: at {moment:%H:%M} {who} wrote "{sign}". Unless a parent has already said how Theo is, ask {who if who in tools_mod.PARENTS else "both parents"} and whoever is on duty, in one short line, how Theo is now and if they reached a doctor. This is no new emergency, so don\'t set emergency. Quote nothing else, and no advice.')

    async def ended(self, event):
        """What Muse started ended by itself, so the parent on duty hears it, quietly. Too late to matter is only tidied."""
        payload, moment = event["payload"], event["moment"]
        namespace = (*tools_mod.FACTS, self.settings.home)
        found = await self.store.aget(namespace, payload["key"])
        if not found or found.value["value"] != payload["until"]:  # turned off earlier, or started again
            return await self.finish(event, "done", "Nothing done.")
        await self.store.adelete(namespace, payload["key"])
        if payload["key"] == "warmer_off_at":
            await self.store.adelete(namespace, self.hand_key("Tapo P110 - Bottle Warmer"))
        if payload.get("late"):
            return await self.finish(event, "done", "Nothing done.")
        facts = await tools_mod.facts(self.store, self.settings.home)
        duty = who_is_on(moment, facts)
        line = ENDED[payload["key"]]["en" if self.settings.lang == "en" else "es"].format(at=f"{datetime.datetime.fromisoformat(payload['until']):%H:%M}")
        await self.say_fixed(event, duty, line, quiet=True)
        return await self.finish(event, "done", f"Told {duty}.")

    def current_feed(self, moment):
        """The last feed that counts: at home, a log nobody writes to says nothing about Theo (Nov 3, a false alarm to both parents)."""
        feed = self.last_feed(moment)
        if feed and part("log") == "real" and (moment - feed).total_seconds() / 3600 >= safety.STALE_LOG_H:
            return None
        return feed

    def gap_due(self, feed, facts, after, until):
        """The first moment in (after, until] the ladder reaches a step it hasn't said yet, or None. Nobody has to send anything for it to speak."""
        if not feed:
            return None
        told = str(facts.get("feed_gap_told", "")).rsplit("|", 1)
        said = int(told[1]) if told[0] == feed.isoformat() and len(told) == 2 else 0
        for step in safety.GAP_STEPS:
            at = feed + datetime.timedelta(hours=step)
            if step > said and at <= until:
                if at > after or safety.gap_step((until - feed).total_seconds() / 3600) == step:
                    return max(at, after)
        return None

    async def tick_gap(self, moment=None):
        """The ladder, as time passes. The real home calls this on a timer, and the simulator's clock calls it on its way."""
        moment = moment or datetime.datetime.now(TZ)
        feed = await asyncio.to_thread(self.current_feed, moment)
        facts = await tools_mod.facts(self.store, self.settings.home)
        at = self.gap_due(feed, facts, moment - datetime.timedelta(seconds=1), moment)
        return await self.dispatch("gap_check", {}, source="clock", at=moment.isoformat()) if at else None

    async def gap_only(self, event):
        moment = event["moment"]
        facts = await self.tidy_facts(moment)
        self.feed = await asyncio.to_thread(self.current_feed, moment)
        said = await self.raise_gap(event, moment, facts)
        return await self.finish(event, "done", "Raised the feed gap." if said else "Nothing done.")

    async def raise_gap(self, event, moment, facts):
        """The feed gap ladder, from code: each step said once, both parents from BOTH_FROM up. Returns what Muse has to know."""
        hours = self.gap_hours() if self.feed else 0
        step = safety.gap_step(hours)
        if step is None:
            return []
        told = str(facts.get("feed_gap_told", "")).rsplit("|", 1)
        if not (told[0] == self.feed.isoformat() and len(told) == 2 and int(told[1]) >= step):
            await self.store.aput((*tools_mod.FACTS, self.settings.home), "feed_gap_told", {"value": f"{self.feed.isoformat()}|{step}"})
            to = list(tools_mod.PARENTS) if step >= safety.BOTH_FROM else [who_is_on(moment, facts)]
            line = safety.gap_line(hours, step, self.settings.lang)
            for parent in to:
                try:
                    await asyncio.to_thread(self.channel.send, parent, line)
                    await self.record(event["id"], "gap_message", {"to": parent, "step": step}, line)
                except Exception as failure:
                    await self.record(event["id"], "gap_message", {"to": parent, "step": step}, f"Failed: {type(failure).__name__}")
            self.publish("gate", event_id=event["id"], gate="feed_gap", to=to, text=line)
        return [f"There is a gap: no feed in the log for {hours:.0f} hours, and the parents have been told. Any message of yours about Theo says that fact plainly, as the hours since the last feed. Never reassure about it, and never mention an alert or a notice."]

    def log_note(self, event, moment):
        """Last night's feeds from the log, so a morning check can't call yesterday's day feeds last night's."""
        if event["type"] != "schedule" or event["payload"].get("name") != "morning":
            return []
        start = moment.replace(hour=22, minute=0, second=0, microsecond=0) - datetime.timedelta(days=1)
        try:
            entries = self.log.entries("feeding", None, 50)
        except Exception:
            return []
        times = [datetime.datetime.fromisoformat(e["ts"]) for e in entries]
        night = sum(1 for t in times if start <= (t if t.tzinfo else t.replace(tzinfo=TZ)) <= moment)
        return [f"Feeds in the log last night, since 22:00: {night}. Any earlier ones were daytime feeds, not last night's."]

    def reading_note(self, event, moment):
        payload = event["payload"]
        if event["type"] != "state_changed" or not str(payload.get("entity_id", "")).startswith("sensor."):
            return []
        if self.quiet_start(event):
            try:
                self.readings[payload["entity_id"]] = (float(payload.get("state")), moment)
            except (TypeError, ValueError):
                pass
            return ["The agent just restarted and this is its first reading. It is not a check-in. Look after the room if it needs it, and message nobody."]
        try:
            value = float(payload.get("state"))
        except (TypeError, ValueError):
            return []
        before = self.readings.get(payload["entity_id"])
        self.readings[payload["entity_id"]] = (value, moment)
        if not before:
            return []
        why = safety.sensor_jump(payload["entity_id"], value, before[0], abs((moment - before[1]).total_seconds()) / 60)
        return [why] if why else []

    screen = None
    in_check = False  # for this event: a morning or evening check
    said_out = {}  # for this event: what really went out, by what Muse asked
    follow_up = False  # for this event: asking how Theo is after an alarm
    alarm_writer = None  # for this event: who wrote the alarm it asks about
    reminder_for = None  # for this event: the parent who asked for this reminder
    real_danger = False  # for this event: emergency can wake the parent off duty
    a_cry = False  # for this event: a cry was heard
    room_reading = None  # for this event: Theo's room far out of range
    about_recipe = False  # for this event: a recipe is on the table
    vital_check = False  # for this event: a check after an alarm about his breathing or colour
    frightened = False  # for this event: a parent afraid about a sign in Theo now
    camera_off = False  # for this event: the camera saw no hand on him
    routine = False  # for this event: nothing someone must act on, so at night it makes no sound
    last_night_known = True  # for this event: last night's duty has a record
    reminder_set = False  # for this event: a promise needs a reminder behind it
    after_start = False  # for this event: the first reading after a restart
    duty_told = None  # for this event: who has to hear about a duty change
    ping_topic = None  # for this event: what a wake of Muse's own is about, so it asks once

    async def decide(self, event, started):
        self.reminder_set = False
        self.after_start = self.quiet_start(event)
        await agent_mod.repair(self.agent, self.config)
        moment = event["moment"]
        facts = await self.tidy_facts(moment)
        self.last_night_known = await self.knows_last_night(event, moment, facts)
        self.vital_check = event["type"] == "schedule" and vital_alarm(facts)
        self.feed = await asyncio.to_thread(self.current_feed, moment)
        extra = [event["note"]] if event.get("note") else []
        if event["type"] == "message" and safety.reports_feed(self.heard):  # the feed goes in the log first: it may close the gap, and no alarm goes out over it
            self.feed = None
            extra.append("This parent is telling you about a feed. Log it first, then answer from what the log shows.")
        extra += await self.raise_gap(event, moment, facts)
        extra += self.log_note(event, moment)
        room_before = self.readings.get(event["payload"].get("entity_id"))
        extra += self.reading_note(event, moment)
        if safety.IMPOSSIBLE_ML.search(self.heard):
            extra.append(f"An amount in this message can't be one feed for a newborn: more than {safety.MAX_FEED_ML} ml is surely a typo, and no emergency. Log the amounts that can be true, ask about that one in one line, and don't set emergency.")
        if self.about_recipe and safety.FOR_BABY.search(self.heard):
            extra.append("This recipe is meant for Theo. Never call it suitable.")
        if self.frightened:
            other = next(p for p in tools_mod.PARENTS if p != self.sender)
            extra.append(f"{self.sender.capitalize()} is scared about a sign in Theo right now. Answer in one or two short lines: first who to call, his pediatrician, or 911 if it can't wait, with no feed amounts or totals and no other advice. Tell {other} too, with emergency set, in one line saying what {self.sender} wrote.")
        self.warm_until = datetime.datetime.fromisoformat(facts["warmer_off_at"]) if "warmer_off_at" in facts else None
        text = describe(event, moment, facts, self.feed, self.settings.lang, extra, self.last_night_known)
        if event.get("again"):
            text += "\n\nAn earlier try at this event was cut off. Some of it may already be done, so check before repeating anything."
        self.calls, self.capped = [], False  # another try at this event starts clean
        final, used, calls = "", 0, self.calls

        async def think(words):
            nonlocal final, used
            pending = {}
            async for update in self.agent.astream({"messages": [HumanMessage(words)]}, self.config, stream_mode="updates"):
                for node, step in update.items():
                    if node not in ("model", "tools"):  # the trim's update holds the whole kept history: nothing in it happened now
                        continue
                    for message in (step or {}).get("messages", []) if isinstance(step, dict) else []:
                        if message.type == "ai":
                            used += (message.usage_metadata or {}).get("total_tokens", 0)
                            for call in message.tool_calls:
                                pending[call["id"]] = call
                                self.publish("tool_call", event_id=event["id"], tool=call["name"], arguments=call["args"])
                            if not message.tool_calls:
                                final = tools_mod.text_of(message.content)
                        elif message.type == "tool":
                            call = pending.pop(message.tool_call_id, {"name": message.name, "args": {}})
                            result = tools_mod.text_of(message.content)
                            arguments = call["args"]
                            if call["name"] == "notify" and result.startswith("Sent"):  # the record says what went out, which a check may have tidied
                                arguments = {**arguments, "text": self.said_out.get((arguments.get("parent"), arguments.get("text")), arguments.get("text"))}
                            calls.append((call["name"], arguments, result))
                            await self.record(event["id"], call["name"], arguments, result)
                            self.publish("tool_result", event_id=event["id"], tool=call["name"], arguments=arguments, result=result[:600])
                if node == "tools" and (self.capped or sum(1 for _, _, result in calls if tools_mod.FAILED.match(result or "")) >= MAX_REFUSALS_IN_EVENT):  # Muse is fighting the checks, and a parent is waiting
                    self.capped = True
                    return

        # The history is trimmed before each model call, so a second ask can lose the event it is about. Then Muse told a parent "I didn't catch your last message" (Nov 4). It carries its own context.
        context = text.split("\n", 1)[0] + (f"\n{self.sender or 'Someone'} wrote: {rules.parent_text(self.heard)}" if self.heard else "") + "\n"

        async def again(words):
            if not self.capped:
                await think(context + words)
        await think(text)
        if unanswered(event, calls):  # Muse sometimes leaves a parent's question with no reply at all (Nov 3, 1 of 3 runs). Ask once.
            await again(f"{self.sender} wrote to you and has received nothing from you. Answer them with notify, in one short line.")
        elif unheard_cry(event, calls):  # the same with a cry: once the warmer went on and nobody was told (Nov 3)
            if not self.cry_told_lately(moment):
                await again("Theo is crying and no parent has been told. Tell the parent on duty with notify, in one short line that says he is crying.")
        for nudge in await self.loose_ends(event, facts, calls):
            await again(nudge)
        reading = self.room_reading
        if reading is not None and not told_out_loud(calls):  # asked and still nothing (Nov 3, 1 of 6 runs)
            await self.room_line(event, reading)
        if reading is not None and not self.after_start and not any(w["why"] == RECHECK_ROOM for w in await self.wakes()):  # told once and dropped is how a hot room gets forgotten (Nov 3). The first extreme reading is read again soon: it may be the sensor, and it may not.
            first = not (room_before and safety.unsafe_room({"entity_id": event["payload"]["entity_id"], "state": room_before[0]}) is not None)
            await self.add_wake(moment + (datetime.timedelta(minutes=RECHECK_SOON_MIN) if first else datetime.timedelta(hours=RECHECK_ROOM_H)), RECHECK_ROOM)
        lang = "en" if self.settings.lang == "en" else "es"
        if self.frightened:
            other = next(p for p in tools_mod.PARENTS if p != self.sender)
            if other not in sent_to(calls):  # asked and still not told: this is the one thing that may wake them
                await self.say_fixed(event, other, FRIGHT_TOLD[lang].format(who=self.sender.capitalize(), words=safety.sign_of(self.heard)))
        if self.warm_until and warmer_started(calls) and not self.warmer_end_said(calls):  # asked and still unsaid: nobody leaves it running without knowing it ends
            await self.say_fixed(event, self.sender if self.sender in tools_mod.PARENTS else who_is_on(moment, facts), WARMER_ENDS[lang].format(at=f"{self.warm_until:%H:%M}"), quiet=self.hushed() or (is_night(moment) and not self.sender and not self.a_cry))
        await self.recipe_lines(event, calls, moment, facts, lang)
        if event["type"] == "camera" and event["payload"].get("verdict") == "off":
            if not any(tool == "notify" and (result or "").startswith("Sent") for tool, _, result in calls):
                await self.say_fixed(event, who_is_on(moment, facts), CAMERA_OFF[lang])
            if not any(tool == "say_on_echo" and (result or "").startswith("Said") for tool, _, result in calls):
                await self.echo_fixed(event, CAMERA_OFF[lang])
        if self.reminder_for:
            await self.finish_reminder(event, calls, lang)
        if event["type"] == "schedule" and event["payload"].get("name") == "morning":
            if plans_of(facts) and not safety.PLAN_TOLD.search(sent_words(calls)):  # asked and still left out: their own words go out
                for parent in tools_mod.PARENTS:
                    for _, plan in plans_of(facts):
                        await self.say_fixed(event, parent, plan)
            for key in [k for k, _ in plans_of(facts)] + [k for k in facts if k.startswith("duty_note_")]:
                await self.store.adelete((*tools_mod.FACTS, self.settings.home), key)
        if self.duty_told and not any(tool == "notify" and arguments.get("parent") == self.duty_told and (result or "").startswith("Sent") for tool, arguments, result in calls):  # nobody gets a night without hearing it
            await self.say_fixed(event, self.duty_told, HANDED_OVER[lang].format(who=str(self.sender).capitalize()))
        if event["type"] == "schedule":
            await self.check_said(event, calls, facts, lang)
        if self.follow_up and not is_night(moment) and len(sent_to(calls)) == 1 and any(a_said_alarm(k) for k in facts):  # one question, and by day the other parent hears once if nobody answers. At night the morning check does it.
            asked = next(iter(sent_to(calls)))
            await self.add_wake(moment + datetime.timedelta(minutes=ESCALATE_MIN), f"{UNANSWERED}:{asked}: how Theo is, after an alarm")
        if unanswered(event, calls):  # asked twice and still nothing: nobody is left waiting on Muse
            line = self.plain_line(self.sender)
            await self.say_fixed(event, self.sender, line)
            calls.append(("notify", {"parent": self.sender, "text": line}, f"Sent to {self.sender}."))
        if unheard_cry(event, calls) and not self.cry_told_lately(moment):  # the answer may have been about something else: the cry is still said
            await self.say_fixed(event, who_is_on(moment, facts), CRY_LINE[lang])
            calls.append(("notify", {"parent": who_is_on(moment, facts), "text": CRY_LINE[lang]}, "Sent."))
        if self.a_cry and not unheard_cry(event, calls):
            self.cry_told_at = moment
        if self.real_danger and any(tool == "notify" and arguments.get("emergency") and (result or "").startswith("Sent") for tool, arguments, result in calls):  # from their words, or the house's: what the agent wrote never opens an alarm
            await self.keep_alarm(event, self.sender or "the home", self.heard or str(event["payload"].get("kind", "")), ask=event["type"] == "message", verb="wrote" if event["type"] == "message" else "heard")
        line = tools_mod.record_line(calls)
        if final:  # Muse's own closing line can contradict what it did (Nov 3), so it is kept apart and the record is the calls
            final = safety.plain(final)
            await self.record(event["id"], "muse_note", {}, final)
            for key in memory_named(final, facts):
                self.publish("memory_used", event_id=event["id"], key=key, value=str(facts[key]))
        self.publish("decision", event_id=event["id"], text=line, note=final, seconds=round(time.monotonic() - started, 1), tokens=used)
        return await self.finish(event, "done", line)

    async def recipe_lines(self, event, calls, moment, facts, lang):
        """What a recipe message owes the parent and Muse left out goes in one message from code: the recipe itself, Theo's age, and that it can't be sent."""
        preview = preview_of(calls)
        if not preview:
            return
        words = sent_words(calls)
        lines = []
        if not recipe_shown(preview, words):
            out, _ = safety.outbound(recipe_card(preview, lang), lang)
            lines += [out] if out else []
        if not safety.LATER_ON.search(words):  # the age is a fact the home knows, and it isn't a judgment on the food
            lines.append(RECIPE_LATER[lang])
        if not safety.says_cant_send(words):
            lines.append(NO_COOKIDOO[lang])
        if lines:
            await self.say_fixed(event, self.sender if self.sender in tools_mod.PARENTS else who_is_on(moment, facts), "\n\n".join(lines))

    async def check_said(self, event, calls, facts, lang):
        """After a morning or evening check. What nobody heard goes out from code. An answered alarm is closed now. One with no answer stays open: an evening check carries it
        to the morning, and after the morning it is known but no check says it again, until a parent answers."""
        namespace = (*tools_mod.FACTS, self.settings.home)
        moment = event["moment"]
        alarms = {k: v for k, v in facts.items() if a_said_alarm(k)}
        written = sent_words(calls).lower()
        answered = ANSWERED in facts
        for key, value in sorted(alarms.items()):
            found = ALARM_FACT.match(str(value))
            if found and found.group(1) not in written and found.group(2).lower() not in written:
                line = ALARM_SAID[lang].format(at=found.group(1), sign=found.group(2), ask="" if answered else ASK_HOW[lang]).strip()
                for parent in tools_mod.PARENTS:
                    await self.say_fixed(event, parent, line)
        if self.capped and not sent_to(calls):  # refused to the end: the check still says whose night it is
            duty = who_is_on(moment, facts)
            for parent in tools_mod.PARENTS:
                await self.say_fixed(event, parent, TONIGHT_YOU[lang] if parent == duty else TONIGHT_OTHER[lang].format(who=duty.capitalize()))
        if not alarms:
            return
        await self.close_follow_up()
        if answered or event["payload"].get("name") == "morning":
            for key, value in alarms.items():
                found = re.search(r'"(.+)"', str(value))
                if found:
                    self.closed_signs.add(found.group(1).lower())
                await self.store.adelete(namespace, key)
                if not answered:
                    await self.store.aput(namespace, OPEN_ALARM + key[len("alarm_"):], {"value": f"{value} Nobody has said how Theo is since."})
            await self.store.adelete(namespace, "fever_reported")
            await self.store.adelete(namespace, ANSWERED)

    def warmer_end_said(self, calls):
        words = sent_words(calls)
        return f"{self.warm_until:%H:%M}" in words and bool(safety.ENDS_ALONE.search(words))

    def cry_told_lately(self, moment):
        return bool(self.cry_told_at) and abs(moment - self.cry_told_at) < datetime.timedelta(minutes=CRY_TOLD_MIN)

    async def knows_last_night(self, event, moment, facts):
        """Who was on last night can only be said if a parent changed it, or the home was already running and something happened by then."""
        night = night_of(moment) - datetime.timedelta(days=1)
        if tools_mod.duty_key(night) in facts:
            return True
        ended = datetime.datetime.combine(night + datetime.timedelta(days=1), datetime.time(7), TZ)
        async with self.pool.connection() as db:
            row = await (await db.execute("select 1 from events where home = %s and id < %s and happened_at <= %s limit 1", (self.settings.home, event["id"], ended))).fetchone()
        if row:
            return True
        try:
            entries = await asyncio.to_thread(self.log.entries, None, None, 50)
        except Exception:
            return False
        began = datetime.datetime.combine(night, datetime.time(22), TZ)
        for entry in entries:
            at = datetime.datetime.fromisoformat(entry["ts"])
            if began <= (at if at.tzinfo else at.replace(tzinfo=TZ)) <= ended:
                return True
        return False

    async def echo_fixed(self, event, line):
        said = await asyncio.to_thread(self.channel.echo, line) or "Said on the kitchen Echo."
        await self.record(event["id"], "say_on_echo", {"text": line}, said)
        self.publish("tool_result", event_id=event["id"], tool="say_on_echo", arguments={"text": line}, result=said)

    async def finish_reminder(self, event, calls, lang):
        """A reminder a parent asked for reaches them, and by day the other parent hears once if they stay silent."""
        why = str(event["payload"]["why"])[len(REMINDER) + 1:].split(":", 1)[1].strip()
        if not any(tool == "notify" and arguments.get("parent") == self.reminder_for and (result or "").startswith("Sent") for tool, arguments, result in calls):
            await self.say_fixed(event, self.reminder_for, REMINDED[lang].format(why=why))
        if not is_night(event["moment"]):
            await self.add_wake(event["moment"] + datetime.timedelta(minutes=ESCALATE_MIN), f"{UNANSWERED}:{self.reminder_for}: {why}")

    async def room_line(self, event, reading):
        duty = who_is_on(event["moment"], await tools_mod.facts(self.store, self.settings.home))
        line = (f"Theo's room reads {reading:g} degrees. Please check the room, and whether the sensor is right." if self.settings.lang == "en"
                else f"El cuarto de Theo marca {reading:g} grados. Fijate cómo está el cuarto, y si el sensor está bien.")
        for parent in [duty] if is_night(event["moment"]) else list(tools_mod.PARENTS):
            await self.say_fixed(event, parent, line)

    async def loose_ends(self, event, facts, calls):
        """What must not stay unsaid, whatever Muse decided: each is asked for once."""
        told = any(tool == "notify" and (result or "").startswith("Sent") for tool, _, result in calls)
        asks = []
        if self.after_start:
            return asks
        if started(calls):
            asks.append("You started something and nobody knows. Tell the parent on duty in one short line that it is on and until when. "
                        + ("It is night and they didn't ask, so set quiet." if is_night(event["moment"]) else ""))
        reading = self.room_reading
        if reading is not None and not told_out_loud(calls):
            asks.append(f"Theo's room is at {reading:g} degrees, which is far out of range, and nobody knows. It is urgent even if the sensor may be wrong. Tell the parent on duty the reading and to go and check the room, not quietly, and by day the other parent too. No medical advice.")
        if self.reminder_for and self.reminder_for not in sent_to(calls):
            asks.append(f"{self.reminder_for.capitalize()} asked for this reminder and hasn't got it. Send it to them with notify, in one short line.")
        if self.frightened:
            other = next(p for p in tools_mod.PARENTS if p != self.sender)
            if other not in sent_to(calls):
                asks.append(f"{self.sender.capitalize()} is scared and {other} doesn't know. Tell {other} now in one line, with emergency set, what {self.sender} wrote, and to call his pediatrician.")
        if warmer_started(calls) and told and self.warm_until and not self.warmer_end_said(calls):
            asks.append(f"You started the bottle warmer. In one short line, say the time it ends, {self.warm_until:%H:%M}, and that it ends by itself.")
        name = event["payload"].get("name")
        if event["type"] == "schedule":
            if not told and self.checked_today.get(name) != event["moment"].date():
                asks.append(f"This is today's {name} check and nobody has heard from you. Do what it asks for, with notify.")
            self.checked_today[name] = event["moment"].date()
        if event.get("hand") and not told:
            asks.append(f"A person switched {event['hand']} by hand and nobody has heard from you. Tell the parent on duty in one short line, or ask them. At night, set quiet.")
        said_to = sent_to(calls)
        if self.duty_told and self.duty_told not in said_to:
            asks.append(f"{self.sender} changed who is on duty and {self.duty_told} doesn't know. Tell {self.duty_told} in one line, so they can say if it's wrong.")
        if event["type"] == "camera" and event["payload"].get("verdict") == "off":
            if not told:
                asks.append("No hand is on the baby at the changing table and nobody has heard from you. Tell the parent on duty lightly, in one short line, what the camera saw, and to put a hand on him.")
            if not any(tool == "say_on_echo" and (result or "").startswith("Said") for tool, _, result in calls):
                asks.append("No hand is on the baby at the changing table. Say so on the kitchen Echo as well, in one short sentence.")
        if self.follow_up and not told:
            asks.append("You were woken to ask how Theo is after an alarm, and nobody has heard from you. Ask them now, in one short line.")
        if event["type"] == "schedule":
            written = " ".join(str(arguments.get("text", "")) for tool, arguments, result in calls if tool == "notify" and (result or "").startswith("Sent")).lower()
            signs = [found.group(1) for k, v in sorted(facts.items()) if a_said_alarm(k) and (found := re.search(r'"(.+)"', str(v)))]
            left_out = [sign for sign in signs if sign.lower() not in written]
            if left_out:
                asks.append(f"Your message left out what happened since the last check. Say it plainly in one short line, with the time, quoting these words: {'; '.join(left_out)}. No advice.")
            if self.vital_check and not safety.ASKS_HOW.search(written):
                asks.append("There was an alarm about his breathing or his colour, and your message didn't ask how Theo is. Ask each parent now, in one short line.")
            if name == "morning" and plans_of(facts) and not safety.PLAN_TOLD.search(written):
                asks.append("Your message left out the plan a parent reported. Say it to each parent in one short line, in their words: " + " ".join(v for _, v in plans_of(facts)))
            notes = [v for k, v in facts.items() if k.startswith("duty_note_")] if name == "morning" else []
            if notes:
                asks.append("If you haven't yet, tell the other parent in one short line: " + " ".join(notes))
        cry_words = " ".join(str(arguments.get("text", "")) for tool, arguments, _ in calls if tool == "notify")
        if event["type"] == "sound" and "cry" in str(event["payload"].get("kind", "")).lower() and self.gap_hours() >= safety.FEED_GAP_H and not GAP_TOLD.search(cry_words):
            asks.append(f"Your message about the crying left out that the log shows no feed for {self.gap_hours():.0f} hours. Tell the same parent, in one short line, without reassuring.")
        return asks

    async def coach_line(self, parent, text, step=None):
        """A line the car seat coach on the Mac says to the parent. It comes from the seat's manual, so Muse isn't woken for it."""
        out, why = safety.outbound(text, self.settings.lang)
        if why or parent not in tools_mod.PARENTS:
            return why or "Refused: parent is gonza or ceci."
        async with self.pool.connection() as db:
            row = await (await db.execute("insert into events (home, happened_at, type, source, payload, status, outcome) values (%s, now(), 'coach_line', 'coach', %s, 'done', %s) returning id",
                                          (self.settings.home, Jsonb({"parent": parent, "step": step}), "Coach spoke."))).fetchone()
        await asyncio.to_thread(self.channel.send, parent, out)
        await self.record(row["id"], "coach_line", {"parent": parent, "step": step}, out)
        self.publish("coach_line", event_id=row["id"], parent=parent, step=step, text=out)
        return None

    async def whatsapp_status(self, parent, status):
        """What the WhatsApp provider reported about a message, on record next to the action that sent it. Muse isn't woken for it."""
        outcome = f"WhatsApp to {parent}: {status}."
        async with self.pool.connection() as db:
            await db.execute("insert into events (home, happened_at, type, source, payload, status, outcome) values (%s, now(), 'whatsapp_status', 'whatsapp', %s, 'done', %s)",
                             (self.settings.home, Jsonb({"parent": parent, "status": status}), outcome))
        self.publish("whatsapp_status", parent=parent, status=status)

    async def actions(self, event_id=None, limit=200):
        async with self.pool.connection() as db:
            one = "and a.event_id = %s" if event_id else ""
            args = (self.settings.home, event_id, limit) if event_id else (self.settings.home, limit)
            return await (await db.execute(f"select a.* from actions a join events e on e.id = a.event_id where e.home = %s {one} order by a.id desc limit %s", args)).fetchall()

    async def events(self, limit=100):
        async with self.pool.connection() as db:
            return await (await db.execute("select * from events where home = %s order by id desc limit %s", (self.settings.home, limit))).fetchall()
