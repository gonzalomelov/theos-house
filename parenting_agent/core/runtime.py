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
ALARM_HOURS = 24
OWN_MOVE_S = 60
# A wake to get something ready means nothing after its moment has passed, unlike a reminder.
PREPARES = re.compile(r"warm|bottle|feed|mamadera|calent|toma|dehumid|deshumid|humid", re.I)
ABOUT_THE_AIR = re.compile(r"dehumid|deshumid|humid", re.I)
ENDED = {"warmer_off_at": {"es": "El calentador de mamaderas se apagó solo a las {at}.", "en": "The bottle warmer turned itself off at {at}."},
         "vacuum_off_at": {"es": "La aspiradora terminó y volvió a su base a las {at}.", "en": "The vacuum finished and went back to its base at {at}."}}
GAP_TOLD = re.compile(r"\d+\s*(?:h|hs|hours?|horas?)\b|\bfeeds?\b|\btomas?\b|comi[oó]", re.I)
FOLLOW_UP = "alarm_follow_up"
FOLLOW_UP_MIN = 40
RECHECK_ROOM_H = 1
CAMERA_OFF = {"es": "La cámara del cambiador ve que ninguna mano está sobre Theo. Poné una mano sobre él.", "en": "The changing table camera sees no hand on Theo. Please keep a hand on him."}
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


def rota_note(event, moment, facts):
    """Who really covered last night, from the record, for a check after a night changed by hand. Muse says it this way."""
    last_night = night_of(moment) - datetime.timedelta(days=1)
    if event["type"] != "schedule" or tools_mod.duty_key(last_night) not in facts:
        return None
    last, usual = facts[tools_mod.duty_key(last_night)], on_duty(moment - datetime.timedelta(days=1))
    said = f"Last night {last} was on duty" + (f", in place of {usual}, changed by hand for that night only" if last != usual else "")
    if tools_mod.duty_key(night_of(moment)) in facts:
        return f"{said}. Tonight {who_is_on(moment, facts)} is on, a parent already said so: don't ask again."
    return f"{said}. The rota alone gives tonight to {who_is_on(moment, facts)}: ask whether that stands."


def today_note(event, moment, facts):
    """What was remembered for today, so a morning check can't skip an appointment."""
    if event["type"] != "schedule" or event["payload"].get("name") != "morning":
        return None
    names = [str(moment.date()), moment.strftime("%A").lower(), {"Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles", "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo"}[moment.strftime("%A")]]
    found = [f"{k}: {v}" for k, v in facts.items() if not k.startswith(("on_duty", "duty_note", "hand_", "feed_gap", "fever", "alarm_")) and any(n in str(v).lower() for n in names)]
    return "Remembered for today, name it with its time: " + "; ".join(found) + "." if found else None


def alarm_note(event, facts):
    """What the gate or an emergency set off since the last check, so a check can't read as if the night was quiet."""
    if event["type"] != "schedule":
        return None
    found = [v for k, v in sorted(facts.items()) if k.startswith("alarm_")]
    return "Since the last check, these happened, say them plainly in one line to each parent, with the time and the words in quotes, and no advice: " + " ".join(found) if found else None


def describe(event, moment, facts, feed=None, lang="es", extra=()):
    """The event as Muse reads it. A parent's words pass through rules.parent_text so they can't pose as the system."""
    payload = event["payload"]
    when = moment.strftime("%A %Y-%m-%d %H:%M")
    night = is_night(moment)
    notes = [f"Write for people in {'English' if lang == 'en' else 'Rioplatense Spanish'}.", *timed_lines(moment, facts), feed_line(moment, feed), rota_note(event, moment, facts), today_note(event, moment, facts), alarm_note(event, facts), *extra]
    facts = {k: v for k, v in facts.items() if k not in ("warmer_off_at", "vacuum_off_at", "feed_gap_told", "language") and not k.startswith("hand_")}
    rota = (f"The night that belongs to this moment began on the evening of {night_of(moment)}. On duty that night: {who_is_on(moment, facts)}"
            if night else
            f"On duty: last night {who_is_on(moment - datetime.timedelta(days=1), facts)}, tonight ({night_of(moment)}) {who_is_on(moment, facts)}")
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
        body = f"You asked to be woken now, to: {payload.get('why')}.{late} Nobody else knows about this. Look at how things are now and decide."
    elif event["type"] == "schedule":
        body = f"Scheduled check: {payload.get('name')}. Nobody asked for anything. Decide if anything is worth doing now."
    elif event["type"] == "camera":
        body = f"{payload.get('model', 'A camera model')} at {payload.get('camera')}: {payload.get('saw')}. This came from a recording, computed earlier."
        if payload.get("verdict") == "off":
            body += " No hand on the baby at the changing table is the danger this camera watches for. Tell the parent on duty now, in one short line, to keep a hand on him."
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


