"""House sounds: the camera microphone becomes labels on the bus, the audio itself is never kept (issue #14).

Audio arrives as 16 kHz mono PCM on a pipe from ffmpeg (the Tapo camera's RTSP stream, or a test file decoded the same
way), one second at a time. Every second the last 2 s are scored, and labels that pass their threshold become
episodes. Only labels, scores, times and a few numbers about a cry (length, loudness, pitch) go on the bus. Samples
live in numpy arrays in memory, nothing opens a file for audio, and a test checks that.

Every model the Ear calls is a Meta model (Oct 31 2026, results/sounds/meta-hearing/README.md):
- MetaListener: Meta's Perception Encoder Audio Frame (facebook/pe-a-frame-small, Apache 2.0) in a worker process
  (parenting_agent/hearing_worker.py), zero shot against text prompts per label.
- SignalListener: plain signal processing for the cry (parenting_agent/cry_signal.py), no learned model at all.
- Listeners: several listeners, each owning some labels. The default Ear is the one the held-out test chose: the
  Meta model for every label.
PANNs, the listener until Oct 31, is not a Meta model and is no longer called. It stays offline only, as the before
baseline in scripts/panns_baseline.py.
"""
import json
import os
import re
import struct
import subprocess
from pathlib import Path

import numpy as np

from . import cry_signal

RATE = 16000
STEP = RATE
WINDOW = 2 * RATE
REPO = Path(__file__).resolve().parent.parent
DEFAULT_PYTHON = REPO / ".venv-hearing/bin/python"
DEFAULT_MODEL = REPO / ".models/pe-a-frame-small"
WORKER = Path(__file__).with_name("hearing_worker.py")

LABELS = ("cry", "dog", "doorbell", "splash")
# Written before any scoring in results/sounds/meta-hearing/split.json, copied here unchanged.
PROMPTS = {
    "cry": ["a baby crying", "an infant crying", "a newborn baby wailing", "a crying baby"],
    "doorbell": ["a doorbell ringing", "a ding dong doorbell chime", "an electronic door chime", "a door buzzer"],
    "dog": ["a dog barking", "a dog bark", "a dog growling and barking"],
    "splash": ["water splashing", "water running from a tap", "water pouring into a bath", "water splashing in a sink"],
}
BACKGROUND = ["people talking", "a quiet room", "kitchen noise", "music playing", "a person coughing",
              "a radio broadcast", "household background noise"]
# Chosen on the tune set only (results/sounds/meta-hearing/tune.json). Meta thresholds are on the model's logit scale,
# the probability is the sigmoid: cry 0.988, doorbell 0.9998, dog 0.998, splash 0.9995.
MODES = {"cry": "logit", "dog": "logit", "doorbell": "logit", "splash": "logit"}
THRESHOLDS = {"cry": 4.43, "dog": 6.4588, "doorbell": 8.3168, "splash": 7.6583}
# The signal listener's cry limits, from the same tune set. Its score is 1 or 0, so its cry threshold is 0.5.
CRY_LIMITS = {"level_dbfs": -40.0, "voiced_share": 0.2, "longest_s": 0.2, "harmonicity": 0.8}
# Which listener hears which label. The held-out test (results/sounds/meta-hearing/eval.json) gave the cry to the Meta
# model: 339 of 348 cries with 1 false alarm, against 283 with 2 for the signal listener. Set a label to "signal" in
# the house_sounds "listener" block ("owners") to hear cries without any model.
OWNERS = {"cry": "meta", "dog": "meta", "doorbell": "meta", "splash": "meta"}
DEFAULTS = {"thresholds": THRESHOLDS, "gap_s": 2, "cry_report_s": 30, "cry_keep_s": 60}


class Unavailable(RuntimeError):
    pass


class MetaListener:
    """Scores 2 s windows with Perception Encoder Audio Frame in the hearing worker, in the Python that has transformers."""

    name = "pe-a-frame"

    def __init__(self, config=None):
        config = config or {}
        python = Path(os.path.expanduser(config.get("python") or os.environ.get("HEARING_PYTHON") or DEFAULT_PYTHON))
        model_dir = Path(os.path.expanduser(config.get("model_dir") or os.environ.get("HEARING_MODEL_DIR") or DEFAULT_MODEL))
        if not python.is_file():
            raise Unavailable(f"hearing: no Python with transformers at {python}, run scripts/hearing-setup.sh")
        if not (model_dir / "model.safetensors").is_file():
            raise Unavailable(f"hearing: no Perception Encoder weights in {model_dir}, run scripts/hearing-setup.sh")
        labels = [label for label in config.get("labels", LABELS) if label in PROMPTS]
        cfg = {"model_dir": str(model_dir), "prompts": {label: PROMPTS[label] for label in labels},
               "background": BACKGROUND, "modes": {**MODES, **config.get("modes", {})},
               "device": config.get("device") or os.environ.get("HEARING_DEVICE") or "cpu"}
        env = {**os.environ, "HEARING_CONFIG": json.dumps(cfg), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        self.thresholds = {label: THRESHOLDS[label] for label in labels}
        self.process = subprocess.Popen([str(python), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=env)
        hello = json.loads(self.process.stdout.readline() or b'{"blocked": "worker exited"}')
        if "blocked" in hello:
            self.process.kill()
            raise Unavailable(f"hearing: {hello['blocked']}")
        self.info = hello

    def score(self, samples):
        data = np.ascontiguousarray(samples, np.float32).tobytes()
        self.process.stdin.write(struct.pack(">I", len(data)) + data)
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline() or b'{"scores": {}}')

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)


