"""Read-only MCP server for Meta Muse: Theo's room temperature and humidity, and nothing else in the house.

Muse runs in Meta's cloud, so this is reached through a Cloudflare hostname and needs the key in NURSERY_MCP_KEY. It
holds one tool and makes two GETs to Home Assistant. There is no path from a request to a service call. Standard
library only, so it runs on the Vostro's system Python. See install.sh.
"""
import datetime
import hmac
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENTITIES = {"temperature_c": "sensor.nursery_climate_temperature", "humidity_pct": "sensor.nursery_climate_humidity"}
MAX_AGE_MIN = 5
GUIDE = {"low_c": 16, "high_c": 20, "source": "Lullaby Trust and NHS",
         "url": "https://www.lullabytrust.org.uk/safer-sleep-advice/baby-room-temperature/"}
TOOL = {"name": "nursery_climate",
        "description": "Read the temperature and humidity in Theo's room now, from a sensor in the family's home, with "
                       "the 16 to 20 °C room guide and its source. Changes nothing. State the reading and the guide, "
                       "never whether the room is safe or what to do with the baby.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False}}
PROTOCOL = "2025-03-26"


def ha_state(entity):
    request = urllib.request.Request(f"{os.environ.get('HA_URL', 'http://127.0.0.1:8123')}/api/states/{entity}",
                                     headers={"Authorization": f"Bearer {os.environ['HA_TOKEN']}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def reading(fetch=ha_state, now=None):
    """The two values with their age. A value that is stale, missing or not a number is null, never a guess."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out = {"guide": GUIDE}
    for key, entity in ENTITIES.items():
        try:
            state = fetch(entity)
            at = datetime.datetime.fromisoformat(state.get("last_reported") or state["last_updated"])
            age = (now - at).total_seconds() / 60
            out[key] = float(state["state"]) if age <= MAX_AGE_MIN else None
        except (urllib.error.URLError, OSError, KeyError, TypeError, ValueError):
            out[key] = None
    return out


def rpc(message, fetch=ha_state):
    """The JSON-RPC answer to one MCP message, or None for a notification."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "nursery-climate", "version": "1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call" and (message.get("params") or {}).get("name") == TOOL["name"]:
        data = reading(fetch)
        result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                  "structuredContent": data, "isError": data["temperature_c"] is None}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "unknown method or tool"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def authorized(headers, key):
    sent = headers.get("X-API-Key") or (headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    return bool(key) and hmac.compare_digest(sent.encode(), key.encode())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body=None):
        self.send_response(code)
        payload = json.dumps(body).encode() if body is not None else b""
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.send(405)

    def do_POST(self):
        if self.path != "/mcp":
            return self.send(404)
        if not authorized(self.headers, os.environ.get("NURSERY_MCP_KEY", "")):
            return self.send(401, {"error": "unauthorized"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > 65536:
            return self.send(413)
        try:
            message = json.loads(self.rfile.read(length))
            answer = rpc(message)
        except (ValueError, AttributeError):
            return self.send(400, {"error": "bad request"})
        self.send(202) if answer is None else self.send(200, answer)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8933"))), Handler).serve_forever()
