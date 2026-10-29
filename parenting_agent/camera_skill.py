"""Camera skills from config only: a new head-camera routine is a skill file and one line of agent config.

Add "parenting_agent.camera_skill:CameraSkills" to the agent config plugins, with a "camera_skills" list:
    [{"skill": "skills/bath.json", "source": "phone" | "0" | "loop.mp4"}]
Each skill file carries an "agent" block that names its two tools and what they say, and an optional
"reminders" block with the routine steps spoken when it arms. For the bath:
    "bath time" -> start_bath: watch the head camera, speak the routine reminders on the ear
    "bath done" -> finish_bath: log the bath to Baby Buddy, read it back, tell the agent with an observation

While armed it runs the same core as the changing table: the local reflex chimes at once when both hands
leave the baby, SAM 3.1 confirms or cancels, the voice prompt plays when it is real. The skill only
listens for the parent's hands. It never watches the baby in the parent's place, and every text it speaks
is checked at start so it never says or implies the baby can be left alone.
"""
import re
import threading
import time

from . import config as config_mod
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .reflex import MediaPipeReflex
from .skill import Skill, watch
from .sources import PhoneSource, open_source
from .speaker import Speaker

# A sentence that mentions leaving or being alone is only safe when it says not to.
LEAVES = re.compile(r"\b(leav(?:e|ing) (?:her|him|them|the baby|baby)|left (?:alone|on (?:her|his|their) own)|alone|"
                    r"step(?:ping)? (?:away|out)|walk(?:ing)? away|be right back|back in a (?:sec|second|minute|moment)|"
                    r"unattended|unsupervised|on (?:her|his|their) own|go (?:and )?(?:get|answer|grab|check|open))\b", re.I)
NEGATED = re.compile(r"\b(never|not|don't|do not|no)\b", re.I)
# The parent's hands leaving the baby is what the alarm is about, not the parent leaving.
HANDS_LEAVE = re.compile(r"\bhands?\s+(?:\w+\s+){0,2}?(?:leave|leaves|leaving|left)\s+(?:the\s+)?(?:baby|her|him)\b", re.I)
TAKES_OVER = re.compile(r"\b(i'?ll|i will|i am|i'm|let me|i can)\s+(?:\w+\s+)?(watch|keep an eye|look after|mind|stay with|"
                        r"take over|hold (?:her|him|them|the baby))\b", re.I)


STAY = "Keep a hand on the baby. I can say one moment on the house speaker, hold notifications or call your partner."


def keep_with_baby(text):
    """The reply without any sentence that says or implies the parent may leave, or that the agent watches the baby.
    A reasoning brain can paraphrase a safety fact into "if you need to go, take her with you", which still describes
    going. Those sentences never reach a parent while a camera skill is on."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    kept = [s for s in sentences if s.strip() and not implies_left_alone(s)]
    if len(kept) == len([s for s in sentences if s.strip()]):
        return text
    return " ".join(kept + [STAY]) if kept else STAY


def implies_left_alone(text):
    """True when text says or implies the parent may leave the baby, or that the agent watches the baby instead."""
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        sentence = HANDS_LEAVE.sub("", sentence)
        if TAKES_OVER.search(sentence):
            return True
        if LEAVES.search(sentence) and not NEGATED.search(sentence):
            return True
    return False


def spoken_texts(skill_cfg):
    agent, reminders = skill_cfg.get("agent", {}), skill_cfg.get("reminders", {})
    texts = [v for k, v in agent.items() if not k.endswith(("_tool", "_phrases"))]
    return [skill_cfg["alarm"]["voice_text"], *texts, *reminders.values()]


AGENT_KEYS = ("start_tool", "start_description", "finish_tool", "finish_description", "armed_result", "already_armed",
              "not_armed", "finished_result", "closed_observation")


def check(skill_cfg):
    """A camera skill names its tools and texts, and none of its texts implies the baby can be left alone."""
    missing = [k for k in AGENT_KEYS if not skill_cfg.get("agent", {}).get(k)]
    if missing:
        raise config_mod.ConfigError(f"{skill_cfg['name']}: agent block lacks {', '.join(missing)}")
    for text in spoken_texts(skill_cfg):
        if implies_left_alone(text):
            raise config_mod.ConfigError(f"{skill_cfg['name']}: never imply the baby can be left alone: {text!r}")
    return skill_cfg


def phrase(text):
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


def hhmm(moment):
    return moment.astimezone().strftime("%H:%M")


class AgentLogTracker:
    """Logs the closed routine in the agent's own baby log (Baby Buddy in the real config) and keeps the record."""

    def __init__(self, config, bus, baby_log, label):
        self.cfg, self.bus, self.baby_log, self.label = config, bus, baby_log, label
        self.record = None

    def skill_closed(self, skill, started, ended):
        kind = self.cfg.get("on_closed")
        if kind == "bath":
            entry = ("bath", {"text": f"Bath {hhmm(started)} to {hhmm(ended)}, logged by the {self.label} skill"})
        else:
            return
        try:
            self.record = self.baby_log.add(*entry)
            self.bus.publish("tracked", entry=entry[0], id=self.record.get("id"))
        except Exception as error:  # a log that fails never hides the routine's end
            self.bus.publish("track_error", entry=entry[0], error=str(error)[:200])


