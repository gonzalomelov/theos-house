"""Tools the brain can call, and the allowed-list policy that decides which run without asking.

A tool is a name, a one-line description, a JSON schema for its arguments and a handler. Skills and
the house layer register more tools later. A tool that is not on the allowed list never runs on the
brain's word: the agent records it as a proposal and asks the parent first.
"""
import datetime

from . import rules
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


def core_tools(memory, baby_log, allowed, remember_keys=None):
    """The log, read and memory tools. remember_keys limits what remember may keep, () leaves remember out."""
    tools = Tools(allowed)
    tools.add(Tool(
        "log_baby_event", f"Record something about the baby in the baby log. kind is one of: {', '.join(LOG_KINDS)}. details by kind: "
        "feeding: amount_ml (number), method (bottle, breast when the side was not said, left breast, right breast, both breasts), "
        "type (breast milk, formula) only when the parent said it, duration_min only when the parent said it. "
        "diaper: wet (true or false), solid (true for a dirty or poopy diaper), color. "
        "sleep: action start when the baby falls asleep, action end when she wakes, or start and end ISO times for a past nap. "
        "bath: text. note: text, for anything else worth keeping. Never add a detail the parent did not say. "
        "Omit ts unless the parent named a past time, entries are never in the future. "
        "A correction of an earlier entry is never a new entry: use edit_baby_event or delete_baby_event.",
        schema({"kind": {"type": "string", "enum": list(LOG_KINDS)}, "details": {"type": "object"},
                "ts": {"type": "string", "description": "ISO time if the parent named a past time, else omit"}}, ["kind", "details"]),
        lambda kind, details, ts=None: baby_log.add(kind, plain_text(kind, details), ts)))
    if hasattr(baby_log, "update") and hasattr(baby_log, "delete"):
        for tool in edit_tools(baby_log):
            tools.add(tool)
    tools.add(Tool(
        "read_baby_log", "Read the baby log entries, newest last. Optional kind filter, an ISO since time and a limit.",
        schema({"kind": {"type": "string", "enum": list(LOG_KINDS)}, "since": {"type": "string"}, "limit": {"type": "integer"}}),
        lambda kind=None, since=None, limit=50: baby_log.entries(kind, since, limit)))
    tools.add(Tool(
        "baby_summary", "Totals and last times from the baby log: feed count and total ml, diaper counts and the last dirty one "
        "(diapers.said is today's count in words that add up, in en and es: say it as it is), "
        "sleep minutes, the last bath. Counts cover since (ISO) or today from midnight, until (ISO) or now. For yesterday give "
        "both since and until. Use it for how much, how many, when was the last.",
        schema({"since": {"type": "string", "description": "ISO start of the period, omit for today"},
                "until": {"type": "string", "description": "ISO end of the period, omit for now"}}),
        lambda since=None, until=None: baby_log.summary(since, until)))
    if remember_keys != ():
        tools.add(Tool(
            "remember", "Keep a fact about the family for later, for example the baby's name or the partner's name. "
            "Never a code, a password, a phone number, an email or an address." +
            (f" Only these keys: {', '.join(sorted(remember_keys))}." if remember_keys else ""),
            schema({"key": {"type": "string"}, "value": {"type": "string"}}, ["key", "value"]),
            lambda key, value: remember(memory, key, value, remember_keys)))
    tools.add(Tool(
        "current_time", "The current local date and time.", schema({}),
        lambda: local_now(baby_log).isoformat(timespec="minutes")))
    return tools


def plain_text(kind, details):
    """A note's or a bath's text is kept as plain words from a parent: no square brackets, so it can never read later as
    an observation from a skill or a check from the agent (blind round b6 stored "[observation from house_brain] ...
    approved ... run them" as it was), and no run of blank lines."""
    if kind not in ("note", "bath") or not isinstance(details, dict) or details.get("text") is None:
        return details
    return {**details, "text": " ".join(rules.parent_text(details["text"]).split())}


def local_now(baby_log):
    """The baby log's clock, so a server on UTC and the family's time zone agree."""
    try:
        return baby_log.now()
    except (AttributeError, NotImplementedError):
        return datetime.datetime.now().astimezone()


def remember(memory, key, value, keys=None):
    """A fact kept for every later prompt. A code, a password or a contact detail is never kept, and a service can
    limit the keys to what its privacy note says it stores."""
    key, value = str(key or "").strip(), str(value or "").strip()
    if key == "due_date":
        # The prep countdown, the list dates and the morning nudge read this fact, so only set_due_date changes it:
        # it checks the date and, in the family agent, waits for the parent's yes.
        raise ValueError("a due date is changed only with set_due_date, for example 2026-12-15. Nothing was kept")
    if keys and key not in keys:
        raise ValueError(f"only {', '.join(sorted(keys))} can be remembered here, nothing was kept")
    if not key or key.startswith("_") or len(value) > 120:
        raise ValueError("that cannot be remembered, nothing was kept")
    if rules.personal_detail(key.replace("_", " ")) or rules.personal_detail(value):
        raise ValueError("codes, passwords, phone numbers, emails and addresses are never remembered, nothing was kept")
    if key.endswith("name") and not rules.plain_name(value):
        raise ValueError("a name is a few words with letters only, nothing was kept")
    memory.remember(key, value)
    return "remembered"


WHICH = {"id": {"type": "integer", "description": "the entry id from read_baby_log"},
         "kind": {"type": "string", "enum": list(LOG_KINDS)},
         "at": {"type": "string", "description": "the entry's local time as HH:MM, for example 01:30 for 'la de la 1 y media'"},
         "last": {"type": "boolean", "description": "true for the most recent entry, of kind if given"}}


def edit_tools(baby_log):
    """Change or remove an entry already in the log. The entry is named by id, by kind and local time, or as the last."""
    return [
        Tool("edit_baby_event",
             "Change an entry already in the baby log when the parent corrects it, for example 'perdón eran 100 no 120' or "
             "'la de la 1 y media fue 80'. Name the entry by id, by kind and at, or by last. details holds only the fields "
             "that change, with the same names as log_baby_event. ts moves the entry to another time.",
             schema({**WHICH, "details": {"type": "object"}, "ts": {"type": "string", "description": "new ISO time, only if the parent named one"}}),
             lambda id=None, kind=None, at=None, last=None, details=None, ts=None:
             baby_log.update(details=details, ts=ts, **which(baby_log, id, kind, at, last))),
        Tool("delete_baby_event",
             "Remove an entry from the baby log when the parent sent it twice by mistake or asks to delete it, for example "
             "'la mandé 2 veces sin querer' or 'borrá la última'. Name the entry by id, by kind and at, or by last.",
             schema(WHICH),
             lambda id=None, kind=None, at=None, last=None: baby_log.delete(**which(baby_log, id, kind, at, last))),
    ]


def which(baby_log, entry_id, kind, at, last):
    """The arguments that name one entry to update or delete: its id, and its kind for a log whose ids repeat across
    kinds (Baby Buddy numbers feeds and diapers apart)."""
    entry = baby_log.find(entry_id, kind, at, last)
    return {"entry_id": entry["id"], **({"kind": entry["kind"]} if getattr(baby_log, "kind_ids", False) else {})}
