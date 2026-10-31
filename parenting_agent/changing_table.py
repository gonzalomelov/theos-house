"""Changing-table skill as a plug-in of the persistent agent.

Add "parenting_agent.changing_table:ChangingTable" to the agent config plugins, with a "changing_table" block:
    {"skill": "skills/changing-table.json", "source": "phone" | "glasses" | "0" | "loop.mp4", "arm": "start" | "command",
     "channel": "console" | "glasses"}  # the channel the agent answers on when the change is logged
With arm "command" the brain (Muse Spark Open in the glasses config) decides: "changing time" goes to it like any
message and it calls start_changing_table, and at "done, it was dirty" it calls finish_changing_table with the
diaper's content. The tool logs the change to Baby Buddy, reads the entry back and hands it to the brain, which
speaks the summary from the log. The exact phrases (START_PHRASES and FINISH_PHRASES, or start_phrases and
finish_phrases in the block, and a finish phrase followed by more words) are only a fallback: when the brain's turn
ends, or phrase_fallback_s passes, and it did not call the tool, the phrase arms or finishes the watch and a
"phrase_fallback" event says so. Every arm publishes "changing_armed" with who armed it and the seconds since the
parent's words. The agent's memory holds whether the watch is on, so a bare "done" is not read as a new change.
With arm "start" the skill arms when the agent starts.

While armed it watches the newest frames from the source: the local reflex chimes at once, the spoken "hand"
plays when SAM 3.1 confirms no hand is on the baby or the alarm holds for voice_hold_s, and one hand on stays
silent. Closing restores the house, logs the diaper to Baby Buddy and tells the agent with an observation, so
the agent can answer "when was the last diaper?" from its own memory too.

With "preload_confirm": true the confirm detector (SAM 3.1, about 10 s to load on the Mac) loads when the agent
starts and again after each change, so "changing time" starts watching at once instead of after the load. Without
it the skill is blind for those 10 s, and a hover in them is never seen (results/hero/README.md).
A load that is still running after preload_wait_s (default 5) never holds up "changing time": the watch starts with
the MediaPipe hand regions only, the agent says so, and the detector is used from the next change (round 3 red team).
With "keep_confirm": true the loaded detector is kept between changes instead of closed and loaded again, so one
SAM 3.1 process serves the agent from start to stop and other checks can share it (sam3_local.live(), the dog watch
on the glasses). "confirm_ready" says when the preload finished and how long it took.
"""
import datetime
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
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
# Plain words for the parent: no model names (agent/final_guard.py). The tool result for the brain names them.
REGIONS_ONLY = ("Watching the changing table with the hand check only, the second check is still loading. "
                "The chime works, this change the hand check is not confirmed a second time.")
REGIONS_ONLY_TOOL = "MediaPipe hand regions only, SAM 3.1 is still loading: " + REGIONS_ONLY

LAST_CHANGE = "last-diaper-change"
CONTENT = {"wet": {"type": "boolean", "description": "true when the parent said wet or pee"},
           "solid": {"type": "boolean", "description": "true when the parent said dirty, poop or solid"}}
SOLID_WORDS, WET_WORDS = {"dirty", "poop", "poopy", "solid", "poo"}, {"wet", "pee"}


def content_from(text):
    """The diaper's content from the parent's words, for the fallback only. The brain reads it in every other case."""
    words = set(phrase(text).split())
    return {"wet": bool(words & WET_WORDS), "solid": bool(words & SOLID_WORDS)}


def local_hhmm(stamp):
    """Baby Buddy answers in UTC ("07:20:55Z"), the parent hears local time."""
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return str(stamp or "")[11:16]


def describe(entry):
    if entry.get("solid") and entry.get("wet"):
        return "wet and dirty"
    return "dirty" if entry.get("solid") else "wet" if entry.get("wet") else "dry, nothing said about it"


