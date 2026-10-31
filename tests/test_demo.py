"""Tests for the public demo: isolation between visitors, caps, the walled-off config, the sessions contract,
and the refusal of health questions. Fake brain, no network. The HTTP tests run the real server on a free port.
"""
import datetime
import http.client
import io
import json
import re
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

from parenting_agent.agent import brain as brain_mod
from parenting_agent.agent import rules
from parenting_agent.demo import export_sessions
from parenting_agent.demo import settings as settings_mod
from parenting_agent.demo.app import RESTING, DemoApp
from parenting_agent.demo.babylog import DemoBabyLog
from parenting_agent.demo.records import Records, visitor_id
from parenting_agent.demo import server as server_mod
from parenting_agent.demo.server import serve

SECRET = "test-fixture-not-a-real-secret-0000000000"
DEMO_DIR = Path(__file__).resolve().parent.parent / "parenting_agent" / "demo"


def settings(**extra):
    env = {"PA_DEMO_BRAIN": "fake", "PA_DEMO_DATA_DIR": tempfile.mkdtemp(), "PA_DEMO_PORT": "0"}
    env.update(extra)
    return settings_mod.load(env)


class CountingBrain:
    """A brain that answers plainly, reports usage, and counts its calls."""
    name, model, destination = "scripted", "test", "inference.baseten.co"

    def __init__(self, tokens=(1000, 100)):
        self.calls, self.tokens = 0, tokens

    def step(self, system, transcript, tools):
        self.calls += 1
        return brain_mod.Reply("Here is what the log says.", usage={"input_tokens": self.tokens[0], "output_tokens": self.tokens[1]})


class DemoLog(unittest.TestCase):
    def test_week_ends_now_and_nothing_is_in_the_future(self):
        now = datetime.datetime(2026, 10, 28, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        log = DemoBabyLog(clock=lambda: now)
        entries = log.entries(None, None, 1000)
        self.assertGreater(len(entries), 150)
        self.assertTrue(all(datetime.datetime.fromisoformat(e["ts"]) <= now for e in entries))
        self.assertEqual(entries[-1]["ts"][:10], "2026-10-28")
        self.assertEqual({e["kind"] for e in entries}, {"feeding", "diaper", "sleep", "bath", "note"})

    def test_sleep_start_then_end_makes_one_record(self):
        moments = [datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=50)]
        log = DemoBabyLog(clock=lambda: moments[-1])
        before = len(log.entries("sleep", None, 1000))
        log.add("sleep", {"action": "start"})
        self.assertEqual(len(log.entries("sleep", None, 1000)), before)
        moments.append(moments[0] + datetime.timedelta(minutes=45))
        record = log.add("sleep", {"action": "end"})
        self.assertEqual(record["details"]["duration_min"], 45)
        self.assertEqual(len(log.entries("sleep", None, 1000)), before + 1)
        with self.assertRaises(ValueError):
            DemoBabyLog().add("sleep", {"action": "end"})


class Isolation(unittest.TestCase):
    def test_two_visitors_never_see_each_other(self):
        app = DemoApp(settings())
        self.addCleanup(app.close)
        status, body = app.message("visitor-a", False, "bottle 155 ml")
        self.assertEqual(status, 200)
        a_feeds = app.visitor("visitor-a").baby_log.entries("feeding", None, 1000)
        b_feeds = app.visitor("visitor-b").baby_log.entries("feeding", None, 1000)
        self.assertEqual(a_feeds[-1]["details"]["amount_ml"], 155.0)
        self.assertNotIn(155.0, [e["details"]["amount_ml"] for e in b_feeds])
        self.assertEqual(len(a_feeds), len(b_feeds) + 1)
        self.assertEqual(app.visitor("visitor-b").memory.recent_messages(), [])
        self.assertIsNot(app.visitor("visitor-a").bus, app.visitor("visitor-b").bus)

    def test_reset_gives_a_fresh_copy(self):
        app = DemoApp(settings())
        self.addCleanup(app.close)
        app.message("v", False, "bottle 155 ml")
        app.reset("v", False)
        self.assertNotIn(155.0, [e["details"]["amount_ml"] for e in app.visitor("v").baby_log.entries("feeding", None, 1000)])

    def test_questions_are_answered_from_the_demo_log(self):
        app = DemoApp(settings())
        self.addCleanup(app.close)
        log = app.visitor("v").baby_log
        last = log.entries("feeding", None, 1)[-1]
        status, body = app.message("v", False, "When did she last eat?")
        self.assertEqual(status, 200)
        self.assertIn(datetime.datetime.fromisoformat(last["ts"]).astimezone(log.now().tzinfo).strftime("%H:%M"), body["reply"])
        self.assertIn("next_feed", body["proactive"])
        self.assertIn("Next on duty", body["proactive"]["night_summary"]["text"])


