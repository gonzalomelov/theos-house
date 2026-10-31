"""Ray-Ban Meta glasses as the agent's head camera and a channel to talk to it.

The companion iPhone app (apps/glasses) reads the glasses camera through Meta's Wearables Device Access
Toolkit, samples the frames (10 per second by default, see results/glasses/README.md for why not 2) and posts them here as JPEG. It also sends what the
parent says and listens for what the agent says back, which it shows as text and speaks.

    POST /frame   one JPEG, kept in memory as the newest frame, never written to disk
    POST /say     {"text": "..."} becomes a "message" on the "glasses" channel
    POST /hear    one utterance from the glasses microphone, a 16 kHz mono WAV (or {"text": ...} from glasses that
                  transcribe on the device). Muse's ear writes it down and the speech gate decides if it was meant for
                  the agent (glasses_speech.py)
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

Each parent who wears glasses pairs with their own token ("wearers" in the glasses block, one token file each), so
the endpoint knows whose glasses are live. Everything the agent tells that parent that fits a glance also becomes a
display card on their glasses (hud_cards.py): the answer to what they said on the glasses, and the copy of what
reached them on another channel (a Telegram push or the answer to their Telegram message), while that parent's
glasses are listening. The Telegram copy still goes out. Only the parent a message is for gets its card: the same
person the Telegram copy went to, and for the agent's own events (nap mode) the family push's routing.
"""
import collections
import concurrent.futures
import hmac
import ipaddress
import json
import os
import queue
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import hud_cards as cards
from .glasses_speech import EAR_PROMPT, Gate, plain, race
from .agent.people import People
from .agent.plugins import Plugin
from .sources import MAX_FRAME_BYTES, Latest

DEFAULT_PORT = 8766
# A short acknowledgement of a red flag card on the glasses ("entendido", "got it"): the sticky card goes. Matched on the
# plain words (glasses_speech.plain), so the ear's "Ya llame" without the accent counts too.
ACK = re.compile(r"^(ok|okay|got it|understood|entendido|entendi|listo|dale|ya llame|llame|i called|called)\b")
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


