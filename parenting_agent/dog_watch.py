"""Dog near the baby (issue #109): warn the parents when a dog is close to the baby.

Two stages, so the GPU only works when something moves:
1. A cheap gate. The Tapo C200's ONVIF motion and person sensors in Home Assistant (the Tapo integration exposes no
   pet sensor in this house, see results/dog-near-baby/README.md), plus a low-rate snapshot every snapshot_every_s
   so a dog that walks in without tripping a sensor is still seen.
2. SAM 3.1 on this machine with open-vocabulary prompts ("dog", "baby", "bassinet", "play mat"). The baby's area is
   the baby mask plus any bassinet or play mat that overlaps it. The gap is the shortest pixel distance from any dog
   mask to that area, divided by the baby's size (the square root of the baby mask's area), so the threshold means
   the same at any distance from the camera.

The rule: alert when a dog and a baby are both in view and the dog touches the baby's area or is within near_ratio
baby sizes of it. A dog with no baby in view never alerts. One alert per room per rate_limit_s.

The alert: a Telegram message to TELEGRAM_CHAT_ID only ("Dog close to Theo in the living room"), and an announce on
the kitchen Echo, which is a dry run (a house_dry event) unless house.live is true.

Frames come from Home Assistant's camera proxy straight into memory and are never written to disk. The last few sit in
a short deque (buffer_frames) and are dropped as new ones arrive.

Add "parenting_agent.dog_watch:DogWatch" to the agent config plugins, with an optional "dog_watch" block (DEFAULTS).

GlassesDogWatch runs the same look on the glasses camera (parenting_agent.dog_watch:GlassesDogWatch, block
"dog_watch_glasses", GLASSES_DEFAULTS): the newest glasses frame every every_s, through the SAM 3.1 worker the
changing table already runs (sam3_local.live()), never a second model on the GPU. It pauses while a camera skill
watches, and from the moment the parent says a start phrase, so the SAM 3.1 look that finds hands hidden by a diaper
never waits behind a dog look (Oct 30 rehearsal: it waited 2.3 s and "hand" was spoken before it answered). Its alert goes to a capture file unless alert_to is "telegram", and its
house announce is always a dry run.
"""
import collections
import json
import os
import threading
import time
import urllib.error
from pathlib import Path

from .agent.plugins import Plugin
from .channels.messaging import Messenger, MessagingError
from .confirm import Unavailable
from .channels.router import HomeSpeaker
from .house import HomeAssistant

DEFAULTS = {
    "room": "living room", "baby_name": "Theo",
    "camera": "camera.tapo_c200_sofa_hd_stream",
    "gate_sensors": ["binary_sensor.tapo_c200_sofa_onvif_cell_motion_detection",
                     "binary_sensor.tapo_c200_sofa_onvif_person_detection"],
    "snapshot_every_s": 30, "poll_s": 2,
    "dog_prompts": ["dog"], "baby_prompts": ["baby"], "area_prompts": ["bassinet", "play mat"],
    "dog_score": 0.5, "baby_score": 0.6, "area_score": 0.5,
    "near_ratio": 0.5, "rate_limit_s": 300, "buffer_frames": 4, "work_px": 512,
    "ha_url": "http://127.0.0.1:18123", "ha_token_env": "HA_MCP_TOKEN",
    "telegram_token_env": "TELEGRAM_BOT_TOKEN", "telegram_chat_env": "TELEGRAM_CHAT_ID",
    "house": {"live": False}, "sam3": {},
}


def prompts(cfg):
    return [*cfg["dog_prompts"], *cfg["baby_prompts"], *cfg["area_prompts"]]


def _union(found, words, min_score, shape):
    import numpy as np
    out = np.zeros(shape, bool)
    for word in words:
        for score, mask in found.get(word, []):
            if score >= min_score:
                out |= mask
    return out


def best_score(found, words):
    scores = [score for word in words for score, _ in found.get(word, [])]
    return round(max(scores), 3) if scores else None