class Caps(unittest.TestCase):
    def test_per_visitor_message_limit(self):
        app = DemoApp(settings(PA_DEMO_MAX_MESSAGES="3"))
        self.addCleanup(app.close)
        statuses = [app.message("v", False, "bottle 60 ml")[0] for _ in range(5)]
        self.assertEqual(statuses, [200, 200, 200, 429, 429])
        self.assertEqual(app.message("other", False, "bottle 60 ml")[0], 200)
        self.assertEqual(app.message("v", True, "bottle 60 ml")[0], 200)  # internal visitors are not capped

    def test_daily_spend_cap_rests_the_demo(self):
        brain = CountingBrain(tokens=(1_000_000, 0))
        app = DemoApp(settings(PA_DEMO_DAILY_USD="0.25", PA_DEMO_PRICE_IN="0.10", PA_DEMO_PRICE_OUT="0.50"), brain=brain)
        self.addCleanup(app.close)
        results = [app.message(f"v{i}", False, "how is she doing today?") for i in range(5)]
        self.assertEqual([s for s, _ in results], [200, 200, 200, 503, 503])
        self.assertEqual(results[-1][1]["reply"], RESTING)
        self.assertEqual(brain.calls, 3)
        self.assertAlmostEqual(app.records.spent_today(), 0.30, places=6)

    def test_missing_usage_is_still_charged(self):
        app = DemoApp(settings(PA_DEMO_PRICE_IN="1", PA_DEMO_PRICE_OUT="1"), brain=CountingBrain())
        self.addCleanup(app.close)
        self.assertGreater(app.brain.cost(None), 0)

    def test_max_input_length(self):
        app = DemoApp(settings(PA_DEMO_MAX_INPUT="50"))
        self.addCleanup(app.close)
        self.assertEqual(app.message("v", False, "x" * 51)[0], 413)
        self.assertEqual(app.message("v", False, "   ")[0], 400)
        self.assertEqual(app.records.rows(), [])


class HealthQuestions(unittest.TestCase):
    def test_health_questions_get_the_kind_refusal_without_a_brain_call(self):
        brain = CountingBrain()
        app = DemoApp(settings(), brain=brain)
        self.addCleanup(app.close)
        for question in ("She has a cough, should I give her paracetamol?", "Is this rash normal?", "What dose of ibuprofen?"):
            status, body = app.message("v", False, question)
            self.assertEqual(status, 200)
            self.assertEqual(body["reply"], rules.REFUSAL)
        self.assertEqual(brain.calls, 0)


class WalledOff(unittest.TestCase):
    HOUSE_ENV = {"HA_URL": "http://192.0.2.10:8123", "HA_TOKEN": "x", "BABYBUDDY_URL": "http://127.0.0.1:18790",
                 "BABYBUDDY_TOKEN": "y", "TELEGRAM_BOT_TOKEN": "z", "DEEPSEEK_API_KEY": "k", "GITHUB_TOKEN": "g",
                 "SOME_URL": "http://vostro:8790", "TS_NODE": "100.64.0.1"}

    def test_scrub_keeps_only_the_brain_key(self):
        env = dict(self.HOUSE_ENV, BASETEN_API_KEY="sk-test", PATH="/usr/bin:/Users/x/.local/bin", PA_DEMO_BRAIN="fake",
                   HTTPS_PROXY="http://egress:8888", LANG="en_US.UTF-8")
        removed = settings_mod.scrub_environment(env)
        self.assertEqual(sorted(removed), sorted(self.HOUSE_ENV))
        self.assertEqual(set(env), {"BASETEN_API_KEY", "PATH", "PA_DEMO_BRAIN", "HTTPS_PROXY", "LANG"})

    def test_brain_env_file_yields_only_the_brain_key(self):
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text("BABYBUDDY_URL=http://127.0.0.1:18790\nHA_TOKEN=abc\nBASETEN_API_KEY=sk-test\n# comment\n")
        env = {}
        self.assertEqual(settings_mod.read_brain_key(path, env), ["BASETEN_API_KEY"])
        self.assertEqual(env, {"BASETEN_API_KEY": "sk-test"})

    def test_settings_hold_no_route_to_the_house(self):
        for brain in ("baseten", "fake"):
            text = json.dumps(settings_mod.load({"PA_DEMO_BRAIN": brain}))
            self.assertIsNone(settings_mod.HOUSE_VALUES.search(text), brain)
            urls = re.findall(r"https?://[^\"]+", text)
            self.assertTrue(all(u.startswith("https://inference.baseten.co") for u in urls), urls)

    def test_demo_code_has_no_house_client(self):
        for path in DEMO_DIR.glob("*.py"):
            source = path.read_text()
            # house_brain.py and sleep_forecast.py are allowed: they plan, the Home Assistant client is house.py.
            for word in ("import BabyBuddyLog", "agent.babybuddy", "babybuddy import", "rhythm.log import", "HomeAssistant(",
                         r"from \.\.house\b(?!_brain)", r"\bimport house\b",
                         r"\b(house_plan|day_engine|night_feed|house_tools)\b import|import .*\b(house_plan|day_engine|night_feed|house_tools)\b",
                         "load_env(", "HA_URL", "BABYBUDDY_URL", "urlopen"):
                self.assertIsNone(re.search(word if "\\" in word else re.escape(word), source), f"{path.name} uses {word}")

    def test_a_conversation_opens_no_network_connection(self):
        opened = []
        real = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError("network"))
        self.addCleanup(setattr, urllib.request, "urlopen", real)
        app = DemoApp(settings())
        self.addCleanup(app.close)
        for text in ("bottle 120 ml", "wet and dirty diaper", "she just fell asleep", "how much did she drink today?"):
            self.assertEqual(app.message("v", False, text)[0], 200)
        self.assertEqual(opened, [])
        self.assertEqual(app.visitor("v").baby_log.name, "demo")


