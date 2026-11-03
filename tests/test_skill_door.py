"""The Alexa skill's door (#177): a Cloudflare hostname behind an Access service token, then deploy/door, then the
relay's voice bridge port. The wall must still hold: no way from the door to Home Assistant, Baby Buddy, the LAN or
any other path of the agent.

Offline: the configs are read as text, and deploy/wall_check.py's door mode runs against fake doors on 127.0.0.1.
"""
import contextlib
import importlib.util
import io
import json
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOOR_SUBNET = "192.0.2.0/29"


def load_wall_check():
    spec = importlib.util.spec_from_file_location("wall_check", ROOT / "deploy" / "wall_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def servers(conf):
    """Each nginx server block's text, keyed by its listen port."""
    blocks = {}
    for match in re.finditer(r"server \{\n(.*?)\n  \}\n", conf, re.S):
        port = re.search(r"listen (\d+);", match.group(1)).group(1)
        blocks[port] = match.group(1)
    return blocks


def compose_service(text, name):
    match = re.search(rf"\n  {name}:\n(.*?)(?=\n  [a-z]+:\n|\nnetworks:)", text, re.S)
    return match.group(1)


class FakeDoor:
    """A door on 127.0.0.1. answer(method, path) -> (status, body)."""

    def __init__(self, answer):
        self.seen = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _answer(self):
                fake.seen.append((self.command, self.path))
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                status, body = answer(self.command, self.path)
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = _answer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def honest_door(method, path):
    if path in ("/ask", "/health") and method in ("GET", "POST"):
        return 401, json.dumps({"error": "unauthorized"})
    if method not in ("GET", "POST"):
        return 403, "<html>403 Forbidden</html>"
    return 404, "<html>404 Not Found</html>"


class DoorConfigTest(unittest.TestCase):
    def setUp(self):
        self.door = (ROOT / "deploy" / "door" / "nginx.conf").read_text()
        self.relay = (ROOT / "deploy" / "relay" / "nginx.conf").read_text()
        self.compose = (ROOT / "deploy" / "compose.yml").read_text()

    def test_the_door_forwards_two_paths_to_the_voice_bridge_port_and_nothing_else(self):
        blocks = servers(self.door)
        self.assertEqual(list(blocks), ["8080"])
        self.assertEqual(re.findall(r"set \$relay (\S+);", self.door), ["parenting-agent-relay:8767"])
        self.assertEqual(self.door.count("proxy_pass"), 1)
        self.assertIn("location ~ ^/(ask|health)$ {", self.door)
        self.assertRegex(blocks["8080"], r"location / \{\s+return 404;")
        self.assertIn("limit_except GET POST { deny all; }", self.door)
        for name in ("homeassistant", "babybuddy", ":8123", ":8790", "parenting-agent:"):
            self.assertNotIn(name, self.door)

    def test_the_relay_refuses_the_door_network_on_the_house_and_baby_buddy_ports(self):
        blocks = servers(self.relay)
        self.assertIn(f"deny {DOOR_SUBNET};", blocks["8123"])
        self.assertIn(f"deny {DOOR_SUBNET};", blocks["8790"])
        self.assertNotIn("deny", blocks["8767"])
        self.assertIn("location ~ ^/(ask|health|whatsapp)$ {", blocks["8767"])

    def test_only_the_door_is_published_and_only_on_loopback(self):
        door = compose_service(self.compose, "door")
        self.assertIn('ports: ["127.0.0.1:4830:8080"]', door)
        self.assertIn("networks: [door]", door)
        self.assertIn("read_only", self.compose)
        self.assertEqual(self.compose.count("ports:"), 1)
        for name in ("agent", "relay", "egress"):
            self.assertNotIn("ports:", compose_service(self.compose, name))
        self.assertIn("networks: [internal, babybuddy, homeassistant, door]", compose_service(self.compose, "relay"))
        self.assertIn("networks: [internal]", compose_service(self.compose, "agent"))
        self.assertIn(f"- subnet: {DOOR_SUBNET}", self.compose)

    def test_the_deploy_checks_the_door_with_the_wall(self):
        agent_sh = (ROOT / "deploy" / "agent.sh").read_text()
        walled = agent_sh[agent_sh.index("walled() {"):agent_sh.index("door_walled() {")]
        self.assertIn("door_walled", walled)
        self.assertIn('python3 - door < "$DIR/deploy/wall_check.py"', agent_sh)
        self.assertIn('"8080/tcp -> 127.0.0.1:4830"', agent_sh)
        self.assertIn("parenting-agent_door ", agent_sh)

    def test_the_agent_cannot_reach_the_door_or_its_host_port(self):
        wall = (ROOT / "deploy" / "wall_check.py").read_text()
        self.assertIn('tcp("parenting-agent-door", 8080)', wall)
        self.assertIn("(22, 80, 443, 4830, 8086, 8123, 8790)", wall)
        self.assertNotIn("relay:8123/", wall)


class DoorWallCheckTest(unittest.TestCase):
    def run_door(self, answer):
        door = FakeDoor(answer)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = load_wall_check().door(door.url)
            return code, out.getvalue(), door.seen
        finally:
            door.close()

    def test_an_honest_door_holds(self):
        code, out, seen = self.run_door(honest_door)
        self.assertEqual(code, 0, out)
        self.assertIn("wall holds", out)
        self.assertIn(("GET", "/api/states"), seen)
        self.assertIn(("POST", "/api/services/light/turn_on"), seen)
        self.assertIn(("PUT", "/ask"), seen)

    def test_a_door_that_lets_home_assistant_through_breaks_the_wall(self):
        def leaky(method, path):
            if path.startswith("/api/"):
                return 401, json.dumps({"message": "401: Unauthorized"})
            return honest_door(method, path)

        code, out, _ = self.run_door(leaky)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"WRONG +/api/states through the door")

    def test_a_door_that_answers_200_anywhere_breaks_the_wall(self):
        code, out, _ = self.run_door(lambda method, path: honest_door(method, path) if path != "/" else (200, "hi"))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"WRONG +/ through the door")

    def test_a_door_that_does_not_reach_the_bridge_fails(self):
        code, out, _ = self.run_door(lambda method, path: (404, "<html>404</html>"))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"WRONG +/health through the door reaches the voice bridge")

    def test_an_open_bridge_without_a_token_fails(self):
        code, out, _ = self.run_door(lambda method, path: (200, "{}") if path == "/health" else honest_door(method, path))
        self.assertEqual(code, 1)

    def test_no_door_at_all_fails_and_prints_no_secret(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = load_wall_check().door("http://127.0.0.1:9")
        self.assertEqual(code, 1)
        self.assertNotIn("Bearer", out.getvalue())


if __name__ == "__main__":
    unittest.main()
