"""One messaging adapter interface, so WhatsApp later is a new adapter only.

An adapter knows how to fetch new messages and send a text to a chat. MessagingChannel is the plug-in
that runs any adapter: it polls in its own thread, keeps only the family's chats (the allowlist), puts
each message on the bus as a "message" event on its channel, and sends the agent's replies on that
channel back to the chat that spoke last, or to the family's default chat for messages the agent starts.
The agent and its memory are the same for every channel. Other senders are ignored and logged as
"channel_ignored" with their chat id only, never their text.

Each family chat can be tied to a person in the config, so the log says who spoke:
    "people": {"gonza": {"chat_ids_env": "TELEGRAM_CHAT_ID"}, "ceci": {"chat_ids_env": "TELEGRAM_CECI_CHAT_ID"}}
A person's chats are also family chats. At start the channel logs a "family_channels" event that says which people
have a chat on it, so a person with no chat shows as not connected instead of silently counting zero.
"""
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from ..agent.plugins import Plugin


@dataclass
class Incoming:
    update_id: int
    chat_id: str
    text: str
    sender: str = ""
    user_id: str = ""
    chat_type: str = ""
    language_code: str = ""


class MessagingError(Exception):
    pass


class Messenger:
    """The adapter interface. poll() blocks up to timeout seconds and returns new messages after offset."""
    name = "messenger"

    def poll(self, offset, timeout):
        raise NotImplementedError

    def send(self, chat_id, text):
        raise NotImplementedError


class MessagingChannel(Plugin):
    """Runs a Messenger as an agent channel. Subclasses set name and build the adapter in make_messenger()."""
    name = "messaging"
    kind = "channel"

    def __init__(self, agent, config, messenger=None):
        super().__init__(agent, config)
        self.cfg = {"poll_timeout_s": 25, "prefix": "", **config.get(self.name, {})}
        self.messenger = messenger or self.make_messenger()
        self.people = self.person_chats(config.get("people") or {})
        self.allowed = {str(c) for c in self.cfg.get("allowed_chat_ids", [])} | self.env_chat_ids() | set().union(*self.people.values())
        self.default_chat = str(self.cfg.get("default_chat_id") or next(iter(sorted(self.env_chat_ids())), "")) or None
        self.last_chat = None
        self.offset_path = Path(config.get("data_dir", "data")) / f"{self.name}.offset"
        self.stopped = threading.Event()
        self.thread = None
        agent.bus.subscribe(self.speak, ["reply", "ask_parent"])

    def make_messenger(self):
        raise NotImplementedError

    def env_chat_ids(self, name=None):
        raw = os.environ.get(name or self.cfg.get("allowed_chat_ids_env", ""), "")
        return {c.strip() for c in raw.split(",") if c.strip()}

    def person_chats(self, people):
        """{person: set of chat ids} from the people block. A chat id given to two people belongs to neither."""
        chats = {name: {str(c) for c in spec.get("chat_ids", [])} | (self.env_chat_ids(spec["chat_ids_env"]) if spec.get("chat_ids_env") else set())
                 for name, spec in people.items()}
        shared = {c for name, ids in chats.items() for c in ids
                  if any(c in other for o, other in chats.items() if o != name)}
        return {name: ids - shared for name, ids in chats.items()}

    def person_of(self, chat_id):
        return next((name for name, ids in self.people.items() if chat_id in ids), None)

    def start(self):
        self.thread = threading.Thread(target=self.run, name=self.name, daemon=True)
        self.thread.start()
        self.agent.bus.publish("channel_started", channel=self.name, allowed_chats=len(self.allowed))
        if self.people:
            self.agent.bus.publish("family_channels", channel=self.name,
                                   people={name: bool(ids) for name, ids in sorted(self.people.items())})
        print(f"{self.name}: polling started for {len(self.allowed)} family chat(s)", flush=True)

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=self.cfg["poll_timeout_s"] + 5)

    def read_offset(self):
        try:
            return int(self.offset_path.read_text().strip())
        except (OSError, ValueError):
            return 0

    def save_offset(self, offset):
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.offset_path.write_text(str(offset))

    def run(self):
        while not self.stopped.is_set():
            self.poll_once()

    def poll_once(self, timeout=None):
        """Fetch one batch, hand the family's messages to the agent. Returns the accepted messages."""
        try:
            batch = self.messenger.poll(self.read_offset(), self.cfg["poll_timeout_s"] if timeout is None else timeout)
        except MessagingError as error:
            self.agent.bus.publish("channel_error", channel=self.name, error=str(error)[:200])
            self.stopped.wait(5)
            return []
        accepted = []
        for item in batch:
            self.save_offset(item.update_id + 1)
            if item.chat_id not in self.allowed:
                self.agent.bus.publish("channel_ignored", channel=self.name, chat_id=item.chat_id)
                continue
            if not item.text.strip():
                continue
            self.last_chat = item.chat_id
            self.agent.bus.publish("message", channel=self.name, text=item.text.strip(), chat_id=item.chat_id,
                                   person=self.person_of(item.chat_id))
            accepted.append(item)
        return accepted

    def speak(self, event):
        if event.get("channel") != self.name:
            return
        chat = event.get("chat_id") or self.last_chat or self.default_chat
        if chat is None:
            self.agent.bus.publish("channel_error", channel=self.name, error="no family chat to send to")
            return
        text = event["text"] if event["kind"] == "reply" else f"I want to use {event['name']}. Say yes to let me."
        try:
            sent = self.messenger.send(chat, self.cfg["prefix"] + text)
            self.agent.bus.publish("channel_sent", channel=self.name, chat_id=chat, message_id=sent)
        except MessagingError as error:
            self.agent.bus.publish("channel_error", channel=self.name, error=str(error)[:200])