class SessionsContract(unittest.TestCase):
    def test_one_row_per_message_with_the_contract_columns(self):
        s = settings()
        app = DemoApp(s)
        self.addCleanup(app.close)
        app.message(visitor_id("cookie-a"), False, "bottle 120 ml with a secret word banana")
        app.message(visitor_id("cookie-a"), False, "when did she last eat?")
        app.message(visitor_id("cookie-b"), True, "hello")
        db = sqlite3.connect(str(Path(s["data_dir"]) / "demo_sessions.sqlite"))
        self.addCleanup(db.close)
        columns = [(c[1], c[2]) for c in db.execute("pragma table_info(sessions)")]
        self.assertEqual(columns, [("ts", "TEXT"), ("visitor_id", "TEXT"), ("channel", "TEXT"), ("kind", "TEXT"), ("internal", "INTEGER")])
        rows = db.execute("select ts, visitor_id, channel, kind, internal from sessions").fetchall()
        self.assertEqual(len(rows), 3)
        for ts, vid, channel, kind, internal in rows:
            moment = datetime.datetime.fromisoformat(ts)
            self.assertEqual(moment.utcoffset(), datetime.timedelta(0))
            self.assertRegex(vid, r"^[0-9a-f]{64}$")
            self.assertEqual((channel, kind), ("web", "demo"))
        self.assertEqual([r[4] for r in rows], [0, 0, 1])
        self.assertEqual(rows[0][1], visitor_id("cookie-a"))
        self.assertNotIn(b"banana", Path(s["data_dir"], "demo_sessions.sqlite").read_bytes())

    def test_export_prints_json_lines(self):
        s = settings()
        records = Records(s["data_dir"])
        records.add_message(visitor_id("c"), False)
        records.add_message(visitor_id("c"), True)
        records.close()
        out = io.StringIO()
        with redirect_stdout(out):
            code = export_sessions.main(["--db", str(Path(s["data_dir"]) / "demo_sessions.sqlite")])
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([l["internal"] for l in lines], [0, 1])
        self.assertEqual(set(lines[0]), {"ts", "visitor_id", "channel", "kind", "internal"})


