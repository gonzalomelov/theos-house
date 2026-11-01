"""A small in-memory Baby Buddy for tests: the REST endpoints the agent uses, with the same field names,
token check and the same refusal of future times. Runs on 127.0.0.1 on a free port in a thread.
"""
import datetime
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "test-token"
TIME_FIELDS = {"feedings": "end", "changes": "time", "sleep": "end", "notes": "time", "timers": "start"}


def parse(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def duration(start, end):
    seconds = int((parse(end) - parse(start)).total_seconds())
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class FakeBabyBuddy:
    def __init__(self, refuse_overlaps=False):
        """refuse_overlaps mirrors the real server's refusal of feeds or sleeps whose times intersect. Tests that
        log many notes in the same second turn it off, since real notes arrive minutes apart."""
        self.refuse_overlaps = refuse_overlaps
        self.records = {name: {} for name in TIME_FIELDS}
        self.next_id = 1
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def all(self, name):
        return list(self.records[name].values())

    def create(self, name, body):
        now = datetime.datetime.now().astimezone()
        for field in ("start", "end", "time"):
            if body.get(field) and parse(body[field]) > now + datetime.timedelta(seconds=5):
                return 400, {field: ["Date/time can not be in the future."]}
        if name == "feedings" and (body.get("type") is None or body.get("method") is None):
            return 400, {"type": ["This field is required."]}
        if name == "changes" and ("wet" not in body or "solid" not in body):
            return 400, {"wet": ["This field is required."]}
        if self.refuse_overlaps and name in ("feedings", "sleep"):
            for other in self.all(name):
                if parse(body["start"]) < parse(other["end"]) and parse(other["start"]) < parse(body["end"]):
                    return 400, {"start": ["Another entry intersects the specified time period."]}
        record = dict(body, id=self.next_id)
        if name in ("feedings", "sleep"):
            record["duration"] = duration(body["start"], body["end"])
        self.records[name][self.next_id] = record
        self.next_id += 1
        return 201, record

    def handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body=None):
                raw = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def route(self):
                if self.headers.get("Authorization") != f"Token {TOKEN}":
                    self.reply(401, {"detail": "Invalid token."})
                    return None, None, None
                url = urlparse(self.path)
                parts = [p for p in url.path.split("/") if p]
                name = parts[1] if len(parts) > 1 else None
                record_id = int(parts[2]) if len(parts) > 2 else None
                return name, record_id, parse_qs(url.query)

            def do_GET(self):
                name, record_id, query = self.route()
                if name is None:
                    return
                if name == "children":
                    self.reply(200, {"count": 1, "results": [{"id": 1, "first_name": "Test", "last_name": "Baby", "slug": "test-baby"}]})
                    return
                if record_id is not None:
                    record = fake.records[name].get(record_id)
                    self.reply(200 if record else 404, record or {"detail": "Not found."})
                    return
                items = fake.all(name)
                field = TIME_FIELDS[name]
                items.sort(key=lambda r: parse(r[field]), reverse=query.get("ordering", ["-x"])[0].startswith("-"))
                limit = int(query.get("limit", ["100"])[0])
                self.reply(200, {"count": len(items), "results": items[:limit]})

            def do_POST(self):
                name, _, _ = self.route()
                if name is None:
                    return
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                code, record = fake.create(name, body)
                self.reply(code, record)

            def do_PATCH(self):
                name, record_id, _ = self.route()
                if name is None:
                    return
                record = fake.records[name].get(record_id)
                if record is None:
                    self.reply(404, {"detail": "Not found."})
                    return
                record.update(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"))
                if name in ("feedings", "sleep"):
                    record["duration"] = duration(record["start"], record["end"])
                self.reply(200, record)

            def do_DELETE(self):
                name, record_id, _ = self.route()
                if name is None:
                    return
                fake.records[name].pop(record_id, None)
                self.reply(204)

        return Handler
