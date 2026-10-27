"""The persistent parenting agent: bus, memory, tools, brain and the decide-act loop, wired by build()."""
from pathlib import Path

from ..bus import Bus
from . import brain as brain_mod
from . import config as config_mod
from . import plugins as plugins_mod
from .loop import Agent
from .memory import LocalBabyLog, Memory
from .tools import core_tools


def build(config):
    data = Path(config["data_dir"])
    data.mkdir(parents=True, exist_ok=True)
    config_mod.load_env(config["env_file"])
    bus = Bus(data / "events.jsonl")
    memory = Memory(data / "memory.sqlite")
    baby_log = LocalBabyLog(memory)
    tools = core_tools(memory, baby_log, config["allowed_tools"])
    agent = Agent(bus, memory, baby_log, tools, brain_mod.build(config["brain"]), max_steps=config["max_steps"])
    agent.plugins = [plugins_mod.load(spec, agent, config) for spec in config["plugins"]]
    return agent