class Http(unittest.TestCase):
    def setUp(self):
        self.s = settings(PA_DEMO_MAX_MESSAGES="2", PA_DEMO_HOST="127.0.0.1", PA_DEMO_INTERNAL_SECRET=SECRET)
        self.app = DemoApp(self.s)
        self.server = serve(self.app, self.s)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()

    def request(self, method, path, body=None, headers=None, content_type="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        hdrs = dict(headers or {})
        if data is not None:
            hdrs["Content-Type"] = content_type
        conn.request(method, path, body=data, headers=hdrs)
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        return res, payload

    def cookie(self, res, name="pa_vid"):
        for value in res.headers.get_all("Set-Cookie") or []:
            if value.startswith(name + "="):
                return value.split(";", 1)[0].split("=", 1)[1]
        return None

    def test_page_sets_a_random_cookie_and_rows_hash_it(self):
        res, page = self.request("GET", "/")
        self.assertEqual(res.status, 200)
        self.assertIn(b"Theo", page)
        token = self.cookie(res)
        self.assertRegex(token, r"^[A-Za-z0-9_-]{32,64}$")
        self.assertIn("HttpOnly", res.headers.get("Set-Cookie"))
        res, body = self.request("POST", "/api/message", {"text": "bottle 90 ml"},
                                 {"Cookie": f"pa_vid={token}", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(res.status, 200, body)
        rows = self.app.records.rows()
        self.assertEqual(rows[-1]["visitor_id"], visitor_id(token))
        self.assertEqual(rows[-1]["internal"], 0)  # forwarded through a proxy, so not localhost
        self.assertNotIn("203.0.113.9", json.dumps(rows))

    def test_localhost_and_the_secret_internal_path_mark_internal(self):
        self.request("POST", "/api/message", {"text": "bottle 90 ml"})
        res, _ = self.request("GET", f"/internal/{SECRET}", headers={"X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(res.status, 200)
        marker = self.cookie(res, "pa_internal")
        self.assertEqual(marker, server_mod.internal_marker(SECRET))
        self.assertNotIn(SECRET, res.headers.get("Set-Cookie"))
        self.request("POST", "/api/message", {"text": "bottle 90 ml"},
                     {"Cookie": f"pa_internal={marker}", "X-Forwarded-For": "203.0.113.9"})
        self.request("POST", "/api/message", {"text": "bottle 90 ml"}, {"X-Forwarded-For": "203.0.113.9"})
        self.assertEqual([r["internal"] for r in self.app.records.rows()], [1, 1, 0])

    def test_plain_internal_and_wrong_secrets_are_404(self):
        for path in ("/internal", "/internal/", f"/internal/{SECRET[:-1]}", f"/internal/{SECRET}x", f"/internal/{SECRET}/",
                     "/internal/1", f"/INTERNAL/{SECRET}"):
            res, _ = self.request("GET", path, headers={"X-Forwarded-For": "203.0.113.9"})
            self.assertEqual(res.status, 404, path)
            self.assertIsNone(self.cookie(res, "pa_internal"), path)
        res, _ = self.request("POST", f"/internal/{SECRET}", {"text": "hi"})
        self.assertEqual(res.status, 404)

    def test_a_hand_made_internal_cookie_does_not_count(self):
        for value in ("1", "true", server_mod.internal_marker("another secret that is long enough to be used ok")):
            self.request("POST", "/api/message", {"text": "bottle 90 ml"},
                         {"Cookie": f"pa_internal={value}", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual([r["internal"] for r in self.app.records.rows()], [0, 0, 0])

    def test_without_a_secret_every_internal_address_is_404(self):
        for value in ("", "short"):
            s = settings(PA_DEMO_INTERNAL_SECRET=value)
            self.assertEqual(s["internal_secret"], "")
            handler = server_mod.make_handler(self.app, s)
            server = server_mod.http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                for path in ("/internal", "/internal/", f"/internal/{value}"):
                    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
                    conn.request("GET", path)
                    res = conn.getresponse()
                    res.read()
                    conn.close()
                    self.assertEqual(res.status, 404, (value, path))
            finally:
                server.shutdown()
                server.server_close()

    def test_no_uploads_and_small_json_only(self):
        res, _ = self.request("POST", "/api/message", b"--x\r\nContent-Disposition: form-data; name=file\r\n\r\nabc\r\n--x--",
                              content_type="multipart/form-data; boundary=x")
        self.assertEqual(res.status, 415)
        res, _ = self.request("POST", "/api/message", {"text": "a" * 5000})
        self.assertEqual(res.status, 413)
        res, _ = self.request("PUT", "/api/message", {"text": "hi"})
        self.assertEqual(res.status, 405)
        res, _ = self.request("POST", "/upload", {"text": "hi"})
        self.assertEqual(res.status, 404)
        self.assertEqual(self.app.records.rows(), [])

    def test_state_and_visitor_cap_over_http(self):
        res, _ = self.request("GET", "/")
        jar = {"Cookie": f"pa_vid={self.cookie(res)}", "X-Forwarded-For": "203.0.113.9"}
        res, body = self.request("GET", "/api/state", headers=jar)
        state = json.loads(body)
        self.assertEqual(state["remaining"], 2)
        self.assertIn("night_summary", state["proactive"])
        codes = [self.request("POST", "/api/message", {"text": "bottle 60 ml"}, jar)[0].status for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        self.assertIn("default-src 'self'", res.headers.get("Content-Security-Policy"))


if __name__ == "__main__":
    unittest.main()
