"""One path for every event, real or simulated: recorded, gated, given to Muse, and every step recorded and streamed.

Events run one at a time, so the home's one thread never has two runs. Tables: events and actions. What the agent does is
published as it happens, for the HTTP stream.
"""
import asyncio
import collections
import datetime
import json
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
from .settings import Settings, part

TZ = zoneinfo.ZoneInfo("America/Montevideo")
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


def describe(event, moment, facts):
    """The event as Muse reads it. A parent's words pass through rules.parent_text so they can't pose as the system."""
    payload = event["payload"]
    when = moment.strftime("%A %Y-%m-%d %H:%M")
    night = moment.hour >= 22 or moment.hour < 7
    began = (moment - datetime.timedelta(hours=7)).date()
    rota = (f"The night that belongs to this moment began on the evening of {began}. Rota for that night: {on_duty(moment)} is on duty"
            if moment.hour < 7 or moment.hour >= 22 else
            f"Rota: last night was {on_duty(moment - datetime.timedelta(days=1))}'s, tonight is {on_duty(moment)}'s")
    head = f"[{when}, {'night' if night else 'day'}. {rota}, unless a plan you remember says otherwise.]"
    remembered = "\n".join(f"- {k}: {v}" for k, v in facts.items()) or "- nothing yet"
    if event["type"] == "message":
        body = f"{payload.get('from', 'A parent')} wrote to you on {payload.get('channel', 'the phone')}: {rules.parent_text(payload.get('text', ''))}"
    elif event["type"] == "state_changed":
        body = f"Home sensor: {payload.get('entity_id')} changed to {payload.get('state')}."
    elif event["type"] == "sound":
        body = f"Sound heard in the {payload.get('room', 'house')}: {payload.get('kind')}."
    elif event["type"] == "wake":
        body = f"You asked to be woken now, to: {payload.get('why')}. Nobody else knows about this. Look at how things are now and decide."
    elif event["type"] == "schedule":
        body = f"Scheduled check: {payload.get('name')}. Nobody asked for anything. Decide if anything is worth doing now."
    else:
        body = f"Event {event['type']}: {json.dumps(payload, ensure_ascii=False)}"
    return f"{head}\nWhat you remember:\n{remembered}\n\n{body}"