def measure(found, cfg):
    """found is {prompt: [(score, bool mask)]} from SAM 3.1. Returns what the rule needs, all plain numbers."""
    import cv2
    import numpy as np
    masks = [m for items in found.values() for _, m in items]
    if not masks:
        return {"dog": False, "baby": False}
    shape = masks[0].shape
    dog = _union(found, cfg["dog_prompts"], cfg["dog_score"], shape)
    baby = _union(found, cfg["baby_prompts"], cfg["baby_score"], shape)
    out = {"dog": bool(dog.any()), "baby": bool(baby.any())}
    if not (out["dog"] and out["baby"]):
        return out
    area = baby.copy()
    for word in cfg["area_prompts"]:
        for score, mask in found.get(word, []):
            if score >= cfg["area_score"] and (mask & baby).any():
                area |= mask
    dog &= ~baby  # a mask that calls the same pixels dog and baby is not evidence of a dog next to the baby
    if not dog.any():
        return {**out, "dog": False}
    # Work on a smaller grid: a distance on a 512 px grid is plenty for a threshold in baby sizes.
    scale = min(1.0, cfg["work_px"] / max(shape))
    size = (max(1, round(shape[1] * scale)), max(1, round(shape[0] * scale)))
    small = lambda m: cv2.resize(m.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)
    dog_s, area_s = small(dog), small(area)
    if not dog_s.any() or not area_s.any():
        return {**out, "dog": bool(dog_s.any()), "baby": bool(area_s.any())}
    distance = cv2.distanceTransform((~area_s).astype(np.uint8), cv2.DIST_L2, 5)
    gap = float(distance[dog_s].min()) / scale
    baby_size = float(np.sqrt(baby.sum()))
    return {**out, "gap_px": round(gap, 1), "baby_size_px": round(baby_size, 1), "ratio": round(gap / baby_size, 3),
            "touching": gap <= 1.5 / scale, "area_has_furniture": bool((area & ~baby).any())}


def decide(m, cfg):
    """near, far, no_baby or no_dog. Only near alerts, so a dog alone never does."""
    if not m.get("baby"):
        return "no_baby"
    if not m.get("dog"):
        return "no_dog"
    return "near" if m["touching"] or m["ratio"] <= cfg["near_ratio"] else "far"


class RateLimit:
    def __init__(self, seconds, clock=time.monotonic):
        self.seconds, self.clock, self.last = seconds, clock, {}

    def allow(self, key):
        now = self.clock()
        if key in self.last and now - self.last[key] < self.seconds:
            return False
        self.last[key] = now
        return True


class Gate:
    """Look when a cheap sensor is on, or when the last look is older than snapshot_every_s."""

    def __init__(self, client, sensors, every_s, clock=time.monotonic):
        self.client, self.sensors, self.every_s, self.clock = client, sensors, every_s, clock
        self.last_look = None

    def why(self):
        for sensor in self.sensors:
            try:
                if self.client.state(sensor) == "on":
                    return sensor
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                continue
        if self.last_look is None or self.clock() - self.last_look >= self.every_s:
            return "snapshot"
        return None

    def looked(self):
        self.last_look = self.clock()


def camera_frame(client, entity):
    """One frame from Home Assistant's camera proxy, decoded in memory. Never touches the disk."""
    import cv2
    import numpy as np
    jpeg = client.camera_image(entity)
    frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("camera proxy returned something that is not an image")
    return frame


