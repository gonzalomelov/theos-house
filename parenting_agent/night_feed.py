"""The 3 AM feed (issue #110): the house gets the night feed ready once the baby is awake, never on a guess.

The next feed comes from the log rhythm, the same way the families bot computes it: feeds that start within 30 minutes
of the one before fold into one (sleep_forecast.sessions), then patterns.next_feed takes the median of the last
gaps. That guess can be more than an hour off, so it never touches the nursery or the parent. When the guessed feed
falls in the night (22:00 to 06:00), lead_min minutes before it (or at a Muse plan moment, house_brain.py) the house
may only pre-warm the bottle warmer, silently: water only, a dry virtual plug today, no light, no white noise change,
no push.

The house acts only on a real awake signal:
- a cry on the Tapo microphone at night (a "sound" event from house_sounds) while the feed is due within
  cry_window_min or overdue, or while a pre-warm is running, or a second cry within again_min of one that did not look
  like a feed.
- a parent message at night that says the baby is up or a feed is starting, in English or Spanish ("he's up", "Theo is
  crying", "se despertó", "está llorando", "starting a bottle"), never the parent or the dog ("I woke up to pee", "the
  dog is up"),
  typed on Telegram or said to the Echo or Assist through voice_bridge.py. A question is not a signal.
- a "baby_awake" event, the bus event a "he's up" button publishes.
- a wake-up, a night wake-up note or a feed newly written to the log at night.

Awake means:
- the bottle warmer plug on (VirtualSwitch, dry, virtual_devices.py) with a software auto off after warmer_max_on_min. The
  warmer holds water only: the bottle stays in the fridge until the parent is up, so no milk waits out of the fridge.
- the study light on, dim and warm, unless he sleeps somewhere else at night (night_bed below). Live since Oct 30 on
  the family agent when "night_feed_light" is in house.live_actions (house_live.py): on only from this awake path,
  off only when the same episode turned it on for real, at most 6 writes a night. Otherwise it goes through house_tools as a dry run.
- the white noise down to a share of its level, if it is on (the house_sounds device).
- one push to the parent on duty from the night rota (patterns.next_on_duty over the night wake-up notes), unless the
  signal came from the log, where a parent is already up and logging.

A cry while awake and no feed logged yet means the feed is coming now: the warmer's auto off starts over, and if it had
already run, the warmer goes on again with one push. Every switch-on counts against one per-night total
(warmer_night_max_min, never more than WARMER_NIGHT_CAP_MIN): once the night's minutes are used, the warmer stays off
until the next night. The count lives in memory, so an agent restart in the night starts it over.

The parent logs the feed by voice. A feed in the log turns the warmer off at once (the bottle is out), and
after_feed_min after that feed started the light goes off and the white noise goes back to its level. Only once the
baby is known awake, and without a feed log reminder_min after that, one reminder says how to log it by voice. A
pre-warm with no awake signal closes quietly. The warmer runs when a bottle was logged in the last 24 hours by default
("warmer": "bottle_days"), or "always" or "never". Every step is a "night_feed" event. The texts state times and
actions only, never advice (patterns.no_advice).

"night_bed" says where he sleeps at night when it is not near the study: {"from": "22:00", "to": "06:00", "en": "...",
"es": "..."}. Theo sleeps in his bassinet, next to the parents' bed, from 22:00 to 06:00. In that window the
night feed never turns the study light on or off, not even as a dry run, and the push says where he is instead. Before
Oct 31 the 02:50 push named the study light while he was in his bassinet. A place that reads as bed sharing ("colecho") is refused.

Add "parenting_agent.night_feed:NightFeed" to the agent plugins, after "parenting_agent.house_tools:HouseTools" and
"parenting_agent.house_sounds:HouseSounds" when they are used. Settings live under "night_feed", see DEFAULTS. "push"
maps a rota name to "gonza" (his iPhone through push_gonza) or "notify" (a notify event the router delivers).
"""
import datetime
import os
import re
import threading

from . import baby_phase
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .agent.people import People
from .agent.awake_words import (BABY_EN, BABY_WORD, EN_AWAKE, ES_AWAKE, FEED_RE, I_EN, NOT_RE,  # noqa: F401
                                OTHER_RE, QUESTION_RE, awake_message)
