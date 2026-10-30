"""Ray-Ban Meta glasses as the agent's head camera and a channel to talk to it.

The companion iPhone app (apps/glasses) reads the glasses camera through Meta's Wearables Device Access
Toolkit, samples the frames (10 per second by default, see results/glasses/README.md for why not 2) and posts them here as JPEG. It also sends what the
parent says and listens for what the agent says back, which it shows as text and speaks.

    POST /frame   one JPEG, kept in memory as the newest frame, never written to disk
    POST /say     {"text": "..."} becomes a "message" on the "glasses" channel
    GET  /events  server-sent events: replies, chime, voice, skill state, hand state
    GET  /health  frame and listener counts

Every request carries "Authorization: Bearer <pairing token>". The server listens on 127.0.0.1 by default
(the iOS simulator reaches the Mac there). For a real iPhone it listens on one private home network or
Tailscale address, set with glasses.host or PARENTING_AGENT_GLASSES_HOST. A public address or 0.0.0.0 is
refused, so the endpoint is never reachable from outside the house.

The pairing token is never printed. It is written to a file only its owner can read (data/glasses-token, mode 600,
or PARENTING_AGENT_GLASSES_TOKEN_FILE) and the log prints that path. The endpoint is plain HTTP: on a shared home
Wi-Fi anyone on that network can read the token and the frames off the air and then send "yes" on /say. Use the Mac's
Tailscale 100.x address as the host, so the phone and the Mac talk over WireGuard and nothing on the Wi-Fi sees the
token. A home network address is for a network only the family uses.

Add "parenting_agent.glasses:Glasses" to the agent plugins and set a skill's source to "glasses". The skill
gets a view on the one shared server, so arming and finishing a skill never drops the phone's connection.
"""
import collections
import hmac
import ipaddress
import json
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent.plugins import Plugin
from .sources import MAX_FRAME_BYTES, Latest

DEFAULT_PORT = 8766
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
ARRIVALS_KEPT = 600  # about a minute of frames at 10 per second


