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

Who speaks decides what the words can do. A person tag that names a parent in the "people" block goes to the agent as
above. A guest (a name in "guests", or anyone unknown when "unknown_speaker" is "guest", as on the Vostro where the Echo
cannot tell who spoke) only reads: VoiceGuest answers from the baby log with Muse Spark Open and read tools alone, never
logs, never acts on the house and never answers a yes. Red flags, newborn call-now signs, health and safe sleep get the
same fixed lines as a parent, with no brain call.

Settings under "voice_bridge": host ("container" for the agent's own address on its internal network), port, timeout_s,
token_file, guests, unknown_speaker ("parent" or "guest"). The token is kept in its file across restarts, so Home
Assistant's copy stays valid.

The Alexa skill "baby agent" (issue #177) comes in through its own door: a Cloudflare hostname behind an Access service
token, then deploy/door, then the relay on 8767. It carries its own token, "skill" in the settings: {"token_file": ...,
"role": "guest" | "parent"}. "guest" keeps every skill caller a guest whatever person it names. A skill request may
carry a "request_id": the same id asked again waits for the first answer and never runs the question twice, so the
skill can say a holding line within Alexa's 8 seconds and fetch the answer on the next turn.

Role "echo_log" is the skill's write mode (echo_log.py): a question is answered as a guest's, read only, and anything
else goes through the family agent's loop and guards with the baby log tools alone. A write is never made on that turn:
the reply asks once ("¿Anoto 90 ml de mamadera a las 7:50? Decí sí") and carries {"confirm": {"id": ...}}. Only a
request {"confirm": id} from the skill writes it, tagged "echo". {"cancel": id} drops it. No house action and no
message to anyone can come from this role.

Every spoken reply says dates the way people do ("ayer a las 10:55", spoken_time.py), never "2026-10-31".
"""
import hmac
import json
import os
import re
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent import final_guard
from .agent import brain as brain_mod
from .agent import rules
from .agent.memory import feed_start
from .agent.people import People
from .agent.plugins import Plugin
from .channels.push import find_plugin
from .echo_log import EchoWriter
from .glasses import check_host, write_token
from .spoken_time import natural_dates

DEFAULT_PORT = 8767
CHANNEL = "voice"
SOURCES = ("echo", "assist")
SKILL_ROLES = ("guest", "parent", "echo_log")
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


def own_address(host):
    """"container" is this container's address on its own network, so the bridge listens there and nowhere else."""
    return socket.gethostbyname(socket.gethostname()) if host == "container" else host


def kept_token(path):
    """The token a previous run wrote, or None."""
    try:
        token = Path(path).read_text().strip()
    except OSError:
        return None
    return token if len(token) >= 24 else None


GUEST_TOOLS = ("read_baby_log", "baby_summary", "current_time")
GUEST_SYSTEM = """You answer {who}, a family member who asks out loud at the kitchen speaker about {baby}. {who} can only \
read: you have the baby log, read only.
- Answer in one or two short spoken sentences in {language}. No lists, no markdown, no links.
- Read the log with read_baby_log or baby_summary before you say any time or amount, and never guess one. Say times as \
H:MM, and say the day when it is not today as yesterday or the day and month, never a date in digits (today is {today}).
- Never give medical advice, a diagnosis, a dose or a treatment.
- You cannot log anything, change anything, act on the house or read anything beyond the baby log. If {who} asks you \
to, say that only the parents can, from their phones.
"""
GUEST_LINES = {
    "health": {"es": "No puedo ayudar con preguntas de salud. Llamá a los padres ahora. Si no los ubicás, llamá al "
                     "pediatra. En una emergencia, llamá al 911.",
               "en": "I can't help with health questions. Please call the parents now. If you cannot reach them, call "
                     "the pediatrician. In an emergency call 911."},
    "read_only": {"es": "Solo los padres pueden anotar o cambiar algo, desde su teléfono. Yo te puedo leer el registro.",
                  "en": "Only the parents can log or change anything, from their phones. I can read you the log."},
    "failed": {"es": "Ahora no pude leer el registro. Preguntale a los padres.",
               "en": "I could not read the log just now. Please ask the parents."},
}


class VoiceGuest:
    """Read-only answers for a guest at the speaker: the fixed safety lines first, then Muse Spark Open with the read
    tools of the baby log only. Nothing it does writes to the log, the house or the agent's memory."""

    def __init__(self, agent, baby="the baby", max_steps=4):
        self.agent, self.baby, self.max_steps = agent, baby, max_steps
        self.tools = {name: agent.tools.items[name] for name in GUEST_TOOLS if name in agent.tools.items}

    def fixed(self, words, lang):
        """The gate's own line for a red flag, a newborn sign, health or safe sleep, or None."""
        if rules.spoken_emergency(words) or self.agent.screened_emergency(words):
            return "emergency", rules.EMERGENCY_REPLY[lang]
        today = self.agent.now().date()
        kind = rules.newborn_red_flag(words, rules.under_3_months(self.agent.birth_date(), today))
        if kind:
            return f"urgent_{kind}", rules.URGENT_REPLY[kind][lang]
        if rules.is_safe_sleep_question(words):
            return "safe_sleep_fact", rules.SAFE_SLEEP_FACT[lang]
        if rules.is_health(words):
            return "health", GUEST_LINES["health"][lang]
        return None

    def run_tool(self, call, used):
        tool = self.tools.get(call["name"])
        used.append(call["name"])
        if tool is None:
            self.agent.bus.publish("guest_denied", sitter="voice", name=call["name"])
            return f"{call['name']} is not available to a guest, only reading the baby log is"
        try:
            return tool.handler(**(call["arguments"] or {}))
        except (TypeError, ValueError, KeyError, RuntimeError) as error:
            return f"{call['name']} failed: {error}"

    def brain(self, words, who, lang):
        """Muse with the read tools. Returns (text, tools used)."""
        system = GUEST_SYSTEM.format(who=who, baby=self.baby, today=self.agent.now().date().isoformat(),
                                     language="Spanish" if lang == "es" else "English")
        specs = [tool.spec() for tool in self.tools.values()]
        transcript, used = [{"role": "user", "text": words}], []
        for _ in range(self.max_steps):
            reply, seconds = brain_mod.timed(self.agent.brain, system, transcript, specs)
            usage = reply.usage or {}
            self.agent.bus.publish("brain_call", provider=self.agent.brain.name, model=self.agent.brain.model,
                                   destination=self.agent.brain.destination, seconds=seconds,
                                   tool_calls=len(reply.tool_calls), input_tokens=usage.get("input_tokens"),
                                   output_tokens=usage.get("output_tokens"), usd=reply.usd,
                                   fallback=bool(reply.fallback), guest=True)
            if not reply.tool_calls:
                return (reply.text or "").strip(), used
            transcript.append({"role": "assistant", "text": reply.text, "tool_calls": reply.tool_calls})
            for call in reply.tool_calls:
                transcript.append({"role": "tool", "id": call["id"], "name": call["name"],
                                   "result": self.run_tool(call, used)})
        return "", used

    def checked(self, text, words, lang):
        """The brain's words, or the log's own line when they claim a write or miss the last feed's time."""
        if not text:
            return "empty", None
        if rules.claims_done(text) or rules.claims_done(text.lower()) or rules.claims_acted(text):
            return "claimed_write", GUEST_LINES["read_only"][lang]
        if rules.asks_last_feed(words):
            last = self.agent.latest_of("feeding")
            hhmm = str(feed_start(last or {}) or "")[11:16]
            if last is None or not hhmm or (hhmm not in text and hhmm.lstrip("0") not in text):
                return "last_feed_time", self.agent.last_feed_text(lang)
        return None, text

    def ask(self, words, who, lang=None):
        lang = lang if lang in ("es", "en") else self.agent.lang(words)
        fixed = self.fixed(words, lang)
        used, guard = [], None
        if fixed:
            guard, text = fixed
        else:
            try:
                text, used = self.brain(words, who, lang)
            except brain_mod.BrainError as error:
                self.agent.bus.publish("agent_error", error=str(error)[:300], guest=True)
                text = ""
            guard, kept = self.checked(text, words, lang)
            if kept is None:
                kept = self.agent.last_feed_text(lang) if rules.asks_last_feed(words) else GUEST_LINES["failed"][lang]
            text = final_guard.apply(kept, lang, self.agent.bus, where="voice:guest", names=self.agent.guard_names())
        self.agent.bus.publish("voice_guest", person=who, question=words, reply=text, tools=used, guard=guard,
                               lang=lang)
        return text


class VoiceBridge(Plugin):
    name = "voice-bridge"

    def __init__(self, agent, config, token=None, skill_token=None):
        super().__init__(agent, config)
        self.s = {"port": DEFAULT_PORT, "host": "127.0.0.1", "timeout_s": 35, "guests": [], "unknown_speaker": "parent",
                  **(config.get("voice_bridge") or {})}
        self.host = check_host(own_address(os.environ.get("PARENTING_AGENT_VOICE_HOST") or self.s["host"]))
        self.token_file = (self.s.get("token_file") or os.environ.get("PARENTING_AGENT_VOICE_TOKEN_FILE")
                           or os.path.join(config.get("data_dir", "data"), "voice-bridge-token"))
        self.kept = token is None and not os.environ.get("PARENTING_AGENT_VOICE_TOKEN") and kept_token(self.token_file)
        self.token = token or os.environ.get("PARENTING_AGENT_VOICE_TOKEN") or self.kept or secrets.token_urlsafe(24)
        self.skill = None
        if self.s.get("skill"):
            skill = self.s["skill"]
            if skill.get("role", "guest") not in SKILL_ROLES:
                raise ValueError("voice_bridge.skill.role must be guest, parent or echo_log")
            path = skill.get("token_file") or os.path.join(config.get("data_dir", "data"), "voice-skill-token")
            kept = None if skill_token else kept_token(path)
            self.skill = {"token": skill_token or kept or secrets.token_urlsafe(24), "file": path, "kept": bool(kept),
                          "role": skill.get("role", "guest")}
        self.answers, self.answers_lock = {}, threading.Lock()
        self.people = getattr(agent, "people", None) or People(config.get("people"))
        self.guests = {str(g).lower() for g in self.s["guests"]}
        self.guest = VoiceGuest(agent, (config.get("baby") or {}).get("name") or "the baby")
        self.writer = EchoWriter(agent, config) if self.skill and self.skill["role"] == "echo_log" else None
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
            path = self.token_file if self.kept else write_token(self.token, self.token_file)
            print(f"voice bridge: http://{self.host}:{self.port}/ask token in {path} (readable by this user only)", flush=True)
        if self.skill:
            path = self.skill["file"] if self.skill["kept"] else write_token(self.skill["token"], self.skill["file"])
            print(f"voice bridge: the Alexa skill's token in {path}, role {self.skill['role']}", flush=True)
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

    def role(self, person):
        """"parent" for a person in the people block, "guest" for a named guest, else the unknown_speaker setting."""
        if person and self.people.person(person):
            return "parent"
        if str(person or "").strip().lower() in self.guests:
            return "guest"
        return "guest" if self.s["unknown_speaker"] == "guest" else "parent"

    def ask(self, text, source="assist", person=None, via="home-assistant", lang=None, confirm=None, cancel=None):
        """One utterance in, the agent's answer out. Raises TimeoutError when the agent did not finish in time."""
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        lang = lang if lang in ("es", "en") else None
        writing = via == "skill" and self.writer is not None
        if (confirm or cancel) and not writing:
            raise ValueError("only the Alexa skill in echo_log mode confirms a write")
        words = strip_wake(text)[:MAX_TEXT]
        if not words and not (confirm or cancel):
            return {"reply": "Say baby agent, then what to log or ask.", "replies": []}
        if not self.one_at_a_time.acquire(timeout=self.s["timeout_s"]):
            raise TimeoutError("the agent is still answering the last question")
        try:
            self.asked += 1
            pediatrician = find_plugin(self.agent, "pediatrician")
            if pediatrician is not None and not (confirm or cancel) and pediatrician.asks_summary(words):
                # "resumen para la pediatra": read only, the numbers and how many questions, never their text (anyone
                # in the kitchen hears it), for a guest, a parent and the skill alike (pediatrician.py).
                lang = lang or self.agent.lang(words)
                reply = spoken(pediatrician.spoken(lang))
                return self.said({"reply": reply, "replies": [reply], "role": "read"}, lang)
            if writing:
                lang = lang or self.agent.lang(words)
                return self.said(self.write(words, lang, confirm, cancel), lang)
            who = re.sub(r"[^a-z0-9_-]", "", str(person or "house").lower())[:32] or "house"
            role = self.role(person)
            if via == "skill" and self.skill["role"] == "guest":
                role = "guest"
            if role == "guest":
                reply = spoken(self.guest.ask(words, who if person else "guest", lang))
                return self.said({"reply": reply, "replies": [reply], "role": "guest"}, lang or self.agent.lang(words))
            self.waiting = {"replies": [], "done": threading.Event()}
            self.agent.bus.publish("message", channel=CHANNEL, text=words, person=f"{source}:{who}",
                                   chat_id=f"{source}:{who}", source=source)
            if not self.waiting["done"].wait(self.s["timeout_s"]):
                raise TimeoutError("the agent did not answer in time")
            replies = [spoken(r) for r in self.waiting["replies"]]
            return self.said({"reply": " ".join(replies) or "Done.", "replies": replies, "role": "parent"},
                             lang or self.agent.lang(words))
        finally:
            self.waiting = None
            self.one_at_a_time.release()

    def write(self, words, lang, confirm=None, cancel=None):
        """The skill's write mode: a question read as a guest's, anything else asked first and written after the yes."""
        if confirm:
            result = self.writer.confirm(confirm, lang)
        elif cancel:
            result = self.writer.cancel(lang)
        elif rules.is_question(words) and not rules.is_log_request(words) and not rules.is_edit_request(words):
            self.writer.drop()
            result = {"reply": self.guest.ask(words, "echo", lang)}
        else:
            result = self.writer.turn(words, lang)
        reply = spoken(result["reply"])
        return {**result, "reply": reply, "replies": [reply], "role": "echo_log"}

    def said(self, result, lang):
        """Dates and times in the reply as a person says them: "ayer a las 10:55", never "2026-10-31"."""
        now = self.agent.now()
        lang = lang if lang in ("es", "en") else "en"
        fever = self.agent.fever_line(lang, spoken=True)
        if fever and not any(rules.carries_safety_line(r) for r in [result["reply"]] + list(result.get("replies") or [])):
            # A fever in the log leads every Echo answer with the fixed call-now line, the same words as the gate,
            # unless the answer is already a safety line (round b5: the Echo never said it).
            self.agent.bus.publish("guard", status="fever_first", where="voice")
            result["reply"] = fever + " " + result["reply"]
            result["replies"] = [fever] + list(result.get("replies") or [])
        result["reply"] = natural_dates(result["reply"], now, lang)
        result["replies"] = [natural_dates(r, now, lang) for r in result.get("replies", [])]
        return result

    def once(self, key, work):
        """The first request with this key does the work. The same key again waits for that answer, never a second run."""
        with self.answers_lock:
            entry = self.answers.get(key)
            first = entry is None
            if first:
                entry = self.answers[key] = {"done": threading.Event(), "result": None, "error": None}
                while len(self.answers) > 32:
                    self.answers.pop(next(iter(self.answers)))
        if first:
            try:
                entry["result"] = work()
            except Exception as error:
                entry["error"] = error
                raise
            finally:
                entry["done"].set()
            return entry["result"], False
        if not entry["done"].wait(self.s["timeout_s"]):
            raise TimeoutError("the agent is still answering this question")
        if entry["error"] is not None:
            raise entry["error"]
        return entry["result"], True

    def authorized(self, headers):
        """Which door the request came through, "home-assistant" or "skill", or None for a wrong or missing token."""
        given = headers.get("Authorization", "")
        if not given.startswith("Bearer "):
            return None
        given = given[7:].encode()
        if hmac.compare_digest(given, self.token.encode()):
            return "home-assistant"
        if self.skill and hmac.compare_digest(given, self.skill["token"].encode()):
            return "skill"
        return None

    def handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body):
                data = json.dumps(body).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the skill stopped waiting at its 8 s limit: the answer is kept for its request_id

            def do_GET(self):
                if not bridge.authorized(self.headers):
                    return self.reply(401, {"error": "unauthorized"})
                if self.path == "/health":
                    return self.reply(200, {"ok": True, "asked": bridge.asked})
                return self.reply(404, {"error": "not found"})

            def do_POST(self):
                via = bridge.authorized(self.headers)
                if not via:
                    bridge.agent.bus.publish("voice_bridge", status="unauthorized")
                    return self.reply(401, {"error": "unauthorized"})
                if self.path != "/ask":
                    return self.reply(404, {"error": "not found"})
                repeat = False
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > 4096:
                        return self.reply(413, {"error": "too long"})
                    body = json.loads(self.rfile.read(length) or b"{}")
                    request_id = str(body.get("request_id") or "")[:80]

                    def work():
                        return bridge.ask(body.get("text", ""), body.get("source") or "assist", body.get("person"), via,
                                          body.get("lang"), body.get("confirm"), body.get("cancel"))

                    if request_id:
                        result, repeat = bridge.once((via, request_id), work)
                    else:
                        result = work()
                except (ValueError, json.JSONDecodeError) as error:
                    return self.reply(400, {"error": str(error)[:120]})
                except TimeoutError as error:
                    bridge.agent.bus.publish("voice_bridge", status="timeout", via=via)
                    return self.reply(504, {"error": str(error), "reply": "The baby agent is still thinking, ask again in a moment."})
                bridge.agent.bus.publish("voice_bridge", status="answered", source=body.get("source") or "assist",
                                         role=result.get("role"), chars=len(result["reply"]), via=via, repeat=repeat)
                return self.reply(200, result)

        return Handler
