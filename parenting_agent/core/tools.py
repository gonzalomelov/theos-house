"""One interface per thing the agent touches, real or mock by one setting (settings.part).

Home: Home Assistant's own MCP tools, from the real server or the mock one. Channel: a message to one parent, or a sentence
on the kitchen Echo. Baby log: Baby Buddy, or the local log on a simulated Theo. Memory: facts that outlive the trimmed
history, in LangGraph's PostgreSQL store.
"""
import asyncio
import datetime
import json
import os
import re
import time
from pathlib import Path

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from ..agent import memory as memory_module
from ..agent import rules
from ..agent.memory import LocalBabyLog, Memory
from ..agent.tools import core_tools
from ..channels.telegram import TelegramMessenger
from ..house import HomeAssistant
from ..house_tools import ECHO_ANNOUNCE, ECHO_PLAYER, MAX_ANNOUNCE_VOLUME
from ..rhythm import patterns
from . import safety
from .settings import part

HOME_TOOLS = ("GetLiveContext", "HassTurnOn", "HassTurnOff", "HassVacuumStart", "HassVacuumReturnToBase", "HassListAddItem")
NAMED = ("HassTurnOn", "HassTurnOff")
# These take no device name, so on the real home they stay out until PA_ALLOWED_DEVICES names them.
GATED = {"HassVacuumStart": "vacuum", "HassVacuumReturnToBase": "vacuum", "HassListAddItem": "shopping"}
LOG_TOOLS = ("log_baby_event", "read_baby_log", "baby_summary")
PARENTS = {"gonza": "TELEGRAM_CHAT_ID", "ceci": "TELEGRAM_CECI_CHAT_ID"}
FACTS = ("home", "facts")
WHEN = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2})?\b|\b\d{1,2}:\d{2}\b")


def text_of(result):
    """The text inside what an MCP tool answers."""
    if isinstance(result, list):
        return " ".join(str(block.get("text", block)) if isinstance(block, dict) else str(block) for block in result)
    return str(result)


class MockChannel:
    """Holds what would have been sent, for the simulator and the tests."""
    hold = None  # a list while someone waits at the Echo for an answer: it is spoken by Home Assistant, not announced

    def __init__(self):
        self.sent = []

    def send(self, parent, text):
        self.sent.append({"to": parent, "text": text, "at": time.time()})

    def echo(self, text):
        if self.hold is not None:
            self.hold.append(text)
        self.sent.append({"to": "echo", "text": text, "at": time.time()})


class RealChannel:
    hold = None

    def __init__(self, settings):
        self.telegram = TelegramMessenger(os.environ.get("TELEGRAM_BOT_TOKEN"))
        self.ha = HomeAssistant(settings.ha_url, settings.ha_token)

    def send(self, parent, text):
        self.telegram.send(os.environ[PARENTS[parent]], text)

    def echo(self, text):
        if self.hold is not None:
            self.hold.append(text)
            return
        self.ha.service("media_player.volume_set", ECHO_PLAYER, {"volume_level": min(0.2, MAX_ANNOUNCE_VOLUME)})
        self.ha.service("notify.send_message", ECHO_ANNOUNCE, {"message": text[:300]})


def baby_log(settings, clock):
    if part("log") == "real":
        from ..agent.babybuddy import BabyBuddyLog
        return None, BabyBuddyLog.from_config({"child": os.environ.get("PA_BABY_CHILD", "test-baby")})
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    memory_module.now = lambda: clock().isoformat(timespec="seconds")  # the simulated log lives the simulated moment
    memory = Memory(Path(settings.data_dir) / f"mock-log-{settings.home}.sqlite")
    return memory, LocalBabyLog(memory)


async def home_tools(settings, mock):
    """Home Assistant's own tools under their short names. Only allowed devices can be switched."""
    real = part("home") == "real"
    url = settings.ha_url + "/api/mcp" if real else mock.url
    headers = {"Authorization": "Bearer " + settings.ha_token} if real else {}
    client = MultiServerMCPClient({"home": {"transport": "streamable_http", "url": url, "headers": headers}})
    found = {t.name.rsplit("__", 1)[-1]: t for t in await client.get_tools()}

    def wrap(short, tool):
        async def call(**arguments):
            if short in NAMED and arguments.get("name") not in settings.devices:
                return f"Refused: you may only switch {', '.join(settings.devices)}."
            return text_of(await tool.ainvoke({k: v for k, v in arguments.items() if v is not None}))
        return StructuredTool.from_function(coroutine=call, name=short, description=tool.description or short, args_schema=tool.args_schema)
    usable = [short for short in HOME_TOOLS if not (real and short in GATED and GATED[short] not in settings.devices)]
    return [wrap(short, found[short]) for short in usable if short in found]


