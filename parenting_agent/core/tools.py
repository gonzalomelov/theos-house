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
from ..channels.messaging import MessagingError
from ..channels.telegram import TelegramMessenger
from ..channels.whatsapp import WhatsApp
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

    def send(self, parent, text, quiet=False):
        self.sent.append({"to": parent, "text": text, "at": time.time(), **({"quiet": True} if quiet else {})})

    def echo(self, text):
        if self.hold is not None:
            self.hold.append(text)
        self.sent.append({"to": "echo", "text": text, "at": time.time()})


class RealChannel:
    hold = None

    def __init__(self, settings):
        self.telegram = TelegramMessenger(os.environ.get("TELEGRAM_BOT_TOKEN"))
        self.ha = HomeAssistant(settings.ha_url, settings.ha_token)
        self.whatsapp = WhatsApp.from_env(settings.data_dir)

    def by_telegram(self, parent, text, quiet=False):
        self.telegram.send(os.environ[PARENTS[parent]], text, quiet)

    def send(self, parent, text, quiet=False):
        """WhatsApp when it can carry the words, Telegram when it can't. What happened comes back for the record. A quiet one
        makes no sound, and only Telegram can do that."""
        if quiet or not self.whatsapp or parent not in self.whatsapp.numbers:
            return self.by_telegram(parent, text, quiet)
        try:
            if self.whatsapp.send(parent, text) == "text":
                return "On WhatsApp."
            note = "WhatsApp's 24 hour window is closed: it got the template and this text waits for the reply. Telegram carried it now."
        except MessagingError as error:
            note = f"WhatsApp failed ({error}). Telegram carried it."
        self.by_telegram(parent, text)
        return note

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


async def home_tools(settings, mock, turn=lambda: None, after=None):
    """Home Assistant's own tools under their short names. Only allowed devices can be switched. turn is the event running now, so
    one event reads the whole home once. after hears what moved, and its words go back to Muse."""
    real = part("home") == "real"
    url = settings.ha_url + "/api/mcp" if real else mock.url
    headers = {"Authorization": "Bearer " + settings.ha_token} if real else {}
    client = MultiServerMCPClient({"home": {"transport": "streamable_http", "url": url, "headers": headers}})
    found = {t.name.rsplit("__", 1)[-1]: t for t in await client.get_tools()}
    read = {"turn": None}

    async def GetLiveContext() -> str:
        """The state of every device and sensor in the home right now. It takes no arguments and reads everything."""
        if read["turn"] is not None and read["turn"] == turn():
            return "Nothing changed since your last look in this event."
        try:
            result = text_of(await found["GetLiveContext"].ainvoke({}))
        except Exception as failure:
            return f"Error: the home is not answering ({type(failure).__name__}), nothing changed that you can be sure of."
        read["turn"] = turn()
        return result

    def wrap(short, tool):
        async def call(**arguments):
            if short in NAMED and arguments.get("name") not in settings.devices:
                return f"Refused: you may only switch {', '.join(settings.devices)}."
            try:
                result = text_of(await tool.ainvoke({k: v for k, v in arguments.items() if v is not None}))
                read["turn"] = None
                return result + (await after(short, arguments, result) if after else "")
            except Exception as failure:  # Home Assistant away is something Muse hears about, the run goes on
                return f"Error: the home is not answering ({type(failure).__name__}), nothing changed that you can be sure of."
        return StructuredTool.from_function(coroutine=call, name=short, description=tool.description or short, args_schema=tool.args_schema)
    usable = [short for short in HOME_TOOLS if not (real and short in GATED and GATED[short] not in settings.devices)]
    return [StructuredTool.from_function(coroutine=GetLiveContext) if short == "GetLiveContext" else wrap(short, found[short]) for short in usable if short in found]