def token_path(person, data_dir="data"):
    """The token file of one wearer: data/glasses-token-<person>."""
    return Path(data_dir) / f"glasses-token-{person}"


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

    def __init__(self, port=DEFAULT_PORT, host=None, token=None, on_say=None, person=None):
        super().__init__()
        self.is_file = False
        self.host = check_host(host or os.environ.get("PARENTING_AGENT_GLASSES_HOST") or "127.0.0.1")
        self.token = token or os.environ.get("PARENTING_AGENT_GLASSES_TOKEN") or secrets.token_urlsafe(12)
        self.tokens = {self.token: person}  # token -> the wearer it belongs to (None: a pairing with no person)
        self.profiles = {}                  # wearer -> {"name", "lang"}, sent in the hello
        self.on_say = on_say
        self.on_hear = None                 # (wav bytes or None, wearer, {"text", "speech_end_unix", ...}) -> None
        self.camera_person = person         # whose glasses sent the newest frame
        self.clients = []                   # [(inbox, wearer)]
        self.frames_in, self.rejected = 0, 0
        self.arrivals = collections.OrderedDict()  # stream_s (3 decimals) -> Unix time the frame arrived
        self.server = ThreadingHTTPServer((self.host, port), self._handler())
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f"http://{self.host}:{self.port}/"
        self.thread = threading.Thread(target=self.server.serve_forever, name="glasses", daemon=True)
        self.thread.start()

    def add_wearer(self, person, token=None, profile=None):
        """Pairs one more parent's glasses: their own token. Returns the token, never printed."""
        token = token or secrets.token_urlsafe(12)
        self.tokens[token] = person
        if profile:
            self.profiles[person] = profile
        return token

    def wearer(self, headers):
        """(True, the wearer) for a known token, (False, None) otherwise. Compared in constant time."""
        given = headers.get("Authorization", "")
        if not given.startswith("Bearer "):
            return False, None
        for token, person in list(self.tokens.items()):
            if hmac.compare_digest(given[7:].encode(), token.encode()):
                return True, person
        return False, None

    def live(self, person):
        """True while that parent's glasses app listens to the events: their glasses session is live."""
        return any(who == person for _, who in list(self.clients))

    def wearers_live(self):
        return sorted({who for _, who in list(self.clients) if who is not None})

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
        return self.wearer(headers)[0]

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
                ok, self.person = hub.wearer(self.headers)
                if ok:
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
                    hub._stream(self, self.person)
                elif path == "/health":
                    body = {"frames": hub.frames_in, "listeners": len(hub.clients), "agent": hub.on_say is not None,
                            "wearer": self.person}
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
                    ok = hub._frame(body)
                    if ok and self.person is not None:
                        hub.camera_person = self.person
                    self.reply(204 if ok else 400)
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
                        hub.on_say(text[:500]) if self.person is None else hub.on_say(text[:500], self.person)
                        self.reply(204)
                elif path == "/hear":
                    self.reply(*hub._hear(body, self.headers, self.person))
                else:
                    self.reply(404)

        return Handler

    def _hear(self, body, headers, person):
        """One utterance: a WAV from the microphone, or {"text"} from glasses that transcribe. Handled off this thread."""
        meta = {}
        for name, key in (("X-Speech-End-Unix", "speech_end_unix"), ("X-Speech-Seconds", "speech_s")):
            try:
                meta[key] = float(headers.get(name))
            except (TypeError, ValueError):
                pass
        meta["source"] = str(headers.get("X-Speech-Source") or "glasses mic")[:40]
        wav = None
        if body[:4] == b"RIFF" and body[8:12] == b"WAVE":
            wav = body
        else:
            try:
                meta["text"] = str(json.loads(body or b"{}").get("text", "")).strip()[:500]
            except (ValueError, AttributeError):
                meta["text"] = ""
            if not meta["text"]:
                return 400, b"a WAV or {\"text\": ...}"
        if self.on_hear is None:
            return 503, b"no agent is running on this endpoint"
        meta["received_unix"] = round(time.time(), 3)
        threading.Thread(target=self.on_hear, args=(wav, person, meta), name="glasses-hear", daemon=True).start()
        return 202, b""

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

    def _stream(self, handler, person=None):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        inbox = queue.Queue(maxsize=200)
        hello = {"kind": "hello"}
        if person is not None:
            hello.update(wearer=person, **self.profiles.get(person, {}))
        inbox.put(hello)
        client = (inbox, person)
        self.clients.append(client)
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
            self.clients.remove(client)

    def push(self, event, person=None):
        """Events with a frame's stream_s carry frame_unix, the time that frame arrived, so the app can time frame to card.
        With a person, only that parent's glasses get the event, else every listening app."""
        if event.get("stream_s") is not None and "frame_unix" not in event:
            event = {**event, "frame_unix": self.arrival(event["stream_s"])}
        for inbox, who in list(self.clients):
            if person is not None and who != person:
                continue
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
        """A skill's event goes to the glasses whose camera it watches (the newest frame's wearer)."""
        if not self.stopped:
            self.hub.push(event, self.hub.camera_person)

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
    "skill_armed": lambda e: {"kind": "skill", "skill": e.get("skill"), "text": f"{e.get('skill')} armed, watching through the glasses"},
    "skill_closed": lambda e: {"kind": "skill", "skill": e.get("skill"), "text": f"{e.get('skill')} closed after {e.get('frames')} frames"},
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
    """The glasses as an agent channel. Config block "glasses":
        {"port": 8766, "host": "127.0.0.1", "person": "gonza", "wearers": ["gonza", "ceci"],
         "speech": {"wake_words": ["agente", "agent"], "ear": {"reasoning_effort": "minimal"}}}
    "wearers" pairs each parent's glasses with their own token (data/glasses-token-<person>, or the env variable
    PARENTING_AGENT_GLASSES_TOKEN_<PERSON>). "person" names the wearer of the single legacy token. "speech" sets the
    glasses microphone's gate and Muse's ear (glasses_speech.py)."""

    name = "glasses"
    kind = "channel"
    CARD_KINDS = ("routine", "carseat_step", "carseat_summary", "voice")
    # What the agent waits to hear, by the event that opens or closes the wait (glasses_speech.Gate)
    WAITS = {"changing_armed": ("finish", True), "change_read_back": ("finish", False), "ask_parent": ("answer", True),
             "carseat_heard": ("answer", False), "carseat_summary": ("answer", False)}

    def __init__(self, agent, config, clock=time.time):
        super().__init__(agent, config)
        self.cfg = {"port": DEFAULT_PORT, **config.get("glasses", {})}
        self.data_dir = config.get("data_dir", "data")
        self.people = getattr(agent, "people", None) or People(config.get("people"))
        self.house_live = bool((config.get("house") or {}).get("live"))
        self.clock = clock  # the real time a card left the agent, for latency
        self.car_seat = {"steps": [], "index": 0}
        self.hub = GlassesHub.shared(self.cfg["port"], host=self.cfg.get("host"), token=self.cfg.get("token"),
                                     token_file=self.cfg.get("token_file") or Path(self.data_dir) / "glasses-token",
                                     on_say=self.heard, person=self.cfg.get("person"))
        for person in self.cfg.get("wearers") or []:
            env = f"PARENTING_AGENT_GLASSES_TOKEN_{person.upper()}"
            token = self.hub.add_wearer(person, os.environ.get(env), self.profile(person))
            path = write_token(token, token_path(person, self.data_dir))
            print(f"glasses: {person}'s pairing token in {path} (readable by this user only)", flush=True)
        if self.cfg.get("person"):
            self.hub.profiles[self.cfg["person"]] = self.profile(self.cfg["person"])
        agent.bus.subscribe(self.forward, list(FORWARDED) + list(self.CARD_KINDS))
        speech = self.cfg.get("speech") or {}
        self.gate = Gate(**({"wake_words": speech["wake_words"]} if speech.get("wake_words") else {}))
        self.ear_cfg = speech.get("ear") or {}
        self.race_cfg = {k: speech[k] for k in ("calls", "rounds") if k in speech}
        self._make_ear = None
        self.ear_pool = concurrent.futures.ThreadPoolExecutor(max_workers=12, thread_name_prefix="glasses-ear")
        self.hub.on_hear = self.hear
        agent.bus.subscribe(self.track_waits, list(self.WAITS) + ["carseat_step", "skill_closed"])

    def profile(self, person):
        return {"name": self.people.name(person) or person.capitalize(), "lang": self.lang(person)}

    def lang(self, person):
        return self.people.lang(person) or "en"

    def heard(self, text, person=None, pushed=False):
        if person is not None:
            if not pushed:
                self.hub.push({"kind": "heard", "text": text}, person)
            if ACK.match(plain(text)) and len(text) <= 40:
                self.hub.push({"kind": "red_flag_clear", "by": "parent"}, person)
                self.gate.wait(person, "ack", False)
        self.agent.bus.publish("message", channel=self.name, text=text, person=person,
                               **({"chat_id": person} if person is not None else {}))

    # Speech

    def make_ear(self):
        """One ear call: Muse Spark Open on Baseten, the same as voice notes, one attempt (the race asks again)."""
        if self._make_ear is not None:
            return self._make_ear()
        from .voice.ear import Ear
        return Ear(**{"reasoning_effort": "minimal", "attempts": 1, "prompt": EAR_PROMPT, **self.ear_cfg})

    def hear(self, wav, person=None, meta=None):
        """One utterance from a wearer's glasses: Muse's ear writes it down (or the glasses did), the gate decides if it
        was for the agent, and only then it becomes a message, the same as words typed on the glasses."""
        meta = dict(meta or {})
        text, ear_s, error, ear_info = meta.pop("text", ""), None, None, {}
        if wav is not None:
            started = time.monotonic()
            try:
                text, ear_info = race(self.make_ear, wav, pool=self.ear_pool, **self.race_cfg)
            except Exception as failure:  # the ear failing must never stop the channel, it is logged and shown
                error = str(failure)[:200]
            ear_s = round(time.monotonic() - started, 3)
        decision = self.gate.decide(text, person) if error is None else {"take": False, "text": "", "why": "ear failed"}
        heard = {"text": text, "took": decision["take"], "why": decision["why"], "ear": "muse" if wav is not None else
                 meta.get("source"), "ear_s": ear_s, "heard_unix": round(self.clock(), 3), **meta}
        self.agent.bus.publish("speech", person=person, **heard, ear_calls=ear_info.get("calls"),
                               ear_answers=ear_info.get("answers"), **({"error": error} if error else {}))
        if person is not None:
            self.hub.push({"kind": "heard", **heard}, person)
        if decision["take"]:
            if decision["why"].startswith("answer"):
                self.gate.wait(person, "answer", False)  # one answer per question, the next question opens it again
            self.heard(decision["text"], person, pushed=True)
        return decision

    def track_waits(self, event):
        kind = event["kind"]
        person = self.hub.camera_person
        if kind == "carseat_step":
            self.gate.wait(person, "answer", event.get("step_kind") == "ask")
        elif kind == "skill_closed":
            self.gate.wait(person, "finish", False)
        elif kind == "ask_parent" and event.get("channel") != self.name:
            return
        elif kind in self.WAITS:
            wait, on = self.WAITS[kind]
            self.gate.wait(person, wait, on)

    # Cards

    def send_card(self, card, person, cause, via):
        """One card to one parent's glasses, while they are live. Every send is a "glasses_card" event in the log."""
        if card is None or person is None:
            return None
        live = self.hub.live(person)
        if card.get("sticky"):
            self.gate.wait(person, "ack")
        self.agent.bus.publish("glasses_card", person=person, topic=card["topic"], via=via, cause=cause, shown=live,
                               title=card["title"], status=card["status"], alert=card["alert"], sticky=card["sticky"])
        if live:
            self.hub.push({"kind": "card", "card": card, "cause": cause, "via": via, "agent_unix": round(self.clock(), 3)},
                          person)
        return card

    def person_of_reply(self, event):
        """The parent a reply on another channel reached: its person, or the person of its chat."""
        if event.get("person"):
            return self.people.person(event["person"]) or event["person"]
        channel = find_plugin(self.agent, event.get("channel"))
        person_of = getattr(channel, "person_of", None)
        return person_of(str(event["chat_id"])) if person_of and event.get("chat_id") else None

    def routed(self, event):
        """The parents an event of the agent's own is for: the family push's routing (the Telegram rule), else all."""
        push = find_plugin(self.agent, "family-push")
        if push is not None and hasattr(push, "route"):
            return push.route(event)[0]
        return self.people.keys()

    def forward(self, event):
        kind = event["kind"]
        if kind == "reply" and event.get("channel") != self.name:
            person = self.person_of_reply(event)
            if person is None:
                return None
            lang = self.lang(person)
            card = cards.from_push(event, lang) if event.get("proactive") else cards.from_reply(event, lang)
            return self.send_card(card, person, event.get("routine") or event.get("source") or "reply", event.get("channel"))
        if kind == "ask_parent" and event.get("channel") != self.name:
            return None
        if kind == "routine":
            if event.get("name") != "nap_mode" or event.get("step") not in ("on", "off"):
                return None
            since = _hhmm(event["since"]) if event.get("since") else None
            for person in self.routed({"routine": "nap_mode", **event}):
                self.send_card(cards.nap_mode(event["step"], self.lang(person), event.get("sleep"), since, self.house_live),
                               person, f"nap_mode {event['step']}", "house")
            return None
        if kind in ("carseat_step", "carseat_summary", "voice"):
            return self.car_seat_card(event)
        person = self.hub.camera_person
        if kind == "reply":
            person = event.get("chat_id") or person
            if (event.get("text") or "").rstrip().endswith("?"):
                self.gate.wait(person, "answer")  # the agent asked this wearer something: a spoken "sí" answers it
            self.send_card(cards.from_reply(event, self.lang(person)), person, "reply", self.name)
        elif kind == "skill_armed" and event.get("skill") == "bath":
            self.send_card(cards.bath(self.lang(person)), person, "skill_armed bath", "camera")
        shown = to_app(event)
        if shown is not None:
            self.hub.push(shown, person)
        return None

    def car_seat_card(self, event):
        """The car seat coach (carseat/coach.py), step by step, on the glasses whose camera it watches."""
        state = self.car_seat
        if event["kind"] == "carseat_step":
            if not state["steps"] or event["step"] in state["steps"][:state["index"]]:
                state["steps"] = car_seat_steps()
            state["index"] = state["steps"].index(event["step"]) + 1 if event["step"] in state["steps"] else state["index"] + 1
            state["kind"] = event.get("step_kind")
            return None
        person = self.hub.camera_person
        if event["kind"] == "carseat_summary":
            return self.send_card(cards.car_seat("summary", self.lang(person)), person, "carseat_summary", "camera")
        if event.get("skill") != "car-seat" or event.get("step") in (None, "summary"):
            return None
        card = cards.car_seat(event["step"], self.lang(person), state["index"], len(state["steps"]), event.get("result"),
                              ask=state.get("kind") == "ask")
        return self.send_card(card, person, f"car seat {event['step']}", "camera")

    def start(self):
        self.agent.bus.publish("channel_started", channel=self.name, url=self.hub.url)

    def stop(self):
        self.hub.close()
        self.ear_pool.shutdown(wait=False, cancel_futures=True)


def car_seat_steps(skill="skills/car-seat.json"):
    """The coach's step ids in order, from the same plan the coach runs."""
    from .carseat.coach import CAMERA_STEPS
    try:
        hand = [h["id"] for h in json.loads(Path(skill).read_text())["hand_checks"]]
    except (OSError, ValueError, KeyError):
        hand = []
    return ["car_position", *CAMERA_STEPS, *hand]


def find_plugin(agent, name):
    return next((p for p in getattr(agent, "plugins", []) if getattr(p, "name", "") == name), None)
