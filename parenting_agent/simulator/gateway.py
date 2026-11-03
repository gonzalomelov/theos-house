"""The web side: the page, and each visitor's private session behind an HttpOnly cookie. Nothing else is reachable."""
import asyncio
import contextlib
import datetime
import json
import os
from pathlib import Path

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .scenes import SCENES, checked_event
from .sessions import MAX_TEXT, Full, Sessions

STATIC = Path(__file__).parent / "static"
COOKIE = "pa_sim"
CLIENT_HEADER = os.environ.get("PA_SIM_CLIENT_HEADER", "")
SECURE = os.environ.get("PA_SIM_SECURE_COOKIE") == "1"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self'; "
       "media-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
BUSY = "The simulator is full. Try again in a few minutes."
STREAMED = {"event", "tool_call", "tool_result", "gate", "decision", "done", "error"}
PARENTS = ("gonza", "ceci")


class Headers(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.update({"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
        return response


def visible(item):
    """What the page may see of one step. A failure's own text stays on the server, it could name internals."""
    if item["kind"] == "error":
        return {"seq": item["seq"], "kind": "error", "event_id": item.get("event_id")}
    if item["kind"] == "done" and item.get("status") == "failed":
        return {**item, "outcome": ""}
    return item


def app(model=None, media=None):
    sessions = Sessions(model)
    media = Path(media or os.environ.get("PA_SIM_MEDIA", "data-sim/media"))

    def client_of(request):
        return request.headers.get(CLIENT_HEADER, "") if CLIENT_HEADER else (request.client.host if request.client else "")

    def current(request):
        return sessions.get(request.cookies.get(COOKIE, ""))

    async def body_of(request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return body if isinstance(body, dict) else {}

    def with_cookie(response, session):
        response.set_cookie(COOKIE, session.token, httponly=True, samesite="strict", secure=SECURE, path="/", max_age=7200)
        return response

    async def page(request):
        return FileResponse(STATIC / "index.html")

    async def open_session(request):
        session = current(request)
        if session is None:
            try:
                session = await sessions.create(client_of(request), "es" if (await body_of(request)).get("lang") == "es" else "en")
            except Full:
                return JSONResponse({"error": BUSY}, 503)
        return with_cookie(JSONResponse({**await session.state(), "scenes": [s["id"] for s in SCENES]}), session)

    def session_only(handler):
        async def run(request):
            session = current(request)
            if session is None:
                return JSONResponse({"error": "This session ended. Start over."}, 410)
            return await handler(request, session)
        return run

    async def state(request, session):
        return JSONResponse(await session.state())

    async def scene(request, session):
        try:
            event_id = await session.play(str((await body_of(request)).get("id")))
        except Full:
            return JSONResponse({"error": "This session used all its moments. Start over."}, 429)
        if event_id is None:
            return JSONResponse({"error": "There is no such moment."}, 404)
        return JSONResponse({"id": event_id}, 202)

    async def write(request, session):
        body = await body_of(request)
        text = str(body.get("text", "")).strip()
        if body.get("as") not in PARENTS or not text or len(text) > MAX_TEXT:
            return JSONResponse({"error": f"Write up to {MAX_TEXT} characters, as Gonza or Ceci."}, 400)
        try:
            return JSONResponse({"id": await session.write(body["as"], text)}, 202)
        except Full:
            return JSONResponse({"error": "This session used all its moments. Start over."}, 429)

    async def event(request, session):
        """The same events the real home sends. What happens next is Muse's to decide."""
        body = await body_of(request)
        payload = checked_event(body.get("type"), body.get("payload"), session.lang)
        if payload is None:
            return JSONResponse({"error": "That isn't an event this home can send."}, 400)
        try:
            return JSONResponse({"id": await session.event(body["type"], payload)}, 202)
        except Full:
            return JSONResponse({"error": "This session used all its moments. Start over."}, 429)

    async def set_home(request, session):
        """Changes the home without waking anyone, as when a device moved before this moment."""
        body = await body_of(request)
        payload = checked_event("state_changed", body, session.lang)
        if payload is None:
            return JSONResponse({"error": "That isn't a device reading this home has."}, 400)
        session.core.mock.set_state(payload["entity_id"], payload["state"])
        return JSONResponse(await session.state())

    async def clock(request, session):
        body = await body_of(request)
        minutes = body.get("minutes")
        if minutes not in (60, 360):
            return JSONResponse({"error": "The clock moves 60 or 360 minutes."}, 400)
        await session.advance(session.moment + datetime.timedelta(minutes=minutes))
        return JSONResponse(await session.state())

    async def lang(request, session):
        await session.set_lang("es" if (await body_of(request)).get("lang") == "es" else "en")
        return JSONResponse({"lang": session.lang})

    async def reset(request, session):
        chosen = session.lang
        await sessions.drop(session.token)
        try:
            fresh = await sessions.create(client_of(request), chosen)
        except Full:
            return JSONResponse({"error": BUSY}, 503)
        return with_cookie(JSONResponse({**await fresh.state(), "scenes": [s["id"] for s in SCENES]}), fresh)

    async def stream(request, session):
        core = session.core
        try:
            after = int(request.query_params.get("after", core.seq))
        except ValueError:
            after = core.seq
        queue = asyncio.Queue()
        for item in core.recent:
            if item["seq"] > after:
                queue.put_nowait(item)
        core.subscribers.add(queue)

        async def items():
            try:
                while True:
                    item = await queue.get()
                    if item["kind"] in STREAMED:
                        yield {"id": str(item["seq"]), "event": item["kind"], "data": json.dumps(visible(item), ensure_ascii=False)}
            finally:
                core.subscribers.discard(queue)
        return EventSourceResponse(items(), ping=15)

    async def health(request):
        return JSONResponse({"ok": True, "sessions": len(sessions.live)})

    @contextlib.asynccontextmanager
    async def lifespan(_):
        sweep = asyncio.create_task(sessions.sweep())
        try:
            yield
        finally:
            sweep.cancel()
            await sessions.close()

    built = Starlette(lifespan=lifespan, middleware=[Middleware(Headers)], routes=[
        Route("/", page), Route("/health", health), Route("/api/session", open_session, methods=["POST"]),
        Route("/api/state", session_only(state)), Route("/api/scene", session_only(scene), methods=["POST"]),
        Route("/api/write", session_only(write), methods=["POST"]), Route("/api/events", session_only(event), methods=["POST"]),
        Route("/api/home", session_only(set_home), methods=["POST"]), Route("/api/clock", session_only(clock), methods=["POST"]), Route("/api/lang", session_only(lang), methods=["POST"]),
        Route("/api/reset", session_only(reset), methods=["POST"]), Route("/api/stream", session_only(stream)),
        Mount("/media", StaticFiles(directory=media, check_dir=False)), Mount("/static", StaticFiles(directory=STATIC))])
    built.state.sessions = sessions
    return built
