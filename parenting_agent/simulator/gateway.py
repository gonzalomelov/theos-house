"""The web side: the page, and each visitor's private session behind an HttpOnly cookie. Nothing else is reachable."""
import asyncio
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse
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
FRESH = {"Cache-Control": "no-cache"}
BUSY = "All the simulated homes are in use right now. One frees up within two minutes, and this page keeps trying."
STARTS_USED = "This address started many homes this hour. Please try again in a while."
USED = "This session reached its limit. Start over, or try again in an hour."
ONE_AT_A_TIME = "Muse is still on the last one."
STREAMED = {"event", "tool_call", "tool_result", "gate", "decision", "done", "error"}
PARENTS = ("gonza", "ceci")


class Headers(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.update({"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
        if request.url.path.startswith("/api/"):  # a cached answer froze the page on a home that had ended
            response.headers["Cache-Control"] = "no-store"
        return response


class Revalidated(StaticFiles):
    """Cloudflare keeps static files for hours by default, and an old page.js on a new page breaks the page. It must ask first."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(FRESH)
        return response


def page_html():
    """The page, with each script and style named by its content, so a new deploy can't be served an old copy."""
    html = (STATIC / "index.html").read_text()
    for name in ("page.css", "page.js"):
        version = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
        html = html.replace(f"/static/{name}", f"/static/{name}?v={version}")
    return html


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
        return HTMLResponse(page_html(), headers=FRESH)

    async def open_session(request):
        session = current(request)
        if session is None:
            try:
                session = await sessions.create(client_of(request), "es" if (await body_of(request)).get("lang") == "es" else "en")
            except Full as why:
                return JSONResponse({"error": STARTS_USED if str(why) == "address" else BUSY}, 429 if str(why) == "address" else 503)
        return with_cookie(JSONResponse({**await session.state(), "scenes": [s["id"] for s in SCENES]}), session)

    def session_only(handler):
        async def run(request):
            session = current(request)
            if session is None:
                return JSONResponse({"error": "This session ended. Start over."}, 410)
            return await handler(request, session)
        return run

    def one_at_a_time(handler):
        """Rapid presses don't queue up Muse calls: one may wait behind the one running."""
        async def run(request, session):
            if session.core.queue.qsize() > 0:
                return JSONResponse({"error": ONE_AT_A_TIME}, 409)
            return await handler(request, session)
        return run

    async def state(request, session):
        return JSONResponse(await session.state())

    async def scene(request, session):
        try:
            event_id = await session.play(str((await body_of(request)).get("id")))
        except Full:
            return JSONResponse({"error": USED}, 429)
        if event_id is None:
            return JSONResponse({"error": "There is no such moment."}, 404)
        return JSONResponse({"id": event_id or None}, 202)

    async def sense(request, session):
        """A saved result from Meta's model goes in as an event, and Muse decides live."""
        try:
            event_id = await session.sense(str((await body_of(request)).get("id")))
        except Full:
            return JSONResponse({"error": USED}, 429)
        if event_id is None:
            return JSONResponse({"error": "That recording wakes nobody."}, 404)
        return JSONResponse({"id": event_id}, 202)

    async def write(request, session):
        body = await body_of(request)
        text = str(body.get("text", "")).strip()
        if body.get("as") not in PARENTS or not text or len(text) > MAX_TEXT:
            return JSONResponse({"error": f"Write up to {MAX_TEXT} characters, as Gonza or Ceci."}, 400)
        try:
            return JSONResponse({"id": await session.write(body["as"], text)}, 202)
        except Full:
            return JSONResponse({"error": USED}, 429)

    async def event(request, session):
        """The same events the real home sends. What happens next is Muse's to decide."""
        body = await body_of(request)
        payload = checked_event(body.get("type"), body.get("payload"), session.lang)
        if payload is None:
            return JSONResponse({"error": "That isn't an event this home can send."}, 400)
        try:
            return JSONResponse({"id": (await session.event(body["type"], payload)) or None}, 202)
        except Full:
            return JSONResponse({"error": USED}, 429)

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
        try:
            session.count()  # a wake it fires can call Muse
        except Full:
            return JSONResponse({"error": USED}, 429)
        await session.advance(session.moment + datetime.timedelta(minutes=minutes))
        return JSONResponse(await session.state())

    async def feeds(request, session):
        """Whether simulated Theo keeps eating. Off, nobody logs a feed, and what the home does about it is Muse's and the ladder's."""
        session.feeds_on = bool((await body_of(request)).get("on"))
        return JSONResponse(await session.state())

    async def lang(request, session):
        await session.set_lang("es" if (await body_of(request)).get("lang") == "es" else "en")
        return JSONResponse({"lang": session.lang})

    async def reset(request, session):
        chosen = session.lang
        if not sessions.opened.left(client_of(request)):  # checked first, so a refused start doesn't lose the home that's open
            return JSONResponse({"error": STARTS_USED}, 429)
        await sessions.drop(session.token)
        try:
            fresh = await sessions.create(client_of(request), chosen)
        except Full as why:
            return JSONResponse({"error": STARTS_USED if str(why) == "address" else BUSY}, 429 if str(why) == "address" else 503)
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
        return JSONResponse({"ok": True})

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
        Route("/api/state", session_only(state)), Route("/api/scene", session_only(one_at_a_time(scene)), methods=["POST"]),
        Route("/api/sense", session_only(one_at_a_time(sense)), methods=["POST"]), Route("/api/write", session_only(one_at_a_time(write)), methods=["POST"]), Route("/api/events", session_only(one_at_a_time(event)), methods=["POST"]),
        Route("/api/home", session_only(set_home), methods=["POST"]), Route("/api/clock", session_only(clock), methods=["POST"]), Route("/api/lang", session_only(lang), methods=["POST"]), Route("/api/feeds", session_only(feeds), methods=["POST"]),
        Route("/api/reset", session_only(reset), methods=["POST"]), Route("/api/stream", session_only(stream)),
        Mount("/media", StaticFiles(directory=media, check_dir=False)), Mount("/static", Revalidated(directory=STATIC))])
    built.state.sessions = sessions
    return built
