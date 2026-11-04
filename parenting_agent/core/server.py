"""The HTTP API, for the event simulator and the Mac's senses.

POST /events        {"type": "...", "payload": {...}, "at": "ISO time, optional"} -> {"id": n}. wait=1 in the query answers when done
GET  /stream        server-sent events of everything the agent does. after=<seq> replays what came after that
GET  /events        latest events, GET /actions?event_id=n actions of one event
GET  /home          the simulated home's devices and moves, POST /home {"entity_id": ..., "state": ...} sets one (mock only)
GET  /messages      what was sent to whom (mock only)
POST /reset         back to the starting home and outbox (mock only)
POST /whatsapp      Meta's webhook, on the Echo's port and through its own door: GET answers Meta's check, POST is signed with the app secret
POST /coach         {"parent": ..., "text": ..., "step": ...}: a line from the car seat coach on the Mac, Muse isn't woken
GET  /health
"""
import asyncio
import hashlib
import hmac
import json
import os

from urllib.parse import parse_qsl

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from ..channels.messaging import MessagingError
from ..channels.twilio_whatsapp import signature as twilio_signature, takes_voice
from ..voice_bridge import spoken, strip_wake
from . import sources

NOTHING_TO_SAY = {"es": "No tengo nada para decirte por acá.", "en": "I have nothing to say here."}  # an empty answer would leave the Echo silent, which reads as broken
HEAR_NOTE_S = 120  # the ear retries by itself, so this is only for a voice service or a Muse that never answers


def clean(row):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(row).items()}


def echo_app(core):
    """POST /ask {"text", "source", "person", "request_id"} -> {"reply", "replies"}: what the old voice bridge answers, so Home Assistant's
    automations and the Alexa skill stay as they are. What Muse says with say_on_echo comes back for them to speak, as soon as it is said: Alexa waits 8 seconds, and the phones
    can come after. The skill asks again with the same request_id after its holding line, which gets the first answer and never runs the words twice."""
    tokens = [t for t in (os.environ.get("PARENTING_AGENT_VOICE_TOKEN", ""), os.environ.get("PARENTING_AGENT_SKILL_TOKEN", "")) if t]
    answers = {}

    async def first_words(words, who, source):
        event_id, done = await core.dispatch("message", {"from": who, "channel": "the kitchen Echo", "text": words}, source=source, ask=True)
        while not done.done():
            if core.current == event_id and core.channel.hold:
                return list(core.channel.hold)
            await asyncio.sleep(0.1)
        return (await done).get("said", [])

    async def ask(request):
        given = request.headers.get("authorization", "")
        if not any(hmac.compare_digest(given, f"Bearer {token}") for token in tokens):
            return JSONResponse({"error": "unauthorized"}, 401)
        body = await request.json()
        words = strip_wake(body.get("text", ""))[:500]
        if not words:
            return JSONResponse({"reply": "Decí agente, y después lo que querés saber.", "replies": []})
        who = str(body["person"])[:32] if body.get("person") else "someone in the kitchen, you can't tell who"
        request_id = str(body.get("request_id") or "")[:80]
        answer = answers.get(request_id) if request_id else None
        if answer is None:
            answer = asyncio.ensure_future(first_words(words, who, str(body.get("source", "echo"))[:16]))
            if request_id:
                answers[request_id] = answer
                while len(answers) > 32:
                    answers.pop(next(iter(answers)))
        said = await asyncio.shield(answer)  # the skill hanging up at its limit doesn't stop what it asked for
        return JSONResponse({"reply": spoken(" ".join(said)) or NOTHING_TO_SAY["en" if core.settings.lang == "en" else "es"], "replies": said})

    async def health(request):
        return JSONResponse({"ok": True})
    return Starlette(routes=[Route("/ask", ask, methods=["POST"]), Route("/health", health), *whatsapp_routes(core)])


