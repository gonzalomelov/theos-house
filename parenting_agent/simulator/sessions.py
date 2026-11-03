"""One private home per visitor: its own mock Home Assistant, outbox, baby log, thread and facts, gone when the session ends."""
import asyncio
import datetime
import json
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path

from ..agent.memory import LOG_KINDS, LocalBabyLog, Memory, parse_time
from ..core import tools as tools_mod
from ..core.runtime import Core
from ..core.settings import Settings
from .scenes import BY_ID, FACTS, LOG, START, event, sense_event

IDLE_S = int(os.environ.get("PA_SIM_IDLE_S", "1200"))
MAX_SESSIONS = int(os.environ.get("PA_SIM_MAX_SESSIONS", "12"))
MAX_PER_CLIENT = int(os.environ.get("PA_SIM_MAX_PER_CLIENT", "3"))
MAX_EVENTS = int(os.environ.get("PA_SIM_MAX_EVENTS", "40"))
MAX_TEXT = 280
# One address, across all its sessions, so Start over can't spend Muse without end.
HOUR_S = 3600
ADDRESS_EVENTS = int(os.environ.get("PA_SIM_ADDRESS_EVENTS", "120"))
ADDRESS_SESSIONS = int(os.environ.get("PA_SIM_ADDRESS_SESSIONS", "12"))
HIDDEN_FACTS = ("language", "warmer_off_at", "vacuum_off_at", "feed_gap_told")
DAILY = (((7, 30), "morning"), ((21, 30), "evening"))
HUMIDITY_STEP = 5.0
# A clock press can't outlive a browser's request behind Cloudflare, which gives up at 100 s. What's still running keeps its order.
ADVANCE_WAIT_S = 75
EVICT_IDLE_S = 120  # when every home is taken, the one nobody has touched for this long makes room
DAY_FEED_H, NIGHT_FEED_H = 3, 7.5
SIM_FEED = {"amount_ml": 90, "method": "bottle", "simulated": True}


class Full(Exception):
    pass


class Allowance:
    """How much one address used in the last hour."""
    def __init__(self, limit, clock=time.monotonic):
        self.limit = limit
        self.clock = clock
        self.used = {}

    def take(self, address):
        now = self.clock()
        recent = [at for at in self.used.get(address, ()) if now - at < HOUR_S]
        if len(recent) >= self.limit:
            self.used[address] = recent
            raise Full("address")
        self.used[address] = [*recent, now]

    def left(self, address):
        now = self.clock()
        return max(0, self.limit - sum(1 for at in self.used.get(address, ()) if now - at < HOUR_S))


class SimLog(LocalBabyLog):
    """The local baby log on the simulated clock, so a December night is not clamped to today."""
    def __init__(self, memory, clock):
        super().__init__(memory)
        self.clock = clock

    def now(self):
        return self.clock()

    def add(self, kind, details, ts=None):
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind}, expected one of {', '.join(LOG_KINDS)}")
        current = self.clock()
        moment = parse_time(ts, current.tzinfo) if ts else current
        entry = {"ts": min(moment, current).isoformat(timespec="seconds"), "kind": kind, "details": details}
        with self.memory.lock:
            self.memory.db.execute("insert into baby_log (ts, kind, details) values (?, ?, ?)", (entry["ts"], kind, json.dumps(details)))
            self.memory.db.commit()
        return entry


class SimChannel(tools_mod.MockChannel):
    """The mock outbox, stamped with the simulated moment."""
    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def send(self, parent, text, quiet=False):
        super().send(parent, text, quiet)
        self.sent[-1]["at"] = self.clock().isoformat()

    def echo(self, text):
        super().echo(text)
        self.sent[-1]["at"] = self.clock().isoformat()


