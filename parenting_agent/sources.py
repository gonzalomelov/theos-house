"""Where frames come from: a camera index, a video file played back at real time and looped, or the head
camera page (the phone today, the Ray-Ban glasses relay later).

Every source keeps only the newest frame, so a slow detector skips stale frames instead of falling
behind. Frames live in memory only, nothing is written to disk.
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

PAGE = Path(__file__).with_name("phone.html")
CERT_DIR = Path.home() / ".config" / "parenting-agent" / "phone-cert"
MAX_FRAME_BYTES = 2_000_000


class Latest:
    """Shared newest-frame slot."""

    def __init__(self):
        self.lock = threading.Lock()
        self.frame, self.seq, self.stream_s = None, 0, 0.0
        self.started, self.stopped = None, False

    def put(self, frame, stream_s):
        with self.lock:
            self.frame, self.seq, self.stream_s = frame, self.seq + 1, stream_s

    def latest(self, after_seq):
        with self.lock:
            if self.frame is None or self.seq == after_seq:
                return None
            return self.frame, self.seq, self.stream_s

    def push(self, event):
        """Events for the viewer (chime, voice). Only the phone page listens."""

    def close(self):
        self.stopped = True


class VideoSource(Latest):
    """A camera index such as '0', a stream URL OpenCV opens, or a file paced to real time and looped."""

    def __init__(self, source, loops=True):
        super().__init__()
        self.source, self.loops = source, loops
        self.is_file = Path(source).is_file()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        import cv2
        capture = cv2.VideoCapture(int(self.source) if self.source.isdigit() else self.source)
        if not capture.isOpened():
            self.stopped = True
            return
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        self.started, index = time.monotonic(), 0
        while not self.stopped:
            ok, frame = capture.read()
            if not ok:
                if self.is_file and self.loops:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                break
            if self.is_file:
                stream_s = index / fps
                index += 1
                delay = self.started + stream_s - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
            else:
                stream_s = time.monotonic() - self.started
            self.put(frame, stream_s)
        capture.release()
        self.stopped = True


def lan_ip():
    """The address this machine uses on the home network (a UDP connect sends nothing)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 9))
        ip = s.getsockname()[0]
    if not ipaddress.ip_address(ip).is_private:
        raise SystemExit(f"phone source: {ip} is not a private address, refusing to serve")
    return ip


def certificate(ip):
    """Self-signed certificate for this address, with the extensions iOS requires before it completes TLS."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert, key, stamp = CERT_DIR / "cert.pem", CERT_DIR / "key.pem", CERT_DIR / "ip.txt"
    if not (cert.exists() and key.exists() and stamp.exists() and stamp.read_text() == ip):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                        "-subj", "/CN=parenting-agent-head-camera", "-addext", f"subjectAltName=IP:{ip}",
                        "-addext", "extendedKeyUsage=serverAuth", "-addext", "basicConstraints=critical,CA:FALSE",
                        "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
                        "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
        key.chmod(0o600)
        stamp.write_text(ip)
    return cert, key


class PhoneSource(Latest):
    """The head camera page. The phone posts JPEG frames one at a time and listens for chime and voice.

    host: PARENTING_AGENT_HOST, else the home network address. 127.0.0.1 serves plain http for tests.
    A Tailscale address (100.x) works too and is the reliable route from an iPhone.
    """

    def __init__(self, port=8443, host=None):
        super().__init__()
        self.is_file = False
        self.clients = []
        ip = host or os.environ.get("PARENTING_AGENT_HOST") or lan_ip()
        self.server = ThreadingHTTPServer((ip, port), self._handler())
        self.server.daemon_threads = True
        port = self.server.server_address[1]  # port 0 picks a free one
        if ip == "127.0.0.1":
            self.url = f"http://{ip}:{port}/"
        else:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*certificate(ip))
            # Handshake per connection: an idle Safari preconnection must not block accept().
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True, do_handshake_on_connect=False)
            self.url = f"https://{ip}:{port}/"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _handler(self):
        source = self

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

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                elif path == "/events":
                    source._stream(self)
                else:
                    self.reply(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                if length > MAX_FRAME_BYTES:
                    self.reply(413)
                    return
                body = self.rfile.read(length)
                if self.path == "/frame":
                    source._frame(body)
                    self.reply(204)
                else:
                    self.reply(404)

        return Handler

    def _frame(self, body):
        import cv2
        import numpy as np
        frame = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return
        now = time.monotonic()
        if self.started is None:
            self.started = now
        self.put(frame, now - self.started)

    def _stream(self, handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        inbox = queue.Queue(maxsize=100)
        self.clients.append(inbox)
        try:
            while not self.stopped:
                try:
                    handler.wfile.write(f"data: {json.dumps(inbox.get(timeout=10))}\n\n".encode())
                except queue.Empty:
                    handler.wfile.write(b": keepalive\n\n")
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, OSError):
            pass
        finally:
            self.clients.remove(inbox)

    def push(self, event):
        for inbox in list(self.clients):
            try:
                inbox.put_nowait(event)
            except queue.Full:
                pass

    def close(self):
        self.stopped = True
        self.server.shutdown()
        self.server.server_close()


def open_source(spec):
    """'phone' or 'phone:PORT' for the head camera page, anything else for VideoSource."""
    if spec.split(":")[0] == "phone":
        port = int(spec.split(":", 1)[1]) if ":" in spec else 8443
        return PhoneSource(port)
    return VideoSource(spec)
