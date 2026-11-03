"""Frame sources for the camera skills. open_source picks one from a short text:

  "glasses" or "glasses:PORT"  the glasses app, through the one shared endpoint in parenting_agent/glasses.py
  "phone" or "phone:PORT"      a phone browser used as a head camera, serving phone.html
  anything else                a camera index, a stream URL or a video file

A reader only ever gets the newest frame: when the detector is slow, older frames are gone. Frames stay in memory.
"""
import ipaddress
import json
import os
import queue
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PHONE_PAGE = Path(__file__).with_name("phone.html")
TLS_DIR = Path.home() / ".config" / "parenting-agent" / "phone-cert"
MAX_FRAME_BYTES = 2_000_000


class Latest:
    """One slot holding the newest frame, its number and its time in the stream."""

    def __init__(self):
        self._guard = threading.Lock()
        self._slot = None
        self.seq = 0
        self.started = None
        self.stopped = False

    def put(self, frame, stream_s):
        with self._guard:
            self.seq += 1
            self._slot = (frame, self.seq, stream_s)

    def latest(self, after_seq):
        """The newest (frame, seq, stream_s), or None when nothing arrived since after_seq."""
        with self._guard:
            return self._slot if self._slot and self._slot[1] != after_seq else None

    def push(self, event):
        """Only a source with a listener cares about chime and voice events."""

    def close(self):
        self.stopped = True


class VideoSource(Latest):
    """OpenCV's reader on a camera, a URL or a file. A file plays at its own speed and can loop."""

    def __init__(self, source, loops=True):
        super().__init__()
        self.source, self.loops = source, loops
        self.is_file = Path(source).is_file()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        import cv2
        reader = cv2.VideoCapture(int(self.source) if self.source.isdigit() else self.source)
        if reader.isOpened():
            self._pump(reader, cv2, reader.get(cv2.CAP_PROP_FPS) or 30.0)
        reader.release()
        self.stopped = True

    def _pump(self, reader, cv2, fps):
        self.started = time.monotonic()
        played = 0
        while not self.stopped:
            got, image = reader.read()
            if not got and self.is_file and self.loops:
                reader.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            if not got:
                return
            if not self.is_file:
                self.put(image, time.monotonic() - self.started)
                continue
            at = played / fps
            played += 1
            time.sleep(max(0.0, self.started + at - time.monotonic()))
            self.put(image, at)


def _home_address():
    """This machine's address on the home network. Connecting a UDP socket sends no packet."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    finally:
        probe.close()
    if ipaddress.ip_address(address).is_private:
        return address
    raise SystemExit(f"phone camera: refusing to serve on {address}, it is not private")


def _tls_files(address):
    """A self-signed certificate for this address. Safari needs the camera page on https and these extensions set."""
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    cert, key, made_for = TLS_DIR / "cert.pem", TLS_DIR / "key.pem", TLS_DIR / "ip.txt"
    fresh = cert.exists() and key.exists() and made_for.exists() and made_for.read_text() == address
    if not fresh:
        extensions = [f"subjectAltName=IP:{address}", "extendedKeyUsage=serverAuth", "basicConstraints=critical,CA:FALSE",
                      "keyUsage=critical,digitalSignature,keyEncipherment"]
        command = ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=parenting-agent-phone",
                   "-keyout", str(key), "-out", str(cert)]
        for extension in extensions:
            command += ["-addext", extension]
        subprocess.run(command, check=True, capture_output=True)
        key.chmod(0o600)
        made_for.write_text(address)
    return cert, key


class _PhoneHandler(BaseHTTPRequestHandler):
    """GET / is the page, GET /events its chime and voice stream, POST /frame takes one JPEG."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def _answer(self, status, body=b"", kind="text/plain"):
        self.send_response(status)
        for name, value in (("Content-Type", kind), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")):
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = self.path.partition("?")[0]
        if route == "/events":
            self.server.source.listen(self)
        elif route in ("/", "/index.html"):
            self._answer(200, PHONE_PAGE.read_bytes(), "text/html; charset=utf-8")
        else:
            self._answer(404)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        if size > MAX_FRAME_BYTES:
            self._answer(413)
            return
        jpeg = self.rfile.read(size)
        if self.path != "/frame":
            self._answer(404)
            return
        self.server.source.take_jpeg(jpeg)
        self._answer(204)


class PhoneSource(Latest):
    """A phone browser as the head camera: it posts JPEGs one by one and plays the chime and voice it is sent.

    The address is host, else PARENTING_AGENT_HOST, else the home network one. A Tailscale address suits an iPhone best.
    127.0.0.1 serves plain http, for tests.
    """

    def __init__(self, port=8443, host=None):
        super().__init__()
        self.is_file = False
        self.clients = []
        address = host or os.environ.get("PARENTING_AGENT_HOST") or _home_address()
        self.server = ThreadingHTTPServer((address, port), _PhoneHandler)
        self.server.source = self
        self.server.daemon_threads = True
        scheme = "http"
        if address != "127.0.0.1":
            scheme = "https"
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(*_tls_files(address))
            # The handshake runs per connection, so Safari's idle preconnect can't hold up accept().
            self.server.socket = tls.wrap_socket(self.server.socket, server_side=True, do_handshake_on_connect=False)
        self.url = f"{scheme}://{address}:{self.server.server_address[1]}/"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def take_jpeg(self, jpeg):
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is not None:
            self.started = self.started or time.monotonic()
            self.put(image, time.monotonic() - self.started)

    def listen(self, handler):
        """Server-sent events for one page, until it leaves."""
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        mailbox = queue.Queue(maxsize=100)
        self.clients.append(mailbox)
        try:
            while not self.stopped:
                try:
                    line = f"data: {json.dumps(mailbox.get(timeout=10))}\n\n"
                except queue.Empty:
                    line = ": still here\n\n"
                handler.wfile.write(line.encode())
                handler.wfile.flush()
        except OSError:  # the page left: BrokenPipeError, ConnectionResetError and ssl.SSLError are all OSError
            pass
        finally:
            self.clients.remove(mailbox)

    def push(self, event):
        for mailbox in tuple(self.clients):
            if not mailbox.full():
                mailbox.put_nowait(event)

    def close(self):
        self.stopped = True
        self.server.shutdown()
        self.server.server_close()


def open_source(spec):
    kind, _, port = spec.partition(":")
    if kind == "glasses":
        from .glasses import DEFAULT_PORT, GlassesHub
        return GlassesHub.shared(int(port) if port else DEFAULT_PORT).view()
    if kind == "phone":
        return PhoneSource(int(port) if port else 8443)
    return VideoSource(spec)