def whatsapp_routes(core):
    """Meta's webhook. A parent's words wake Muse, anything else is ignored. Only a body signed with the app secret counts."""
    verify, secret = os.environ.get("WHATSAPP_VERIFY_TOKEN", ""), os.environ.get("WHATSAPP_APP_SECRET", "")
    seen = {}
    hearing = set()  # the running voice notes: Twilio waits 15 seconds at most, and hearing one can take longer

    async def check(request):
        q = request.query_params
        if verify and q.get("hub.mode") == "subscribe" and hmac.compare_digest(q.get("hub.verify_token", ""), verify):
            return PlainTextResponse(q.get("hub.challenge", ""))
        return JSONResponse({"error": "forbidden"}, 403)

    async def incoming(request):
        raw = await request.body()
        signed = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(request.headers.get("x-hub-signature-256", ""), signed):
            return JSONResponse({"error": "forbidden"}, 403)
        whatsapp = getattr(core.channel, "whatsapp", None)
        if whatsapp and whatsapp.kind == "meta":
            for change in (c.get("value", {}) for entry in json.loads(raw).get("entry", []) for c in entry.get("changes", [])):
                for message in change.get("messages", []):
                    await heard_on_whatsapp(core, whatsapp, message, seen, hearing)
                for status in change.get("statuses", []):
                    await refused_on_whatsapp(core, whatsapp, status)
        return JSONResponse({"ok": True})

    async def signed_form(request, whatsapp):
        """The form Twilio sent, or None unless it's signed with the account's auth token for this exact public URL."""
        params = dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))
        url = whatsapp.webhook + request.url.path
        if not hmac.compare_digest(request.headers.get("x-twilio-signature", ""), twilio_signature(whatsapp.token, url, params)):
            return None
        return params

    async def from_twilio(request):
        whatsapp = getattr(core.channel, "whatsapp", None)
        params = await signed_form(request, whatsapp) if whatsapp and whatsapp.kind == "twilio" else None
        if params is None:
            return JSONResponse({"error": "forbidden"}, 403)
        await heard_on_whatsapp(core, whatsapp, {"from": "".join(c for c in params.get("From", "") if c.isdigit()), "id": params.get("MessageSid"), "media": params.get("MediaUrl0"),
                                                 "type": twilio_kind(params), "text": {"body": params.get("Body", "")}}, seen, hearing)
        return Response("<Response/>", media_type="text/xml")

    async def twilio_status(request):
        whatsapp = getattr(core.channel, "whatsapp", None)
        params = await signed_form(request, whatsapp) if whatsapp and whatsapp.kind == "twilio" else None
        if params is None:
            return JSONResponse({"error": "forbidden"}, 403)
        await status_from_twilio(core, whatsapp, params)
        return Response("<Response/>", media_type="text/xml")
    return [Route("/whatsapp", check, methods=["GET"]), Route("/whatsapp", incoming, methods=["POST"]),
            Route("/twilio", from_twilio, methods=["POST"]), Route("/twilio/status", twilio_status, methods=["POST"])]


def twilio_kind(params):
    """What Twilio's form holds. Words sent with a photo are still words. Audio Muse's ear can't take is a voice note it can't hear."""
    kind = params.get("MediaContentType0", "")
    if kind.startswith("audio"):
        return "audio" if takes_voice(kind) and params.get("MediaUrl0") else "unheard"
    return "text" if params.get("Body", "").strip() else "other_media"


async def hear_note(core, whatsapp, parent, message):
    """A voice note goes the way one does on Telegram: its words become the parent's message, or the parent hears it wasn't heard. Never silence."""
    reasons = []
    try:
        item = type("Note", (), {"voice_file_id": message["media"]})()
        kind, payload = await asyncio.wait_for(sources.heard(whatsapp, sources.voice_ears(), item, parent, reasons.append), HEAR_NOTE_S)
    except Exception as failure:  # whatever it was, the parent still gets an answer
        kind, payload = "voice_note_not_heard", {"from": parent}
        reasons.append(type(failure).__name__)
    if reasons:
        core.publish("error", error=f"WhatsApp voice note from {parent}: {reasons[0][:200]}")
        payload = {**payload, "why": reasons[0][:200]}
    await core.dispatch(kind, payload, source="whatsapp")


async def heard_on_whatsapp(core, whatsapp, message, seen, hearing=None):
    parent = whatsapp.parents.get(message.get("from"))
    if not parent or message.get("id") in seen:  # Meta delivers again when in doubt
        return
    seen[message.get("id")] = True
    while len(seen) > 500:
        seen.pop(next(iter(seen)))
    try:
        await asyncio.to_thread(whatsapp.heard, parent)
    except MessagingError as error:
        core.publish("error", error=f"WhatsApp couldn't send what waited for {parent}: {error}")
    if message.get("type") == "text":
        await core.dispatch("message", {"from": parent, "channel": "WhatsApp", "text": message.get("text", {}).get("body", "")[:2000]}, source="whatsapp")
    elif message.get("type") == "audio" and message.get("media"):
        task = asyncio.create_task(hear_note(core, whatsapp, parent, message))
        hearing.add(task)
        task.add_done_callback(hearing.discard)
    elif message.get("type") in ("audio", "voice", "unheard"):
        await core.dispatch("voice_note_not_heard", {"from": parent}, source="whatsapp")
    elif message.get("type") == "other_media":
        await core.dispatch("media_not_read", {"from": parent}, source="whatsapp")


