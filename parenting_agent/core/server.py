"""The HTTP API, for the event simulator and the Mac's senses.

POST /events        {"type": "...", "payload": {...}, "at": "ISO time, optional"} -> {"id": n}. wait=1 in the query answers when done
GET  /stream        server-sent events of everything the agent does. after=<seq> replays what came after that
GET  /events        latest events, GET /actions?event_id=n actions of one event
GET  /home          the simulated home's devices and moves, POST /home {"entity_id": ..., "state": ...} sets one (mock only)
GET  /messages      what was sent to whom (mock only)
POST /reset         back to the starting home and outbox (mock only)
POST /coach         {"parent": ..., "text": ..., "step": ...}: a line from the car seat coach on the Mac, Muse isn't woken
GET  /health
"""
import asyncio
import hmac
import json
import os

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..voice_bridge import spoken, strip_wake


def clean(row):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(row).items()}


def echo_app(core):
    """POST /ask {"text", "source", "person"} -> {"reply", "replies"}: what the old voice bridge answers, so Home Assistant's
    automations stay as they are. It waits for Muse, and what Muse says with say_on_echo comes back for Home Assistant to speak."""
    token = os.environ.get("PARENTING_AGENT_VOICE_TOKEN", "")

    async def ask(request):
        if not token or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
            return JSONResponse({"error": "unauthorized"}, 401)
        body = await request.json()
        words = strip_wake(body.get("text", ""))[:500]
        if not words:
            return JSONResponse({"reply": "Decí agente, y después lo que querés saber.", "replies": []})
        who = str(body.get("person") or "someone in the kitchen, you can't tell who")[:32]
        _, done = await core.dispatch("message", {"from": who, "channel": "the kitchen Echo", "text": words}, source=str(body.get("source", "echo"))[:16], ask=True)
        said = (await done).get("said", [])
        return JSONResponse({"reply": spoken(" ".join(said)), "replies": said})

    async def health(request):
        return JSONResponse({"ok": True})
    return Starlette(routes=[Route("/ask", ask, methods=["POST"]), Route("/health", health)])


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
