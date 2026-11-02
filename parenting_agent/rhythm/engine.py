"""The daily rhythm: the agent speaks first, from the baby log, without being asked.

tick(now) looks at the log and returns the reminders that are due right now: the next-feed warning a few
minutes before the estimated feed, a note when a full day differed from the rest, and the night summary
in the morning. Each reminder fires once. Rhythm runs it as a plug-in on the agent: it reads the log on a
timer, speaks through the agent on the configured channel, and publishes a "proactive" event with what it
was computed from. Real delivery on Telegram, the ear or the speakers comes with the channel issues.
"""
import datetime
import threading

from .. import baby_phase
from ..agent.plugins import Plugin
from . import patterns
from .log import BabyBuddyLog, FixtureLog

CHANNELS = ("ear", "speaker", "telegram", "partner_phone")
DEFAULTS = {"source": "babybuddy", "fixture": "tests/fixtures/simweek.json", "child": "Test",
            "channel": "telegram", "lead_min": 20, "summary_at": "07:30", "notes_at": "20:00",
            "parents": ["Parent A", "Parent B"], "poll_s": 60, "utc_offset_h": -3, "dawn_min": 60}


class Rhythm:
    def __init__(self, log, settings=None):
        self.log = log
        self.s = {**DEFAULTS, **(settings or {})}
        if self.s["channel"] not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}")
        self.tz = datetime.timezone(datetime.timedelta(hours=self.s["utc_offset_h"]))
        self.sent = set()

    def _at(self, now, hhmm):
        h, m = map(int, hhmm.split(":"))
        return now.astimezone(self.tz).replace(hour=h, minute=m, second=0, microsecond=0)

    def _reminder(self, key, kind, text, computed_from):
        if key in self.sent or not computed_from or not patterns.no_advice(text):
            return None
        self.sent.add(key)
        return {"kind": kind, "text": text, "computed_from": computed_from, "channel": self.s["channel"]}

    def tick(self, now):
        entries = self.log.entries()
        due = []
        nxt = patterns.next_feed(entries, now)
        if nxt:
            lead = datetime.timedelta(minutes=self.s["lead_min"])
            if nxt["at"] - lead <= now < nxt["at"] + lead:
                minutes = max(0, round((nxt["at"] - now).total_seconds() / 60))
                text = (f"Next feed in about {minutes} min, around {patterns.hhmm(nxt['at'].astimezone(self.tz))}. "
                        f"Feeds have been about {nxt['gap_min']} min apart.")
                due.append(self._reminder(("feed", nxt["computed_from"][-1]), "next_feed", text, nxt["computed_from"]))
        if now >= self._at(now, self.s["summary_at"]):
            summary = patterns.night_summary(entries, now, self.tz, self.s["parents"])
            day = now.astimezone(self.tz).date()
            due.append(self._reminder(("summary", day), "night_summary", summary["text"], summary["computed_from"]))
        if now >= self._at(now, self.s["notes_at"]):
            for note in patterns.unusual_notes([e for e in entries if patterns.when(e) <= now], self.tz):
                due.append(self._reminder(("note", note["day"], note["text"]), "unusual_day", note["text"],
                                          note["computed_from"]))
        return [r for r in due if r]


def make_log(settings, env):
    if settings.get("source") == "fixture":
        return FixtureLog(settings["fixture"])
    return BabyBuddyLog(env["BABYBUDDY_URL"], env["BABYBUDDY_TOKEN"], settings.get("child", "Test"), settings.get("tag"))