class SignalListener:
    """The cry from loudness, voicing and pitch alone (cry_signal.py). In process, no model, nothing to load.

    Not the default: on the held-out test it heard fewer cries than the Meta model and took two doorbells for cries.
    Its score is 1 or 0, so its cry threshold is 0.5."""

    name = "signal"

    def __init__(self, config=None):
        self.limits = {**CRY_LIMITS, **(config or {}).get("cry_limits", {})}
        self.thresholds = {"cry": 0.5}
        self.info = {"ready": True, "model": "signal processing, no learned model", "limits": self.limits}

    def score(self, samples):
        feats = cry_signal.features(samples)
        return {"scores": {"cry": 1.0 if cry_signal.is_cry(feats, self.limits) else 0.0}, "cry_signal": feats}

    def close(self):
        pass


class Listeners:
    """Several listeners behind one score(): each label's score comes from the listener that owns it."""

    def __init__(self, owned):
        self.owned = owned  # [(listener, labels)]
        self.name = "+".join(listener.name for listener, _ in owned)
        self.info = {listener.name: getattr(listener, "info", {}) for listener, _ in owned}
        self.thresholds = {label: getattr(listener, "thresholds", THRESHOLDS)[label]
                           for listener, labels in owned for label in labels}

    def score(self, samples):
        reply = {"scores": {}}
        for listener, labels in self.owned:
            got = listener.score(samples)
            reply["scores"].update({k: v for k, v in got.get("scores", {}).items() if k in labels})
            reply.update({k: v for k, v in got.items() if k != "scores"})
        return reply

    def close(self):
        for listener, _ in self.owned:
            listener.close()


def default_listener(config=None):
    """The Ear's listener as the held-out test chose it (OWNERS). config: the house_sounds "listener" block."""
    config = config or {}
    owners = {**OWNERS, **config.get("owners", {})}
    owned = []
    meta_labels = [label for label, owner in owners.items() if owner == "meta"]
    signal_labels = [label for label, owner in owners.items() if owner == "signal"]
    if signal_labels:
        owned.append((SignalListener(config), signal_labels))
    if meta_labels:
        owned.append((MetaListener({**config, "labels": meta_labels}), meta_labels))
    return owned[0][0] if len(owned) == 1 else Listeners(owned)


def dbfs(x):
    return round(float(20 * np.log10(max(float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0, 1e-9))), 1)


def pitch_hz(x, low=250, high=700, frame=800):
    """Median pitch of the voiced 50 ms frames by autocorrelation, and the share of frames that are voiced."""
    pitches, frames = [], 0
    floor = 10 ** (-45 / 20)
    for start in range(0, x.size - frame + 1, frame):
        part = x[start:start + frame] - np.mean(x[start:start + frame])
        frames += 1
        if np.sqrt(np.mean(part ** 2)) < floor:
            continue
        corr = np.correlate(part, part, mode="full")[frame - 1:]
        lo, hi = RATE // high, RATE // low
        lag = lo + int(np.argmax(corr[lo:hi]))
        if corr[0] > 0 and corr[lag] / corr[0] >= 0.3:
            pitches.append(RATE / lag)
    voiced = round(len(pitches) / frames, 2) if frames else 0.0
    return (round(float(np.median(pitches))) if pitches else None), voiced


def cry_features(samples, seconds):
    """Weak extra signals about a cry, as plain numbers: length, loudness, pitch and how much of it is voiced."""
    pitch, voiced = pitch_hz(samples)
    peak = round(float(20 * np.log10(max(float(np.abs(samples).max()), 1e-9))), 1) if samples.size else None
    return {"length_s": seconds, "level_dbfs": dbfs(samples), "peak_dbfs": peak, "pitch_hz": pitch, "voiced_share": voiced}


