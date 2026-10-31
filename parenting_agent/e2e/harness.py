"""The end-to-end day: the real family agent (config/agent.vostro.json, its plug-ins, Muse on Baseten, Baby Buddy, Home
Assistant reads) through one first-month day and night on a fast clock.

What is real: every plug-in and its own run loop, the brain (Muse Spark Open, the fixed rules as its fallback), the ear
(Muse hears the voice note), Baby Buddy (a new test child per run, entries written by the agent), Home Assistant reads
(states, weather, the shopping list).

What the harness replaces, and why:
- The clock: freezegun moves it one minute per step (clock.py). Each plug-in loop waits in virtual time.
- Telegram: a capturing messenger. Nothing reaches api.telegram.org (refused at the socket call too), the parents are
  fake chat ids, so no real chat can get a message.
- House writes: forced dry. house.live_actions is emptied, and any Home Assistant POST that is not a read service is
  refused before it leaves the Mac.
- The voice service on the Vostro is on an internal network the Mac cannot reach: ffmpeg runs here instead, and the
  spoken reply is recorded as text, not synthesized.
- The night cry: no microphone feeds the family agent, so the cry is a "sound" event marked simulated, the event a
  house microphone would publish.
"""
import collections
import copy
import datetime
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..channels.messaging import Incoming, Messenger
from .clock import REAL

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path.home() / ".parenting-agent.env"
TZ = datetime.timezone(datetime.timedelta(hours=-3))
# The API user cannot create a child (docs/deploy-babybuddy.md), so the run uses the test child "Test Baby" in a
# window after its last entry (Oct 29 05:05) and before now, and removes what it added before the next run.
CHILD = "test-baby"
BASELINE = Path(os.environ.get("E2E_BASELINE", str(Path.home() / ".cache/parenting-agent-e2e-baseline.json")))
CHATS = {"gonza": "9000001", "ceci": "9000002", "grandma": "9000003"}
MUSE_PRICE = (1.25, 4.25)       # USD per million tokens in and out, as in the config
BUDGET_USD = 4.5


def load_env(path=ENV_FILE):
    """Secrets into the process environment. Never printed."""
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")
    os.environ["TELEGRAM_BOT_TOKEN"] = "e2e-no-token"
    os.environ["TELEGRAM_CHAT_ID"] = CHATS["gonza"]
    os.environ["TELEGRAM_CECI_CHAT_ID"] = CHATS["ceci"]


# Transport: the one place every request goes through

