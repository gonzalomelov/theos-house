"""The car seat coach on the glasses path, driven by the parent's voice, recorded as one clip for review.

    # the proof run: a recorded install video as the head camera, MMS-TTS lines as the parent's voice
    python scripts/carseat_glasses_take.py --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat-yt-test/wPEcL5RFEEw.mp4 \\
        --out ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat-yt-test/coach-glasses-take.mp4
    # the real take: the iPhone strapped to the head, its camera and microphone reach this Mac by Continuity Camera
    python scripts/carseat_glasses_take.py --camera "iPhone Camera" --mic "iPhone Microphone" \\
        --out ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat-take/take1.mp4

This script is the glasses app's side of the loop, on this Mac: it posts camera frames to the glasses endpoint's /frame
and the parent's utterances to /hear with the pairing token, listens to /events, speaks every coach line and reply with
Meta's MMS-TTS (Spanish) and draws the lens card it gets. Behind the endpoint everything is the agent as it runs: the
glasses channel, Muse Spark Open's ear and the speech gate, the car seat coach with SAM 3.1 on this Mac (one process,
under /tmp/pa-gpu.lock), the Muse brain for anything the coach does not take. Telegram and Home Assistant variables are
blanked, house.live is false, nothing is sent to anyone.

With --video the parent is mocked: the feed plays the part of the video that matches the step the coach is on (PLAN),
and an MMS-TTS voice says "listo", "ya", "sí" or "no" through /hear when she finishes it, after the coach's line was
spoken, like a parent who listens first. A line the ear misses is said again after 15 s, at most 3 times, and counted.
With --camera and --mic nothing is mocked: the iPhone's camera is the feed and its microphone is cut into utterances
here (the app's UtteranceCutter, apps/glasses/ParentingGlasses/Speech/Utterances.swift), muted while the coach speaks.

The clip (frames with the lens card drawn on them, the coach's voice and the parent's) and a JSON report go to --out.
Keep them outside the repo: the video is a public install video used for a local check, the take is the family's car.
"""
import argparse
import http.client
import io
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PORT = 8769  # not 8766 to 8768, so no other run on this Mac crosses this one
DATA = ROOT / "data-carseat-take"
HEARING_PYTHON = Path(os.environ.get("HEARING_PYTHON") or ROOT / ".venv-hearing" / "bin" / "python")
FPS = 10
REQUEST = "Agente, ayudame a instalar la silla del auto."
# The Joie i-Gemm baby install in wPEcL5RFEEw (8:00 to 9:02), seconds into the video, per coach step: the part she does
# it in ("play"), the part looped after she says the word ("hold", forwards then backwards, never a cut to another seat)
# and what she says, then what she says when she has to say it again. Read off a contact sheet of the video, 2 s per
# tile. One word in MMS-TTS's voice is often misheard by Muse's ear (Nov 1, two calls each: "Sí." as "The", "Listo." as
# "Y esto", "Ya." as nothing), two to four words are heard right ("Listo, ya está.", "Ya está.", "Sí, hizo clic."), so
# the mocked parent says those. Both still open with the word the gate and the coach listen for.
DONE = ("Listo, ya está.", "Ya está, listo.")
REQUEST_AT = 482.0
VIDEO_SPAN = (480.0, 545.0)
PLAN = {
    "harness_pinch": {"play": (484, 492), "say": ("No, no sobra nada.", "No, nada.")},
    "car_position": {"play": (492, 504), "say": ("Sí, está atrás.", "Sí, señor.")},
    "lap_guides": {"play": (504, 515), "say": DONE, "hold": (515, 524)},
    "buckle": {"play": (515, 520), "say": ("Sí, hizo clic.", "Sí, señor.")},
    "shoulder_guide": {"play": (520, 530), "say": DONE, "hold": (530, 540)},
    "tension": {"play": (530, 534), "say": ("Sí, quedó tenso.", "Sí, señor.")},
    "no_twist": {"play": (532, 536), "say": ("Ya está.", "Ya está, listo."), "hold": (534, 540)},
    "level_line": {"play": (534, 538), "say": DONE, "hold": (534, 540)},
    "handle": {"play": (536, 541), "say": DONE, "hold": (538, 542)},
    "belt_path_movement": {"play": (540, 542), "say": ("Sí, se mueve poco.", "Sí, señor.")},
}
RETRY_S, TRIES = 15.0, 3
BLANKED = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_FAMILIES_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_CECI_CHAT_ID", "HA_MCP_TOKEN",
           "HA_TOKEN", "HA_URL")
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

