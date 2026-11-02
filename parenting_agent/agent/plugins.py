"""Plug-in point for skills and channels.

A plug-in is a class named in the agent config as "module:Class". It gets the running agent, may add
tools to agent.tools, subscribes to the bus for what it cares about, and publishes its own events:
a channel publishes "message" events and speaks the agent's "reply" events, a skill publishes
"observation" events. Each plug-in has a name, start() and stop().
"""
import importlib


class Plugin:
    name = "plugin"

    def __init__(self, agent, config):
        self.agent, self.config = agent, config

    def start(self):
        pass

    def stop(self):
        pass


def load(spec, agent, config):
    module_name, _, class_name = spec.partition(":")
    cls = getattr(importlib.import_module(module_name), class_name)
    return cls(agent, config)


def find_plugin(agent, name):
    """The agent's plug-in with that name, or None."""
    return next((p for p in getattr(agent, "plugins", []) or [] if getattr(p, "name", "") == name), None)
