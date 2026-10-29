"""House sounds: the camera microphone becomes labels on the bus, the audio itself is never kept (issue #14).

Audio arrives as 16 kHz mono PCM on a pipe from ffmpeg (the Tapo camera's RTSP stream, or a test file decoded the same
way), one second at a time. Every second the last 2 s are scored by PANNs CNN14 in a worker process
(parenting_agent/hearing_worker.py), and labels that pass their threshold become episodes. Only labels, scores, times
and a few numbers about a cry (length, loudness, pitch) go on the bus. Samples live in numpy arrays in memory, nothing
opens a file for audio, and a test checks that.

Labels and thresholds are the listener chosen in meta-hackathon-2026 issue #2 (PANNs, related AudioSet classes summed,
tuned on dev clips): 18 of 24 events heard under speech at 0 dB, 0 false alarms on held-out kitchen noise and speech.
"""
import json
import os
import re
import struct
import subprocess
from pathlib import Path

import numpy as np

RATE = 16000
STEP = RATE
WINDOW = 2 * RATE
REPO = Path(__file__).resolve().parent.parent
DEFAULT_PYTHON = Path.home() / "Engineering/gonza/sam3-native/venv/bin/python"
WORKER = Path(__file__).with_name("hearing_worker.py")

GROUPS = {
    "cry": ["Baby cry, infant cry", "Crying, sobbing", "Whimper"],
    "dog": ["Dog", "Bark", "Bow-wow", "Yip", "Howl", "Growling", "Whimper (dog)", "Canidae, dogs, wolves",
            "Domestic animals, pets"],
    "doorbell": ["Doorbell", "Ding-dong", "Ding", "Chime", "Bell", "Buzzer"],
    "splash": ["Splash, splatter", "Bathtub (filling or washing)", "Water", "Water tap, faucet", "Pour", "Liquid",
               "Fill (with liquid)", "Sink (filling or washing)", "Drip", "Stream"],
}
THRESHOLDS = {"cry": 0.05, "dog": 0.6, "doorbell": 0.1, "splash": 0.2}
DEFAULTS = {"thresholds": THRESHOLDS, "gap_s": 2, "cry_report_s": 30, "cry_keep_s": 60}


class Unavailable(RuntimeError):
    pass


class PannsListener:
    """Scores 2 s windows in the hearing worker. The worker runs in the Python that has torch."""

    name = "panns"

    def __init__(self, config=None):
        config = config or {}
        python = Path(os.path.expanduser(config.get("python") or os.environ.get("HEARING_PYTHON") or DEFAULT_PYTHON))
        model_dir = Path(os.path.expanduser(config.get("model_dir") or os.environ.get("PANNS_DIR") or REPO / ".models/panns"))
        if not python.is_file():
            raise Unavailable(f"hearing: no Python with torch at {python}")
        if not (model_dir / "Cnn14_16k.pth").is_file():
            raise Unavailable(f"hearing: no PANNs weights in {model_dir}, run scripts/fetch-panns.sh")
        env = {**os.environ, "HEARING_CONFIG": json.dumps({"model_dir": str(model_dir), "groups": GROUPS})}
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
        self.s = {**DEFAULTS, **(settings or {})}
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