MMS_WORKER = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from parenting_agent.voice.tts import MmsVoice
voice = MmsVoice()
for line in sys.stdin:
    job = json.loads(line)
    wav, _ = voice.synth(job["text"], job.get("lang", "es"))
    open(job["out"], "wb").write(wav)
    print(json.dumps({"out": job["out"]}), flush=True)
"""


# ---------- pieces with no I/O (tests/test_carseat_take.py) ----------

class Cutter:
    """The app's UtteranceCutter in Python: 16 kHz mono floats in, utterances out. 20 ms frames, speech after 3 loud
    frames, 0.2 s kept before, the end after 0.6 s under the gate, at most 15 s, under 0.24 s of voice dropped. The gate
    is 12 dB over the quietest recent level, never under -50 dBFS. Nothing is cut while muted."""
    RATE, FRAME = 16000, 320
    START, END, PREROLL, MAX, MIN_VOICED = 3, 30, 10, 750, 12

    def __init__(self):
        self.floor, self.muted = -60.0, False
        self.pending = np.zeros(0, np.float32)
        self.reset()

    def reset(self):
        self.in_speech, self.current, self.preroll = False, [], []
        self.loud = self.quiet = self.voiced = 0

    def feed(self, samples, unix):
        """Samples whose first one was heard at `unix`. Returns [(samples, start_unix, end_unix)]."""
        start = unix - len(self.pending) / self.RATE
        self.pending = np.concatenate([self.pending, np.asarray(samples, np.float32)])
        done, offset = [], 0
        while len(self.pending) - offset >= self.FRAME:
            chunk = self.pending[offset:offset + self.FRAME]
            at = start + offset / self.RATE
            offset += self.FRAME
            if self.muted:
                self.reset()
                continue
            got = self.step(chunk, at)
            if got is not None:
                done.append(got)
        self.pending = self.pending[offset:]
        return done

    def step(self, chunk, at):
        level = 20 * np.log10(max(float(np.sqrt(np.mean(chunk ** 2))), 1e-7))
        self.floor = level if level < self.floor else min(self.floor + 0.05, level)
        loud = level > max(self.floor + 12, -50)
        frame_s = self.FRAME / self.RATE
        if not self.in_speech:
            self.preroll = (self.preroll + [chunk])[-self.PREROLL:]
            self.loud = self.loud + 1 if loud else 0
            if self.loud >= self.START:
                self.in_speech, self.current = True, list(self.preroll)
                self.start_unix = at - (self.START - 1) * frame_s
                self.voiced, self.quiet, self.last_voiced = self.loud, 0, at + frame_s
                self.preroll = []
            return None
        self.current.append(chunk)
        if loud:
            self.voiced, self.quiet, self.last_voiced = self.voiced + 1, 0, at + frame_s
        else:
            self.quiet += 1
        if self.quiet >= self.END or len(self.current) >= self.MAX:
            return self.finish()
        return None

    def finish(self):
        voiced, quiet, current = self.voiced, self.quiet, self.current
        start, end = self.start_unix, self.last_voiced
        self.reset()
        if voiced < self.MIN_VOICED:
            return None
        keep = len(current) - max(0, quiet - 8)
        return np.concatenate(current[:keep]), start, end


def wav_bytes(samples, rate=16000):
    """16-bit mono WAV, the format /hear takes."""
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


def jpegs(stream):
    """Splits an MJPEG byte stream (ffmpeg image2pipe) into JPEGs."""
    buffer = b""
    while True:
        chunk = stream.read(65536)
        if not chunk:
            return
        buffer += chunk
        while True:
            start = buffer.find(b"\xff\xd8")
            end = buffer.find(b"\xff\xd9", start + 2)
            if start < 0 or end < 0:
                break
            yield buffer[start:end + 2]
            buffer = buffer[end + 2:]


class Cursor:
    """Where the mock feed is in the video: plays a span forwards, then loops its hold span (by default the play span's
    last second) forwards and backwards until the next step."""

    def __init__(self, first_s, fps=FPS):
        self.first_s, self.fps = first_s, fps
        self.lock = threading.Lock()
        self.index, self.phase, self.end, self.hold, self.direction = 0, "free", 0, (0, 0), 1

    def at(self, seconds):
        return int(round((seconds - self.first_s) * self.fps))

    def play(self, span, hold=None):
        with self.lock:
            self.index, self.end, self.phase, self.direction = self.at(span[0]), self.at(span[1]), "play", 1
            self.hold = (self.at(hold[0]), self.at(hold[1])) if hold else (max(self.end - self.fps, self.index), self.end)

    def played(self):
        with self.lock:
            return self.phase == "hold"

    def step(self, frames):
        """The frame index to show now, then one frame on."""
        with self.lock:
            now = min(max(self.index, 0), frames - 1)
            if self.phase == "play" and self.index >= self.end:
                self.phase, self.index, self.direction = "hold", self.hold[0], 1
            elif self.phase == "hold":
                self.index += self.direction
                if self.index >= self.hold[1] or self.index <= self.hold[0]:
                    self.direction *= -1
            else:
                self.index += 1
            return now


# ---------- the glasses app's side ----------

class Voice:
    """MMS-TTS in the hearing venv (torch), one line at a time."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.process = subprocess.Popen([str(HEARING_PYTHON), "-I", "-c", MMS_WORKER, str(ROOT)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                        env={**os.environ, "HF_HUB_OFFLINE": "1"})
        self.n, self.lock = 0, threading.Lock()

    def synth(self, text, lang="es"):
        with self.lock:
            self.n += 1
            out = self.folder / f"line-{self.n:03d}.wav"
            self.process.stdin.write(json.dumps({"text": text, "lang": lang, "out": str(out)}) + "\n")
            self.process.stdin.flush()
            reply = self.process.stdout.readline()
            if not reply:
                raise RuntimeError("the MMS-TTS worker stopped")
            return out

    def close(self):
        self.process.kill()