class Ear:
    """Turns one second of PCM at a time into sound episodes on the bus.

    Doorbell, dog and splash publish a "sound" event at their first second, so the agent reacts at once. A cry
    publishes when it ends, or once it has lasted cry_report_s, with its length and features. Samples of a cry are
    kept in memory only while it lasts, at most cry_keep_s, and dropped when it is reported.
    """

    def __init__(self, listener, bus, settings=None, source="living room camera"):
        self.listener, self.bus, self.source = listener, bus, source
        # Each listener scores on its own scale, so its thresholds come with it unless the settings name others.
        self.s = {**DEFAULTS, "thresholds": getattr(listener, "thresholds", THRESHOLDS), **(settings or {})}
        self.buffer = np.zeros(0, np.float32)
        self.second = 0
        self.open = {}
        self.episodes = 0
        self.rows = []
        # Set by the house sounds plug-in when Muse listens to cries: it gets the cry's samples once, in memory,
        # just before they are dropped. Nothing else ever sees samples.
        self.on_cry_clip = None

    def feed(self, chunk):
        chunk = np.asarray(chunk, np.float32)
        self.buffer = np.concatenate([self.buffer, chunk])[-WINDOW:]
        self.second += 1
        if self.buffer.size < WINDOW:
            return []
        reply = self.listener.score(self.buffer)
        scores = reply.get("scores", {})
        fired = [label for label, threshold in self.s["thresholds"].items() if scores.get(label, 0) >= threshold]
        self.rows.append({"second": self.second, "fired": fired, "scores": scores, "dbfs": dbfs(chunk)})
        published = []
        for label in fired:
            episode = self.open.get(label)
            if episode is None:
                self.episodes += 1
                episode = self.open[label] = {"id": self.episodes, "start": self.second, "last": self.second, "peak": 0.0,
                                              "samples": [], "reported": False}
            episode["last"], episode["peak"] = self.second, max(episode["peak"], scores[label])
            if label != "cry" and episode["start"] == self.second:
                published.append(self._publish(label, episode, "start"))
            if label == "cry" and not episode["reported"]:
                kept = sum(s.size for s in episode["samples"])
                if kept < self.s["cry_keep_s"] * RATE:
                    episode["samples"].append(chunk)
                if self._length(episode) >= self.s["cry_report_s"]:
                    published.append(self._publish(label, episode, "ongoing"))
        for label in list(self.open):
            if label not in fired and self.second - self.open[label]["last"] > self.s["gap_s"]:
                episode = self.open.pop(label)
                if label == "cry" and not episode["reported"]:
                    published.append(self._publish(label, episode, "end"))
                episode["samples"] = []
        return published

    def _length(self, episode):
        return episode["last"] - episode["start"] + 1

    def _publish(self, label, episode, phase):
        fields = {"label": label, "phase": phase, "episode": episode["id"], "source": self.source,
                  "stream_s": episode["start"], "seconds": self._length(episode), "peak": round(episode["peak"], 4)}
        if label == "cry":
            samples = np.concatenate(episode["samples"]) if episode["samples"] else np.zeros(0, np.float32)
            fields["features"] = cry_features(samples, self._length(episode))
            episode["reported"], episode["samples"] = True, []
            if self.on_cry_clip is not None and samples.size:
                self.on_cry_clip(episode["id"], samples)
        return self.bus.publish("sound", **fields)

    def flush(self, seconds=None):
        """Feed silence until every open episode closes, as the stream going quiet would."""
        out = []
        for _ in range(seconds or self.s["gap_s"] + 3):
            out += self.feed(np.zeros(STEP, np.float32))
        return out


def play(ear, samples):
    """Feeds samples into the ear one second at a time, then silence. Returns the published sound events."""
    out = []
    for start in range(0, samples.size, STEP):
        chunk = samples[start:start + STEP]
        if chunk.size < STEP:
            chunk = np.pad(chunk, (0, STEP - chunk.size))
        out += ear.feed(chunk)
    return out + ear.flush()


def decode_command(path, start=0.0, seconds=None):
    command = ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE)]
    if seconds:
        command += ["-t", str(seconds)]
    return command + ["-f", "s16le", "pipe:1"]


def from_file(path, start=0.0, seconds=None, camera_channel=True):
    """Decodes a test file into memory the way the camera stream arrives: ffmpeg on a pipe, never to disk.

    With camera_channel the audio goes through 8 kHz G.711 A-law and back, like the Tapo C200 RTSP audio track.
    """
    decoded = subprocess.run(decode_command(path, start, seconds), capture_output=True, check=True).stdout
    if camera_channel:
        alaw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0",
                               "-ar", "8000", "-c:a", "pcm_alaw", "-f", "alaw", "pipe:1"],
                              input=decoded, capture_output=True, check=True).stdout
        decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "alaw", "-ar", "8000", "-ac", "1", "-i", "pipe:0",
                                  "-ar", str(RATE), "-f", "s16le", "pipe:1"], input=alaw, capture_output=True, check=True).stdout
    return np.frombuffer(decoded, np.int16).astype(np.float32) / 32768


def mask(text):
    return re.sub(r"rtsp://[^@/\s]+@", "rtsp://***@", text)


def camera_url(env=os.environ):
    return "rtsp://{}:{}@{}:554/{}".format(env["TAPO_USER"], env["TAPO_PASS"], env["TAPO_HOST"], env.get("TAPO_STREAM", "stream2"))


def camera_seconds(url):
    """Yields one second of float32 PCM at a time from the camera's RTSP audio, video dropped, through a pipe."""
    proc = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp", "-timeout", "10000000",
                             "-i", url, "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        while True:
            data = proc.stdout.read(STEP * 2)
            if len(data) < STEP * 2:
                error = mask(proc.stderr.read().decode(errors="replace").strip())[-300:]
                raise ConnectionError(error or "camera stream ended")
            yield np.frombuffer(data, np.int16).astype(np.float32) / 32768
    finally:
        proc.kill()
        proc.wait()