def unheard_cry(event, calls):
    if event["type"] != "sound" or "cry" not in str(event["payload"].get("kind", "")).lower():
        return False
    return not any(tool == "notify" and (result or "").startswith("Sent") for tool, _, result in calls)


STARTS = {"Tapo P110 - Bottle Warmer": ("warmer_off_at", "It turns itself off", 30), "vacuum": ("vacuum_off_at", "It finishes and docks", 60)}


def started(calls):
    """What this event turned on, and whether anyone was told."""
    told = any(tool == "notify" and (result or "").startswith("Sent") for tool, _, result in calls)
    return not told and any((tool == "HassTurnOn" and arguments.get("name") in STARTS or tool == "HassVacuumStart") and not tools_mod.FAILED.match(result or "")
                            for tool, arguments, result in calls)


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
        self.tools = [*await tools_mod.home_tools(s, self.mock, lambda: self.current, self.moved, self.held_by_hand),
                      *tools_mod.channel_tools(self.channel, s, self.log, lambda: self.heard, self.night_check, self.claims, self.note_said),
                      *tools_mod.log_tools(self.log, memory), *tools_mod.memory_tools(self.store, s.home), *tools_mod.duty_tool(self.store, s.home, self.duty_set),
                      *tools_mod.next_feed_tool(self.log, self.now), *tools_mod.coach_tool(), *tools_mod.recipe_tool(), *tools_mod.vacuum_tool(s, self.mock), *tools_mod.wake_tool(self)]
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

    def note_said(self, parent, text):
        self.last_said = text

    async def night_check(self, parent, emergency):
        """Why this message can't wake this parent, or None. At night only the parent on duty, whoever wrote to the agent, or an emergency."""
        moment = self.now()
        if emergency or not is_night(moment) or parent == self.sender or self.follow_up or parent == self.duty_told:
            return None
        duty = who_is_on(moment, await tools_mod.facts(self.store, self.settings.home))
        if parent == duty:
            return None
        return (f"Refused, nothing was sent: it is the night and {duty} is on duty, so {parent} sleeps. If the plan changed, call set_on_duty first. "
                "If this is a danger to someone's life or the house, send it with emergency true.")

    async def duty_set(self, day, parent):
        """Nobody gets a night on someone else's word without hearing it, even at 3: they are the one the next cry reaches, and they can say no.
        A parent taking a night themself is told to the other, or at night kept for the morning so the other can sleep."""
        moment = self.now()
        other = next(p for p in tools_mod.PARENTS if p != self.sender) if self.sender in tools_mod.PARENTS else None
        if not other:
            return ""
        if parent == other:
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
            return f" {how} at {until:%H:%M}. The parent on duty hears from you that it is on, and until when."
        if short in ("HassTurnOff", "HassVacuumReturnToBase") and (name in STARTS or short == "HassVacuumReturnToBase"):
            key = STARTS[name][0] if name in STARTS else "vacuum_off_at"
            await self.store.adelete(namespace, key)
            if key == "warmer_off_at":
                self.warm_until = None
        return ""

    def by_hand(self, entity, state):
        """A plug that changed with no call from the agent, and not because it ended by itself."""
        name = HAND.get(entity)
        if not name or state not in ("on", "off") or time.monotonic() - self.own.get(name, -OWN_MOVE_S * 2) < OWN_MOVE_S:
            return False
        ended = "Warmer" in name and state == "off" and self.warm_until and self.now() >= self.warm_until - datetime.timedelta(minutes=2)
        return not ended

    @staticmethod
    def hand_key(name):
        return "hand_" + re.sub(r"\W+", "_", name)[:50]

    async def note_hand(self, event):
        """Someone switched a plug: it is held for a while, and Muse hears it as a person's choice."""
        payload, moment = event["payload"], event["moment"]
        if not self.by_hand(payload.get("entity_id"), payload.get("state")):
            return
        name = HAND[payload["entity_id"]]
        until = moment + datetime.timedelta(hours=HAND_HOLD_H)
        await self.store.aput((*tools_mod.FACTS, self.settings.home), self.hand_key(name),
                              {"value": f"A person switched {name} {payload['state']} by hand at {moment:%H:%M}, held until {until.isoformat()}"})
        event["hand"] = name
        if "Warmer" in name and payload.get("state") == "on":  # the plug ends by itself whoever started it, and the parent hears it the same way
            key, _, minutes = STARTS[name]
            ends = moment + datetime.timedelta(minutes=minutes)
            await self.store.aput((*tools_mod.FACTS, self.settings.home), key, {"value": ends.isoformat()})
            await self.add_wake(ends, f"device_end:{key}:{ends.isoformat()}")
        event["note"] = (f"A person switched {name} {payload['state']} by hand just now. It stays that way for {HAND_HOLD_H} hours unless a parent asks. "
                         "Tell the parent on duty in one short line, or ask them. At night, set quiet.")

    async def held_by_hand(self, short, arguments):
        """A plug a person just switched isn't switched back by Muse on its own. The vacuum cleans by itself only with nobody home."""
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
        found = await self.store.aget((*tools_mod.FACTS, self.settings.home), self.hand_key(name))
        if not found:
            return None
        until = datetime.datetime.fromisoformat(found.value["value"].rsplit(" ", 1)[-1])
        if self.now() >= until:
            await self.store.adelete((*tools_mod.FACTS, self.settings.home), self.hand_key(name))
            return None
        return f"Refused: a person switched {name} by hand, so it stays until {until:%H:%M} unless a parent asks. Tell the parent on duty or ask them."

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
        if safety.CANT_KEEP.search(text):
            return "Refused, nothing was sent: that isn't yours to promise. Checks still go out, and at night only the parent on duty is woken. Say what will happen."
        if safety.WRONG_NUMBER.search(text):
            return "Refused, nothing was sent: the home is in Uruguay and the emergency number is 911."
        if safety.JARGON.search(text):
            return "Refused, nothing was sent: write like a friend, without words such as rota or per. Say whose night it is, in plain words."
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
            alarm = re.match(r"alarm_(\d{12})$", key)
            if alarm and datetime.datetime.strptime(alarm.group(1), "%Y%m%d%H%M").replace(tzinfo=TZ) < moment - datetime.timedelta(hours=ALARM_HOURS):
                await self.store.adelete((*tools_mod.FACTS, self.settings.home), key)
                del facts[key]
        return facts

    async def add_wake(self, moment, why):
        if not why.startswith("device_end:"):
            self.reminder_set = True
        async with self.pool.connection() as db:
            if ABOUT_THE_AIR.search(why):  # the home's own check on the dehumidifier and Muse's reminder often land together (Nov 3)
                near = await (await db.execute("select why from wakes where home = %s and not fired and at between %s and %s",
                                               (self.settings.home, moment - datetime.timedelta(minutes=2), moment + datetime.timedelta(minutes=2)))).fetchall()
                if any(ABOUT_THE_AIR.search(row["why"]) for row in near):
                    return
            await db.execute("insert into wakes (home, at, why) values (%s, %s, %s)", (self.settings.home, moment, why))

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
            elif PREPARES.search(row["why"]):
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
        self.follow_up = event["type"] == "wake" and str(event["payload"].get("why", "")).startswith(FOLLOW_UP)
        self.duty_told = None
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
            if event["type"] == "message":
                stopped = await self.gated(event)
                if stopped:
                    return stopped
            return await self.attempts(event, started)
        except Exception as failure:  # one bad event never stops the agent: it is on record, and the next one runs
            self.publish("error", event_id=event["id"], error=f"{type(failure).__name__}: {str(failure)[:300]}")
            return await self.finish(event, "failed", f"{type(failure).__name__}: {str(failure)[:300]}")

    retry_waits = RETRY_WAITS

    async def attempts(self, event, started):
        """The brain can be away for a moment. It gets asked again, and if it stays away, what can't wait goes out without it."""
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
        else:
            return []
        told = []
        for parent in to:
            try:
                await asyncio.to_thread(self.channel.send, parent, line)
                await self.record(event["id"], "no_brain_message", {"to": parent}, line)
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
            await asyncio.to_thread(self.channel.send, duty, safety.because(sender, text, rules.NO_ADVICE[lang], lang), True)
            await self.record(event["id"], "gate_message", {"to": duty, "kind": kind, "quiet": True}, "Told quietly.")
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
        await self.record(event["id"], "fever_logged", {"by": sender}, "In the log.")
        await self.store.aput((*tools_mod.FACTS, self.settings.home), "fever_reported", {"value": f'{sender} reported at {moment:%A %H:%M}: "{safety.sign_of(text)}". Both parents were told to call.'})

    async def keep_alarm(self, event, who, text):
        """An alarm goes in the log and in memory with the words that raised it, nothing else from the message. The next check says it once, and
        before that Muse asks how Theo is."""
        moment, sign = event["moment"], safety.sign_of(text)
        try:
            await asyncio.to_thread(self.log.add, "note", {"text": f'Alarm at {moment:%H:%M}, {who}: "{sign}"'}, moment.isoformat())
        except Exception as failure:
            self.publish("error", event_id=event["id"], error=f"{type(failure).__name__}: {str(failure)[:300]}")
        await self.store.aput((*tools_mod.FACTS, self.settings.home), f"alarm_{moment:%Y%m%d%H%M}", {"value": f'At {moment:%A %H:%M} {who} wrote "{sign}", and both parents were told.'})
        await self.add_wake(moment + datetime.timedelta(minutes=FOLLOW_UP_MIN), f'{FOLLOW_UP}: at {moment:%H:%M} {who} wrote "{sign}". Ask {who if who in tools_mod.PARENTS else "both parents"} and whoever is on duty, in one short line, how Theo is now and if they reached a doctor. Quote nothing else, and no advice.')

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
        await asyncio.to_thread(self.channel.send, duty, line, True)
        await self.record(event["id"], "notify", {"parent": duty, "text": line, "quiet": True}, f"Sent to {duty}.")
        self.publish("tool_result", event_id=event["id"], tool="notify", arguments={"parent": duty, "text": line, "quiet": True}, result=f"Sent to {duty}.")
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
    last_said = None  # the words of the last message that went out
    follow_up = False  # for this event: asking how Theo is after an alarm
    reminder_set = False  # for this event: a promise needs a reminder behind it
    after_start = False  # for this event: the first reading after a restart
    duty_told = None  # for this event: who has to hear about a duty change

    async def decide(self, event, started):
        self.reminder_set = False
        self.after_start = self.quiet_start(event)
        await agent_mod.repair(self.agent, self.config)
        moment = event["moment"]
        facts = await self.tidy_facts(moment)
        self.feed = await asyncio.to_thread(self.current_feed, moment)
        extra = [event["note"]] if event.get("note") else []
        if event["type"] == "message" and safety.reports_feed(self.heard):  # the feed goes in the log first: it may close the gap, and no alarm goes out over it
            self.feed = None
            extra.append("This parent is telling you about a feed. Log it first, then answer from what the log shows.")
        extra += await self.raise_gap(event, moment, facts)
        extra += self.log_note(event, moment)
        extra += self.reading_note(event, moment)
        self.warm_until = datetime.datetime.fromisoformat(facts["warmer_off_at"]) if "warmer_off_at" in facts else None
        text = describe(event, moment, facts, self.feed, self.settings.lang, extra)
        if event.get("again"):
            text += "\n\nAn earlier try at this event was cut off. Some of it may already be done, so check before repeating anything."
        final, used, calls = "", 0, []

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
                            if call["name"] == "notify" and result.startswith("Sent") and self.last_said:  # the record says what went out, which a check may have tidied
                                arguments = {**arguments, "text": self.last_said}
                            calls.append((call["name"], arguments, result))
                            await self.record(event["id"], call["name"], arguments, result)
                            self.publish("tool_result", event_id=event["id"], tool=call["name"], arguments=arguments, result=result[:600])
        await think(text)
        if unanswered(event, calls):  # Muse sometimes leaves a parent's question with no reply at all (Nov 3, 1 of 3 runs). Ask once.
            await think(f"{self.sender} wrote to you and has received nothing from you. Answer them with notify, in one short line.")
        elif unheard_cry(event, calls):  # the same with a cry: once the warmer went on and nobody was told (Nov 3)
            await think("Theo is crying and no parent has been told. Tell the parent on duty with notify, in one short line.")
        for nudge in await self.loose_ends(event, facts, calls):
            await think(nudge)
        reading = safety.unsafe_room(event["payload"]) if event["type"] == "state_changed" else None
        if reading is not None and not any(tool == "notify" and (result or "").startswith("Sent") for tool, _, result in calls):  # asked and still nothing (Nov 3, 1 of 6 runs)
            await self.room_line(event, reading)
        if reading is not None and not self.after_start:  # told once and dropped is how a hot room gets forgotten (Nov 3)
            await self.add_wake(moment + datetime.timedelta(hours=RECHECK_ROOM_H), "check Theo's room temperature again: read it, and tell the parent on duty the reading if it is still far out of range")
        if event["type"] == "camera" and event["payload"].get("verdict") == "off" and not any(tool == "notify" and (result or "").startswith("Sent") for tool, _, result in calls):
            duty = who_is_on(moment, facts)
            line = CAMERA_OFF["en" if self.settings.lang == "en" else "es"]
            await asyncio.to_thread(self.channel.send, duty, line)
            await self.record(event["id"], "notify", {"parent": duty, "text": line}, f"Sent to {duty}.")
        if event["type"] == "schedule":  # said once in a check, an alarm is closed: it doesn't come back as new 18 hours later
            for key in [k for k in facts if k.startswith("alarm_")]:
                await self.store.adelete((*tools_mod.FACTS, self.settings.home), key)
        if unanswered(event, calls) or unheard_cry(event, calls):  # asked twice and still nothing: nobody is left waiting on Muse
            for parent in await self.without_brain(event):
                calls.append(("notify", {"parent": parent}, f"Sent to {parent}."))
        if any(tool == "notify" and arguments.get("emergency") and (result or "").startswith("Sent") for tool, arguments, result in calls):
            await self.keep_alarm(event, "the agent", " ".join(str(arguments.get("text", "")) for tool, arguments, _ in calls if tool == "notify" and arguments.get("emergency"))[:120])
        line = tools_mod.record_line(calls)
        if final:  # Muse's own closing line can contradict what it did (Nov 3), so it is kept apart and the record is the calls
            final = safety.plain(final)
            await self.record(event["id"], "muse_note", {}, final)
        self.publish("decision", event_id=event["id"], text=line, note=final, seconds=round(time.monotonic() - started, 1), tokens=used)
        return await self.finish(event, "done", line)

    async def room_line(self, event, reading):
        duty = who_is_on(event["moment"], await tools_mod.facts(self.store, self.settings.home))
        line = (f"Theo's room reads {reading:g} degrees. Please check the room, and whether the sensor is right." if self.settings.lang == "en"
                else f"El cuarto de Theo marca {reading:g} grados. Fijate cómo está el cuarto, y si el sensor está bien.")
        for parent in [duty] if is_night(event["moment"]) else list(tools_mod.PARENTS):
            await asyncio.to_thread(self.channel.send, parent, line)
            await self.record(event["id"], "notify", {"parent": parent, "text": line}, f"Sent to {parent}.")

    async def loose_ends(self, event, facts, calls):
        """What must not stay unsaid, whatever Muse decided: each is asked for once."""
        told = any(tool == "notify" and (result or "").startswith("Sent") for tool, _, result in calls)
        asks = []
        if self.after_start:
            return asks
        if started(calls):
            asks.append("You started something and nobody knows. Tell the parent on duty in one short line that it is on and until when. "
                        + ("It is night and they didn't ask, so set quiet." if is_night(event["moment"]) else ""))
        reading = safety.unsafe_room(event["payload"]) if event["type"] == "state_changed" else None
        if reading is not None and not told:
            asks.append(f"Theo's room is at {reading} degrees, which is far out of range, and nobody knows. Tell the parent on duty the reading and to check the room, and by day the other parent too. No medical advice.")
        if event["type"] == "schedule":
            name = event["payload"].get("name")
            if not told and self.checked_today.get(name) != event["moment"].date():
                asks.append(f"This is today's {name} check and nobody has heard from you. Do what it asks for, with notify.")
            self.checked_today[name] = event["moment"].date()
        if event.get("hand") and not told:
            asks.append(f"A person switched {event['hand']} by hand and nobody has heard from you. Tell the parent on duty in one short line, or ask them. At night, set quiet.")
        said_to = {arguments.get("parent") for tool, arguments, result in calls if tool == "notify" and (result or "").startswith("Sent")}
        if self.duty_told and self.duty_told not in said_to:
            asks.append(f"{self.sender} changed who is on duty and {self.duty_told} doesn't know. Tell {self.duty_told} in one line, so they can say if it's wrong.")
        if event["type"] == "camera" and event["payload"].get("verdict") == "off" and not told:
            asks.append("No hand is on the baby at the changing table and nobody has heard from you. Tell the parent on duty in one short line to keep a hand on him.")
        if self.follow_up and not told:
            asks.append("You were woken to ask how Theo is after an alarm, and nobody has heard from you. Ask them now, in one short line.")
        if event["type"] == "schedule" and any(k.startswith("alarm_") for k in facts) and not safety.ALARM_TOLD.search(" ".join(str(arguments.get("text", "")) for tool, arguments, _ in calls if tool == "notify")):
            asks.append("Your message left out what happened since the last check. Say it plainly in one short line, with the time, no advice.")
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