def check_host(host):
    """The address to listen on, refused unless it is loopback, a private home network or Tailscale address."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError(f"glasses: {host!r} is not an IP address") from error
    if ip.is_unspecified:
        raise ValueError("glasses: refusing to listen on every interface, give one home network address")
    if not (ip.is_loopback or ip in TAILSCALE or (ip.is_private and not ip.is_link_local)):
        raise ValueError(f"glasses: {host} is not a private address, refusing to serve")
    return str(ip)


def write_token(token, path=None):
    """Writes the pairing token to a file only this user can read, and returns the path. The token is never printed."""
    path = Path(path or os.environ.get("PARENTING_AGENT_GLASSES_TOKEN_FILE") or Path("data") / "glasses-token")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as out:
        out.write(token + "\n")
    os.chmod(path, 0o600)
    return path


class GlassesHub(Latest):
    """The one HTTP endpoint the glasses app talks to. Keeps the newest frame and fans events out to the app."""

    _hubs = {}
    _hubs_lock = threading.Lock()

    def __init__(self, port=DEFAULT_PORT, host=None, token=None, on_say=None):
        super().__init__()
        self.is_file = False
        self.host = check_host(host or os.environ.get("PARENTING_AGENT_GLASSES_HOST") or "127.0.0.1")
        self.token = token or os.environ.get("PARENTING_AGENT_GLASSES_TOKEN") or secrets.token_urlsafe(12)
        self.on_say = on_say
        self.clients = []
        self.frames_in, self.rejected = 0, 0
        self.arrivals = collections.OrderedDict()  # stream_s (3 decimals) -> Unix time the frame arrived
        self.server = ThreadingHTTPServer((self.host, port), self._handler())
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f"http://{self.host}:{self.port}/"
        self.thread = threading.Thread(target=self.server.serve_forever, name="glasses", daemon=True)
        self.thread.start()

    @classmethod
    def shared(cls, port=DEFAULT_PORT, token_file=None, **kwargs):
        """One hub per port in this process, so the channel and every skill share the phone's connection."""
        with cls._hubs_lock:
            hub = cls._hubs.get(port)
            if hub is None or hub.stopped:
                hub = cls(port=port, **kwargs)
                cls._hubs[hub.port] = hub
                path = write_token(hub.token, token_file)
                print(f"glasses endpoint: {hub.url} pairing token in {path} (readable by this user only)", flush=True)
            elif kwargs.get("on_say") is not None:
                hub.on_say = kwargs["on_say"]
            return hub

    def view(self):
        return GlassesView(self)

    def authorized(self, headers):
        given = headers.get("Authorization", "")
        return given.startswith("Bearer ") and hmac.compare_digest(given[7:].encode(), self.token.encode())

    def _handler(self):
        hub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def reply(self, code, body=b"", kind="text/plain"):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def length(self):
                """The body length, or None for a Content-Length that is negative or not a number."""
                try:
                    length = int(self.headers.get("Content-Length", 0) or 0)
                except ValueError:
                    return None
                return length if length >= 0 else None

            def guard(self):
                if hub.authorized(self.headers):
                    return True
                hub.rejected += 1
                length = self.length()
                if length is not None and 0 < length <= MAX_FRAME_BYTES:
                    self.rfile.read(length)
                else:
                    self.close_connection = True
                self.reply(401)
                return False

            def do_GET(self):
                if not self.guard():
                    return
                path = self.path.split("?", 1)[0]
                if path == "/events":
                    hub._stream(self)
                elif path == "/health":
                    body = {"frames": hub.frames_in, "listeners": len(hub.clients), "agent": hub.on_say is not None}
                    self.reply(200, json.dumps(body).encode(), "application/json")
                else:
                    self.reply(404)

            def do_POST(self):
                if not self.guard():
                    return
                length = self.length()
                if length is None:
                    # Content-Length -1 would read until the client hangs up and hold a server thread (round 2).
                    self.close_connection = True
                    self.reply(400)
                    return
                if length > MAX_FRAME_BYTES:
                    self.reply(413)
                    self.close_connection = True
                    return
                body = self.rfile.read(length)
                path = self.path.split("?", 1)[0]
                if path == "/frame":
                    self.reply(204 if hub._frame(body) else 400)
                elif path == "/say":
                    try:
                        text = str(json.loads(body or b"{}").get("text", "")).strip()
                    except (ValueError, AttributeError):
                        text = ""
                    if not text:
                        self.reply(400)
                    elif hub.on_say is None:
                        self.reply(503, b"no agent is running on this endpoint")
                    else:
                        hub.on_say(text[:500])
                        self.reply(204)
                else:
                    self.reply(404)

        return Handler

    def _frame(self, body):
        import cv2
        import numpy as np
        frame = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return False
        now = time.monotonic()
        if self.started is None:
            self.started = now
        self.frames_in += 1
        stream_s = now - self.started
        with self.lock:
            self.arrivals[round(stream_s, 3)] = round(time.time(), 3)
            while len(self.arrivals) > ARRIVALS_KEPT:
                self.arrivals.popitem(last=False)
        self.put(frame, stream_s)
        return True

    def arrival(self, stream_s):
        """The Unix time the frame with this stream time reached the endpoint, or None once it is forgotten."""
        with self.lock:
            return self.arrivals.get(round(stream_s, 3))

    def _stream(self, handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        inbox = queue.Queue(maxsize=200)
        inbox.put({"kind": "hello"})
        self.clients.append(inbox)
        try:
            while not self.stopped:
                try:
                    handler.wfile.write(f"data: {json.dumps(inbox.get(timeout=10))}\n\n".encode())
                except queue.Empty:
                    handler.wfile.write(b": keepalive\n\n")
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.clients.remove(inbox)

    def push(self, event):
        """Events with a frame's stream_s carry frame_unix, the time that frame arrived, so the app can time frame to card."""
        if event.get("stream_s") is not None and "frame_unix" not in event:
            event = {**event, "frame_unix": self.arrival(event["stream_s"])}
        for inbox in list(self.clients):
            try:
                inbox.put_nowait(event)
            except queue.Full:
                pass

    def close(self):
        self.stopped = True
        self.server.shutdown()
        self.server.server_close()
        with self._hubs_lock:
            if self._hubs.get(self.port) is self:
                del self._hubs[self.port]


class GlassesView:
    """What a skill holds while it is armed: the hub's newest frames and a way to speak to the app.

    Closing the view stops this skill's watch loop and its speaker, never the hub or the phone's connection.
    """

    def __init__(self, hub):
        self.hub, self.closed = hub, False
        self.is_file, self.url = False, hub.url

    @property
    def stopped(self):
        return self.closed or self.hub.stopped

    @property
    def started(self):
        return self.hub.started

    def latest(self, after_seq):
        return None if self.stopped else self.hub.latest(after_seq)

    def push(self, event):
        if not self.stopped:
            self.hub.push(event)

    def close(self):
        self.closed = True


def _hhmm(stamp):
    from .changing_table import local_hhmm
    return local_hhmm(stamp)


def _frame(event):
    return {"stream_s": event["stream_s"]} if event.get("stream_s") is not None else {}


def _alarm(event):
    if event.get("action") in ("raise", "reraise"):
        return {"kind": "alarm", "state": event.get("state") or "off", "episode": event.get("episode"), **_frame(event)}
    return {"kind": "clear", "episode": event.get("episode"), **_frame(event)}


def _held(event):
    if not event.get("held"):
        return None
    objects = event.get("objects") or []
    return {"kind": "held", "verdict": "on" if event.get("based") else "off", "object": objects[0] if objects else None,
            "model": "SAM 3.1", **_frame(event)}


def _logged(event):
    contents = [word for word, on in (("wet", event.get("wet")), ("dirty", event.get("solid"))) if on]
    return {"kind": "logged", "what": "diaper", "at": _hhmm(event.get("time")), "contents": contents, "entry": event.get("id")}


# The one path from the agent to the app and its glasses display (HUD): bus event kind -> the app event, or None to skip.
# Each app event kind is one card kind in apps/glasses/ParentingGlasses/HUD/HUDState.swift. A new HUD card is one entry
# here and one case there, nothing else: the hub, the event stream, the frame times and DisplayHUD are shared.
TO_APP = {
    "reply": lambda e: {"kind": "reply", "text": e.get("text", "")},
    "ask_parent": lambda e: {"kind": "reply", "text": f"I want to use {e.get('name')}. Say yes to let me."},
    "skill_armed": lambda e: {"kind": "skill", "text": f"{e.get('skill')} armed, watching through the glasses"},
    "skill_closed": lambda e: {"kind": "skill", "text": f"{e.get('skill')} closed after {e.get('frames')} frames"},
    "frame": lambda e: {"kind": "state", "state": e.get("state"), "hands": e.get("hands"), "lift_cm": e.get("lift_cm"),
                        **({"held": e["held"]} if e.get("held") else {}), **_frame(e)},
    "changing_armed": lambda e: {"kind": "armed", "by": e.get("via"), "seconds": e.get("since_words_s"),
                                 **({"tool": "start_changing_table"} if e.get("via") == "brain" else {})},
    "alarm": _alarm,
    "confirm": lambda e: {"kind": "confirm", "verdict": e.get("verdict"), "episode": e.get("episode"), "model": "SAM 3.1",
                          **_frame(e)},
    "anchor": _held,
    "change_read_back": _logged,
    "dog_watch": lambda e: {"kind": "dog", "verdict": e.get("verdict"), "ratio": e.get("ratio"), "dog_score": e.get("dog_score"),
                            "baby_score": e.get("baby_score"), "seconds": e.get("sam_s"), "model": "SAM 3.1", **_frame(e)},
}
FORWARDED = tuple(TO_APP)


def to_app(event):
    """The bus event as the app sees it, or None for events the app does not show."""
    shown = TO_APP.get(event["kind"])
    return shown(event) if shown else None


class Glasses(Plugin):
    """The glasses as an agent channel. Config block "glasses": {"port": 8766, "host": "127.0.0.1"}."""

    name = "glasses"
    kind = "channel"

    def __init__(self, agent, config):
        super().__init__(agent, config)
        self.cfg = {"port": DEFAULT_PORT, **config.get("glasses", {})}
        self.hub = GlassesHub.shared(self.cfg["port"], host=self.cfg.get("host"), token=self.cfg.get("token"),
                                     token_file=self.cfg.get("token_file") or Path(config.get("data_dir", "data")) / "glasses-token",
                                     on_say=self.heard)
        agent.bus.subscribe(self.forward, list(FORWARDED))

    def heard(self, text):
        self.agent.bus.publish("message", channel=self.name, text=text)

    def forward(self, event):
        if event["kind"] in ("reply", "ask_parent") and event.get("channel") != self.name:
            return
        shown = to_app(event)
        if shown is not None:
            self.hub.push(shown)

    def start(self):
        self.agent.bus.publish("channel_started", channel=self.name, url=self.hub.url)

    def stop(self):
        self.hub.close()
