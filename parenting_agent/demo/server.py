"""The demo's web server: one phone-first page and a small JSON API, on the standard library only.

Routes: GET / (the page), GET /internal/<secret> (marks this browser as internal), GET /api/state, POST /api/message,
POST /api/reset, GET /healthz. The secret is PA_DEMO_INTERNAL_SECRET. Any other /internal address is a plain 404,
and the internal cookie is a signature of the secret, so a hand-made cookie does not count and a new secret unmarks
every browser. Every visitor gets a random first-party cookie pa_vid, and only its sha256 is kept.
Requests must be small JSON. There is no upload route and multipart bodies are refused.
"""
import hashlib
import hmac
import http.server
import ipaddress
import json
import re
import secrets
from http.cookies import SimpleCookie
from pathlib import Path

from .app import dumps
from .records import visitor_id

PAGE = Path(__file__).with_name("page.html")
COOKIE = "pa_vid"
INTERNAL_COOKIE = "pa_internal"
COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
FORWARDED = ("X-Forwarded-For", "Forwarded", "CF-Connecting-IP", "X-Real-IP")
YEAR = 365 * 24 * 3600
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def is_loopback(address):
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_loopback
    except ValueError:
        return False


def internal_marker(secret):
    """The internal cookie's value: a signature of the secret, never the secret itself. "" when the feature is off."""
    return hmac.new(secret.encode(), b"pa-demo-internal-v1", hashlib.sha256).hexdigest() if secret else ""


def make_handler(app, settings):
    secure = "; Secure" if settings["secure_cookie"] else ""
    secret = settings.get("internal_secret", "")
    marker = internal_marker(secret)
    internal_path = f"/internal/{secret}".encode() if secret else b""

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "demo"
        sys_version = ""

        def log_message(self, fmt, *args):  # no IPs or paths in the logs
            pass

        def cookies(self):
            jar = SimpleCookie()
            try:
                jar.load(self.headers.get("Cookie", ""))
            except Exception:
                return {}
            return {k: m.value for k, m in jar.items()}

        def visitor(self):
            """(visitor id, internal, Set-Cookie headers to send). A missing or odd cookie gets a fresh random one."""
            jar, headers = self.cookies(), []
            token = jar.get(COOKIE, "")
            if not COOKIE_RE.match(token):
                token = secrets.token_urlsafe(32)
                headers.append(f"{COOKIE}={token}; Path=/; Max-Age={YEAR}; HttpOnly; SameSite=Lax{secure}")
            local = is_loopback(self.client_address[0]) and not any(self.headers.get(h) for h in FORWARDED)
            marked = bool(marker) and hmac.compare_digest(jar.get(INTERNAL_COOKIE, "").encode(), marker.encode())
            return visitor_id(token), marked or local, headers

        def send(self, status, body, content_type="application/json; charset=utf-8", cookies=()):
            data = body if isinstance(body, bytes) else dumps(body)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                return self.send(200, {"ok": True})
            vid, internal, cookies = self.visitor()
            if path == "/":
                return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8", cookies)
            if internal_path and hmac.compare_digest(path.encode(), internal_path):
                cookies = list(cookies) + [f"{INTERNAL_COOKIE}={marker}; Path=/; Max-Age={YEAR}; HttpOnly; SameSite=Lax{secure}"]
                page = b"<!doctype html><meta name=viewport content='width=device-width'><p>This browser is marked as internal. " \
                       b"Its messages are not counted as strangers.</p><p><a href='/'>Open the demo</a></p>"
                return self.send(200, page, "text/html; charset=utf-8", cookies)
            if path == "/api/state":
                return self.send(200, app.state(vid, internal), cookies=cookies)
            return self.send(404, {"error": "not_found"})

        def read_json(self):
            if "application/json" not in self.headers.get("Content-Type", ""):
                return 415, None
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return 400, None
            if length > settings["max_body_bytes"]:
                return 413, None
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return 400, None
            return (200, body) if isinstance(body, dict) else (400, None)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path not in ("/api/message", "/api/reset"):
                return self.send(404, {"error": "not_found"})
            status, body = self.read_json()
            if status != 200:
                self.close_connection = True
                return self.send(status, {"error": "bad_request"})
            vid, internal, cookies = self.visitor()
            if path == "/api/reset":
                return self.send(200, app.reset(vid, internal), cookies=cookies)
            text = body.get("text")
            status, out = app.message(vid, internal, text if isinstance(text, str) else "")
            return self.send(status, out, cookies=cookies)

        def do_PUT(self):
            self.send(405, {"error": "method_not_allowed"})

        do_DELETE = do_PATCH = do_PUT

    return Handler


def serve(app, settings):
    server = http.server.ThreadingHTTPServer((settings["host"], settings["port"]), make_handler(app, settings))
    server.daemon_threads = True
    return server
