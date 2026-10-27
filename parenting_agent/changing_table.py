"""Changing-table skill as a plug-in of the persistent agent.

Add "parenting_agent.changing_table:ChangingTable" to the agent config plugins, with a "changing_table" block:
    {"skill": "skills/changing-table.json", "source": "phone" | "0" | "loop.mp4", "arm": "start" | "command"}
With arm "start" the skill arms when the agent starts. With arm "command" it waits for the agent's
start_changing_table and finish_changing_table tools, so the parent can say "changing time" and "done".

While armed it watches the newest frames from the source: the local reflex chimes at once, the spoken "hand"
plays when SAM 3.1 confirms no hand is on the baby or the alarm holds for voice_hold_s, and one hand on stays
silent. Closing restores the house, logs the diaper to Baby Buddy and tells the agent with an observation, so
the agent can answer "when was the last diaper?" from its own memory too.
"""
import threading

from . import config as config_mod
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .reflex import MediaPipeReflex
from .skill import Skill, watch
from .sources import PhoneSource, open_source
from .speaker import Speaker


class ChangingTable(Plugin):
    name = "changing-table"
    kind = "skill"

    def __init__(self, agent, config, reflex=None, confirm_detector=None, source=None, quiet=False):
        super().__init__(agent, config)
        self.cfg = {"skill": "skills/changing-table.json", "source": "phone", "arm": "command", **config.get("changing_table", {})}
        self.skill_cfg = config_mod.load(self.cfg["skill"])
        self._reflex, self._confirm, self._source, self.quiet = reflex, confirm_detector, source, quiet
        self.skill, self.source, self.thread = None, None, None
        self.lock = threading.Lock()
        agent.tools.add(Tool("start_changing_table", "Start watching the changing table, when the parent says a change is starting.",
                             schema({}), self.arm))
        agent.tools.add(Tool("finish_changing_table", "Stop watching the changing table and log the diaper change.",
                             schema({}), self.finish))

    def start(self):
        if self.cfg["arm"] == "start":
            self.arm()

    def arm(self):
        with self.lock:
            if self.skill is not None:
                return "already watching the changing table"
            self.source = self._source or open_source(self.cfg["source"])
            if isinstance(self.source, PhoneSource):
                self.agent.bus.publish("head_camera", url=self.source.url)
            speaker = Speaker(self.source, quiet=self.quiet)
            self.agent.bus.subscribe(speaker.on_event, ["chime", "voice"])
            reflex = self._reflex or MediaPipeReflex(self.skill_cfg["contact"])
            self.skill = Skill(self.skill_cfg, self.agent.bus, reflex, confirm_detector=self._confirm)
            self.skill.arm()
            self.thread = threading.Thread(target=watch, args=(self.skill, self.source), name="changing-table", daemon=True)
            self.thread.start()
            return "watching the changing table"

    def finish(self):
        with self.lock:
            if self.skill is None:
                return "the changing table was not being watched"
            self.source.close()
            self.thread.join(timeout=5)
            self.skill.close()
            closed = next(e for e in reversed(self.agent.bus.history) if e["kind"] == "skill_closed")
            self.agent.bus.publish("observation", source=self.name, channel="console",
                                   text=f"A diaper change just finished at the changing table. Hand alerts spoken: {closed['voices']}.")
            self.skill, self.source, self.thread = None, None, None
            return "diaper change logged"

    def stop(self):
        self.finish()