class Session:
    def __init__(self, client, model=None, lang="en", allowance=None, opened=None):
        self.allowance = allowance
        self.opened = opened
        self.token = secrets.token_urlsafe(24)
        self.client = client
        self.lang = lang
        self.moment = datetime.datetime.fromisoformat(START)
        self.played = []
        self.said = []
        self.last_said = None
        self.events_used = 0
        self.checks = set()
        self.feeds_on = True
        self.last_seen = time.monotonic()
        self.dir = tempfile.mkdtemp(prefix="sim-")
        self.memory = Memory(Path(self.dir) / "log.sqlite")
        self.log = SimLog(self.memory, self.living)
        self.channel = SimChannel(self.living)
        self.settings = Settings(home="sim-" + secrets.token_hex(8), mock_port=0, data_dir=self.dir, lang=lang,
                                 pool_max=int(os.environ.get("PA_DB_POOL", "3")))
        self.core = Core(self.settings, model=model, channel=self.channel, log=(self.memory, self.log))

    def living(self):
        """The moment of the event running now, which a wake can set earlier than the clock on the page."""
        return self.core.moment or self.moment

    async def start(self):
        await self.core.__aenter__()
        for ts, kind, details in LOG:
            self.seed(ts, kind, details)
        await self.set_lang(self.lang)
        return self

    def seed(self, ts, kind, details):
        with self.memory.lock:
            self.memory.db.execute("insert into baby_log (ts, kind, details) values (?, ?, ?)", (ts, kind, json.dumps(details)))
            self.memory.db.commit()

    async def set_lang(self, lang):
        self.lang = self.settings.lang = lang
        await self.core.store.aput((*tools_mod.FACTS, self.settings.home), "language", {"value": FACTS[lang]})

    async def close(self):
        try:
            await self.core.forget()
        finally:
            await self.core.__aexit__(None, None, None)
            self.memory.db.close()
            shutil.rmtree(self.dir, ignore_errors=True)

    def next_feed(self):
        """When simulated Theo eats next: every few hours by day, one long stretch at night. A parent's logged feed moves it, the log is the only record."""
        last = self.core.last_feed(self.moment) if self.feeds_on else None
        if not last:
            return None
        day = last + datetime.timedelta(hours=DAY_FEED_H)
        return day if 7 <= day.hour < 22 else last + datetime.timedelta(hours=NIGHT_FEED_H)

    async def next_step(self, moment, daily):
        """What happens first on the way to this moment: a daily check, a wake Muse asked for, a feed, or a step of the feed gap ladder."""
        steps = []
        feed = self.next_feed()
        if feed and feed <= moment:
            steps.append((feed, 0, "feed", None))
        for row in await self.core.wakes():
            if row["at"] <= moment:
                steps.append((row["at"].astimezone(self.moment.tzinfo), 1, "wake", None))
        day = self.moment.date()
        while daily and day <= moment.date():
            for (h, m), name in DAILY:
                at = self.moment.replace(year=day.year, month=day.month, day=day.day, hour=h, minute=m, second=0, microsecond=0)
                if self.moment < at < moment and (at.date(), name) not in self.checks:
                    steps.append((at, 2, "check", name))
            day += datetime.timedelta(days=1)
        gap = self.core.gap_due(self.core.last_feed(self.moment), await tools_mod.facts(self.core.store, self.settings.home), self.moment, moment)
        if gap and not (feed and feed <= gap):
            steps.append((gap, 3, "gap", None))
        return min(steps, key=lambda s: s[:2]) if steps else None

    async def settled(self, deadline):
        """Waits for what is running, so the next step reads the log and the wakes it left behind."""
        pending = [v[1] for v in self.core.running.values() if not v[1].done()]
        left = deadline - time.monotonic()
        if pending and left > 0:
            await asyncio.wait(pending, timeout=left)

    async def advance(self, moment, daily=True):
        """The clock moves, one thing at a time and each at its own moment: a wake Muse asked for fires then, not hours late, and nothing is skipped
        by a long jump. A moment from the story skips the daily checks on the way: a judge pressed one thing, and sees that thing."""
        deadline = time.monotonic() + ADVANCE_WAIT_S
        await self.settled(deadline)
        while (step := await self.next_step(moment, daily)):
            at, _, kind, name = step
            self.moment = max(self.moment, at)
            if kind == "feed":
                self.seed(at.isoformat(timespec="seconds"), "feeding", SIM_FEED)
            elif kind == "wake":
                await self.core.fire_wakes(at)
            elif kind == "check":
                self.checks.add((at.date(), name))
                await self.core.dispatch("schedule", {"name": name}, "simulator", at.isoformat())
            else:
                await self.core.dispatch("gap_check", {}, "clock", at.isoformat())
            await self.settled(deadline)
        self.moment = moment
        before = self.humidity()
        self.core.mock.tick(moment)
        after = self.humidity()
        if before is not None and after is not None and abs(after - before) >= HUMIDITY_STEP:  # the room moved: the sensor says so, as it does at home
            await self.core.dispatch("state_changed", {"entity_id": "sensor.nursery_climate_humidity", "state": str(after)}, "simulator", moment.isoformat())

    def humidity(self):
        try:
            return float(self.core.mock.state("sensor.nursery_climate_humidity"))
        except (TypeError, ValueError):
            return None

    async def play(self, scene_id):
        """A shortcut: it sends its event at its time, or just after the clock if that time has passed. It can be pressed again."""
        scene = BY_ID.get(scene_id)
        if scene is None:
            return None
        self.count()
        if scene_id not in self.played:
            self.played.append(scene_id)
        kind, payload = event(scene, self.lang)
        return await self.send(kind, payload, datetime.datetime.fromisoformat(scene["at"]), daily=False)

    async def sense(self, sense_id):
        """What Meta's model made of a recording, computed earlier, as the event the home would send. None if it wakes nobody."""
        found = sense_event(sense_id, self.lang)
        if found is None:
            return None
        self.count()
        return await self.send(*found)

    async def send(self, kind, payload, at=None, daily=True):
        """One event down the real path. The clock only moves forward. A daily check runs once a day, as it does at home: 0 means it already ran."""
        target = max(self.moment + datetime.timedelta(minutes=1), at or self.moment)
        if kind == "schedule":
            check = (target.date(), payload["name"])
            if check in self.checks:
                return 0
            self.checks.add(check)
        await self.advance(target, daily)
        event_id, _ = await self.core.dispatch(kind, payload, "simulator", self.moment.isoformat())
        if kind == "message" and event_id != self.last_said:
            self.last_said = event_id
            self.said.append({"from": payload["from"], "text": payload["text"], "channel": payload["channel"], "at": self.moment.isoformat()})
        return event_id

    async def write(self, parent, text):
        self.count()
        return await self.send("message", {"from": parent, "channel": "the phone", "text": text})

    async def event(self, kind, payload):
        self.count()
        return await self.send(kind, payload)

    def count(self):
        if self.events_used >= MAX_EVENTS:
            raise Full("events")
        if self.allowance:
            self.allowance.take(self.client)
        self.events_used += 1

    async def state(self):
        facts = await tools_mod.facts(self.core.store, self.settings.home)
        return {"clock": self.moment.isoformat(), "lang": self.lang, "played": self.played, "events_left": MAX_EVENTS - self.events_used,
                "starts_left": self.opened.left(self.client) if self.opened else None, "feeds_on": self.feeds_on,
                "home": self.core.mock.snapshot(), "sent": list(self.channel.sent), "said": self.said,
                "facts": {k: v for k, v in facts.items() if k not in HIDDEN_FACTS},
                "log": self.log.entries(limit=8), "seq": self.core.seq}


