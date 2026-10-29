"""The persistent parenting agent: bus, memory, tools, brain and the decide-act loop, wired by build()."""
from pathlib import Path

from ..bus import Bus
from . import brain as brain_mod
from . import config as config_mod
from . import plugins as plugins_mod
from .babybuddy import BabyBuddyLog
from .loop import Agent
from .memory import LocalBabyLog, Memory
from .tools import core_tools

REMEMBER_KEYS = ("baby_name", "partner_name")


def build(config):
    data = Path(config["data_dir"])
    data.mkdir(parents=True, exist_ok=True)
    config_mod.load_env(config["env_file"])
    bus = Bus(data / "events.jsonl")
    memory = Memory(data / "memory.sqlite")
    log_config = config.get("baby_log") or {"provider": "local"}
    baby_log = BabyBuddyLog.from_config(log_config) if log_config.get("provider") == "babybuddy" else LocalBabyLog(memory)
    # remember writes only these keys: a free key ("house_rule", "before_he_arrives") would ride in every prompt.
    tools = core_tools(memory, baby_log, config["allowed_tools"], remember_keys=tuple(config.get("remember_keys", REMEMBER_KEYS)))
    agent = Agent(bus, memory, baby_log, tools, brain_mod.build(config["brain"]), max_steps=config["max_steps"])
    agent.plugins = [plugins_mod.load(spec, agent, config) for spec in config["plugins"]]
    return agent