class RhythmPlugin(Plugin):
    """Agent plug-in "parenting_agent.rhythm.engine:RhythmPlugin", settings under "rhythm".

    On the family agent ("kinds": ["next_feed"]) it sends one next feed reminder per feed, lead_min before the feed
    the log rhythm expects. A feed expected deep in the night gets none: the night feed (night_feed.py) gets the house
    ready on a real awake signal instead of a guess. The first feed of the morning, expected from dawn_min before the
    night ends, does get one. The feed comes from sleep_forecast.predict_feed, the rhythm the night feed and the
    families bot read (a top-up within 30 min is the same feed, no guess from a feed older than 6 h). With the family
    push loaded the reminder is a notify event in English and Spanish: to both parents by day, and to the parent on
    duty only at night or once a parent asked to sleep tonight, so a sleeping parent is never woken by a guess. With
    no night rota to name that parent, nothing goes out at night. Without the family push it is said on the
    configured channel as before, by day only. Silent before the birth ("baby": {"born": false}, baby_phase.py)."""
    name = "rhythm"

    def __init__(self, agent, config, log=None, clock=None):
        super().__init__(agent, config)
        self.s = {**DEFAULTS, "kinds": ["next_feed", "night_summary", "unusual_day"], **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.s["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self._log = log
        self.born = baby_phase.born(config)
        self.rhythm = None
        self.sent = set()
        self.stopped = threading.Event()
        tools = getattr(agent, "tools", None)
        if self.born and tools is not None and "next_feed" not in tools.items:
            # The chat answers "¿cuándo le toca?" with the same next feed the reminders push (blind round b6).
            from ..agent.tools import Tool, schema
            tools.add(Tool("next_feed", "When the next feed is expected, from the rhythm of the baby's own log, the same "
                           "as the reminders. Use it for 'when is the next feed?' and answer with its text.",
                           schema({}), self.next_feed_text))
            tools.allowed.add("next_feed")

    def next_feed_text(self, lang=None):
        """The next feed as a sentence in lang, from sleep_forecast.predict_feed, or how the log stands."""
        from ..sleep_forecast import predict_feed
        now = self.clock()
        try:
            nxt = predict_feed(self.log.entries(), now)
        except Exception as error:  # noqa: BLE001 the tool answers that it failed, the chat goes on
            raise RuntimeError(f"the log could not be read: {str(error)[:120]}") from error
        lang = "es" if lang == "es" else "en"
        if not nxt:
            return ("Todavía no hay tomas recientes en el registro para estimar la próxima." if lang == "es"
                    else "There are no recent feeds in the log to estimate the next one from.")
        if nxt["at"] < now:
            late = round((now - nxt["at"]).total_seconds() / 60)
            at = patterns.hhmm(nxt["at"].astimezone(self.tz))
            return (f"Se esperaba una toma cerca de las {at}, hace {late} min." if lang == "es"
                    else f"A feed was expected around {at}, {late} min ago.")
        return next_feed_texts(nxt, now, self.tz)[lang]

    @property
    def log(self):
        if self._log is None:
            import os
            self._log = make_log(self.s, os.environ)
        return self._log

    def start(self):
        self.rhythm = Rhythm(self.log, self.s)
        self.thread = threading.Thread(target=self.run, name="rhythm", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.tick(self.clock())
            except Exception as error:  # a bad read must not stop the agent
                self.agent.bus.publish("rhythm_error", error=str(error)[:300])
            self.stopped.wait(self.s["poll_s"])

    def tick(self, now):
        if not self.born:
            return []
        out = []
        if "next_feed" in self.s["kinds"]:
            reminder = self.next_feed(now)
            if reminder is not None:
                out.append(reminder)
        others = [k for k in self.s["kinds"] if k != "next_feed"]
        if others and self.rhythm is not None:
            for reminder in self.rhythm.tick(now):
                if reminder["kind"] in others:
                    out.append(deliver(self.agent, reminder))
        return out

    def next_feed(self, now):
        from ..sleep_forecast import predict_feed
        nxt = predict_feed(self.log.entries(), now)
        if not nxt or self.deep_night(nxt["at"]):
            return None
        key = nxt["computed_from"][-1]
        lead = datetime.timedelta(minutes=self.s["lead_min"])
        if key in self.sent or not (nxt["at"] - lead <= now < nxt["at"] + datetime.timedelta(minutes=5)):
            return None
        pushed = any(getattr(p, "name", "") == "family-push" for p in getattr(self.agent, "plugins", []))
        night = patterns.is_night(now.astimezone(self.tz))
        duty = self.on_duty(now, night) if pushed else None
        if night and duty is None:
            return None
        self.sent.add(key)
        texts = next_feed_texts(nxt, now, self.tz)
        if not all(patterns.no_advice(t) for t in texts.values()):
            return None
        if pushed:
            to = {"parent": duty} if duty else {}
            return self.agent.bus.publish("notify", text=texts["en"], texts=texts, channel="telegram", source="rhythm",
                                          routine="next_feed", at=now.isoformat(), computed_from=nxt["computed_from"],
                                          **to)
        return deliver(self.agent, {"kind": "next_feed", "text": texts["en"], "computed_from": nxt["computed_from"],
                                    "channel": self.s["channel"]})

    def deep_night(self, t):
        """True for a feed expected at night but not in the last dawn_min before the night ends."""
        local = t.astimezone(self.tz)
        return patterns.is_night(local) and patterns.is_night(local + datetime.timedelta(minutes=self.s["dawn_min"]))

    def on_duty(self, now, night):
        """The rota label of the parent on duty when only they should get the reminder: at night, or from the evening a
        parent asked to sleep (night_feed.py). None by day otherwise, and None with no night rota."""
        rota = getattr(self.agent, "rota", None)
        if rota is None:
            return None
        ask = getattr(rota, "sleep_ask", None)
        asked = bool(ask) and ask.get("night") == rota.night_of(now, self.tz) and now.astimezone(self.tz).hour >= 12
        if not (night or asked):
            return None
        try:
            return rota.on_duty(now)
        except Exception as error:  # a bad log read: no night push rather than one to a sleeping parent
            self.agent.bus.publish("rhythm_error", error=f"night rota: {str(error)[:180]}")
            return None

    def stop(self):
        self.stopped.set()


def next_feed_texts(nxt, now, tz):
    """The reminder in both languages: when, and the gap it comes from. Times and numbers only."""
    at = patterns.hhmm(nxt["at"].astimezone(tz))
    minutes = max(0, round((nxt["at"] - now).total_seconds() / 60))
    gap = nxt["gap_min"]
    hours = f"{gap // 60} h {gap % 60:02d} min" if gap >= 60 else f"{gap} min"
    return {"en": f"Next feed in about {minutes} min, around {at}. Feeds have been about {hours} apart.",
            "es": f"Próxima toma en unos {minutes} min, cerca de las {at}. Las tomas vienen cada {hours} más o menos."}


def deliver(agent, reminder):
    """Speak a reminder through the agent on its channel and record it on the bus. Returns the delivery event."""
    agent.say(reminder["channel"], reminder["text"])
    return agent.bus.publish("proactive", channel=reminder["channel"], reminder=reminder["kind"],
                             text=reminder["text"], computed_from=reminder["computed_from"], asked=False)