class Core:
    def __init__(self, settings=None, model=None):
        self.settings = settings or Settings()
        self.model = model
        self.queue = asyncio.Queue()
        self.subscribers = set()
        self.recent = collections.deque(maxlen=500)
        self.seq = 0
        self.mock = None
        self.channel = None
        self.moment = None
        self.heard = ""

    def now(self):
        """The moment the agent is living: the current event's, which a simulated event sets."""
        return self.moment or datetime.datetime.now(TZ)

    async def __aenter__(self):
        s = self.settings
        self.pool = AsyncConnectionPool(s.db_url, min_size=1, max_size=6, open=False,
                                        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0})
        await self.pool.open()
        saver, self.store = AsyncPostgresSaver(self.pool), AsyncPostgresStore(self.pool)
        await saver.setup()
        await self.store.setup()
        async with self.pool.connection() as db:
            for statement in SCHEMA:
                await db.execute(statement)
        if part("home") != "real":
            self.mock = MockHome(s.mock_port).start()
        self.channel = tools_mod.RealChannel(s) if part("channel") == "real" else tools_mod.MockChannel()
        memory, self.log = tools_mod.baby_log(s, self.now)
        self.tools = [*await tools_mod.home_tools(s, self.mock), *tools_mod.channel_tools(self.channel, s, self.log, lambda: self.heard),
                      *tools_mod.log_tools(self.log, memory), *tools_mod.memory_tools(self.store, s.home),
                      *tools_mod.next_feed_tool(self.log, self.now), *tools_mod.coach_tool(), *tools_mod.wake_tool(self)]
        self.agent = agent_mod.build(self.model or agent_mod.muse(), self.tools, saver, self.store)
        self.config = {"configurable": {"thread_id": f"home-{s.home}"}, "recursion_limit": 24}
        self.worker = asyncio.create_task(self.work())
        return self

    async def __aexit__(self, *exc):
        self.worker.cancel()
        if self.mock:
            self.mock.stop()
        await self.pool.close()

    def publish(self, kind, **fields):
        self.seq += 1
        item = {"seq": self.seq, "kind": kind, "at": time.time(), **fields}
        self.recent.append(item)
        for subscriber in self.subscribers:
            subscriber.put_nowait(item)
        return item

    async def add_wake(self, moment, why):
        async with self.pool.connection() as db:
            await db.execute("insert into wakes (home, at, why) values (%s, %s, %s)", (self.settings.home, moment, why))

    async def wakes(self):
        async with self.pool.connection() as db:
            return await (await db.execute("select * from wakes where home = %s and not fired order by at", (self.settings.home,))).fetchall()

    async def fire_wakes(self, moment=None):
        """Dispatch every wake that is due at this moment, once each."""
        moment = moment or datetime.datetime.now(TZ)
        async with self.pool.connection() as db:
            due = await (await db.execute("update wakes set fired = true where home = %s and not fired and at <= %s returning why, at",
                                          (self.settings.home, moment))).fetchall()
        return [await self.dispatch("wake", {"why": row["why"]}, source="wake", at=row["at"].isoformat()) for row in due]

    async def dispatch(self, type, payload=None, source="simulator", at=None, ask=False):
        """The one way in. at is an ISO time for a simulated moment, the agent then lives that moment. ask holds what is
        said on the Echo, for the one waiting there."""
        moment = datetime.datetime.fromisoformat(at).astimezone(TZ) if at else datetime.datetime.now(TZ)
        event = {"type": type, "payload": payload or {}, "source": source, "moment": moment, "ask": ask}
        async with self.pool.connection() as db:
            row = await (await db.execute("insert into events (home, happened_at, type, source, payload) values (%s, %s, %s, %s, %s) returning id",
                                          (self.settings.home, moment, type, source, Jsonb(event["payload"])))).fetchone()
        event["id"] = row["id"]
        if type == "state_changed" and self.mock:
            self.mock.set_state(event["payload"].get("entity_id"), event["payload"].get("state"))
        self.publish("event", event_id=event["id"], type=type, source=source, payload=event["payload"], happened_at=moment.isoformat())
        done = asyncio.get_running_loop().create_future()
        event["done"] = done
        await self.queue.put(event)
        return event["id"], done

    async def work(self):
        while True:
            event = await self.queue.get()
            outcome = await self.run(event)
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
        self.channel.hold = [] if event["ask"] else None
        try:
            if event["type"] == "message":
                stopped = await self.gated(event)
                if stopped:
                    return stopped
            return await self.decide(event, started)
        except Exception as failure:  # one bad event never stops the agent: it is on record, and the next one runs
            self.publish("error", event_id=event["id"], error=f"{type(failure).__name__}: {str(failure)[:300]}")
            return await self.finish(event, "failed", f"{type(failure).__name__}: {str(failure)[:300]}")

    async def gated(self, event):
        """Red flags and medical questions never reach Muse. The fixed line goes out and the thread learns it happened."""
        text = event["payload"].get("text", "")
        verdict = await asyncio.to_thread(safety.gate, text, self.screen)
        if not verdict:
            return None
        kind, line = verdict
        sender = event["payload"].get("from")
        to = list(tools_mod.PARENTS) if kind != "medical" or sender not in tools_mod.PARENTS else [sender]
        for parent in to:
            await asyncio.to_thread(self.channel.send, parent, line)
            await self.record(event["id"], "gate_message", {"to": parent, "kind": kind}, line)
        if self.channel.hold is not None:
            self.channel.hold.append(line)
        self.publish("gate", event_id=event["id"], gate=kind, to=to, text=line)
        await self.agent.aupdate_state(self.config, {"messages": [
            HumanMessage(f"{sender or 'A parent'} wrote: {rules.parent_text(text)}"),
            AIMessage(f"The safety gate answered this with its fixed {kind} line to {', '.join(to)}. I did not answer it.")]}, as_node="model")
        return await self.finish(event, "gated", kind)

    screen = None

    async def decide(self, event, started):
        await agent_mod.repair(self.agent, self.config)
        text = describe(event, event["moment"], await tools_mod.facts(self.store, self.settings.home))
        pending, final, used, calls = {}, "", 0, []
        async for update in self.agent.astream({"messages": [HumanMessage(text)]}, self.config, stream_mode="updates"):
            for step in update.values():
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
                        calls.append((call["name"], call["args"], result))
                        await self.record(event["id"], call["name"], call["args"], result)
                        self.publish("tool_result", event_id=event["id"], tool=call["name"], arguments=call["args"], result=result[:600])
        line = tools_mod.record_line(calls)
        if final:  # Muse's own closing line can contradict what it did (Nov 3), so it is kept apart and the record is the calls
            await self.record(event["id"], "muse_note", {}, final)
        self.publish("decision", event_id=event["id"], text=line, note=final, seconds=round(time.monotonic() - started, 1), tokens=used)
        return await self.finish(event, "done", line)

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

    async def actions(self, event_id=None, limit=200):
        async with self.pool.connection() as db:
            one = "and a.event_id = %s" if event_id else ""
            args = (self.settings.home, event_id, limit) if event_id else (self.settings.home, limit)
            return await (await db.execute(f"select a.* from actions a join events e on e.id = a.event_id where e.home = %s {one} order by a.id desc limit %s", args)).fetchall()

    async def events(self, limit=100):
        async with self.pool.connection() as db:
            return await (await db.execute("select * from events where home = %s order by id desc limit %s", (self.settings.home, limit))).fetchall()