def channel_tools(channel, settings, log=None, heard=lambda: "", night_check=None, claims=lambda text: None):
    def checked(text):
        out, why = safety.outbound(text, settings.lang)
        return out, why or claims(out or "") or (safety.unbacked(out, lambda: log.entries(None, None, 50), heard()) if log else None)

    async def notify(parent: str, text: str, emergency: bool = False, quiet: bool = False) -> str:
        """Send one message to one parent's phone. parent is gonza or ceci. It wakes them at night. emergency is only for a
        danger to someone's life or the house, and it wakes a parent who isn't on duty. quiet makes no sound, for what they
        should know but isn't worth waking them."""
        if parent not in PARENTS:
            return "Refused: parent is gonza or ceci."
        why = await night_check(parent, emergency) if night_check else None
        if why:
            return why
        out, why = await asyncio.to_thread(checked, text)
        if why:
            return why
        try:
            note = await asyncio.to_thread(channel.send, parent, out, *([True] if quiet else []))
        except Exception as failure:  # the phone channel away is something Muse hears about, the run goes on
            return f"Failed, nothing was sent: the phone channel is not answering ({type(failure).__name__})."
        return f"Sent to {parent}. {note}" if note else f"Sent to {parent}."

    def say_on_echo(text: str) -> str:
        """Say one sentence out loud on the kitchen Echo, at low volume. Everyone in the kitchen hears it."""
        out, why = checked(text)
        if why:
            return why
        try:
            channel.echo(out)
        except Exception as failure:
            return f"Failed, nothing was said: the Echo is not answering ({type(failure).__name__})."
        return "Said on the kitchen Echo."
    return [StructuredTool.from_function(coroutine=notify), StructuredTool.from_function(say_on_echo)]


# What each tool did, for the record. Tools that only read aren't here. The record comes from the calls, never from Muse's words.
DID = {"HassTurnOn": lambda a: f"Turned on {a.get('name', 'a device')}", "HassTurnOff": lambda a: f"Turned off {a.get('name', 'a device')}",
       "HassVacuumStart": lambda a: "Started the vacuum", "HassVacuumReturnToBase": lambda a: "Sent the vacuum back",
       "HassListAddItem": lambda a: f"Added {a.get('item', 'an item')} to the list", "notify": lambda a: f"Told {a.get('parent', 'a parent')}",
       "say_on_echo": lambda a: "Spoke on the Echo", "log_baby_event": lambda a: f"Logged {a.get('kind', 'an entry')}",
       "set_on_duty": lambda a: f"Put {a.get('parent', 'a parent')} on duty for the night of {a.get('night', 'a date')}",
       "remember": lambda a: f"Remembered {a.get('key', 'a fact')}", "forget": lambda a: f"Forgot {a.get('key', 'a fact')}",
       "wake_me_at": lambda a: f"Set a wake for {a.get('at', 'later')}", "start_car_seat_coach": lambda a: f"Started the car seat coach for {a.get('parent', 'a parent')}"}
FAILED = re.compile(r'^\s*(refused|failed|error|ask_parent|.{0,40}"error"|.{0,200}"response_type":\s*"error")', re.I | re.S)


def record_line(calls):
    """One line of what was really done, from (tool, arguments, result) of one event."""
    done, refused = [], []
    for tool, arguments, result in calls:
        if tool in DID:
            (refused if FAILED.match(result or "") else done).append(DID[tool](arguments))
    unique = list(dict.fromkeys(done))
    line = ". ".join(unique) + "." if unique else "Nothing done."
    return line + (" Refused or failed: " + ", ".join(dict.fromkeys(refused)) + "." if refused else "")


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
                "your own, not even in a message. Their yes, no and listo go to the coach by themselves, so don't answer those.")
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


def duty_key(night):
    return f"on_duty_{night}"


def duty_tool(store, home, on_set=None):
    async def set_on_duty(night: str, parent: str) -> str:
        """Change who is on duty for one night. night is the date of that night's evening, YYYY-MM-DD. parent is gonza or ceci."""
        if parent not in PARENTS:
            return "Refused: parent is gonza or ceci."
        try:
            day = datetime.date.fromisoformat(night)
        except ValueError:
            return "Refused: night is a date, for example 2026-11-04."
        await store.aput((*FACTS, home), duty_key(day), {"value": parent})
        note = await on_set(day, parent) if on_set else ""
        return f"{parent} is on duty the night of {day}.{note}"
    return [StructuredTool.from_function(coroutine=set_on_duty)]


async def facts(store, home):
    return {item.key: item.value["value"] for item in await store.asearch((*FACTS, home), limit=1000)}  # Core.prune keeps this small