def seconds_of(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def pad16k(path):
    """The utterance as the cutter would send it: 0.3 s of quiet on each side, 16 kHz mono."""
    with wave.open(str(path)) as w:
        rate, pcm = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32767
    assert rate == 16000, "MMS-TTS speaks at 16 kHz"
    quiet = np.zeros(int(0.3 * rate), np.float32)
    return wav_bytes(np.concatenate([quiet, pcm, quiet]))


class Lens:
    """What the glasses app does: frames up, utterances up, events down, spoken lines and the lens card."""

    def __init__(self, port, token, voice, live_audio, t0):
        self.port, self.token, self.voice, self.live_audio, self.t0 = port, token, voice, live_audio, t0
        self.card, self.said, self.heard_line, self.sam = None, "", "", ""
        self.audio = []      # (seconds into the clip, wav path, who)
        self.timeline = []   # what the app got and did, for the report
        self.lines = queue.Queue()
        self.speaking_until = 0.0
        self.sending = self.busy = False
        self.stopped = False
        threading.Thread(target=self.events, daemon=True).start()
        threading.Thread(target=self.speak, daemon=True).start()

    def now(self):
        return round(time.time() - self.t0, 3)

    def request(self, method, path, body=b"", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        connection.request(method, path, body=body, headers={"Authorization": f"Bearer {self.token}", **(headers or {})})
        response = connection.getresponse()
        response.read()
        connection.close()
        return response.status

    def frame(self, jpeg):
        """One frame up, dropped while the last one is still uploading (the app does the same)."""
        if self.sending:
            return
        self.sending = True

        def send():
            try:
                self.request("POST", "/frame", jpeg, {"Content-Type": "image/jpeg"})
            finally:
                self.sending = False
        threading.Thread(target=send, daemon=True).start()

    def hear(self, wav, end_unix, words=None, path=None):
        status = self.request("POST", "/hear", wav, {"Content-Type": "audio/wav", "X-Speech-End-Unix": f"{end_unix:.3f}",
                                                     "X-Speech-Source": "carseat take"})
        if path is not None:
            self.audio.append((round(end_unix - self.t0 - seconds_of(path), 3), path, "parent"))
        self.timeline.append({"t": self.now(), "kind": "posted_utterance", "words": words, "status": status})
        return status

    def events(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3600)
        connection.request("GET", "/events", headers={"Authorization": f"Bearer {self.token}"})
        response = connection.getresponse()
        while not self.stopped:
            line = response.readline()
            if not line:
                return
            if not line.startswith(b"data: "):
                continue
            event = json.loads(line[6:])
            kind = event.get("kind")
            if kind == "card":
                self.card = event["card"]
                self.timeline.append({"t": self.now(), "kind": "card", **event["card"]})
            elif kind in ("voice", "reply") and event.get("text"):
                self.timeline.append({"t": self.now(), "kind": kind, "text": event["text"], "step": event.get("step"),
                                      "result": event.get("result"), "view": event.get("view")})
                self.lines.put((event["text"], event.get("lang") or "es"))
            elif kind == "heard" and event.get("why"):
                if event.get("took"):
                    self.heard_line = event.get("text") or ""
                self.timeline.append({"t": self.now(), "kind": "heard", "text": event.get("text"), "took": event.get("took"),
                                      "why": event.get("why"), "ear_s": event.get("ear_s")})

    def speak(self):
        """Every coach line and reply, in order, in MMS-TTS. The app speaks one line at a time and mutes its own
        microphone while it does."""
        while not self.stopped:
            try:
                text, lang = self.lines.get(timeout=0.5)
            except queue.Empty:
                continue
            self.busy = True
            path = self.voice.synth(text, lang)
            length = seconds_of(path)
            start = time.time()
            self.speaking_until = start + length + 0.3
            self.said = text
            self.audio.append((round(start - self.t0, 3), path, "agent"))
            if self.live_audio:
                subprocess.run(["afplay", str(path)], check=False)
            else:
                time.sleep(length)
            time.sleep(0.3)
            self.busy = False

    def speaking(self):
        return self.busy or time.time() < self.speaking_until or not self.lines.empty()


# ---------- drawing the lens on the frame ----------

class Painter:
    def __init__(self, width, height, credit):
        from PIL import ImageFont
        self.w, self.h, self.credit = width, height, credit
        self.font = lambda size, bold=False: ImageFont.truetype(FONT_BOLD if bold else FONT, size)
        self.fonts = {k: self.font(*v) for k, v in {"title": (24, True), "status": (24, False), "detail": (19, False),
                                                    "meta": (16, False), "sub": (21, False), "small": (15, False)}.items()}

    def wrap(self, draw, text, font, width):
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width:
                line = trial
            else:
                lines.append(line)
                line = word
        return lines + ([line] if line else [])

    def draw(self, frame_bgr, lens, step):
        from PIL import Image, ImageDraw
        image = Image.fromarray(frame_bgr[:, :, ::-1]).convert("RGBA")
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        f = self.fonts
        card = lens.card
        if card:
            x0, y0, width = self.w - 440, 20, 420
            rows = [("title", card.get("title"), (255, 255, 255)), ("status", card.get("status"), (255, 255, 255)),
                    ("detail", card.get("detail"), (210, 230, 255)), ("meta", card.get("meta"), (170, 170, 170))]
            body = [(key, line, color) for key, text, color in rows if text
                    for line in self.wrap(d, text, f[key], width - 32)]
            height = 24 + sum(f[k].size + 8 for k, _, _ in body)
            accent = (230, 70, 60, 255) if card.get("alert") else (80, 200, 120, 255)
            d.rounded_rectangle((x0, y0, x0 + width, y0 + height), 18, fill=(0, 0, 0, 190), outline=accent, width=3)
            y = y0 + 14
            for key, line, color in body:
                d.text((x0 + 16, y), line, font=f[key], fill=color + (255,))
                y += f[key].size + 8
            d.text((x0, y0 + height + 6), "Lente de los anteojos (tarjeta HUD)", font=f["small"], fill=(220, 220, 220, 230))
        subs = [("Agente: ", lens.said), ("Vos: ", lens.heard_line)]
        lines = [(who, line) for who, text in subs if text for line in self.wrap(d, text, f["sub"], self.w - 140)[-2:]]
        if lines:
            top = self.h - 18 - len(lines) * 30
            d.rectangle((0, top - 8, self.w, self.h), fill=(0, 0, 0, 170))
            for n, (who, line) in enumerate(lines):
                d.text((20, top + n * 30), who + line, font=f["sub"], fill=(255, 255, 255, 255))
        d.rectangle((0, 0, self.w - 460 if card else self.w, 50), fill=(0, 0, 0, 120))
        d.text((12, 6), self.credit, font=f["small"], fill=(230, 230, 230, 255))
        d.text((12, 27), f"SAM 3.1: {lens.sam}" if lens.sam else (f"Paso: {step}" if step else ""), font=f["small"],
               fill=(255, 230, 120, 255))
        out = Image.alpha_composite(image, layer).convert("RGB")
        return np.asarray(out)[:, :, ::-1].copy()


# ---------- the run ----------

def device(kind, name):
    """The avfoundation index of the first video or audio device whose name holds `name`."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                         capture_output=True, text=True).stderr
    part = log.split("AVFoundation audio devices:")[1 if kind == "audio" else 0]
    for index, label in re.findall(r"\[(\d+)\] (.+)", part):
        if name.lower() in label.lower():
            return index
    raise SystemExit(f"no {kind} device named like {name!r}: {re.findall(r'] (.+)', part)}")


def load_env():
    from parenting_agent.e2e import harness
    harness.load_env()
    for key in BLANKED:
        os.environ[key] = ""


def agent_config():
    live = json.loads((ROOT / "config/agent.glasses-live.json").read_text())
    people = json.loads((ROOT / "config/agent.vostro.json").read_text())["people"]
    return {
        "data_dir": str(DATA), "env_file": live["env_file"], "brain": live["brain"], "max_steps": 6,
        "baby_log": {"provider": "local"}, "people": {"gonza": people["gonza"]},
        "allowed_tools": ["read_baby_log", "baby_summary", "current_time", "start_car_seat_coach", "answer_car_seat_check",
                          "car_seat_outgrow"],
        "plugins": ["parenting_agent.glasses:Glasses", "parenting_agent.carseat.plugin:CarSeatCoach"],
        "glasses": {"port": PORT, "host": "127.0.0.1", "person": "gonza"},
        # the coach's lines are spoken by the glasses side (this script, MMS-TTS), not by `say` on the Mac
        "car_seat": {"skill": "skills/car-seat.json", "source": f"glasses:{PORT}", "channel": "glasses", "quiet": True},
        "house": {"live": False},
    }


class Take:
    def __init__(self, args):
        self.args = args
        self.out = Path(os.path.expanduser(args.out))
        self.work = self.out.with_suffix("")
        self.work = self.work.parent / (self.work.name + "-work")
        self.retries = {}

    def start_agent(self):
        load_env()
        from parenting_agent.agent import build
        self.token = secrets.token_urlsafe(12)
        os.environ["PARENTING_AGENT_GLASSES_TOKEN"] = self.token
        DATA.mkdir(exist_ok=True)
        for stale in DATA.glob("*.jsonl"):
            stale.unlink()
        self.agent = build(agent_config())
        self.agent.start()
        for plugin in self.agent.plugins:
            plugin.start()
        self.coach_plugin = next(p for p in self.agent.plugins if p.name == "car-seat")
        self.dropped = []
        next(p for p in self.agent.plugins if p.name == "glasses").on_dropped_words = self.dropped.append
        self.agent.bus.subscribe(self.on_frame, ["carseat_frame"])

    def on_frame(self, event):
        view = f" {event['view']}" if event.get("view") else ""
        self.lens.sam = f"{event['step']}{view} {event['phase']}: {event['result']} ({event.get('sam_s')} s)"

    def count(self, kind, **match):
        return sum(1 for e in self.agent.bus.history if e["kind"] == kind and all(e.get(k) == v for k, v in match.items()))

    def say(self, lines, done, retry_s=RETRY_S):
        """The parent says the first line (MMS-TTS through /hear), the next ones after retry_s while `done()` is false."""
        lines = (lines,) if isinstance(lines, str) else tuple(lines)
        words = lines[0]
        for attempt in range(1, TRIES + 1):
            line = lines[min(attempt - 1, len(lines) - 1)]
            path = self.voice.synth(line, "es")
            while self.lens.speaking():
                time.sleep(0.1)
            time.sleep(0.6)
            self.lens.hear(pad16k(path), time.time(), line, path)
            deadline = time.time() + retry_s
            while time.time() < deadline:
                if done():
                    self.retries[words + f" #{len(self.retries)}"] = attempt - 1
                    return attempt
                time.sleep(0.1)
        self.retries[words + f" #{len(self.retries)}"] = TRIES
        return None

    def direct(self):
        """The mocked parent on the video: follows each step the coach says, does it in the video, then answers."""
        cursor = self.cursor
        cursor.play((VIDEO_SPAN[0], REQUEST_AT))
        while time.time() - self.t0 < REQUEST_AT - VIDEO_SPAN[0]:
            time.sleep(0.05)
        # SAM 3.1 loads before the coach's first line (about 13 s): the request counts as taken once the agent took it
        self.say(REQUEST, lambda: self.count("guard", status="answer_taken") > 0 or self.count("skill_armed") > 0, 30.0)
        done_steps = set()
        while not self.stopped.is_set():
            step = next((e for e in reversed(self.agent.bus.history) if e["kind"] == "carseat_step"), None)
            if self.count("carseat_summary"):
                while self.lens.speaking():
                    time.sleep(0.2)
                time.sleep(3)
                return
            if step is None or step["step"] in done_steps:
                time.sleep(0.1)
                continue
            sid, plan = step["step"], PLAN[step["step"]]
            done_steps.add(sid)
            cursor.play(plan["play"], plan.get("hold"))
            deadline = time.time() + 20  # the step's line reaches the lens, then she listens to it
            while time.time() < deadline and not any(r["kind"] == "voice" and r.get("step") == sid
                                                     for r in self.lens.timeline):
                time.sleep(0.05)
            while self.lens.speaking():
                time.sleep(0.1)
            coach = self.coach_plugin.coach
            if step["step_kind"] == "camera":
                while not cursor.played() and coach.waiting == sid:
                    time.sleep(0.1)
                if coach.waiting != sid:
                    continue  # the check passed on its own while she worked
                self.say(plan["say"], lambda: sid in coach.readies or coach.waiting != sid)
            else:
                while not cursor.played():
                    time.sleep(0.1)
                self.say(plan["say"], lambda: sid in coach.answers or coach.asking != sid)

    def live_mic(self):
        """The iPhone's microphone, cut into utterances here, muted while the coach speaks."""
        index = device("audio", self.args.mic)
        raw = self.work / "mic.raw"
        process = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "avfoundation", "-i", f":{index}", "-ac", "1", "-ar",
                                    "16000", "-f", "f32le", "-"], stdout=subprocess.PIPE)
        self.processes.append(process)
        cutter = Cutter()
        self.mic_start = time.time()
        with open(raw, "wb") as keep:
            while not self.stopped.is_set():
                block = process.stdout.read(3200 * 4)
                if not block:
                    return
                keep.write(block)
                cutter.muted = self.lens.speaking()
                samples = np.frombuffer(block, np.float32)
                for utterance, start, end in cutter.feed(samples, time.time() - len(samples) / 16000):
                    threading.Thread(target=self.lens.hear, args=(wav_bytes(utterance), end), daemon=True).start()

    def frames(self):
        """(source of JPEGs, frame count or None). The video: decoded once at 10 fps. The camera: newest frame."""
        if self.args.video:
            first, last = VIDEO_SPAN
            process = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(first), "-t", str(last - first), "-i",
                                      os.path.expanduser(self.args.video), "-vf", f"fps={FPS},scale=1280:720", "-q:v", "4",
                                      "-f", "image2pipe", "-c:v", "mjpeg", "-"], capture_output=True, check=True)
            return list(jpegs(io.BytesIO(process.stdout)))
        index = device("video", self.args.camera)
        process = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "avfoundation", "-framerate", "30", "-pixel_format", "nv12",
                                    "-i", f"{index}:none",
                                    "-vf", f"fps={FPS},scale=1280:720:force_original_aspect_ratio=decrease,"
                                    "pad=1280:720:(ow-iw)/2:(oh-ih)/2", "-q:v", "4", "-f", "image2pipe", "-c:v", "mjpeg",
                                    "-"], stdout=subprocess.PIPE)
        self.processes.append(process)
        self.newest = None

        def read():
            for jpeg in jpegs(process.stdout):
                self.newest = jpeg
        threading.Thread(target=read, daemon=True).start()
        deadline = time.time() + 30
        while self.newest is None:
            if process.poll() is not None or time.time() > deadline:
                raise SystemExit(f"no frame from the camera {self.args.camera!r} in 30 s: is the iPhone near and locked, "
                                 "and has this terminal camera and microphone access (System Settings, Privacy)?")
            time.sleep(0.05)
        return None

    def run(self):
        import cv2
        self.work.mkdir(parents=True, exist_ok=True)
        self.processes, self.stopped = [], threading.Event()
        self.voice = Voice(self.work)
        self.voice.synth("Hola.")  # loads the model before the clock starts
        clip = self.frames()
        self.start_agent()
        self.t0 = time.time()
        self.lens = Lens(PORT, self.token, self.voice, live_audio=not self.args.video, t0=self.t0)
        credit = ("Cámara: video público de instalación (prueba local) · voz del padre: MMS-TTS · lente simulada"
                  if self.args.video else "Cámara: iPhone en la cabeza (Continuity Camera) · lente simulada")
        painter = Painter(1280, 720, credit)
        silent = self.work / "frames.mp4"
        writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (1280, 720))
        if clip is not None:
            self.cursor = Cursor(VIDEO_SPAN[0])
            director = threading.Thread(target=self.direct, daemon=True)
            director.start()
        else:
            threading.Thread(target=self.live_mic, daemon=True).start()
            print("live: say \"Agente, ayudame a instalar la silla del auto\". Ctrl-C ends the take.", flush=True)
        n, limit = 0, self.args.max_minutes * 60 * FPS
        try:
            while n < limit:
                jpeg = clip[self.cursor.step(len(clip))] if clip is not None else self.newest
                self.lens.frame(jpeg)
                frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                step = next((e["step"] for e in reversed(self.agent.bus.history) if e["kind"] == "carseat_step"), "")
                writer.write(painter.draw(frame, self.lens, step))
                n += 1
                if clip is not None and not director.is_alive():
                    break
                time.sleep(max(0.0, self.t0 + n / FPS - time.time()))
        except KeyboardInterrupt:
            pass
        finally:
            writer.release()
            self.stopped.set()
            self.lens.stopped = True
            self.stop_agent()
        return self.report(silent, n / FPS)

    def stop_agent(self):
        coach = self.coach_plugin
        if coach.coach is not None:
            coach.coach.stop()
        vision = getattr(getattr(coach, "coach", None), "vision", None)
        for plugin in self.agent.plugins:
            plugin.stop()
        if vision is not None and getattr(vision, "process", None) is not None:
            vision.process.kill()  # the one SAM 3.1 process, stopped
        for process in self.processes:
            process.kill()
        self.voice.close()
        self.agent.stop()
        self.agent.close()

    def report(self, silent, length_s):
        inputs, filters = ["-i", str(silent)], []
        tracks = [(t, p) for t, p, _ in self.lens.audio if 0 <= t < length_s]
        if not self.args.video and (self.work / "mic.raw").exists():
            mic = self.work / "mic.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", "16000", "-ac", "1", "-i",
                            str(self.work / "mic.raw"), str(mic)], check=True)
            tracks.append((round(self.mic_start - self.t0, 3), mic))
        for n, (t, path) in enumerate(tracks, 1):
            inputs += ["-i", str(path)]
            ms = int(max(t, 0) * 1000)
            filters.append(f"[{n}:a]aresample=48000,adelay={ms}|{ms}[a{n}]")
        mix = "".join(f"[a{n}]" for n in range(1, len(tracks) + 1))
        graph = ";".join(filters + [f"{mix}amix=inputs={len(tracks)}:normalize=0,apad[a]"]) if tracks else None
        self.out.parent.mkdir(parents=True, exist_ok=True)
        command = ["ffmpeg", "-v", "error", "-y", *inputs]
        command += (["-filter_complex", graph, "-map", "0:v", "-map", "[a]"] if graph else ["-map", "0:v"])
        command += ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a",
                    "128k", "-t", f"{length_s:.2f}", str(self.out)]
        subprocess.run(command, check=True)
        from parenting_agent.glasses import with_dropped_words
        history = with_dropped_words(self.agent.bus.history, self.dropped)
        keep = ("speech", "carseat_step", "carseat_check", "carseat_heard", "carseat_summary", "glasses_card", "voice",
                "reply", "message", "brain_call", "skill_armed")
        run = {
            "date": time.strftime("%Y-%m-%d %H:%M %z"), "camera": self.args.video or self.args.camera,
            "mic": "MMS-TTS lines through /hear" if self.args.video else self.args.mic, "clip": str(self.out),
            "length_s": round(length_s, 1), "said_again": self.retries,
            "checks": {e["check"]: e.get("result") for e in history if e["kind"] == "carseat_check"},
            "summary": next((e["text"] for e in history if e["kind"] == "carseat_summary"), None),
            "heard": [{k: e.get(k) for k in ("text", "took", "why", "ear_s", "error")} for e in history if e["kind"] == "speech"],
            "cards": [{k: e.get(k) for k in ("cause", "title", "status", "alert", "shown")} for e in history
                      if e["kind"] == "glasses_card"],
            "sam_frames": sum(1 for e in history if e["kind"] == "carseat_frame"),
            "brain_calls": sum(1 for e in history if e["kind"] == "brain_call"),
            "lens": self.lens.timeline,
            "events": [{k: v for k, v in e.items() if k != "results"} for e in history if e["kind"] in keep],
        }
        report = self.out.with_suffix(".json")
        report.write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str) + "\n")
        print(json.dumps({k: run[k] for k in ("clip", "length_s", "checks", "said_again", "summary")}, ensure_ascii=False,
                         indent=1))
        return run


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--video", help="a recorded install video as the camera (the proof run)")
    parser.add_argument("--camera", help="an avfoundation camera by name, e.g. \"iPhone Camera\" (Continuity Camera)")
    parser.add_argument("--mic", default="iPhone Microphone", help="an avfoundation microphone by name, with --camera")
    parser.add_argument("--out", required=True, help="the clip, outside the repo; its report goes next to it as .json")
    parser.add_argument("--max-minutes", type=float, default=20.0)
    args = parser.parse_args()
    if bool(args.video) == bool(args.camera):
        parser.error("give --video or --camera")
    import signal

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, stop)  # a run started in the background ignores SIGINT otherwise
    signal.signal(signal.SIGTERM, stop)
    from glasses_hud_speech import GPU_LOCK, gpu_lock
    gpu_lock()
    run = Take(args)
    try:
        run.run()
    finally:
        for process in getattr(run, "processes", []):
            process.kill()
        GPU_LOCK.rmdir()


if __name__ == "__main__":
    main()
