"""Talk to the agent through the Echo Dot or Home Assistant Assist (issue #112), with core Home Assistant only.

Home Assistant hears the words, this bridge turns them into one message for the agent and hands back what the agent
said, for Home Assistant to speak:

    POST /ask     {"text": "...", "source": "echo" | "assist", "person": "..."} -> {"reply": "...", "replies": [...]}
    GET  /health  {"ok": true, "asked": n}

- Assist (the Home Assistant app, the web UI, a voice satellite later): custom sentences match "baby agent ..." and an
  intent_script calls rest_command, then speaks the reply. See deploy/home-assistant/.
- The Echo Dot: the core Alexa Devices integration publishes every voice command the Echo hears on
  event.gonza_s_echo_dot_voice_event. An automation picks the ones that start with "baby agent", calls the same
  rest_command and says the reply on the Echo with notify.gonza_s_echo_dot_speak. No Alexa skill, no skill store.

Every request carries "Authorization: Bearer <token>". The token is written to data/voice-bridge-token (mode 600, or
PARENTING_AGENT_VOICE_TOKEN_FILE) and never printed. The server listens only on loopback, a private home network or
Tailscale address, the same check as the glasses endpoint, never on every interface.

The message goes on the "voice" channel with chat_id "<source>:<person>", so a yes said to the Echo answers only a
question the agent asked on that same voice chat, never one asked on Telegram. One request at a time: the agent
handles its messages in order, so the replies said until the agent's "turn" event are this request's answer.
"""
import hmac
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent.plugins import Plugin
from .glasses import check_host, write_token

DEFAULT_PORT = 8767
CHANNEL = "voice"
SOURCES = ("echo", "assist")
MAX_TEXT = 500
MAX_SPOKEN = 400
WAKE = re.compile(r"^\s*(?:alexa[,\s]+)?(?:(?:ask|tell)\s+)?(?:the\s+)?baby\s+agent[,\s]*(?:that\s+)?", re.IGNORECASE)
WAKE_ES = re.compile(r"^\s*(?:alexa[,\s]+)?(?:(?:preguntale|decile)\s+al\s+)?agente(?:\s+del\s+beb[eé])?[,\s]*(?:que\s+)?",
                     re.IGNORECASE)


def strip_wake(text):
    """The words after "baby agent" (or "agente del bebé"), so the agent sees what the parent asked."""
    text = str(text or "").strip()
    for pattern in (WAKE, WAKE_ES):
        match = pattern.match(text)
        if match and match.end() > 0:
            return text[match.end():].strip()
    return text


def spoken(text):
    """One reply as a speaker says it: no markdown, no links, short."""
    text = re.sub(r"https?://\S+", "", str(text))
    text = re.sub(r"[*`#>]+", "", text).replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= MAX_SPOKEN else text[:MAX_SPOKEN].rsplit(" ", 1)[0] + "."


class VoiceBridge(Plugin):
    name = "voice-bridge"

    def __init__(self, agent, config, token=None):
        super().__init__(agent, config)
        self.s = {"port": DEFAULT_PORT, "host": "127.0.0.1", "timeout_s": 35, **(config.get("voice_bridge") or {})}
        self.host = check_host(os.environ.get("PARENTING_AGENT_VOICE_HOST") or self.s["host"])
        self.token = token or os.environ.get("PARENTING_AGENT_VOICE_TOKEN") or secrets.token_urlsafe(24)
        self.one_at_a_time = threading.Lock()
        self.waiting = None
        self.asked = 0
        self.server = None
        agent.bus.subscribe(self.on_event, ["reply", "ask_parent", "turn"])

    def start(self):
        self.server = ThreadingHTTPServer((self.host, int(self.s["port"])), self.handler())
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        if not os.environ.get("PARENTING_AGENT_VOICE_TOKEN"):
            path = write_token(self.token, self.s.get("token_file") or os.environ.get("PARENTING_AGENT_VOICE_TOKEN_FILE")
                               or os.path.join(self.config.get("data_dir", "data"), "voice-bridge-token"))
            print(f"voice bridge: http://{self.host}:{self.port}/ask token in {path} (readable by this user only)", flush=True)
        threading.Thread(target=self.server.serve_forever, name="voice-bridge", daemon=True).start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    def on_event(self, event):
        waiting = self.waiting
        if waiting is None or event.get("channel") != CHANNEL:
            return
        if event["kind"] == "reply":
            waiting["replies"].append(event["text"])
        elif event["kind"] == "ask_parent" and event.get("source") != "plugin":
            waiting["replies"].append(f"I want to use {event['name']}. Say baby agent yes to let me.")
        elif event["kind"] == "turn":
            waiting["done"].set()

    def ask(self, text, source="assist", person=None):
        """One utterance in, the agent's answer out. Raises TimeoutError when the agent did not finish in time."""
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        words = strip_wake(text)[:MAX_TEXT]
        if not words:
            return {"reply": "Say baby agent, then what to log or ask.", "replies": []}
        if not self.one_at_a_time.acquire(timeout=self.s["timeout_s"]):
            raise TimeoutError("the agent is still answering the last question")
        try:
            self.waiting = {"replies": [], "done": threading.Event()}
            self.asked += 1
            who = re.sub(r"[^a-z0-9_-]", "", str(person or "house").lower())[:32] or "house"
            self.agent.bus.publish("message", channel=CHANNEL, text=words, person=f"{source}:{who}",
                                   chat_id=f"{source}:{who}", source=source)
            if not self.waiting["done"].wait(self.s["timeout_s"]):
                raise TimeoutError("the agent did not answer in time")
            replies = [spoken(r) for r in self.waiting["replies"]]
            return {"reply": " ".join(replies) or "Done.", "replies": replies}
        finally:
            self.waiting = None
            self.one_at_a_time.release()

    def authorized(self, headers):
        given = headers.get("Authorization", "")
        return given.startswith("Bearer ") and hmac.compare_digest(given[7:].encode(), self.token.encode())

    def handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if not bridge.authorized(self.headers):
                    return self.reply(401, {"error": "unauthorized"})
                if self.path == "/health":
                    return self.reply(200, {"ok": True, "asked": bridge.asked})
                return self.reply(404, {"error": "not found"})

            def do_POST(self):
                if not bridge.authorized(self.headers):
                    bridge.agent.bus.publish("voice_bridge", status="unauthorized")
                    return self.reply(401, {"error": "unauthorized"})
                if self.path != "/ask":
                    return self.reply(404, {"error": "not found"})
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > 4096:
                        return self.reply(413, {"error": "too long"})
                    body = json.loads(self.rfile.read(length) or b"{}")
                    result = bridge.ask(body.get("text", ""), body.get("source") or "assist", body.get("person"))
                except (ValueError, json.JSONDecodeError) as error:
                    return self.reply(400, {"error": str(error)[:120]})
                except TimeoutError as error:
                    bridge.agent.bus.publish("voice_bridge", status="timeout")
                    return self.reply(504, {"error": str(error), "reply": "The baby agent is still thinking, ask again in a moment."})
                bridge.agent.bus.publish("voice_bridge", status="answered", source=body.get("source") or "assist",
                                         chars=len(result["reply"]))
                return self.reply(200, result)

        return Handler
