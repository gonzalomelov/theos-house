"""The 3 AM feed (issue #110): the house gets the night feed ready before the parent on duty is up.

The next feed comes from the log rhythm, the same way the families bot computes it: feeds that start within 30 minutes
of the one before fold into one (families.service.sessions), then patterns.next_feed takes the median of the last
gaps. When that feed falls in the night (22:00 to 06:00), lead_min minutes before it, or the moment a cry starts on
the Tapo microphone at night (a "sound" event from house_sounds) while the feed is due within cry_window_min or
overdue, or a second cry within again_min of one that did not look like a feed, the house gets ready once. A cry
while the house is ready and no feed is logged yet means the feed is later than the rhythm said: the warmer goes on
again if its auto off ran.

- the bottle warmer plug turns on. The plug is not bought yet, so it is a VirtualSwitch (dry, virtual_devices.py)
  with a hard auto off after warmer_max_on_min. The warmer holds water only: the bottle stays in the fridge until the
  parent is up, so no milk waits out of the fridge for the plan.
- the study light goes on, dim and warm, through house_tools (dry while house.live is false).
- the white noise goes down to a share of its level, if it is on (the house_sounds device).
- one push to the parent on duty from the night rota (patterns.next_on_duty over the night wake-up notes).

The parent logs the feed by voice: a Telegram voice note, the Echo or Assist through voice_bridge.py. A feed in the
log after the episode started turns the warmer off at once (the bottle is out), and after_feed_min after that feed
started the light goes off and the white noise goes back to its level. Without a feed log reminder_min after the
expected time, one reminder says how to log it by voice. The warmer runs when a bottle was logged in the last 24 hours by
default ("warmer": "bottle_days"), or "always" or "never". Every step is a "night_feed"
event. The texts state times and actions only, never advice (patterns.no_advice).

Add "parenting_agent.night_feed:NightFeed" to the agent plugins, after "parenting_agent.house_tools:HouseTools" and
"parenting_agent.house_sounds:HouseSounds" when they are used. Settings live under "night_feed", see DEFAULTS. "push"
maps a rota name to "gonza" (his iPhone through push_gonza) or "notify" (a notify event the router delivers).
"""
import datetime
import os
import threading

from .agent.plugins import Plugin
from .rhythm import patterns
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .rhythm.engine import make_log
from .virtual_devices import SHOPPING, VirtualSwitch

DEFAULTS = {"lead_min": 10, "cry_window_min": 45, "late_window_min": 30, "warmer_max_on_min": 30, "light_pct": 10,
            "white_noise_share": 0.5, "reminder_min": 30, "after_feed_min": 30, "give_up_min": 120, "warmer": "bottle_days", "again_min": 15, "max_gap_h": 6, "poll_s": 30,
            "warmer_entity": "switch.bottle_warmer_plug", "push": {}}
WARMER_CAP_MIN = 45  # no setting keeps the warmer on longer than this


def find_plugin(agent, name):
    return next((p for p in getattr(agent, "plugins", []) if getattr(p, "name", "") == name), None)


def predict(rows, now, max_gap_h=6):
    """The next feed from the log, or None before two feeds or when the last feed is too old to guess from."""
    from .families.service import sessions  # the families rhythm: a top-up within 30 min is the same feed
    rows = sessions(rows)
    feeds = patterns.feeds(rows, now)
    if not feeds or now - patterns.when(feeds[-1]) > datetime.timedelta(hours=max_gap_h):
        return None
    return patterns.next_feed(rows, now)