class Alerter:
    """Telegram to Gonza's chat only, plus the kitchen Echo announce (dry run while house.live is false)."""

    def __init__(self, cfg, bus, client=None, messenger=None):
        self.cfg, self.bus = cfg, bus
        self.chat_id = os.environ.get(cfg["telegram_chat_env"], "")
        if messenger is None and os.environ.get(cfg["telegram_token_env"]):
            from .channels.telegram import TelegramMessenger
            messenger = TelegramMessenger(os.environ[cfg["telegram_token_env"]])
        self.messenger = messenger
        live = cfg["house"].get("live") is True
        self.speaker = HomeSpeaker(client if live else None, cfg["house"].get("speaker", {}), bus)

    def text(self):
        return f"Dog close to {self.cfg['baby_name']} in the {self.cfg['room']}"

    def __call__(self, m):
        text = self.text()
        sent = False
        if self.messenger is not None and self.chat_id:
            try:
                self.messenger.send(self.chat_id, text)
                sent = True
            except MessagingError as error:
                self.bus.publish("dog_alert_error", channel="telegram", error=str(error)[:200])
        try:
            spoken = self.speaker(text + ".")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            spoken = {"error": str(error)[:200]}
        self.bus.publish("dog_alert", text=text, telegram=sent, announce=spoken, ratio=m.get("ratio"),
                         touching=m.get("touching"))
        return sent


class Watch:
    """One look: frame in, measure, decide, maybe alert. Plain objects in, so tests need no camera or GPU."""

    def __init__(self, cfg, bus, segmenter, alert, frames=None, clock=time.monotonic):
        self.cfg, self.bus, self.segmenter, self.alert = cfg, bus, segmenter, alert
        self.limit = RateLimit(cfg["rate_limit_s"], clock)
        self.buffer = collections.deque(maxlen=cfg["buffer_frames"])
        self.frames = frames

    def look(self, frame, why="snapshot", **extra):
        """extra goes on the dog_watch event as it is (the glasses frame's stream_s)."""
        self.buffer.append(frame)
        started = time.monotonic()
        found, sam_s = self.segmenter.masks(frame, prompts(self.cfg))
        m = measure(found, self.cfg)
        verdict = decide(m, self.cfg)
        alerted = verdict == "near" and self.limit.allow(self.cfg["room"])
        self.bus.publish("dog_watch", room=self.cfg["room"], why=why, verdict=verdict, alerted=alerted,
                         sam_s=round(sam_s, 3), seconds=round(time.monotonic() - started, 3),
                         dog_score=best_score(found, self.cfg["dog_prompts"]), baby_score=best_score(found, self.cfg["baby_prompts"]),
                         **{k: v for k, v in m.items() if k in ("gap_px", "ratio", "touching")}, **extra)
        if alerted:
            self.alert(m)
        return verdict, alerted, m


class DogWatch(Plugin):
    name = "dog-watch"
    kind = "eyes"

    def __init__(self, agent, config, client=None, segmenter=None, messenger=None):
        super().__init__(agent, config)
        self.cfg = {**DEFAULTS, **(config.get("dog_watch") or {})}
        self.cfg["house"] = {**DEFAULTS["house"], **(config.get("house") or {}), **self.cfg["house"]}
        token = os.environ.get(self.cfg["ha_token_env"])
        self.client = client if client is not None else (HomeAssistant(self.cfg["ha_url"], token) if token else None)
        self.segmenter = segmenter
        self.alert = Alerter(self.cfg, agent.bus, self.client, messenger)
        self.gate = Gate(self.client, self.cfg["gate_sensors"], self.cfg["snapshot_every_s"]) if self.client else None
        self.stopping = threading.Event()
        self.thread = None

    def start(self):
        if self.client is None:
            self.agent.bus.publish("dog_watch_off", reason="no Home Assistant token")
            return
        if self.segmenter is None:
            from .carseat.sam3_masks import Sam3Masks
            self.segmenter = Sam3Masks(self.cfg["sam3"])
        self.watch = Watch(self.cfg, self.agent.bus, self.segmenter, self.alert)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopping.wait(self.cfg["poll_s"]):
            self.step()

    def step(self):
        why = self.gate.why()
        if why is None:
            return None
        self.gate.looked()
        try:
            frame = camera_frame(self.client, self.cfg["camera"])
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            self.agent.bus.publish("dog_watch_error", error=str(error)[:200])
            return None
        return self.watch.look(frame, why)

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=10)
        if self.segmenter is not None and hasattr(self.segmenter, "close"):
            self.segmenter.close()


