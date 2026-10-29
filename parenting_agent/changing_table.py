"""Changing-table skill as a plug-in of the persistent agent.

Add "parenting_agent.changing_table:ChangingTable" to the agent config plugins, with a "changing_table" block:
    {"skill": "skills/changing-table.json", "source": "phone" | "glasses" | "0" | "loop.mp4", "arm": "start" | "command",
     "channel": "console" | "glasses"}  # the channel the agent answers on when the change is logged
Exact phrases ("changing time", "change done", see START_PHRASES and FINISH_PHRASES, or start_phrases and
finish_phrases in the block) arm and finish it as a reflex, without waiting for the brain to pick the tool, and
the agent's memory holds whether the watch is on, so a bare "done" is not read as a new change.
With arm "start" the skill arms when the agent starts. With arm "command" it waits for the agent's
start_changing_table and finish_changing_table tools, so the parent can say "changing time" and "done".

While armed it watches the newest frames from the source: the local reflex chimes at once, the spoken "hand"
plays when SAM 3.1 confirms no hand is on the baby or the alarm holds for voice_hold_s, and one hand on stays
silent. Closing restores the house, logs the diaper to Baby Buddy and tells the agent with an observation, so
the agent can answer "when was the last diaper?" from its own memory too.

With "preload_confirm": true the confirm detector (SAM 3.1, about 10 s to load on the Mac) loads when the agent
starts and again after each change, so "changing time" starts watching at once instead of after the load. Without
it the skill is blind for those 10 s, and a hover in them is never seen (results/hero/README.md).
A load that is still running after preload_wait_s (default 5) never holds up "changing time": the watch starts with
the MediaPipe hand regions only, the agent says so, and the detector is used from the next change (round 3 red team).
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from . import confirm as confirm_mod
from . import config as config_mod
from .camera_skill import phrase
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .reflex import MediaPipeReflex
from .skill import Skill, watch
from .sources import PhoneSource, open_source
from .speaker import Speaker


START_PHRASES = ["changing time", "diaper change", "time for a change", "changing her", "changing him"]
FINISH_PHRASES = ["done", "all done", "change done", "done with the change", "changing done", "finished the change"]
ARMED_FACT = ("The changing-table watch is on now. When the parent says done, call finish_changing_table, "
              "never start_changing_table again.")
IDLE_FACT = "No diaper change in progress, the changing-table watch is off."
# How long "changing time" waits for a SAM 3.1 that is still loading before it watches with MediaPipe alone.
PRELOAD_WAIT_S = 5
REGIONS_ONLY = ("Watching the changing table with the MediaPipe hand regions only, SAM 3.1 is still loading. "
                "The chime works, the hand check is not confirmed by SAM this change.")


class ChangingTable(Plugin):
    name = "changing-table"
    kind = "skill"

    def __init__(self, agent, config, reflex=None, confirm_detector=None, source=None, quiet=False):
        super().__init__(agent, config)
        self.cfg = {"skill": "skills/changing-table.json", "source": "phone", "arm": "command", "channel": "console",
                    **config.get("changing_table", {})}
        self.skill_cfg = config_mod.load(self.cfg["skill"])
        self._reflex, self._confirm, self._source, self.quiet = reflex, confirm_detector, source, quiet
        self.skill, self.source, self.thread = None, None, None
        self.lock = threading.Lock()
        self.loader, self.warm, self.stopping, self.arming = None, None, False, False
        agent.tools.add(Tool("start_changing_table", "Start watching the changing table, when the parent says a change is starting.",
                             schema({}), self.arm))
        agent.tools.add(Tool("finish_changing_table", "Stop watching the changing table and log the diaper change.",
                             schema({}), self.finish))
        self.phrases = {**{phrase(p): self.arm for p in self.cfg.get("start_phrases", START_PHRASES)},
                        **{phrase(p): self.finish for p in self.cfg.get("finish_phrases", FINISH_PHRASES)}}
        agent.bus.subscribe(self.on_message, ["message"])
        agent.memory.remember(self.name, IDLE_FACT)

    def on_message(self, event):
        """The exact phrases arm and finish the watch at once. A finish phrase does nothing while nothing is watched."""
        action = self.phrases.get(phrase(event.get("text", "")))
        if action is None or (action == self.finish and self.skill is None):
            return
        self.agent.bus.publish("phrase", skill=self.name, action=action.__name__)
        threading.Thread(target=action, name=f"{self.name}-{action.__name__}", daemon=True).start()

    def start(self):
        self.preload()
        if self.cfg["arm"] == "start":
            self.arm()

    def preload(self):
        """Starts loading the next change's confirm detector in the background (changing_table.preload_confirm)."""
        if not self.cfg.get("preload_confirm") or self._confirm is not None or self.warm is not None or self.stopping:
            return
        self.loader = self.loader or ThreadPoolExecutor(max_workers=1)
        self.warm = self.loader.submit(confirm_mod.build, self.skill_cfg["confirm"])

    def take_warm(self):
        """The preloaded detector, waiting up to preload_wait_s for it if it is still loading, or None to build one
        at arm as before. A load that takes longer leaves the watch on the MediaPipe hand regions only, and the late
        detector stays for the next change."""
        warm = self.warm
        if warm is None:
            return None
        started = time.monotonic()
        try:
            detector = warm.result(timeout=self.cfg.get("preload_wait_s", PRELOAD_WAIT_S))
        except FutureTimeout:
            self.agent.bus.publish("confirm_preload_timeout", waited_s=round(time.monotonic() - started, 3))
            return confirm_mod.NoConfirm()
        except Exception as error:  # the skill builds its own and raises Unavailable the usual way
            self.warm = None
            self.agent.bus.publish("confirm_preload_error", error=str(error)[:200])
            return None
        self.warm = None
        self.agent.bus.publish("confirm_preloaded", waited_s=round(time.monotonic() - started, 3))
        return detector

    def arm(self):
        """Never waits for a loading detector while holding the lock, so "done" always answers."""
        with self.lock:
            if self.skill is not None or self.arming:
                return "already watching the changing table"
            self.arming = True
        try:
            detector = self._confirm or self.take_warm()
            with self.lock:
                self.source = self._source or open_source(self.cfg["source"])
                if isinstance(self.source, PhoneSource):
                    self.agent.bus.publish("head_camera", url=self.source.url)
                speaker = Speaker(self.source, quiet=self.quiet)
                self.agent.bus.subscribe(speaker.on_event, ["chime", "voice"])
                reflex = self._reflex or MediaPipeReflex(self.skill_cfg["contact"])
                self.skill = Skill(self.skill_cfg, self.agent.bus, reflex, confirm_detector=detector)
                self.skill.arm()
                self.thread = threading.Thread(target=watch, args=(self.skill, self.source), name="changing-table", daemon=True)
                self.thread.start()
                self.agent.memory.remember(self.name, ARMED_FACT)
        finally:
            self.arming = False
        if isinstance(detector, confirm_mod.NoConfirm) and self._confirm is None:
            self.agent.say(self.cfg["channel"], REGIONS_ONLY)
            return REGIONS_ONLY
        return "watching the changing table"

    def finish(self):
        with self.lock:
            if self.skill is None:
                return "the changing table was not being watched"
            self.source.close()
            self.thread.join(timeout=5)
            self.skill.close()
            closed = next(e for e in reversed(self.agent.bus.history) if e["kind"] == "skill_closed")
            self.agent.bus.publish("observation", source=self.name, channel=self.cfg["channel"],
                                   text=f"A diaper change just finished at the changing table. Hand alerts spoken: {closed['voices']}.")
            self.skill, self.source, self.thread = None, None, None
            self.agent.memory.remember(self.name, IDLE_FACT)
            self.preload()
            return "diaper change logged"

    def stop(self):
        self.stopping = True
        self.finish()
        if self.warm is not None:
            try:
                getattr(self.warm.result(timeout=60), "close", lambda: None)()
            except Exception:  # a detector that never loaded has nothing to close
                pass
            self.warm = None
        if self.loader:
            self.loader.shutdown(wait=False)