class Sessions:
    def __init__(self, model=None):
        self.model = model
        self.live = {}
        self.lock = asyncio.Lock()
        self.events = Allowance(ADDRESS_EVENTS)
        self.opened = Allowance(ADDRESS_SESSIONS)

    def get(self, token):
        session = self.live.get(token)
        if session:
            session.last_seen = time.monotonic()
        return session

    async def create(self, client, lang="en"):
        async with self.lock:  # one at a time: PostgreSQL's setup statements must not race
            mine = sorted((s for s in self.live.values() if s.client == client), key=lambda s: s.last_seen)
            if len(mine) >= MAX_PER_CLIENT:
                await self.drop(mine[0].token)
            if len(self.live) >= MAX_SESSIONS:  # a home nobody is touching makes room, so nobody is locked out by a tab left open
                idle = min(self.live.values(), key=lambda s: s.last_seen)
                if time.monotonic() - idle.last_seen < EVICT_IDLE_S:
                    raise Full("sessions")
                await self.drop(idle.token)
            self.opened.take(client)
            session = await Session(client, self.model, lang, self.events, self.opened).start()
            self.live[session.token] = session
            return session

    async def drop(self, token):
        session = self.live.pop(token, None)
        if session:
            await session.close()

    async def sweep(self):
        """Ends what has been idle, which also deletes it."""
        while True:
            await asyncio.sleep(60)
            for token, session in list(self.live.items()):
                if time.monotonic() - session.last_seen > IDLE_S:
                    await self.drop(token)

    async def close(self):
        for token in list(self.live):
            await self.drop(token)
