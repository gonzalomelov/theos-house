"""Tools the brain can call, and the allowed-list policy that decides which run without asking.

A tool is a name, a one-line description, a JSON schema for its arguments and a handler. Skills and
the house layer register more tools later. A tool that is not on the allowed list never runs on the
brain's word: the agent records it as a proposal and asks the parent first.
"""
import datetime

from .memory import LOG_KINDS


class Tool:
    def __init__(self, name, description, parameters, handler):
        self.name, self.description, self.parameters, self.handler = name, description, parameters, handler

    def spec(self):
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


class Tools:
    def __init__(self, allowed):
        self.items = {}
        self.allowed = set(allowed)

    def add(self, tool):
        self.items[tool.name] = tool

    def specs(self):
        return [tool.spec() for tool in self.items.values()]

    def names(self):
        return sorted(self.items)

    def run(self, name, arguments):
        """Returns (status, result): status is ran, ask_parent or error."""
        tool = self.items.get(name)
        if tool is None:
            return "error", f"no tool named {name}"
        if name not in self.allowed:
            return "ask_parent", f"{name} needs the parent's yes before it runs"
        try:
            return "ran", tool.handler(**(arguments or {}))
        except (TypeError, ValueError, KeyError, RuntimeError) as error:
            return "error", f"{name} failed: {error}"


def schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


def core_tools(memory, baby_log, allowed):
    tools = Tools(allowed)
    tools.add(Tool(
        "log_baby_event", f"Record something about the baby in the baby log. kind is one of: {', '.join(LOG_KINDS)}. details by kind: "
        "feeding: amount_ml (number), method (bottle, left breast, right breast, both breasts), type (breast milk, formula), duration_min. "
        "diaper: wet (true or false), solid (true for a dirty or poopy diaper), color. "
        "sleep: action start when the baby falls asleep, action end when she wakes, or start and end ISO times for a past nap. "
        "bath: text. note: text, for anything else worth keeping. Omit ts unless the parent named a past time, entries are never in the future.",
        schema({"kind": {"type": "string", "enum": list(LOG_KINDS)}, "details": {"type": "object"},
                "ts": {"type": "string", "description": "ISO time if the parent named a past time, else omit"}}, ["kind", "details"]),
        lambda kind, details, ts=None: baby_log.add(kind, details, ts)))
    tools.add(Tool(
        "read_baby_log", "Read the baby log entries, newest last. Optional kind filter, an ISO since time and a limit.",
        schema({"kind": {"type": "string", "enum": list(LOG_KINDS)}, "since": {"type": "string"}, "limit": {"type": "integer"}}),
        lambda kind=None, since=None, limit=50: baby_log.entries(kind, since, limit)))
    tools.add(Tool(
        "baby_summary", "Totals and last times from the baby log: feed count and total ml, diaper counts and the last dirty one, "
        "sleep minutes, the last bath. Counts cover since (ISO) or today from midnight. Use it for how much, how many, when was the last.",
        schema({"since": {"type": "string", "description": "ISO start of the period, omit for today"}}),
        lambda since=None: baby_log.summary(since)))
    tools.add(Tool(
        "remember", "Keep a fact about the family for later, for example the baby's name or the partner's name.",
        schema({"key": {"type": "string"}, "value": {"type": "string"}}, ["key", "value"]),
        lambda key, value: memory.remember(key, value) or "remembered"))
    tools.add(Tool(
        "current_time", "The current local date and time.", schema({}),
        lambda: datetime.datetime.now().astimezone().isoformat(timespec="minutes")))
    return tools
