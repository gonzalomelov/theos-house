"""Console channel: type to the agent in the terminal that runs it. The first channel, used for tests and demos."""
import sys
import threading

from .plugins import Plugin


class Console(Plugin):
    name = "console"

    def start(self):
        self.agent.bus.subscribe(self.speak, ["reply", "ask_parent"])
        self.thread = threading.Thread(target=self.read, name="console", daemon=True)
        self.thread.start()

    def speak(self, event):
        if event.get("channel", "console") != "console":
            return
        if event["kind"] == "reply":
            print(f"agent> {event['text']}", flush=True)
        else:
            print(f"agent> I want to use {event['name']}. Say yes to let me.", flush=True)

    def read(self):
        for line in sys.stdin:
            if line.strip():
                self.agent.bus.publish("message", channel="console", text=line.strip())
