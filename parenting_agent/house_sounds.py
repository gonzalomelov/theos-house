"""House sounds as an agent plug-in: cry, doorbell and dog become events the agent acts on (issues #14 and #32).

Add "parenting_agent.house_sounds:HouseSounds" to the agent config plugins, with an optional "house_sounds" block:
    {"source": "camera" | "none", "listener": {"python": ..., "model_dir": ...}, "pronoun": "he",
     "white_noise": {"bedtime": "20:30", "timer_min": 30, "calibration": [[1.0, 70.0]]}, "poll_s": 30}
The log is read the way the daily rhythm reads it (the "rhythm" block: Baby Buddy or the simulated-week fixture).

- Doorbell: during an armed skill (hands on the baby) it publishes a "notify" that the channel router sends to the
  ear, and an observation so the brain can offer to answer the visitor, which waits for the parent's yes. Otherwise a
  plain notify, which the router sends where the parent is.
- Cry: a "cry_reason" event with the ranked reasons and the evidence from the log, then a notify with the top reason.
  A short cry at night turns the white noise on first and only wakes the parent on duty if the crying comes back
  within fuss_wait_s.
- Dog: a "house_sound" event only, for the log of the day.
- White noise: on before the nap or bedtime the rhythm expects, timer down once he sleeps, all dry run.
Audio never leaves the Ear in parenting_agent/hearing.py, only labels and numbers reach this plug-in.
"""
import datetime
import os
import threading

from . import cry_reason, hearing
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .rhythm import patterns
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .rhythm.engine import make_log
from .white_noise import SimulatedWhiteNoise, WhiteNoisePlan

DEFAULTS = {"source": "none", "listener": {}, "pronoun": "he", "white_noise": {}, "poll_s": 30, "tell_agent": True}


def active_skill(agent):
    for plugin in getattr(agent, "plugins", []):
        if getattr(plugin, "kind", "") == "skill" and getattr(plugin, "skill", None) is not None:
            return plugin.name
    return None


class HouseSounds(Plugin):
    name = "house-sounds"
    kind = "ears"

    def __init__(self, agent, config, listener=None, log=None, clock=None, device=None):
        super().__init__(agent, config)
        self.cfg = {**DEFAULTS, **config.get("house_sounds", {})}
        self.rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self._log, self._listener, self.ear = log, listener, None
        wn = self.cfg["white_noise"]
        self.device = device or SimulatedWhiteNoise(agent.bus, wn.get("calibration"))
        self.plan = WhiteNoisePlan(self.device, {"utc_offset_h": self.rhythm["utc_offset_h"], **wn})
        self.fuss = None
        self.handled = set()
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.threads = []
        agent.tools.add(Tool("why_crying", "The most likely reasons the baby is crying right now, ranked, with the evidence "
                             "from the baby log (time since the last feed, last diaper, time awake). Never a medical reason.",
                             schema({}), lambda: self.reason(None)["text"]))
        agent.bus.subscribe(self.on_sound, ["sound"])

    @property
    def log(self):
        if self._log is None:
            self._log = make_log(self.rhythm, os.environ)
        return self._log

    def listen(self):
        """The Ear, built on first use so a config without a source never starts the model worker."""
        if self.ear is None:
            self.ear = hearing.Ear(self._listener or hearing.PannsListener(self.cfg["listener"]), self.agent.bus,
                                   self.cfg.get("ear"))
        return self.ear

    def start(self):
        self.threads.append(threading.Thread(target=self.run_plan, name="white-noise", daemon=True))
        if self.cfg["source"] == "camera":
            self.threads.append(threading.Thread(target=self.run_camera, name="house-sounds", daemon=True))
        for thread in self.threads:
            thread.start()

    def run_camera(self):
        while not self.stopped.is_set():
            try:
                ear = self.listen()
                for chunk in hearing.camera_seconds(hearing.camera_url()):
                    if self.stopped.is_set():
                        return
                    ear.feed(chunk)
            except (ConnectionError, OSError, KeyError, hearing.Unavailable) as error:
                self.agent.bus.publish("hearing_error", error=hearing.mask(str(error))[:300])
                self.stopped.wait(10)

    def run_plan(self):
        while not self.stopped.is_set():
            try:
                self.tick(self.clock())
            except Exception as error:  # a bad read must not stop the agent
                self.agent.bus.publish("white_noise_error", error=str(error)[:300])
            self.stopped.wait(self.cfg["poll_s"])

    def tick(self, now):
        with self.lock:
            events = self.plan.tick(self.log.entries(), now)
            if self.fuss and now >= self.fuss["until"]:
                self.agent.bus.publish("fuss_settled", episode=self.fuss["episode"], seconds=self.fuss["seconds"])
                self.fuss = None
            return events

    def stop(self):
        self.stopped.set()
        if self.ear is not None and hasattr(self.ear.listener, "close"):
            self.ear.listener.close()

    def reason(self, features, now=None):
        return cry_reason.explain(self.log.entries(), now or self.clock(), self.tz, features, self.cfg["pronoun"])

    def notify(self, text, **fields):
        return self.agent.bus.publish("notify", text=text, **fields)

    def on_sound(self, event):
        label = event["label"]
        if label == "doorbell" and event["phase"] == "start":
            self.on_doorbell(event)
        elif label == "cry" and event["phase"] in ("end", "ongoing") and event["episode"] not in self.handled:
            self.handled.add(event["episode"])
            self.on_cry(event)
        elif event["phase"] == "start":
            self.agent.bus.publish("house_sound", label=label, source=event.get("source"), peak=event.get("peak"))

    def on_doorbell(self, event):
        skill = active_skill(self.agent)
        self.agent.bus.publish("house_sound", label="doorbell", source=event.get("source"), peak=event.get("peak"),
                               skill_active=skill is not None, skill=skill)
        if skill:
            self.notify("Doorbell at the front door. Your hands stay on the baby, I can ask the visitor to wait.",
                        sound="doorbell", skill=skill)
            if self.cfg["tell_agent"]:
                self.agent.bus.publish("observation", source=self.name, channel="auto",
                                       text=f"The doorbell just rang at the front door. The parent is at the {skill} "
                                            "with both hands on the baby.")
        else:
            self.notify("Doorbell at the front door.", sound="doorbell")

    def on_cry(self, event):
        now = self.clock()
        features = event.get("features") or {}
        with self.lock:
            result = self.reason(features, now)
            night = patterns.is_night(now.astimezone(self.tz))
            fussing_again = self.fuss is not None and now < self.fuss["until"]
            self.agent.bus.publish("cry_reason", episode=event["episode"], top=result["top"], text=result["text"],
                                   ranked=result["ranked"], computed_from=result["computed_from"],
                                   cry_seconds=event["seconds"], features=features, night=night)
            if night and event["phase"] == "end" and not fussing_again:
                fuss = self.plan.night_fuss(now, event["seconds"])
                if fuss is not None:
                    self.fuss = {"episode": event["episode"], "seconds": event["seconds"],
                                 "until": now + datetime.timedelta(seconds=self.plan.s["fuss_wait_s"])}
                    return result
            text = result["text"]
            if night:
                on_duty = self.on_duty(now)
                text += f" {on_duty} is on duty."
            self.fuss = None
            self.notify(text, sound="cry", reason=result["top"])
            return result

    def on_duty(self, now):
        handled = [w["parent"] for w in patterns.night_wakeups(self.log.entries(), self.tz) if w["at"] < now]
        return patterns.next_on_duty(handled, self.rhythm["parents"])
