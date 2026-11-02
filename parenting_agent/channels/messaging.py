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

Voice notes: when the agent config has a "voice" block (parenting_agent/voice/client.py), a voice note is downloaded,
heard by Muse and handed to the agent as the words it heard, so it takes the same path as a typed note. The reply to
it goes back as text that starts with the words heard, so a mishearing is easy to correct, and as a voice note.
The words are screened first (parenting_agent/voice/screen.py): when Muse answered instead of writing down, nothing is
echoed or acted on and the parent is asked to say it again, and heard words with a dose are never echoed.
"""
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..agent import final_guard
from ..agent import rules
from ..agent.plugins import Plugin
from ..voice import client as voice_client
from ..voice import screen as voice_screen


@dataclass
class Incoming:
    update_id: int
    chat_id: str
    text: str
    sender: str = ""
    user_id: str = ""
    chat_type: str = ""
    language_code: str = ""
    voice_file_id: str = ""


NO_VOICE = {"en": "I can only read text here for now. Please type it.", "es": "Por ahora acá solo leo texto. ¿Me lo escribís?"}
NOT_HEARD = {"en": "I could not hear that voice note. Please send it again or type it.",
             "es": "No pude escuchar ese audio. ¿Me lo mandás de nuevo o me lo escribís?"}


def heard_text(heard, reply):
    """The text answer to a voice note: the words heard first, so the parent sees what the agent understood."""
    return f"\u00ab{heard}\u00bb\n{reply}"


class MessagingError(Exception):
    pass


class Messenger:
    """The adapter interface. poll() blocks up to timeout seconds and returns new messages after offset."""
    name = "messenger"

    def poll(self, offset, timeout):
        raise NotImplementedError

    def send(self, chat_id, text):
        raise NotImplementedError

    def download(self, file_id):
        raise MessagingError(f"{self.name} cannot download files")

    def send_voice(self, chat_id, ogg):
        raise MessagingError(f"{self.name} cannot send voice notes")


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
        self.voice = voice_client.build(config.get("voice"))
        self.heard = {}  # chat id -> the words of its last voice note, until the agent answers it
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
            text = item.text.strip()
            voice = False
            self.heard.pop(item.chat_id, None)
            if not text and item.voice_file_id:
                text = self.hear(item)
                verdict = self.screen(item, text) if text else None
                if verdict == "answer":
                    continue
                if verdict == "ok":
                    self.heard[item.chat_id] = text
                voice = bool(text)
            if not text:
                continue
            self.last_chat = item.chat_id
            self.agent.bus.publish("message", channel=self.name, text=text, chat_id=item.chat_id,
                                   person=self.person_of(item.chat_id), voice=voice)
            accepted.append(item)
        return accepted

    def hear(self, item):
        """The words of a voice note, or "" after telling the parent it could not be heard."""
        lang = "es" if (item.language_code or "").startswith("es") else "en"
        if self.voice is None:
            self.send_text(item.chat_id, NO_VOICE[lang])
            return ""
        started = time.monotonic()
        try:
            text = self.voice.hear(self.messenger.download(item.voice_file_id))
        except (MessagingError, voice_client.VoiceError) as error:
            self.agent.bus.publish("channel_error", channel=self.name, error=f"voice note: {str(error)[:180]}")
            self.send_text(item.chat_id, NOT_HEARD[lang])
            return ""
        self.agent.bus.publish("voice_heard", channel=self.name, ear=self.voice.ear.model, chars=len(text),
                               seconds=round(time.monotonic() - started, 3))
        if not text:
            self.send_text(item.chat_id, NOT_HEARD[lang])
        return text

    def screen(self, item, text):
        """ "ok", "no_echo" or "answer". An answer from the ear is never the parent's words: it is not echoed, not
        handed to the agent, and the parent is asked to say it again, with the health line."""
        verdict, reason = voice_screen.screen(text, getattr(self.voice, "seconds", None))
        if verdict != "ok":
            self.agent.bus.publish("voice_screened", channel=self.name, verdict=verdict, reason=reason, chars=len(text))
        if verdict == "answer":
            self.send_text(item.chat_id, voice_screen.not_understood("es" if rules.looks_spanish(text) else "en"))
        return verdict

    def send_text(self, chat, text):
        try:
            sent = self.messenger.send(chat, self.cfg["prefix"] + text)
            self.agent.bus.publish("channel_sent", channel=self.name, chat_id=chat, message_id=sent)
        except MessagingError as error:
            self.agent.bus.publish("channel_error", channel=self.name, error=str(error)[:200])

    def send_spoken(self, chat, text):
        """The reply as a voice note too, in a Meta open voice. A failure here never stops the text answer."""
        started = time.monotonic()
        try:
            ogg = self.voice.speak(text, voice_client.lang_of(text))
            sent = self.messenger.send_voice(chat, ogg)
        except (MessagingError, voice_client.VoiceError) as error:
            self.agent.bus.publish("channel_error", channel=self.name, error=f"voice reply: {str(error)[:180]}")
            return
        self.agent.bus.publish("channel_sent", channel=self.name, chat_id=chat, message_id=sent, voice=True,
                               seconds=round(time.monotonic() - started, 3))

    def final_guard(self, text, event, chat):
        """The text as it may reach the parent of this chat: no machinery, in the language the agent's reply carries
        (guard_lang, None when either is fine), else the language of the people block."""
        people = getattr(self.agent, "people", None)
        person = event.get("person") or self.person_of(chat)
        lang = event["guard_lang"] if "guard_lang" in event else (people.lang(person) if people and person else None)
        return final_guard.apply(text, lang, self.agent.bus, where=f"channel:{self.name}",
                                 names=people.rota_names() if people else None, person=person,
                                 source=event.get("source"))

    def speak(self, event):
        if event.get("channel") != self.name:
            return
        chat = event.get("chat_id") or self.last_chat or self.default_chat
        if chat is None:
            self.agent.bus.publish("channel_error", channel=self.name, error="no family chat to send to")
            return
        text = event["text"] if event["kind"] == "reply" else f"I want to use {event['name']}. Say yes to let me."
        if not event.get("flag"):  # a red flag line is fixed text, never touched
            text = self.final_guard(text, event, chat)
        if event.get("proactive"):
            # A push the agent starts (channels/push.py) is not the answer to a voice note: no heard words before it.
            self.send_text(chat, text)
            return
        heard = self.heard.pop(chat, None)
        self.send_text(chat, heard_text(heard, text) if heard else text)
        if heard and self.voice is not None and self.voice.reply_with_voice:
            self.spoken_thread = voice_client.in_background(self.send_spoken, chat, text)