class KeptConfirm:
    """The kept detector as the skill sees it: everything passes through, except close, which the plug-in does at stop."""

    def __init__(self, detector):
        self.detector = detector
        self.name = detector.name

    def judge(self, frame_bgr):
        return self.detector.judge(frame_bgr)

    @property
    def impl(self):
        return getattr(self.detector, "impl", None)

    @property
    def masks(self):
        return getattr(self.detector, "masks", None)

    def close(self):
        pass


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
        self.kept = None
        agent.tools.add(Tool("start_changing_table", "Start watching the changing table, when the parent says a change is "
                             "starting (for example \"changing time\").", schema({}), lambda: self.arm(via="brain")))
        agent.tools.add(Tool("finish_changing_table", "Stop watching the changing table and log this diaper change with its "
                             "content, when the parent says the change is done. Set wet and solid from the parent's words. Do not "
                             "also call log_baby_event for this diaper. It returns the entry read back from Baby Buddy. Then tell the parent, "
                             "in one or two short sentences, how many hand alerts this change had and the logged diaper's time "
                             "and content.",
                             schema(CONTENT), lambda wet=False, solid=False: self.finish(wet=wet, solid=solid, via="brain")))
        self.starts = {phrase(p) for p in self.cfg.get("start_phrases", START_PHRASES)}
        self.finishes = {phrase(p) for p in self.cfg.get("finish_phrases", FINISH_PHRASES)}
        self.fallback_s = self.cfg.get("phrase_fallback_s", 12)
        self.heard, self.turned = None, threading.Event()
        self.voices_before = 0
        agent.bus.subscribe(self.on_message, ["message"])
        agent.bus.subscribe(lambda event: self.turned.set(), ["turn"])
        agent.memory.remember(self.name, IDLE_FACT)

    def wanted(self, text):
        """"arm", "finish" or None for the parent's words, by the exact phrases (and a finish phrase with more words)."""
        said = phrase(text)
        if said in self.starts:
            return "arm"
        if said in self.finishes or any(said.startswith(p + " ") for p in self.finishes):
            return "finish"
        return None

    def on_message(self, event):
        """A start or finish phrase waits for the brain's turn. A finish phrase does nothing while nothing is watched."""
        text = event.get("text", "")
        action = self.wanted(text)
        if action is None or (action == "finish" and self.skill is None):
            return
        self.heard = time.monotonic()
        self.turned.clear()
        self.agent.bus.publish("phrase", skill=self.name, action=action)
        threading.Thread(target=self.fall_back, args=(action, text), name=f"{self.name}-fallback", daemon=True).start()

    def fall_back(self, action, text):
        """After the brain's turn: the phrase does the job only when the brain did not."""
        self.turned.wait(self.fallback_s)
        time.sleep(0.05)  # the tool call, if any, ran inside the turn
        if action == "arm" and self.skill is None:
            self.agent.bus.publish("phrase_fallback", skill=self.name, action=action, text=text)
            self.arm(via="phrase fallback")
        elif action == "finish" and self.skill is not None:
            self.agent.bus.publish("phrase_fallback", skill=self.name, action=action, text=text)
            self.finish(via="phrase fallback", **content_from(text))

    def start(self):
        self.preload()
        if self.cfg["arm"] == "start":
            self.arm()

    def preload(self):
        """Starts loading the next change's confirm detector in the background (changing_table.preload_confirm)."""
        if not self.cfg.get("preload_confirm") or self._confirm is not None or self.warm is not None or self.stopping:
            return
        self.loader = self.loader or ThreadPoolExecutor(max_workers=1)
        started = time.monotonic()
        self.warm = self.loader.submit(confirm_mod.build, self.skill_cfg["confirm"])
        self.warm.add_done_callback(lambda done: None if done.cancelled() or done.exception() else self.agent.bus.publish(
            "confirm_ready", provider=getattr(done.result(), "name", None), load_s=round(time.monotonic() - started, 3)))

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

    def arm(self, via="direct"):
        """Never waits for a loading detector while holding the lock, so "done" always answers."""
        with self.lock:
            if self.skill is not None or self.arming:
                return "already watching the changing table"
            self.arming = True
            self.voices_before = self.agent.bus.count("voice")
        try:
            detector = self._confirm or self.kept or self.take_warm()  # kept: an arm that failed after taking it
            if self.cfg.get("keep_confirm") and self._confirm is None and detector is not None \
                    and not isinstance(detector, confirm_mod.NoConfirm):
                self.kept, detector = detector, KeptConfirm(detector)
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
                since = None if self.heard is None else round(time.monotonic() - self.heard, 3)
                self.agent.bus.publish("changing_armed", via=via, since_words_s=since)
                self.heard = None
        finally:
            self.arming = False
        if isinstance(detector, confirm_mod.NoConfirm) and self._confirm is None:
            self.agent.say(self.cfg["channel"], REGIONS_ONLY)
            return REGIONS_ONLY_TOOL
        return "watching the changing table"

    def finish(self, wet=False, solid=False, via="direct"):
        """Closes the watch and logs the diaper with its content. The brain's tool gets the entry as Baby Buddy stores
        it, read back after the write, to speak the summary from. Any other caller leaves an observation for the brain."""
        with self.lock:
            if self.skill is None:
                return "the changing table was not being watched"
            self.source.close()
            self.thread.join(timeout=5)
            self.skill.close(content={"wet": bool(wet), "solid": bool(solid)})
            closed = next(e for e in reversed(self.agent.bus.history) if e["kind"] == "skill_closed")
            alerts = self.agent.bus.count("voice") - self.voices_before
            summary = self.logged(alerts)
            if via != "brain":
                self.agent.bus.publish("observation", source=self.name, channel=self.cfg["channel"],
                                       text=f"A diaper change just finished at the changing table. Hand alerts spoken: {closed['voices']}. {summary}")
            self.skill, self.source, self.thread = None, None, None
            self.agent.memory.remember(self.name, IDLE_FACT)
            self.agent.memory.remember(LAST_CHANGE, summary)
            if self.kept is not None:  # keep_confirm: the same loaded detector waits for the next change
                self.warm = Future()
                self.warm.set_result(self.kept)
                self.kept = None
            self.preload()
            return summary if via == "brain" else "diaper change logged"

    def logged(self, alerts):
        """What the change left in Baby Buddy, read back from its API, in words the brain can say."""
        moments = f"Hand alerts spoken this change: {alerts}."
        tracked = next((e for e in reversed(self.agent.bus.history) if e["kind"] in ("tracked", "track_dry", "track_error")
                        and e.get("entry") == "changes"), None)
        if tracked is None or tracked["kind"] != "tracked":
            return f"{moments} The diaper could not be logged in Baby Buddy."
        entry = self.skill.tracker.read("changes", tracked.get("id"))
        if entry is None:
            return f"{moments} The diaper was logged in Baby Buddy as entry {tracked.get('id')}, but reading it back failed."
        self.agent.bus.publish("change_read_back", id=entry.get("id"), time=entry.get("time"), wet=entry.get("wet"),
                               solid=entry.get("solid"))
        at = local_hhmm(entry.get("time"))
        return f"{moments} Read back from Baby Buddy: entry {entry.get('id')}, diaper at {at}, {describe(entry)}."

    def stop(self):
        self.stopping = True
        self.finish()
        if self.kept is not None:  # kept by an arm that never started watching
            getattr(self.kept, "close", lambda: None)()
            self.kept = None
        if self.warm is not None:
            try:
                getattr(self.warm.result(timeout=60), "close", lambda: None)()
            except Exception:  # a detector that never loaded has nothing to close
                pass
            self.warm = None
        if self.loader:
            self.loader.shutdown(wait=False)
