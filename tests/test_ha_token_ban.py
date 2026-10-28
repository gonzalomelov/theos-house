"""A rejected Home Assistant token gets exactly one request, never a retry.

Home Assistant bans an IP after a few failed logins (ip_ban_enabled). On Oct 28 the relay was banned after
four 401s from deploy/probe.py. Offline: a fake Home Assistant on 127.0.0.1 answers 401 and counts requests.
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from parenting_agent import house as house_mod
from parenting_agent.house import REJECTED_MESSAGE, HomeAssistant, TokenRejected
from test_house_tools import make

ROOT = Path(__file__).resolve().parent.parent


class FakeHomeAssistant:
    def __init__(self, status):
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                fake.requests.append(self.path)
                body = b'{"message": "401: Unauthorized"}' if status in (401, 403) else b'{"message": "error"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _answer

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TokenRejectedTests(unittest.TestCase):
    def setUp(self):
        house_mod._rejected["code"] = None
        self.addCleanup(house_mod._rejected.update, {"code": None})

    def fake(self, status=401):
        fake = FakeHomeAssistant(status)
        self.addCleanup(fake.close)
        return fake

    def test_a_401_makes_exactly_one_request_for_the_whole_process(self):
        fake = self.fake(401)
        first, second = HomeAssistant(fake.url, "wrong"), HomeAssistant(fake.url, "wrong")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(TokenRejected) as caught:
                first.ping()
            for call in (lambda: first.state("light.a"), lambda: second.service("light.turn_on", "light.a"),
                         lambda: second.attributes("light.a"), lambda: second.ping()):
                with self.assertRaises(TokenRejected):
                    call()
        self.assertEqual(caught.exception.code, 401)
        self.assertEqual(fake.requests, ["/api/"])
        self.assertEqual(stderr.getvalue(), REJECTED_MESSAGE + "\n")
        self.assertEqual(house_mod.token_rejected(), 401)

    def test_a_403_stops_too(self):
        fake = self.fake(403)
        client = HomeAssistant(fake.url, "wrong")
        with contextlib.redirect_stderr(io.StringIO()):
            for _ in range(3):
                with self.assertRaises(TokenRejected):
                    client.state("light.a")
        self.assertEqual(len(fake.requests), 1)

    def test_rejected_is_a_url_error_so_callers_keep_handling_it(self):
        self.assertTrue(issubclass(TokenRejected, urllib.error.URLError))

    def test_other_errors_do_not_stop_the_client(self):
        fake = self.fake(500)
        client = HomeAssistant(fake.url, "token")
        for _ in range(2):
            with self.assertRaises(urllib.error.HTTPError):
                client.state("light.a")
        self.assertEqual(len(fake.requests), 2)
        self.assertIsNone(house_mod.token_rejected())

    def test_house_status_reads_once_then_stops(self):
        fake = self.fake(401)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            agent, plugin, _ = make(tmp, client=HomeAssistant(fake.url, "wrong"))
            states = plugin.status()
            agent.close()
        self.assertGreater(len(states), 1)
        self.assertTrue(all("rejected the token" in value for value in states.values()))
        self.assertEqual(len(fake.requests), 1)

    def test_probe_token_mode_makes_one_request_and_exits_3(self):
        fake = self.fake(401)
        env = {**os.environ, "HA_URL": fake.url, "HA_MCP_TOKEN": "wrong", "PYTHONPATH": str(ROOT)}
        with open(ROOT / "deploy" / "probe.py") as script:
            done = subprocess.run([sys.executable, "-", "token"], stdin=script, cwd=ROOT, env=env,
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn("HTTP 401 token rejected", done.stdout)
        self.assertIn(REJECTED_MESSAGE, done.stderr)
        self.assertEqual(fake.requests, ["/api/"])

    def test_agent_sh_checks_the_token_before_any_other_home_assistant_call(self):
        script = (ROOT / "deploy" / "agent.sh").read_text()
        checks = script[script.index("checks() {"):]
        self.assertLess(checks.index("ha_token_ok"), checks.index("parenting_agent --check"))
        self.assertLess(checks.index("ha_token_ok"), checks.index("deploy/probe.py\""))
        deploy = script[script.index("deploy() {"):]
        self.assertLess(deploy.index("ha_token_ok"), deploy.index("if healthy && checks"))


if __name__ == "__main__":
    unittest.main()