def channel_tools(channel, settings):
    def notify(parent: str, text: str) -> str:
        """Send one message to one parent's phone. parent is gonza or ceci. It wakes them at night."""
        if parent not in PARENTS:
            return "Refused: parent is gonza or ceci."
        out, why = safety.outbound(text, settings.lang)
        if why:
            return why
        channel.send(parent, out)
        return f"Sent to {parent}."

    def say_on_echo(text: str) -> str:
        """Say one sentence out loud on the kitchen Echo, at low volume. Everyone in the kitchen hears it."""
        out, why = safety.outbound(text, settings.lang)
        if why:
            return why
        channel.echo(out)
        return "Said on the kitchen Echo."
    return [StructuredTool.from_function(notify), StructuredTool.from_function(say_on_echo)]


def log_tools(log, memory):
    """The baby log tools the old agent already had, with the same checks."""
    tools = core_tools(memory, log, LOG_TOOLS, remember_keys=())

    def wrap(name):
        tool = tools.items[name]

        def call(**arguments):
            status, result = tools.run(name, arguments)
            return str(result) if status == "ran" else f"{status}: {result}"
        return StructuredTool.from_function(func=call, name=name, description=tool.description, args_schema=tool.parameters)
    return [wrap(name) for name in LOG_TOOLS]


def next_feed_tool(log, clock):
    def next_feed() -> str:
        """When the next feed is expected, from the gaps between the last feeds in the baby log. An estimate that can be
        more than an hour off, for getting things ready, never to wake anyone."""
        rows = [{**e, "ref": i, "time": e["ts"]} for i, e in enumerate(log.entries("feeding", None, 50))]
        estimate = patterns.next_feed(rows, clock())
        if not estimate:
            return "Not enough feeds in the log to estimate."
        return json.dumps({"expected_at": estimate["at"].isoformat(timespec="minutes"), "usual_gap_min": estimate["gap_min"], "last_feed": rows[-1]["ts"]})
    return [StructuredTool.from_function(next_feed)]


def coach_tool():
    def start_car_seat_coach(parent: str, lang: str = "es") -> str:
        """Start the car seat coach for the parent asking for help installing the car seat. It runs on their glasses, sees
        through their camera and says each step itself from the seat's manual. lang is es or en."""
        if parent not in PARENTS:
            return "Refused: parent is gonza or ceci."
        return ("The coach is running on their glasses and speaks each step itself. Do not give car seat steps or advice of "
                "your own, not even in a message.")
    return [StructuredTool.from_function(start_car_seat_coach)]


def wake_tool(core):
    async def wake_me_at(at: str, why: str) -> str:
        """Ask to get an event later, to do something at that moment that nobody will ask for. at is an ISO time with its
        offset, why is what you meant to do then."""
        try:
            moment = datetime.datetime.fromisoformat(at)
        except ValueError:
            return "Refused: at is an ISO time, for example 2026-11-04T00:40:00-03:00."
        await core.add_wake(moment, why)
        return f"You will get an event at {moment.isoformat(timespec='minutes')}."
    return [StructuredTool.from_function(coroutine=wake_me_at)]


def memory_tools(store, home):
    namespace = (*FACTS, home)

    async def remember(key: str, value: str) -> str:
        """Keep a fact or a plan for later, it stays when older history is gone. Same key replaces it. Put dates in plans."""
        plain = WHEN.sub(" ", f"{key.replace('_', ' ')} {value}")  # a plan's date is not a code
        if rules.has_secret(plain) or len(value) > 300:
            return "Refused: never a code, a password, a phone number, an email or an address."
        await store.aput(namespace, re.sub(r"\W+", "_", key)[:60], {"value": value})
        return "Remembered."

    async def forget(key: str) -> str:
        """Drop a fact or a plan that no longer holds."""
        await store.adelete(namespace, re.sub(r"\W+", "_", key)[:60])
        return "Forgotten."
    return [StructuredTool.from_function(coroutine=remember), StructuredTool.from_function(coroutine=forget)]


async def facts(store, home):
    return {item.key: item.value["value"] for item in await store.asearch((*FACTS, home), limit=100)}
