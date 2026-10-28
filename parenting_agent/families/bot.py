"""The families bot: long polling on the second Telegram bot, and a clock for reminders and summaries.

Nothing listens and nothing is published: the bot pulls messages over HTTPS through the egress proxy. Any
Messenger works here, so the tests use a fake one. The read position is kept in the data folder, so a restart
does not answer a message twice. Message text is never logged, only counts and error types.
"""
import threading
from pathlib import Path

from ..channels.messaging import MessagingError

OFFSET_FILE = "families-telegram.offset"


class FamiliesBot:
    def __init__(self, service, messenger, poll_timeout_s=25, tick_s=60):
        self.service, self.messenger = service, messenger
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
        sent = 0
        for item in batch:
            self.save_offset(item.update_id + 1)
            sent += self.send(self.service.handle(item.user_id, item.chat_id, item.text, item.chat_type or "private",
                                                  getattr(item, "language_code", "")))
        return sent

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