class Cached(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return 200


class Transport:
    """Wraps urllib.request.urlopen: refuses Telegram and house writes, counts the brain's tokens and money, and keeps
    one copy of each Home Assistant read per step and of each Baby Buddy read until the next Baby Buddy write."""

    def __init__(self, babybuddy_url, ha_port=18123):
        self.real = urllib.request.urlopen
        self.bb = urllib.parse.urlparse(babybuddy_url)
        self.ha_port = ha_port
        self.cache, self.lock = {}, threading.Lock()
        self.usd, self.calls, self.refused = 0.0, collections.Counter(), []
        self.over_budget = False
        self.down = []

    def install(self):
        urllib.request.urlopen = self.urlopen

    def uninstall(self):
        urllib.request.urlopen = self.real

    def new_step(self):
        """Home Assistant reads are kept for one step. Baby Buddy reads are kept until the next Baby Buddy write: the
        log only changes when something writes to it, and a read takes about a second through the tunnel."""
        with self.lock:
            self.cache = {k: v for k, v in self.cache.items() if self.is_bb(k[1])}

    def is_bb(self, url):
        parsed = urllib.parse.urlparse(url)
        return parsed.hostname == self.bb.hostname and parsed.port == self.bb.port

    def clear_bb(self):
        with self.lock:
            self.cache = {k: v for k, v in self.cache.items() if not self.is_bb(k[1])}

    def urlopen(self, request, *args, **kwargs):
        try:
            return self._urlopen(request, *args, **kwargs)
        except urllib.error.URLError as error:
            url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
            if isinstance(getattr(error, "reason", None), OSError) and (self.is_bb(url) or f":{self.ha_port}" in url):
                self.down.append(str(error)[:120])  # a tunnel is down: the run stops, it would not be the real stack
            raise

    def _urlopen(self, request, *args, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        method = request.get_method() if isinstance(request, urllib.request.Request) else "GET"
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if host.endswith("telegram.org"):
            self.refused.append({"what": "telegram", "path": parsed.path.rsplit("/", 1)[-1]})
            raise urllib.error.URLError("e2e: Telegram is blocked, the capturing messenger is the only channel")
        if parsed.port == self.ha_port and method != "GET" and "return_response" not in parsed.query:
            self.refused.append({"what": "house write", "path": parsed.path})
            raise urllib.error.URLError("e2e: house writes are forced dry")
        reads = (parsed.port == self.ha_port or (host == self.bb.hostname and parsed.port == self.bb.port))
        if reads and method == "GET" or (parsed.port == self.ha_port and "return_response" in parsed.query):
            key = (method, url, getattr(request, "data", None))
            with self.lock:
                if key in self.cache:
                    return Cached(self.cache[key])
            with self.real(request, *args, **kwargs) as response:
                body = response.read()
            with self.lock:
                self.cache[key] = body
            return Cached(body)
        if host == self.bb.hostname and parsed.port == self.bb.port:
            try:
                return self.real(request, *args, **kwargs)
            finally:
                self.clear_bb()
        if host == "inference.baseten.co":
            if self.usd >= BUDGET_USD:
                self.over_budget = True
                raise urllib.error.URLError(f"e2e: brain budget of {BUDGET_USD} USD used")
            with self.real(request, *args, **kwargs) as response:
                body = response.read()
            self.count(host, body)
            return Cached(body)
        return self.real(request, *args, **kwargs)

    def count(self, host, body):
        try:
            usage = json.loads(body).get("usage") or {}
        except ValueError:
            return
        tin, tout, price = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), MUSE_PRICE
        with self.lock:
            self.calls[host] += 1
            self.usd += (tin * price[0] + tout * price[1]) / 1_000_000


# Telegram and the voice service, captured

class CaptureMessenger(Messenger):
    name = "telegram"

    def __init__(self, clock):
        self.clock = clock
        self.inbox, self.sent, self.files = [], [], {}
        self.update_id = 100

    def incoming(self, person, text="", voice=None):
        self.update_id += 1
        file_id = ""
        if voice is not None:
            file_id = f"voice-{self.update_id}"
            self.files[file_id] = Path(voice).read_bytes()
        self.inbox.append(Incoming(self.update_id, CHATS[person], text, person, CHATS[person], "private", "es", file_id))

    def poll(self, offset, timeout):
        batch, self.inbox = [i for i in self.inbox if i.update_id >= offset], []
        return batch

    def send(self, chat_id, text):
        self.sent.append({"at": self.clock.now().isoformat(timespec="seconds"), "chat": str(chat_id), "text": text})
        return len(self.sent)

    def send_voice(self, chat_id, ogg):
        self.sent.append({"at": self.clock.now().isoformat(timespec="seconds"), "chat": str(chat_id), "voice": True,
                          "bytes": len(ogg)})
        return len(self.sent)

    def download(self, file_id, limit=20 * 1024 * 1024):
        return self.files[file_id]

    def me(self):
        return "e2e_capture_bot"


class LocalEarVoice:
    """The voice service's two jobs on the Mac: ffmpeg to WAV for real, the spoken reply recorded as text only."""

    def __init__(self, url=None, timeout=120):
        self.spoken = []

    def to_wav(self, data):
        from ..voice import audio, client
        try:
            return audio.to_wav(data)
        except audio.AudioError as error:
            raise client.VoiceError(str(error)) from None

    def speak(self, text, lang, fmt="ogg"):
        self.spoken.append({"text": text, "lang": lang})
        return b"OggS e2e reply, not synthesized"


# Baby Buddy: a new test child per run, with three days of history

class BabyBuddy:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def call(self, method, path, body=None):
        request = urllib.request.Request(self.url + path, method=method,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Token {self.token}", "Content-Type": "application/json",
                                                  "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def child(self, slug):
        return next(c for c in self.call("GET", "/api/children/?limit=50")["results"] if c["slug"] == slug)

    def entries(self, child_id):
        out = []
        for endpoint in ENDPOINTS:
            page = self.call("GET", f"/api/{endpoint}/?child={child_id}&limit=1000")
            out += [{"endpoint": endpoint, **row} for row in page["results"] if row.get("child") == child_id]
        return out

    def cleanup(self, child_id, start, end, baseline):
        """Removes what the harness added: entries of this child timed inside the run's window that were not there
        before the first run (baseline). Nothing outside the window, nothing from the baseline, nothing with a tag the
        agent or the harness does not write."""
        removed = 0
        for row in self.entries(child_id):
            stamp = row.get("start") or row.get("time")
            if row["id"] in baseline.get(row["endpoint"], ()) or not stamp:
                continue
            moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if start <= moment <= end and set(row.get("tags") or []) <= {"agent", "e2e"}:
                self.call("DELETE", f"/api/{row['endpoint']}/{row['id']}/")
                removed += 1
        return removed


ENDPOINTS = ("feedings", "changes", "sleep", "notes", "timers")


def iso(moment):
    return moment.astimezone(TZ).isoformat(timespec="seconds")


# The run

class Run:
    def __init__(self, label, config_path, out_dir, start, end, script, overrides=None, step_s=60):
        self.label, self.config_path, self.out = label, Path(config_path), Path(out_dir)
        self.start, self.end, self.script, self.overrides, self.step_s = start, end, script, overrides or {}, step_s
        self.turns, self.events_seen, self.last = 0, [], start.isoformat()

    def config(self, child):
        config = json.loads(self.config_path.read_text())
        config = copy.deepcopy(config)
        config["data_dir"] = str(self.out / "data")
        config["env_file"] = "/nonexistent"
        config["baby_log"] = {**config.get("baby_log", {}), "child": child["slug"]}
        config["rhythm"] = {**config.get("rhythm", {}), "child": child["first_name"]}
        house = config.setdefault("house", {})
        house.update(live=False, live_actions=[], ha_url="http://127.0.0.1:18123")
        for key, value in self.overrides.items():
            target = config
            *path, last = key.split(".")
            for part in path:
                target = target.setdefault(part, {})
            target[last] = value
        return config

    def execute(self):
        from . import clock as clock_mod
        from ..agent import build
        from ..channels import telegram as telegram_mod
        from ..voice import client as voice_client

        load_env()
        self.out.mkdir(parents=True, exist_ok=True)
        bb = BabyBuddy(os.environ["BABYBUDDY_URL"], os.environ["BABYBUDDY_TOKEN"])
        child = bb.child(CHILD)
        baseline_path = BASELINE
        if not baseline_path.exists():
            rows = bb.entries(child["id"])
            baseline_path.write_text(json.dumps({e: [r["id"] for r in rows if r["endpoint"] == e] for e in ENDPOINTS}))
        baseline = json.loads(baseline_path.read_text())
        window = (self.start - datetime.timedelta(minutes=30), self.end + datetime.timedelta(minutes=1))
        removed = bb.cleanup(child["id"], *window, baseline)
        seeded = {"history": "Test Baby's own test entries up to Oct 29 05:05, nothing seeded",
                  "removed_before_run": removed}
        config = self.config(child)
        (self.out / "config.json").write_text(json.dumps(config, indent=2))

        transport = Transport(os.environ["BABYBUDDY_URL"])
        transport.install()
        clock = clock_mod.VirtualClock(self.start, TZ)
        messenger = CaptureMessenger(clock)
        telegram_mod.TelegramMessenger = lambda token, api=None: messenger
        voice_client.RemoteVoice = LocalEarVoice
        agent = build(config)
        agent.bus.subscribe(self.on_event)
        channel = next(p for p in agent.plugins if p.name == "telegram")
        channel.run = lambda: None  # the harness polls the capturing messenger itself, one message at a time
        loops = []
        for plugin in agent.plugins:
            if plugin.name in ("heartbeat", "telegram") or not hasattr(plugin, "stopped"):
                continue
            plugin.stopped = clock.event(plugin.name)
            loops.append(plugin.name)
        agent.start()
        for plugin in agent.plugins:
            plugin.start()
        agent.bus.publish("agent_started", brain=agent.brain.name, destination=agent.brain.destination, e2e=self.label)
        stuck = clock.quiet()
        started = REAL["monotonic"]()
        log = []
        script = sorted(self.script, key=lambda s: s["at"])
        try:
            while clock.now() < self.end and not transport.over_budget and not transport.down:
                now = clock.now()
                while script and script[0]["at"] <= now:
                    step = script.pop(0)
                    log.append(self.act(step, agent, channel, messenger, clock))
                    stuck = clock.quiet() or stuck
                clock.advance(self.step_s)
                self.last = clock.now().isoformat()
                transport.new_step()
                busy = clock.quiet()
                if busy:
                    log.append({"at": clock.now().isoformat(), "error": f"loops still busy after 600 s: {busy}"})
        finally:
            for plugin in agent.plugins:
                plugin.stop()
            agent.stop()
            agent.close()
            clock.stop()
            transport.uninstall()
        run = {"label": self.label, "child": {k: child[k] for k in ("id", "first_name", "slug", "birth_date")},
               "seeded": seeded, "start": self.start.isoformat(), "end": self.end.isoformat(),
               "real_seconds": round(REAL["monotonic"]() - started), "loops": loops, "steps": log,
               "sent": messenger.sent, "spoken": channel.voice.backend.spoken if channel.voice else [],
               "brain_usd": round(transport.usd, 4), "brain_calls": dict(transport.calls),
               "refused": transport.refused, "over_budget": transport.over_budget,
               "chats": CHATS, "tunnel_down": transport.down[:5], "stopped_at": self.last,
               "baby_buddy": [r for r in bb.entries(child["id"]) if r["id"] not in baseline.get(r["endpoint"], ())]}
        (self.out / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str))
        return run

    def on_event(self, event):
        if event["kind"] == "turn":
            self.turns += 1

    def act(self, step, agent, channel, messenger, clock):
        at = clock.now().isoformat(timespec="seconds")
        if step["do"] == "sound":
            agent.bus.publish("sound", label=step["label"], phase="start", simulated=True, source="e2e harness")
            return {"at": at, **step}
        before = self.turns
        messenger.incoming(step["who"], step.get("text", ""), voice=step.get("voice"))
        accepted = channel.poll_once(timeout=0)
        end = REAL["monotonic"]() + 300
        while self.turns < before + len(accepted) and REAL["monotonic"]() < end:
            time.sleep(0.05)
        for thread in threading.enumerate():
            if thread.name == "voice-reply":
                thread.join(timeout=60)
        return {"at": at, **{k: v for k, v in step.items() if k != "at"}, "accepted": len(accepted),
                "answered": self.turns >= before + len(accepted)}