from .house import HomeAssistant
from .house_live import STUDY_LIGHT, gate_for, live_actions
from .house_plan import add_dry_guard
from .rhythm import patterns
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .rhythm.engine import make_log
from .sleep_forecast import predict_feed
from .virtual_devices import SHOPPING, VirtualSwitch

DEFAULTS = {"lead_min": 10, "cry_window_min": 45, "late_window_min": 30, "warmer_max_on_min": 30, "light_pct": 10,
            "white_noise_share": 0.5, "reminder_min": 30, "after_feed_min": 30, "give_up_min": 120, "warmer": "bottle_days",
            "again_min": 15, "max_gap_h": 6, "poll_s": 30, "warmer_night_max_min": 90, "log_signal_min": 20,
            "warmer_entity": "switch.bottle_warmer_plug", "push": {}, "night_bed": None}
WARMER_CAP_MIN = 45  # no setting keeps the warmer on longer than this in one go
WARMER_NIGHT_CAP_MIN = 120  # no setting lets the warmer run longer than this in one night, all switch-ons together

# The awake signal words (the baby, never a parent or the dog) are in agent/awake_words.py, which the demo shares.
# A parent asking to sleep tonight: the other parent takes the night (Oct 30, Ceci: "necesito dormir esta noche").
SLEEP_ASK = re.compile(r"\b(?:necesito|quiero|preciso|dejame|déjame|d[ée]jenme)\s+dormir\b|\bme dejan dormir\b|"
                       r"\b(?:I )?need (?:to|some) sleep\b|\blet me sleep\b|\bI want to sleep\b", re.I)
SIGNAL = {"cry": "a cry was heard", "parent": "a parent said so", "button": "he's up was tapped", "log": "it is in the log"}
SIGNAL_ES = {"cry": "se oyó un llanto", "parent": "lo avisó un padre", "button": "tocaron se despertó",
             "log": "está en el registro"}


def find_plugin(agent, name):
    return next((p for p in getattr(agent, "plugins", []) if getattr(p, "name", "") == name), None)


def predict(rows, now, max_gap_h=6):
    """The next feed from the log, or None before two feeds or when the last feed is too old to guess from. The
    families rhythm: a top-up within 30 min is the same feed (sleep_forecast.sessions)."""
    return predict_feed(rows, now, max_gap_h)


# Words that read as the baby sharing the parents' bed: the night push never says them.
BED_SHARING = re.compile(r"colecho|co-?sleep\w*|bed[ -]?shar\w*|side bed|en (la|nuestra|su) cama|in (our|your|the) bed",
                         re.I)