class NightFeed(Plugin):
    name = "night-feed"

    def __init__(self, agent, config, log=None, clock=None, warmer=None):
        super().__init__(agent, config)
        self.s = {**DEFAULTS, **(config.get("night_feed") or {})}
        self.rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self._log = log
        self.warmer = warmer or VirtualSwitch(agent.bus, self.s["warmer_entity"], "bottle warmer",
                                              min(self.s["warmer_max_on_min"], WARMER_CAP_MIN), SHOPPING["bottle_warmer"])
        self.episode, self.done, self.last_skip = None, set(), None
        # Set by the house brain (house_brain.py) from a checked Muse plan: {"prewarm": [moments], "on_duty": name}.
        # With a plan the warmer goes on at the planned moments instead of the rhythm lead. The cry trigger, the
        # warmer's hard auto off and the wind-down stay as they are. None runs the fixed rules.
        self.plan = None
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        agent.bus.subscribe(self.on_sound, ["sound"])

    @property
    def log(self):
        if self._log is None:
            self._log = make_log(self.rhythm, os.environ)
        return self._log

    def start(self):
        threading.Thread(target=self.run, name="night-feed", daemon=True).start()

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.tick(self.clock())
            except Exception as error:  # a bad read must not stop the agent
                self.agent.bus.publish("night_feed_error", error=str(error)[:300])
            self.stopped.wait(self.s["poll_s"])

    def event(self, step, now, **fields):
        return self.agent.bus.publish("night_feed", step=step, at=now.astimezone(self.tz).isoformat(timespec="seconds"), **fields)

    # When

    def next_night_feed(self, now):
        nxt = predict(self.log.entries(), now, self.s["max_gap_h"])
        if nxt and patterns.is_night(nxt["at"].astimezone(self.tz)):
            return nxt
        return None

    def tick(self, now):
        with self.lock:
            self.warmer.tick(now)
            if self.episode:
                return self.follow(now)
            if self.plan is not None and self.plan.get("prewarm") is not None:
                return self.planned(now)
            nxt = self.next_night_feed(now)
            if not nxt or nxt["computed_from"][-1] in self.done:
                return None
            lead = datetime.timedelta(minutes=self.s["lead_min"])
            late = datetime.timedelta(minutes=self.s["late_window_min"])
            if nxt["at"] - lead <= now < nxt["at"] + late:
                return self.prepare(now, nxt, f"night feed expected around {self.hhmm(nxt['at'])}")
            return None

    def planned(self, now):
        late = datetime.timedelta(minutes=self.s["late_window_min"])
        for moment in self.plan.get("prewarm") or []:
            key = f"plan@{moment.isoformat()}"
            if key not in self.done and moment <= now < moment + late:
                nxt = predict(self.log.entries(), now, self.s["max_gap_h"])
                return self.prepare(now, nxt, f"Muse plan: warm at {self.hhmm(moment)}", trigger="plan", key=key)
        return None

    def on_sound(self, event):
        if event.get("label") != "cry" or event.get("phase") not in ("start", "ongoing"):
            return
        now = self.clock()
        if not patterns.is_night(now.astimezone(self.tz)):
            return
        with self.lock:
            if self.episode:
                if self.episode.get("logged") is None:
                    self.rewarm(now)
                return
            nxt = predict(self.log.entries(), now, self.s["max_gap_h"])
            again = self.last_skip is not None and now - self.last_skip <= datetime.timedelta(minutes=self.s["again_min"])
            if nxt and nxt["at"] - now > datetime.timedelta(minutes=self.s["cry_window_min"]) and not again:
                self.last_skip = now
                self.event("skip", now, reason=f"cry heard, but the next feed is expected around {self.hhmm(nxt['at'])}, "
                                               f"{round((nxt['at'] - now).total_seconds() / 60)} min away",
                           computed_from=nxt["computed_from"])
                return
            if again:
                why = f"crying again within {self.s['again_min']} min of a cry that did not look like a feed"
            elif nxt:
                why = f"cry heard, feed expected around {self.hhmm(nxt['at'])}"
            else:
                why = "cry heard at night, too few recent feeds in the log to predict one"
            self.last_skip = None
            self.prepare(now, nxt, why, trigger="cry")

    def rewarm(self, now):
        """A cry while the house is ready and no feed is logged yet: the feed is coming now, maybe later than the rhythm
        said. The warmer's auto off starts over, and if it had already run, the warmer goes on again with one push."""
        ep = self.episode
        ep["started"] = now
        if not self.wants_warmer():
            return
        was_off = self.warmer.state == "off"
        self.warmer.on(now, "crying, the feed is coming now")
        self.event("rewarm", now, on_duty=ep["parent"], was_off=was_off)
        if was_off:
            self.push(ep["parent"], f"Crying now. Bottle warmer back on. {ep['parent']} is on duty.", now)

    # Ready

    def hhmm(self, moment):
        return patterns.hhmm(moment.astimezone(self.tz))

    def on_duty(self, now):
        if self.plan is not None and self.plan.get("on_duty") in self.rhythm["parents"]:
            return self.plan["on_duty"]
        handled = [w["parent"] for w in patterns.night_wakeups(self.log.entries(), self.tz) if w["at"] < now]
        return patterns.next_on_duty(handled, self.rhythm["parents"])

    def prepare(self, now, nxt, why, trigger="rhythm", key=None):
        key = key or (nxt["computed_from"][-1] if nxt else f"cry@{now.isoformat()}")
        self.done.add(key)
        if nxt and trigger == "plan":  # the rhythm lead does not prepare the same feed again after a fallback
            self.done.add(nxt["computed_from"][-1])
        parent = self.on_duty(now)
        self.episode = {"key": key, "started": now, "expected": nxt["at"] if nxt else now, "parent": parent,
                        "reminded": False, "noise_before": None}
        self.event("prepare", now, trigger=trigger, reason=why, on_duty=parent,
                   expected=self.hhmm(self.episode["expected"]), computed_from=(nxt or {}).get("computed_from", []))
        if self.wants_warmer():
            self.warmer.on(now, why)
            warm = "Bottle warmer on, "
        else:
            self.event("warmer", now, action="left off", reason="no bottle in the last 24 hours" if self.s["warmer"] == "bottle_days"
                       else "warmer set to never")
            warm = ""
        self.house("study_light", on=True, brightness_pct=self.s["light_pct"], warm=True)
        self.noise_down(now)
        when = f"around {self.hhmm(nxt['at'])}" if nxt else "now, a cry was heard"
        self.push(parent, f"Night feed {when}. {warm}{'study' if warm else 'Study'} light dim and warm, white noise down. "
                          f"{parent} is on duty.", now)
        return self.episode

    def wants_warmer(self):
        """always, never, or bottle_days (the default): on when a bottle was logged in the last 24 hours, so a family
        that mixes breast and bottle gets warm water on every night feed, and a breast-only one never runs it."""
        if self.s["warmer"] in ("always", "never"):
            return self.s["warmer"] == "always"
        feeds = patterns.feeds(self.log.entries(), self.clock())
        if not feeds:
            return False
        since = patterns.when(feeds[-1]) - datetime.timedelta(hours=24)
        return any("bottle" in str(e.get("method") or "").lower() for e in feeds if patterns.when(e) >= since)

    def house(self, tool, **arguments):
        plugin = find_plugin(self.agent, "house")
        if plugin is None:
            self.agent.bus.publish("house_call", action=tool, service=None, entity=None, live=False, status="dry",
                                   data=arguments, reason="no house tools loaded")
            return f"{tool}: dry run (no house tools loaded)"
        return getattr(plugin, tool)(**arguments)

    def noise_down(self, now):
        sounds = find_plugin(self.agent, "house-sounds")
        device = getattr(sounds, "device", None)
        if device is None or not device.state["on"]:
            self.event("white_noise", now, action="left", reason="white noise is off or not loaded")
            return
        self.episode["noise_before"] = device.state["level"]
        device.level(round(device.state["level"] * self.s["white_noise_share"], 2), "night feed, turned down")

    def noise_back(self):
        sounds = find_plugin(self.agent, "house-sounds")
        device = getattr(sounds, "device", None)
        before = self.episode.get("noise_before")
        if device is not None and before is not None and device.state["on"]:
            device.level(before, "night feed over, back to its level")

    def push(self, parent, text, now):
        if not patterns.no_advice(text):
            self.event("refused", now, reason="push text failed the no advice guard", text=text)
            return None
        target = (self.s["push"] or {}).get(parent, "notify")
        self.event("push", now, to=parent, via=target, text=text)
        if target == "gonza":
            return self.house("push_gonza", text=text, title="Night feed")
        return self.agent.bus.publish("notify", text=text, parent=parent, source="night_feed")

    # After

    def logged_feed(self):
        since = self.episode["started"] - datetime.timedelta(minutes=20)
        feeds = [e for e in patterns.feeds(self.log.entries()) if patterns.when(e) >= since]
        return feeds[-1] if feeds else None

    def follow(self, now):
        ep = self.episode
        if ep.get("logged") is None:
            feed = self.logged_feed()
            if feed is not None:
                ep["logged"] = {"ref": feed.get("ref"), "at": patterns.when(feed)}
                self.warmer.off(now, "feed logged, the bottle is out")
                self.event("logged", now, logged=feed.get("ref"), feed_at=self.hhmm(patterns.when(feed)))
        if ep.get("logged") is not None:
            if now >= ep["logged"]["at"] + datetime.timedelta(minutes=self.s["after_feed_min"]):
                return self.wind_down(now, f"feed logged at {self.hhmm(ep['logged']['at'])}", ep["logged"]["ref"])
            return None
        if not ep["reminded"] and now >= ep["expected"] + datetime.timedelta(minutes=self.s["reminder_min"]):
            ep["reminded"] = True
            self.push(ep["parent"], "No feed logged yet for the night feed. Say \"baby agent, fed 90 ml\" to the Echo, "
                                    "or send a voice note, and I log it.", now)
        if now >= ep["started"] + datetime.timedelta(minutes=self.s["give_up_min"]):
            return self.wind_down(now, "no feed logged, closed without one", None)
        return None

    def wind_down(self, now, why, ref):
        self.warmer.off(now, why)
        self.house("study_light", on=False)
        self.noise_back()
        self.event("done", now, reason=why, logged=ref, minutes=round((now - self.episode["started"]).total_seconds() / 60))
        ended, self.episode = self.episode, None
        return ended