class CameraSkill:
    """One config-driven head-camera skill: two tools, arm and finish."""

    def __init__(self, owner, entry, reflex=None, confirm_detector=None, source=None, quiet=False):
        self.owner, self.agent = owner, owner.agent
        self.cfg = {"source": "phone", "channel": "console", **entry}
        self.skill_cfg = check(config_mod.load(self.cfg["skill"]))
        self.text = self.skill_cfg["agent"]
        self.name = self.skill_cfg["name"]
        self._reflex, self._confirm, self._source, self.quiet = reflex, confirm_detector, source, quiet
        self.skill, self.source, self.thread, self.tracker, self.finished_at = None, None, None, None, None
        self.lock = threading.Lock()
        self.agent.tools.add(Tool(self.text["start_tool"], self.text["start_description"], schema({}), self.arm))
        self.agent.tools.add(Tool(self.text["finish_tool"], self.text["finish_description"], schema({}), self.finish))
        self.phrases = {**{phrase(p): self.arm for p in self.text.get("start_phrases", [])},
                        **{phrase(p): self.finish for p in self.text.get("finish_phrases", [])}}
        self.agent.bus.subscribe(self.on_message, ["message"])
        if hasattr(self.agent, "reply_guards"):
            self.agent.reply_guards.append(lambda text: keep_with_baby(text) if self.skill is not None else text)
        if self.text.get("idle_fact"):
            self.agent.memory.remember(self.name, self.text["idle_fact"])

    def on_message(self, event):
        """The exact phrases arm and finish the skill as a reflex, without waiting for the brain to pick the tool."""
        action = self.phrases.get(phrase(event.get("text", "")))
        if action:
            self.agent.bus.publish("phrase", skill=self.name, action=action.__name__)
            threading.Thread(target=action, name=f"{self.name}-{action.__name__}", daemon=True).start()

    def arm(self):
        with self.lock:
            if self.skill is not None:
                return self.text["already_armed"]
            busy = self.owner.other_armed(self)
            if busy:
                return f"another camera skill is still on ({busy}), finish it first"
            # The models load first (SAM 3.1 takes seconds), then the camera opens, so no frame waits for them.
            reflex = self._reflex or MediaPipeReflex(self.skill_cfg["contact"])
            self.tracker = AgentLogTracker(self.skill_cfg["tracking"], self.agent.bus, self.agent.baby_log, self.name)
            self.skill = Skill(self.skill_cfg, self.agent.bus, reflex, confirm_detector=self._confirm, tracker=self.tracker)
            source = self._source or (lambda: open_source(self.cfg["source"]))
            self.source = source() if callable(source) else source
            if isinstance(self.source, PhoneSource):
                self.agent.bus.publish("head_camera", url=self.source.url)
            self.speaker = Speaker(self.source, quiet=self.quiet)
            self.agent.bus.subscribe(self.speaker.on_event, ["chime", "voice"])
            self.armed_t = self.agent.bus.now()
            self.skill.arm()
            self.thread = threading.Thread(target=watch, args=(self.skill, self.source), name=self.name, daemon=True)
            self.thread.start()
            on_armed = self.skill_cfg.get("reminders", {}).get("on_armed")
            if on_armed:
                self.agent.bus.publish("notify", source=self.name, text=on_armed)
            if self.text.get("armed_fact"):
                self.agent.memory.remember(self.name, self.text["armed_fact"])
            return self.text["armed_result"] + (f" Reminder spoken to the parent: {on_armed}" if on_armed else "")

    def finish(self):
        with self.lock:
            if self.skill is None:
                recent = self.finished_at is not None and time.monotonic() - self.finished_at < 120
                return self.text["finished_result"] if recent else self.text["not_armed"]
            self.source.close()
            self.thread.join(timeout=5)
            self.skill.close()
            # This routine's listeners leave the bus, so the next bath does not speak or call twice.
            mine = (self.speaker.on_event, self.skill._on_voice)
            self.agent.bus.listeners = [item for item in self.agent.bus.listeners if item[0] not in mine]
            voices = sum(1 for e in list(self.agent.bus.history) if e["kind"] == "voice" and e["t"] >= self.armed_t)
            record = self.read_back(self.tracker.record)
            if record is not None:
                self.agent.bus.publish("read_back", entry=record["kind"], id=record.get("id"), ts=record["ts"])
            self.agent.bus.publish("observation", source=self.name, channel=self.cfg["channel"],
                                   text=self.text["closed_observation"].format(voices=voices))
            if self.text.get("idle_fact"):
                self.agent.memory.remember(self.name, self.text["idle_fact"])
            self.skill, self.source, self.thread, self.finished_at = None, None, None, time.monotonic()
            return self.text["finished_result"]

    def read_back(self, record):
        if not record:
            return None
        getter = getattr(self.agent.baby_log, "get", None)
        if getter and record.get("id") is not None:
            return getter(record["kind"], record["id"])
        return next((e for e in reversed(self.agent.baby_log.entries(record["kind"])) if e["ts"] == record["ts"]), None)


class CameraSkills(Plugin):
    name = "camera-skills"
    kind = "skill"

    def __init__(self, agent, config, **overrides):
        super().__init__(agent, config)
        self.skills = [CameraSkill(self, entry, **overrides) for entry in config.get("camera_skills", [])]

    @property
    def skill(self):
        """The armed core skill, so the channel router knows the parent's hands are busy."""
        return next((s.skill for s in self.skills if s.skill is not None), None)

    def other_armed(self, asking):
        for s in self.skills:
            if s is not asking and s.skill is not None:
                return s.name
        for plugin in getattr(self.agent, "plugins", []):
            if plugin is not self and getattr(plugin, "kind", "") == "skill" and getattr(plugin, "skill", None) is not None:
                return plugin.name
        return None

    def stop(self):
        for s in self.skills:
            s.finish()

