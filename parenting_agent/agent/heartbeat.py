"""Heartbeat plug-in: proves the agent is alive, for the container health check (issue #15).

While the decide-act loop runs, it writes data/heartbeat.json every interval_s seconds. If the loop thread
dies, it stops writing and ends the process with exit code 1, so the container's restart policy brings the
agent back instead of leaving a process that is up but deaf. Nothing goes on the bus, so the event log
does not grow with heartbeats.

    python -m parenting_agent.agent.heartbeat data/heartbeat.json   # exit 0 when the heartbeat is fresh
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

from .plugins import Plugin

DEFAULT_INTERVAL_S = 30
DEFAULT_MAX_AGE_S = 90


class Heartbeat(Plugin):
    name = "heartbeat"

    def __init__(self, agent, config, exit=os._exit):
        super().__init__(agent, config)
        settings = config.get("heartbeat", {})
        self.interval = settings.get("interval_s", DEFAULT_INTERVAL_S)
        self.path = Path(config["data_dir"]) / "heartbeat.json"
        self.exit = exit
        self.stopped = threading.Event()
        self.thread = None

    def start(self):
        self.started = time.time()
        self.thread = threading.Thread(target=self.run, name="heartbeat", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)

    def beat(self):
        """Writes the heartbeat and returns True, or returns False when the agent loop is gone."""
        loop = self.agent.thread
        if loop is None or not loop.is_alive():
            return False
        now = time.time()
        body = {"ts": round(now, 3), "uptime_s": round(now - self.started), "pid": os.getpid(),
                "brain": self.agent.brain.name, "baby_log": self.agent.baby_log.name}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(body))
        temporary.replace(self.path)
        return True

    def run(self):
        while not self.stopped.is_set():
            if not self.beat():
                print("heartbeat: the agent loop stopped, exiting so the container restarts", file=sys.stderr, flush=True)
                self.exit(1)
                return
            self.stopped.wait(self.interval)


def fresh(path, max_age_s=DEFAULT_MAX_AGE_S, now=None):
    try:
        beat = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return False
    return (now or time.time()) - beat.get("ts", 0) <= max_age_s


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/heartbeat.json"
    max_age = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MAX_AGE_S
    raise SystemExit(0 if fresh(target, max_age) else 1)
