"""The families bot: long polling on the second Telegram bot, and a clock for reminders and summaries.

Nothing listens and nothing is published: the bot pulls messages over HTTPS through the egress proxy. Any
Messenger works here, so the tests use a fake one. The read position is kept in the data folder, so a restart
does not answer a message twice. Message text is never logged, only counts and error types.

Voice notes from a parent are heard by Muse Spark Open (parenting_agent/voice) and handled as the words heard. The
answer goes back as text that starts with those words, and as a voice note in a Meta open voice (MMS-TTS).
"""
import threading
from pathlib import Path

from ..channels.messaging import NO_VOICE, NOT_HEARD, MessagingError, heard_text
from ..voice import client as voice_client

OFFSET_FILE = "families-telegram.offset"


class FamiliesBot:
    def __init__(self, service, messenger, poll_timeout_s=25, tick_s=60, voice=None):
        self.service, self.messenger, self.voice = service, messenger, voice
        self.poll_timeout_s, self.tick_s = poll_timeout_s, tick_s
        self.offset_path = Path(service.s["data_dir"]) / OFFSET_FILE
        self.stopped = threading.Event()
        self.errors = 0

    def read_offset(self):
        try:
            return int(self.offset_path.read_text().strip())
        except (OSError, ValueError):
            return 0

    def save_offset(self, offset):
        self.offset_path.write_text(str(offset))

    def send(self, messages):
        sent = 0
        for chat_id, text in messages:
            try:
                self.messenger.send(chat_id, text)
                sent += 1
            except MessagingError as error:
                self.errors += 1
                print(f"families: send failed, {str(error)[:120]}", flush=True)
        return sent

    def poll_once(self, timeout=None):
        """One batch of updates. Returns how many messages were sent back."""
        try:
            batch = self.messenger.poll(self.read_offset(), self.poll_timeout_s if timeout is None else timeout)
        except MessagingError as error:
            self.errors += 1
            print(f"families: poll failed, {str(error)[:120]}", flush=True)
            self.stopped.wait(5)
            return 0
        return self.poll_once_items(batch)

    def poll_once_items(self, batch):
        """Handles one batch of updates already fetched. Returns how many messages were sent back."""
        sent = 0
        for item in batch:
            self.save_offset(item.update_id + 1)
            text, heard = item.text, None
            if not (text or "").strip() and getattr(item, "voice_file_id", ""):
                text = heard = self.hear(item)
                if not heard:
                    sent += 1
                    continue
            replies = self.service.handle(item.user_id, item.chat_id, text, item.chat_type or "private",
                                          getattr(item, "language_code", ""), item.update_id)
            if heard and replies:
                spoken = [r for _, r in replies]
                replies = [(replies[0][0], heard_text(heard, replies[0][1]))] + replies[1:]
                sent += self.send(replies)
                self.spoken_thread = voice_client.in_background(self.send_spoken, item.chat_id, " ".join(spoken))
                continue
            sent += self.send(replies)
        return sent

    def hear(self, item):
        """The words of a parent's voice note, or "" after telling them it could not be heard."""
        lang = self.service.family_lang(item.user_id, getattr(item, "language_code", ""))
        if item.chat_type not in ("", "private") or not self.service.may_hear(item.user_id):
            self.send([(item.chat_id, NO_VOICE[lang])])
            return ""
        if self.voice is None:
            self.send([(item.chat_id, NO_VOICE[lang])])
            return ""
        try:
            text = self.voice.hear(self.messenger.download(item.voice_file_id))
        except (MessagingError, voice_client.VoiceError) as error:
            self.errors += 1
            print(f"families: voice note not heard, {type(error).__name__}", flush=True)
            text = ""
        self.service.heard_spend(item.user_id, getattr(self.voice.ear, "usage", None))
        if not text:
            self.send([(item.chat_id, NOT_HEARD[lang])])
        return text

    def send_spoken(self, chat_id, text):
        if self.voice is None or not self.voice.reply_with_voice:
            return
        try:
            self.messenger.send_voice(chat_id, self.voice.speak(text))
        except (MessagingError, voice_client.VoiceError) as error:
            self.errors += 1
            print(f"families: voice reply failed, {type(error).__name__}", flush=True)

    def tick_once(self, now=None):
        return self.send(self.service.tick(now))

    def run_clock(self):
        while not self.stopped.wait(self.tick_s):
            try:
                self.tick_once()
            except Exception as error:  # the clock must survive one bad family file
                self.errors += 1
                print(f"families: tick failed, {type(error).__name__}", flush=True)

    def run(self):
        clock = threading.Thread(target=self.run_clock, name="families-clock", daemon=True)
        clock.start()
        print("families: polling started", flush=True)
        while not self.stopped.is_set():
            self.poll_once()

    def stop(self):
        self.stopped.set()