class NightFeed(Plugin):
    name = "night-feed"

    def __init__(self, agent, config, log=None, clock=None, warmer=None, client=None):
        super().__init__(agent, config)
        self.s = {**DEFAULTS, **(config.get("night_feed") or {})}
        bed = self.s["night_bed"] or {}
        if any(BED_SHARING.search(str(bed.get(lang) or "")) for lang in ("en", "es")):
            # "Está en el colecho" read as bed sharing in the night push (blind round b6), which the AAP line says no to.
            raise ValueError("night_bed must name where he sleeps on his own, for example \"su cunita, al lado de la cama "
                             "de ustedes\", never a shared bed")
        self.rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=self.rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        house_cfg = config.get("house") or {}
        if client is None and "night_feed_light" in live_actions(house_cfg):
            token = os.environ.get(house_cfg.get("ha_token_env", "HA_MCP_TOKEN"))
            client = HomeAssistant(house_cfg.get("ha_url", "http://127.0.0.1:18123"), token) if token else None
        self.gate = gate_for(agent, config, client, self.clock)
        add_dry_guard(agent)
        self._log = log
        self.warmer = warmer or VirtualSwitch(agent.bus, self.s["warmer_entity"], "bottle warmer",
                                              min(self.s["warmer_max_on_min"], WARMER_CAP_MIN), SHOPPING["bottle_warmer"])
        self.night_cap_min = min(self.s["warmer_night_max_min"], WARMER_NIGHT_CAP_MIN)
        self.night, self.night_base = None, 0.0
        self.episode, self.done, self.last_skip = None, set(), None
        self.seen = None  # log refs already looked at for a wake-up signal, filled on the first tick
        # Set by the house brain (house_brain.py) from a checked Muse plan: {"prewarm": [moments], "on_duty": name}.
        # With a plan the silent pre-warm runs at the planned moments instead of the rhythm lead. The awake signals,
        # the warmer's caps and the wind-down stay as they are. None runs the fixed rules.
        self.plan = None
        self.born = baby_phase.born(config)
        self.sleep_ask = None  # {"night": the evening's date, "person": who asked to sleep, "label": their rota label}
        self.lock = threading.RLock()  # a step publishes on the bus, a handler may come back in on the same thread
        self.stopped = threading.Event()
        agent.bus.subscribe(self.on_sound, ["sound"])
        agent.bus.subscribe(self.on_message, ["message"])
        agent.bus.subscribe(self.on_awake, ["baby_awake"])
        self.people = getattr(agent, "people", None) or People(config.get("people"))
        self.others = [self.people.name(p) for p in self.people.keys()]
        agent.rota = self
        agent.tools.add(Tool("night_rota", "Who is on duty tonight and how the night rota decides it, by name. Changes "
                             "nothing.", schema({}), lambda: self.answer("en")))

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

    def is_night(self, now):
        return patterns.is_night(now.astimezone(self.tz))

    # When

    def next_night_feed(self, now):
        nxt = predict(self.log.entries(), now, self.s["max_gap_h"])
        if nxt and self.is_night(nxt["at"]):
            return nxt
        return None

    def tick(self, now):
        if not self.born:
            return None  # before the birth the log is a test child: nothing to warm, nobody to wake
        with self.lock:
            self.warmer.tick(now)
            self.night_cap(now)
            signal = self.log_signal(now)
            if signal is not None:
                self.awake(now, "log", signal)
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
                return self.prewarm(now, nxt, f"night feed guessed around {self.hhmm(nxt['at'])}")
            return None

    def planned(self, now):
        late = datetime.timedelta(minutes=self.s["late_window_min"])
        for moment in self.plan.get("prewarm") or []:
            key = f"plan@{moment.isoformat()}"
            if key not in self.done and moment <= now < moment + late:
                nxt = predict(self.log.entries(), now, self.s["max_gap_h"])
                return self.prewarm(now, nxt, f"Muse plan: warm at {self.hhmm(moment)}", trigger="plan", key=key)
        return None

    # Awake signals

    def log_signal(self, now):
        """A wake-up, a night wake-up note or a feed that is new in the log and recent, at night: the baby is awake."""
        rows = self.log.entries()
        refs = {e.get("ref") for e in rows if e.get("ref")}
        if self.seen is None:
            self.seen = refs
            return None
        new = [e for e in rows if e.get("ref") and e["ref"] not in self.seen]
        self.seen |= refs
        recent = datetime.timedelta(minutes=self.s["log_signal_min"])
        for e in new:
            if e["kind"] == "feeding":
                moment, what = patterns.when(e), "feed"
            elif e["kind"] == "sleep" and e.get("end"):
                moment, what = patterns.parse(e["end"]), "wake-up"
            elif e["kind"] == "note" and re.search(r"\b(wake|woke|awake|up)\b", e.get("note") or "", re.I):
                moment, what = patterns.when(e), "wake-up note"
            else:
                continue
            if self.is_night(now) and now - recent <= moment <= now + datetime.timedelta(minutes=1):
                return f"{what} logged at {self.hhmm(moment)}"
        return None

    def on_message(self, event):
        if not self.born:
            return
        now = self.clock()
        if SLEEP_ASK.search(str(event.get("text") or "")):
            self.asked_to_sleep(event.get("person"), now)
            return
        self.message_awake(event, now)

    def message_awake(self, event, now=None):
        """The night feed for a parent's "he just woke up": the episode, once, whether the bus or the agent's reply asks
        first. None when the message is no awake signal, by day, or before the birth."""
        now = now or self.clock()
        what = awake_message(event.get("text"), self.others)
        if not self.born or what is None or not self.is_night(now):
            return None
        with self.lock:
            # The parent who says he is up already knows: the house gets ready, the push goes only to someone else.
            duty = self.people.person(self.on_duty(now))
            push = what == "awake" and not (event.get("person") and event.get("person") == duty)
            return self.awake(now, "parent", f"a parent said \"{str(event.get('text'))[:80]}\"", push=push,
                              by=event.get("person"))

    def wake_step(self, event, lang="en"):
        """What the house did for a parent's "he just woke up", for the reply to that parent, or None. It says what
        moved for real and what was only written down (dry run)."""
        ep = self.message_awake(event)
        house = (ep or {}).get("house")
        if not house:
            return None
        light, warm, noise = house
        name = self.people.display(ep["parent"])
        if lang == "es":
            return self.awake_text_es("parent", light, warm, noise, name).split(". ", 1)[1].replace(
                f"Estás de turno, {name}.", f"De turno: {name}.")
        return self.awake_text("parent", light, warm, noise, name).split(". ", 1)[1]

    @staticmethod
    def night_of(now, tz):
        """The evening a night belongs to: 22:00 and 03:00 are the same night."""
        return (now.astimezone(tz) - datetime.timedelta(hours=12)).date()

    def asked_to_sleep(self, person, now):
        """A parent asked to sleep tonight: the other parent is on duty, and is told once."""
        label = self.people.label(person) if person else None
        others = [p for p in self.rhythm["parents"] if p != label]
        local = now.astimezone(self.tz)
        if label is None or len(others) != 1 or 6 <= local.hour < 12:
            return None
        night = self.night_of(now, self.tz)
        if self.sleep_ask and self.sleep_ask["night"] == night and self.sleep_ask["person"] == person:
            return None
        self.sleep_ask = {"night": night, "person": person, "label": label, "on_duty": others[0]}
        asker, duty = self.people.display(label), self.people.display(others[0])
        self.event("handover", now, asked=asker, on_duty=duty)
        texts = {"en": f"{asker} asked to sleep tonight, so you are on duty tonight, {duty}. Night pushes go to you only.",
                 "es": f"{asker} pidió dormir esta noche, así que esta noche estás de turno vos, {duty}. "
                       "Los avisos de la noche te llegan solo a vos."}
        return self.agent.bus.publish("notify", text=texts["en"], texts=texts, parent=others[0], source="night_feed",
                                      routine="handover")

    def on_awake(self, event):
        now = self.clock()
        if not self.born or not self.is_night(now):
            return
        with self.lock:
            self.awake(now, "button", f"{event.get('by') or 'a parent'} tapped he's up")

    def on_sound(self, event):
        if event.get("label") != "cry" or event.get("phase") not in ("start", "ongoing"):
            return
        now = self.clock()
        if not self.born or not self.is_night(now):
            return
        with self.lock:
            if self.episode:
                if not self.episode["awake"]:
                    return self.awake(now, "cry", f"cry heard, feed expected around {self.hhmm(self.episode['expected'])}")
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
            self.awake(now, "cry", why)

    def rewarm(self, now):
        """A cry while awake and no feed logged yet: the feed is coming now, maybe later than the rhythm said. The
        warmer's auto off starts over, within the night's minutes, and if it had already run, the warmer goes on again
        with one push."""
        ep = self.episode
        ep["started"] = now
        if not self.wants_warmer():
            return
        was_off = self.warmer.state == "off"
        if not self.warm(now, "crying, the feed is coming now"):
            return
        self.event("rewarm", now, on_duty=ep["parent"], was_off=was_off)
        if was_off:
            self.push(ep["parent"], f"Crying now. Bottle warmer back on. {ep['parent']} is on duty.", now,
                      es="Está llorando. Calentador de mamadera encendido de nuevo (prueba en seco).")

    # The warmer and its night

    def night_cap(self, now):
        """The warmer's minutes tonight, all switch-ons together. A night runs from noon to noon, so 22:00 and 03:00
        are the same night. Turns the warmer off when the night's minutes are used. Returns the minutes left."""
        night = (now.astimezone(self.tz) - datetime.timedelta(hours=12)).date()
        if night != self.night:
            self.night, self.night_base = night, self.warmer.used_min(now)
        left = self.night_cap_min - (self.warmer.used_min(now) - self.night_base)
        if self.warmer.state == "on" and left <= 0:
            self.warmer.off(now, f"night cap: {self.night_cap_min} min of warmer time tonight")
            self.event("warmer", now, action="night cap", reason=f"{self.night_cap_min} min of warmer time used tonight")
        return max(0.0, left)

    def warm(self, now, why):
        left = self.night_cap(now)
        if left < 1:
            self.event("warmer", now, action="left off", reason=f"night cap: {self.night_cap_min} min of warmer time used tonight")
            return False
        self.warmer.on(now, why, max_min=left)
        return True

    # Ready

    def hhmm(self, moment):
        return patterns.hhmm(moment.astimezone(self.tz))

    def handled(self, now):
        """Who took each night wake-up so far, as rota labels: "handled by Ceci" in the log counts for her label."""
        return [self.people.rota_label(w["parent"]) for w in patterns.night_wakeups(self.log.entries(), self.tz)
                if w["at"] < now]

    def on_duty(self, now):
        ask = self.sleep_ask
        if ask and ask["night"] == self.night_of(now, self.tz):
            return ask["on_duty"]
        if self.plan is not None and self.plan.get("on_duty") in self.rhythm["parents"]:
            return self.plan["on_duty"]
        return patterns.next_on_duty(self.handled(now), self.rhythm["parents"])

    def rota_only(self, now):
        """Who the night rota alone names at now, without tonight's Muse plan: in the morning the plan is last night's."""
        return patterns.next_on_duty(self.handled(now), self.rhythm["parents"])

    def rota(self, now=None):
        """Who is on duty tonight and why, with names: {"on_duty", "person", "counts", "by_plan"}."""
        now = now or self.clock()
        label = self.on_duty(now)
        handled = self.handled(now)
        asked = self.sleep_ask is not None and self.sleep_ask["night"] == self.night_of(now, self.tz)
        by_plan = asked or (self.plan is not None and self.plan.get("on_duty") in self.rhythm["parents"])
        return {"on_duty": self.people.display(label), "person": self.people.person(label),
                "counts": {self.people.display(p): handled.count(p) for p in self.rhythm["parents"]},
                "by_plan": by_plan, "wakeups": len(handled)}

    def answer(self, lang="en", now=None):
        """The rota as a parent reads it, in plain sentences, never advice."""
        r = self.rota(now)
        counts = ", ".join(f"{name} {n}" for name, n in r["counts"].items())
        first = next(iter(r["counts"]), r["on_duty"])
        if lang == "es":
            head = f"Esta noche está de turno {r['on_duty']}."
            if r["by_plan"]:
                return head + " Lo cambió el plan de la casa porque uno de los dos pidió dormir."
            rule = ("Lo decide la rota de la noche: le toca a quien se levantó menos veces de noche, y si empatan, a quien "
                    "no se levantó la última vez.")
            seen = (f" Hasta ahora: {counts}, según las notas de despertares nocturnos del registro." if r["wakeups"] else
                    f" Todavía no hay despertares nocturnos en el registro, así que empieza {first}.")
            return f"{head} {rule}{seen}"
        head = f"{r['on_duty']} is on duty tonight."
        if r["by_plan"]:
            return head + " Tonight's house plan changed it because one of you asked to sleep."
        rule = ("The night rota decides it: whoever has taken fewer night wake-ups takes the next one, and on a tie whoever "
                "did not take the last one.")
        seen = (f" So far: {counts}, from the night wake-up notes in the log." if r["wakeups"] else
                f" No night wake-up is in the log yet, so it starts with {first}.")
        return f"{head} {rule}{seen}"

    def open_episode(self, now, nxt, key):
        self.done.add(key)
        if nxt:  # the rhythm lead does not open the same feed again
            self.done.add(nxt["computed_from"][-1])
        self.episode = {"key": key, "started": now, "expected": nxt["at"] if nxt else now, "parent": self.on_duty(now),
                        "reminded": False, "noise_before": None, "awake": False, "awake_at": None}
        return self.episode

    def prewarm(self, now, nxt, why, trigger="rhythm", key=None):
        """A guess: the warmer may go on, silently. No light, no white noise change, no push."""
        ep = self.open_episode(now, nxt, key or (nxt["computed_from"][-1] if nxt else f"{trigger}@{now.isoformat()}"))
        warmed = self.wants_warmer() and self.warm(now, why)
        self.event("prewarm", now, trigger=trigger, reason=why, warmer="on" if warmed else "off",
                   expected=self.hhmm(ep["expected"]), computed_from=(nxt or {}).get("computed_from", []))
        return ep

    def note_handled(self, now, who):
        """One "Night wake-up handled by Gonza" note in the log per awake episode: the night rota and the morning
        message count night wake-ups from these notes, and on Oct 30 the end-to-end day had none, so Gonza read "no
        te levantaste" after a night up and the rota put him on duty again."""
        name = self.people.display(who)
        log = getattr(self.agent, "baby_log", None)
        if not name or log is None or self.episode.get("noted"):
            return
        self.episode["noted"] = True
        try:
            entry = log.add("note", {"text": f"Night wake-up handled by {name}"}, ts=now.isoformat(timespec="seconds"))
            self.event("handled", now, by=name, entry=(entry or {}).get("id"))
        except Exception as error:  # noqa: BLE001 the house still gets ready when the log cannot be written
            self.event("handled", now, by=name, error=str(error)[:160])

    def awake(self, now, trigger, why, push=None, by=None):
        """A real awake signal. Opens the night feed, or turns a silent pre-warm into it, once."""
        if self.episode and self.episode["awake"]:
            return self.episode
        if self.episode is None:
            nxt = predict(self.log.entries(), now, self.s["max_gap_h"])
            self.open_episode(now, nxt, f"{trigger}@{now.isoformat()}")
        ep = self.episode
        ep.update(awake=True, awake_at=now, parent=self.on_duty(now))
        self.note_handled(now, by or ep["parent"])
        if trigger in ("cry", "button") or (trigger == "parent" and push is not False):
            push = True
        self.event("prepare", now, trigger=trigger, reason=why, on_duty=ep["parent"], expected=self.hhmm(ep["expected"]))
        warm = False
        if trigger == "log" and self.logged_feed() is not None:
            pass  # the feed is already in the log, the bottle is out
        elif self.wants_warmer():
            if self.warm(now, why):  # a pre-warm's auto off starts over, the feed is coming now
                warm = True
        else:
            self.event("warmer", now, action="left off", reason="no bottle in the last 24 hours" if self.s["warmer"] == "bottle_days"
                       else "warmer set to never")
        light = self.in_night_bed(now) or self.light(now, True, trigger, why)
        noise = self.noise_down(now)
        ep["house"] = (light, warm, noise)
        if push:
            name = self.people.display(ep["parent"])
            self.push(ep["parent"], self.awake_text(trigger, light, warm, noise, ep["parent"]), now,
                      es=self.awake_text_es(trigger, light, warm, noise, name))
        return ep

    @staticmethod
    def awake_text(trigger, light, warm, noise, parent):
        """The push says truthfully what moved in the house and what was only written down. light is a status, or
        the night_bed place when he sleeps there and no light was touched."""
        said = {"live": "Study light on, dim and warm: done for real.",
                "failed": "Study light: tried for real, Home Assistant did not take it.",
                "unavailable": "Study light: unavailable in Home Assistant, nothing moved.",
                "dry": "Study light dim and warm: only written down (dry run)."}
        said = f"He is in {light['en']}." if isinstance(light, dict) else said[light]
        dry = [w for w, on in (("bottle warmer on", warm), ("white noise down", noise)) if on]
        rest = f" {' and '.join(dry).capitalize()}: only written down (dry run)." if dry else ""
        return f"He is awake, {SIGNAL[trigger]}. {said}{rest} {parent} is on duty."

    @staticmethod
    def awake_text_es(trigger, light, warm, noise, name):
        said = {"live": "Luz del estudio encendida, tenue y cálida: de verdad.",
                "failed": "Luz del estudio: se intentó de verdad, Home Assistant no la tomó.",
                "unavailable": "Luz del estudio: no disponible en Home Assistant, no se movió nada.",
                "dry": "Luz del estudio tenue: solo anotada (prueba en seco)."}
        said = f"Está en {light['es']}." if isinstance(light, dict) else said[light]
        dry = [w for w, on in (("calentador de mamadera encendido", warm), ("ruido blanco más bajo", noise)) if on]
        rest = f" {' y '.join(dry).capitalize()}: solo anotado (prueba en seco)." if dry else ""
        return f"Se despertó, {SIGNAL_ES[trigger]}. {said}{rest} Estás de turno, {name}."

    def in_night_bed(self, now):
        """The night_bed place when he sleeps there now, and the episode keeps the study light off to its end."""
        bed = self.s["night_bed"]
        if not bed:
            return None
        hhmm = now.astimezone(self.tz).strftime("%H:%M")
        start, end = bed.get("from", "22:00"), bed.get("to", "06:00")
        inside = start <= hhmm < end if start < end else hhmm >= start or hhmm < end
        if not inside:
            return None
        self.episode["night_bed"] = True
        self.event("light", now, action="left off", reason=f"he is in {bed['en']}, no light is moved there")
        return bed

    def light(self, now, on, signal, why):
        """The study light, live through the gate when it allows, else the dry path. Returns live, failed or dry."""
        ep = self.episode or {}
        event = None
        if on:
            event = self.gate.write("night_feed", "light.turn_on", STUDY_LIGHT, {"brightness_pct": self.s["light_pct"]},
                                    f"night feed, he is awake: {why}", signal, now)
        elif ep.get("light_live"):
            event = self.gate.write("night_feed", "light.turn_off", STUDY_LIGHT, None, f"night feed over: {why}", signal, now)
        if event is not None:
            if event["status"] == "ran":
                ep["light_live"] = on
                return "live"
            return "unavailable" if event["status"] == "unavailable" else "failed"
        if on:
            self.house("study_light", on=True, brightness_pct=self.s["light_pct"], warm=True)
        else:
            self.house("study_light", on=False)
        return "dry"

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
            return False
        self.episode["noise_before"] = device.state["level"]
        device.level(round(device.state["level"] * self.s["white_noise_share"], 2), "night feed, he is awake, turned down")
        return True

    def noise_back(self):
        sounds = find_plugin(self.agent, "house-sounds")
        device = getattr(sounds, "device", None)
        before = self.episode.get("noise_before")
        if device is not None and before is not None and device.state["on"]:
            device.level(before, "night feed over, back to its level")

    def push(self, parent, text, now, es=None):
        if not patterns.no_advice(text):
            self.event("refused", now, reason="push text failed the no advice guard", text=text)
            return None
        target = (self.s["push"] or {}).get(parent, "notify")
        self.event("push", now, to=parent, via=target, text=text)
        if target == "gonza":
            return self.house("push_gonza", text=text, title="Night feed")
        texts = {"en": text, "es": es} if es else None
        return self.agent.bus.publish("notify", text=text, parent=parent, source="night_feed",
                                      **({"texts": texts} if texts else {}))

    # After

    def logged_feed(self):
        since = self.episode["started"] - datetime.timedelta(minutes=20)
        feeds = [e for e in patterns.feeds(self.log.entries()) if patterns.when(e) >= since]
        return feeds[-1] if feeds else None

    def follow(self, now):
        ep = self.episode
        if not ep["awake"]:
            if now >= ep["started"] + datetime.timedelta(minutes=self.s["give_up_min"]):
                return self.wind_down(now, "no awake signal, the pre-warm closed quietly", None)
            return None
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
        if not ep["reminded"] and now >= max(ep["expected"], ep["awake_at"]) + datetime.timedelta(minutes=self.s["reminder_min"]):
            ep["reminded"] = True
            self.push(ep["parent"], "No feed logged yet for the night feed. Say \"baby agent, fed 90 ml\" to the Echo, "
                                    "or send a voice note, and I log it.", now,
                      es="Todavía no hay toma anotada de esta noche. Mandame un audio o escribime, por ejemplo "
                         "\"le di 90 ml\", y la anoto.")
        if now >= ep["awake_at"] + datetime.timedelta(minutes=self.s["give_up_min"]):
            return self.wind_down(now, "no feed logged, closed without one", None)
        return None

    def wind_down(self, now, why, ref):
        self.warmer.off(now, why)
        if self.episode["awake"]:
            if not self.episode.get("night_bed"):
                self.light(now, False, "wind_down", why)
            self.noise_back()
        self.event("done", now, reason=why, logged=ref, minutes=round((now - self.episode["started"]).total_seconds() / 60))
        ended, self.episode = self.episode, None
        return ended
