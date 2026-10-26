"""Event bus: every part publishes what happened, listeners react, a JSONL log keeps the numbers.

Events are plain dicts with a kind and a time t (seconds since the skill was armed). Only numbers,
states and short texts go on the bus, never frames or audio.
"""
import json
import threading
import time


class Bus:
    def __init__(self, log_path=None):
        self.started = time.monotonic()
        self.listeners = []
        self.lock = threading.Lock()
        self.log = log_path.open("a") if log_path else None
        self.history = []

    def now(self):
        return round(time.monotonic() - self.started, 3)

    def subscribe(self, listener, kinds=None):
        self.listeners.append((listener, set(kinds) if kinds else None))

    def publish(self, kind, **fields):
        event = {"kind": kind, "t": self.now(), **fields}
        with self.lock:
            self.history.append(event)
            if self.log:
                self.log.write(json.dumps(event) + "\n")
                self.log.flush()
        for listener, kinds in list(self.listeners):
            if kinds is None or kind in kinds:
                listener(event)
        return event

    def count(self, kind):
        return sum(1 for e in self.history if e["kind"] == kind)

    def close(self):
        if self.log:
            self.log.close()
            self.log = None
