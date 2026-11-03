"""One interface per thing the agent touches, real or mock by one setting (settings.part).

Home: Home Assistant's own MCP tools, from the real server or the mock one. Channel: a message to one parent, or a sentence
on the kitchen Echo. Baby log: Baby Buddy, or the local log on a simulated Theo. Memory: facts that outlive the trimmed
history, in LangGraph's PostgreSQL store.
"""
import asyncio
import os
import re
import time
from pathlib import Path

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from ..agent import rules
from ..agent.memory import LocalBabyLog, Memory
from ..agent.tools import core_tools
from ..channels.telegram import TelegramMessenger
from ..house import HomeAssistant
from ..house_tools import ECHO_ANNOUNCE, ECHO_PLAYER, MAX_ANNOUNCE_VOLUME
from . import safety
from .settings import part

HOME_TOOLS = ("GetLiveContext", "HassTurnOn", "HassTurnOff", "HassVacuumStart", "HassVacuumReturnToBase")
NAMED = ("HassTurnOn", "HassTurnOff")
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
    def __init__(self):
        self.sent = []

    def send(self, parent, text):
        self.sent.append({"to": parent, "text": text, "at": time.time()})

    def echo(self, text):
        self.sent.append({"to": "echo", "text": text, "at": time.time()})


class RealChannel:
    def __init__(self, settings):
        self.telegram = TelegramMessenger(os.environ.get("TELEGRAM_BOT_TOKEN"))
        self.ha = HomeAssistant(settings.ha_url, settings.ha_token)

    def send(self, parent, text):
        self.telegram.send(os.environ[PARENTS[parent]], text)

    def echo(self, text):
        self.ha.service("media_player.volume_set", ECHO_PLAYER, {"volume_level": min(0.2, MAX_ANNOUNCE_VOLUME)})
        self.ha.service("notify.send_message", ECHO_ANNOUNCE, {"message": text[:300]})


def baby_log(settings):
    if part("log") == "real":
        from ..agent.babybuddy import BabyBuddyLog
        return None, BabyBuddyLog.from_config({"child": os.environ.get("PA_BABY_CHILD", "test-baby")})
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
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
    # The vacuum tools take no device name, so on the real home they stay out until they are allowed by name.
    usable = [short for short in HOME_TOOLS if not (real and short.startswith("HassVacuum") and "vacuum" not in settings.devices)]
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