async def refused_on_whatsapp(core, whatsapp, status):
    """Meta said no after accepting it: the words go on Telegram, so a closed window never loses them."""
    if status.get("status") != "failed":
        return
    codes = [error.get("code") for error in status.get("errors", [])]
    lost = whatsapp.failed(status.get("id"))
    core.publish("error", error=f"WhatsApp refused a message, codes {codes}")
    if lost:
        await asyncio.to_thread(core.channel.by_telegram, *lost)


async def status_from_twilio(core, whatsapp, params):
    """What really happened to a message. Only this says delivered, and a failure sends the words on Telegram."""
    status, sid = params.get("MessageStatus"), params.get("MessageSid")
    if status == "delivered":
        parent = whatsapp.confirmed(sid)
        if parent:
            await core.whatsapp_status(parent, "delivered")
    elif status in ("failed", "undelivered"):
        code, lost = params.get("ErrorCode"), whatsapp.failed(sid)
        core.publish("error", error=f"WhatsApp through Twilio: {status}, code {code}")
        if lost:
            await core.whatsapp_status(lost[0], f"{status}, code {code}, Telegram carried it")
            await asyncio.to_thread(core.channel.by_telegram, *lost)


def app(core):
    async def post_event(request):
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("type"), str) or not isinstance(body.get("payload", {}), dict):
            return JSONResponse({"error": "type is a string and payload an object"}, 400)
        try:
            event_id, done = await core.dispatch(body["type"], body.get("payload"), body.get("source", "simulator"), body.get("at"))
        except ValueError:
            return JSONResponse({"error": "at is an ISO time"}, 400)
        if request.query_params.get("wait"):
            return JSONResponse({"id": event_id, **await done})
        return JSONResponse({"id": event_id}, 202)

    async def coach(request):
        body = await request.json()
        why = await core.coach_line(body.get("parent"), str(body.get("text", ""))[:600], body.get("step"))
        return JSONResponse({"error": why}, 400) if why else JSONResponse({"ok": True})

    async def stream(request):
        after = int(request.query_params.get("after", core.seq))
        queue = asyncio.Queue()
        for item in core.recent:
            if item["seq"] > after:
                queue.put_nowait(item)
        core.subscribers.add(queue)

        async def items():
            try:
                while True:
                    item = await queue.get()
                    yield {"id": str(item["seq"]), "event": item["kind"], "data": json.dumps(item, ensure_ascii=False)}
            finally:
                core.subscribers.discard(queue)
        return EventSourceResponse(items(), ping=15)

    async def events(request):
        return JSONResponse([clean(r) for r in await core.events(int(request.query_params.get("limit", 100)))])

    async def actions(request):
        event_id = request.query_params.get("event_id")
        return JSONResponse([clean(r) for r in await core.actions(int(event_id) if event_id else None)])

    def mock_only(handler):
        async def run(request):
            if core.mock is None:
                return JSONResponse({"error": "the real home is not set from here"}, 409)
            return await handler(request)
        return run

    def mock_channel(handler):
        async def run(request):
            if not hasattr(core.channel, "sent"):
                return JSONResponse({"error": "the real channel keeps no outbox here"}, 409)
            return await handler(request)
        return run

    async def get_home(request):
        return JSONResponse(core.mock.snapshot())

    async def set_home(request):
        body = await request.json()
        ok = core.mock.set_state(body.get("entity_id"), body.get("state"))
        return JSONResponse(core.mock.snapshot(), 200 if ok else 404)

    async def messages(request):
        return JSONResponse(core.channel.sent)

    async def reset(request):
        core.mock.reset()
        core.moment = None
        core.channel.sent.clear()
        return JSONResponse({"ok": True})

    async def health(request):
        return JSONResponse({"ok": True, "queued": core.queue.qsize(), "seq": core.seq, "home": "mock" if core.mock else "real"})

    return Starlette(routes=[
        Route("/coach", coach, methods=["POST"]), Route("/events", post_event, methods=["POST"]), Route("/events", events), Route("/stream", stream), Route("/actions", actions),
        Route("/home", mock_only(get_home)), Route("/home", mock_only(set_home), methods=["POST"]),
        Route("/messages", mock_channel(messages)), Route("/reset", mock_only(reset), methods=["POST"]), Route("/health", health)])