GLASSES_DEFAULTS = {"source": "glasses", "every_s": 0.25, "room": "changing table", "alert_to": "capture",
                    "pause_while_watching": True, "pause_on_phrase_s": 20}


class SharedSam3:
    """Prompt masks from the SAM 3.1 worker this agent already runs (sam3_local.live()). Never loads a model."""

    name = "sam3_shared"

    def masks(self, frame_bgr, words):
        from . import sam3_local
        worker = sam3_local.live()
        if worker is None:
            raise Unavailable("no SAM 3.1 worker is running in this agent yet")
        return worker.prompt_masks(frame_bgr, words)


class CapturedMessages(Messenger):
    """Stands in for Telegram on test runs: each message that would be sent is appended to a local JSONL file, and
    nothing leaves the Mac."""

    name = "captured"

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def send(self, chat_id, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, self.path.open("a") as out:
            out.write(json.dumps({"unix": round(time.time(), 3), "chat": str(chat_id), "text": text}) + "\n")
        return True


class GlassesDogWatch(Plugin):
    """The dog look on the glasses camera, sharing the agent's one SAM 3.1 worker."""

    name = "dog-watch-glasses"
    kind = "eyes"

    def __init__(self, agent, config, segmenter=None, messenger=None, source=None):
        super().__init__(agent, config)
        self.cfg = {**DEFAULTS, **GLASSES_DEFAULTS, **(config.get("dog_watch_glasses") or {})}
        self.cfg["house"] = {"live": False}  # the announce from the glasses watch is always a dry run
        if messenger is None and self.cfg["alert_to"] == "capture":
            messenger = CapturedMessages(Path(config.get("data_dir", "data")) / "telegram-captured.jsonl")
        self.alert = Alerter(self.cfg, agent.bus, None, messenger)
        if self.cfg["alert_to"] == "capture":
            self.alert.chat_id = "captured"
        self.segmenter = segmenter or SharedSam3()
        self._source, self.source = source, None
        self.watching, self.waiting = set(), False
        self.stopping = threading.Event()
        self.thread, self.seq = None, 0
        self.phrase_until = 0.0
        agent.bus.subscribe(self.on_skill, ["skill_armed", "skill_closed", "phrase"])

    def on_skill(self, event):
        if event["kind"] == "phrase":
            if event.get("action") == "arm":  # a skill is about to arm: keep the GPU free for it, until it does
                self.phrase_until = time.monotonic() + self.cfg["pause_on_phrase_s"]
            return
        self.phrase_until = 0.0
        (self.watching.add if event["kind"] == "skill_armed" else self.watching.discard)(event.get("skill"))

    def start(self):
        from .sources import open_source
        self.source = self._source or open_source(self.cfg["source"])
        self.watch = Watch(self.cfg, self.agent.bus, self.segmenter, self.alert)
        self.thread = threading.Thread(target=self.run, name=self.name, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopping.wait(self.cfg["every_s"]):
            self.step()

    def step(self):
        """One look at the newest glasses frame, or None when paused, when no new frame came, or while SAM 3.1 loads."""
        if self.cfg["pause_while_watching"] and (self.watching or time.monotonic() < self.phrase_until):
            return None
        got = self.source.latest(self.seq)
        if got is None:
            return None
        frame, self.seq, stream_s = got
        try:
            result = self.watch.look(frame, why="glasses", stream_s=round(stream_s, 3))
        except Unavailable as error:
            if not self.waiting:
                self.agent.bus.publish("dog_watch_wait", reason=str(error))
            self.waiting = True
            return None
        self.waiting = False
        return result

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=10)
        if self.source is not None:
            self.source.close()
