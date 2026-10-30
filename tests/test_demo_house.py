"""Tonight's house on the public demo (#132): the endpoint, the per-visitor cache, the limits, the fallback, "let me
sleep" re-planning, Spanish, and the wall (the demo runs house_brain.py with no device module in the process).

Offline: Muse is a fake with canned answers, the clock is fixed at 22:30, the brain is the demo's fake brain.
"""
import datetime
import http.client
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from parenting_agent import house_brain as hb
from parenting_agent.agent.brain import BrainError
from parenting_agent.demo import settings as settings_mod
from parenting_agent.demo import tonight
from parenting_agent.demo.app import PARENTS, DemoApp
from parenting_agent.demo.records import visitor_id
from parenting_agent.demo.server import serve

ROOT = Path(__file__).resolve().parent.parent
TZ = datetime.timezone(datetime.timedelta(hours=-3))
NOW = datetime.datetime(2026, 10, 29, 22, 30, tzinfo=TZ)
META = {"seconds": 4.2, "usd": 0.01, "input_tokens": 3000, "output_tokens": 900, "host": "fake", "model": "fake-muse"}


def answer(**kw):
    base = {"on_duty": "Parent B", "floor_clean": [], "bottle_prewarm": [{"start": "02:40", "why": "night feed"}],
            "door_quiet": [], "white_noise_boost": [{"start": "23:00", "end": "23:30", "why": "settling"}],
            "messages": [], "summary": "Warm water before the 02:50 feed.", "why_changed": ""}
    return {**base, **kw}


class FakeMuse:
    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def ask(self, system, text, schema, name="plan"):
        self.asked.append({"system": system, "context": json.loads(text), "schema": schema})
        got = self.answers.pop(0) if self.answers else answer()
        if isinstance(got, Exception):
            raise got
        return got, dict(META)


def settings(**extra):
    env = {"PA_DEMO_BRAIN": "fake", "PA_DEMO_DATA_DIR": tempfile.mkdtemp(), "PA_DEMO_PORT": "0"}
    env.update(extra)
    return settings_mod.load(env)


def make(muse, **extra):
    app = DemoApp(settings(**extra), clock=lambda: NOW, muse=muse)
    return app


class Endpoint(unittest.TestCase):
    def test_tonight_runs_house_brain_with_its_own_prompt_schema_and_checks(self):
        muse = FakeMuse(answer())
        app = make(muse)
        self.addCleanup(app.close)
        status, body = app.house("v", False, "tonight")
        self.assertEqual(status, 200, body)
        card = body["house"]["tonight"]
        self.assertEqual(card["source"], "muse")
        self.assertEqual(card["badge"], "Simulated house, nothing moves")
        asked = muse.asked[0]
        self.assertEqual(asked["schema"], hb.plan_schema(PARENTS))
        self.assertEqual(asked["system"], app.visitor("v").house.brain.system())
        self.assertEqual(asked["context"]["now"][-5:], "22:30")
        text = {r["label"]: r["text"] for r in card["rows"]}
        self.assertIn("02:40, silent, water only", text["Bottle warmer pre-heats"])
        self.assertIn("up to the cap 23:00 to 23:30", text["White noise"])
        self.assertIn("capped at 50 dB", text["White noise"])
        self.assertEqual(card["why"], "Warm water before the 02:50 feed.")
        # The rota stays fixed unless a parent asked to sleep (on_duty_on_request), whatever Muse names.
        self.assertIn("from the night rota", text["On duty tonight"])

    def test_the_safety_gate_refuses_a_bad_window_and_that_routine_shows_the_fixed_rule(self):
        app = make(FakeMuse(answer(bottle_prewarm=[{"start": "02:00", "why": "a"}, {"start": "02:30", "why": "b"}],
                                   floor_clean=[{"start": "23:00", "end": "23:50", "why": "night clean"}])))
        self.addCleanup(app.close)
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        text = {r["label"]: r["text"] for r in card["rows"]}
        self.assertEqual(card["source"], "muse")
        self.assertIn("did not pass the checks", text["Bottle warmer pre-heats"])
        self.assertIn("did not pass the checks", text["Floor clean"])

    def test_http_route_and_state_carry_the_card(self):
        app = make(FakeMuse())
        self.addCleanup(app.close)
        server = serve(app, app.s)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]

        def call(method, path, body=None, cookie="pa_vid=" + "a" * 40):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            headers = {"Cookie": cookie, "X-Forwarded-For": "203.0.113.5"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=None if body is None else json.dumps(body).encode(), headers=headers)
            res = conn.getresponse()
            out = (res.status, json.loads(res.read()))
            conn.close()
            return out

        status, body = call("POST", "/api/house", {"action": "tonight", "lang": "en"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["house"]["tonight"]["source"], "muse")
        self.assertEqual(call("GET", "/api/state")[1]["house"]["tonight"]["source"], "muse")
        self.assertEqual(call("POST", "/api/house", {"action": "boom"})[0], 400)
        self.assertEqual(call("GET", "/api/state", cookie="pa_vid=" + "b" * 40)[1]["house"], {})


class Cache(unittest.TestCase):
    def test_one_plan_per_visitor_a_second_tap_costs_nothing(self):
        muse = FakeMuse(answer(), answer(on_duty="Parent A"))
        app = make(muse)
        self.addCleanup(app.close)
        first = app.house("v", False, "tonight")[1]["house"]["tonight"]
        again = app.house("v", False, "tonight")[1]["house"]["tonight"]
        self.assertEqual(first, again)
        self.assertEqual(len(muse.asked), 1)
        self.assertEqual(app.records.messages_from("v"), 1)
        self.assertAlmostEqual(app.records.spent_today(), META["usd"])
        app.house("v", False, "sleep")
        app.house("v", False, "sleep")
        self.assertEqual(len(muse.asked), 2)
        self.assertEqual(app.records.messages_from("v"), 2)

    def test_visitors_do_not_share_a_plan(self):
        muse = FakeMuse(answer(), answer())
        app = make(muse)
        self.addCleanup(app.close)
        app.house("v1", False, "tonight")
        app.house("v2", False, "tonight")
        self.assertEqual(len(muse.asked), 2)

    def test_a_fresh_demo_baby_plans_again(self):
        muse = FakeMuse(answer(), answer())
        app = make(muse)
        self.addCleanup(app.close)
        app.house("v", False, "tonight")
        app.reset("v", False)
        self.assertEqual(app.state("v", False)["house"], {})
        app.house("v", False, "tonight")
        self.assertEqual(len(muse.asked), 2)


class Limits(unittest.TestCase):
    def test_each_plan_call_counts_as_a_message_and_the_limit_stops_it(self):
        muse = FakeMuse()
        app = make(muse, PA_DEMO_MAX_MESSAGES="2")
        self.addCleanup(app.close)
        self.assertEqual(app.message("v", False, "bottle 90 ml")[0], 200)
        self.assertEqual(app.house("v", False, "tonight")[0], 200)
        self.assertEqual(app.state("v", False)["remaining"], 0)
        status, body = app.house("v", False, "sleep")
        self.assertEqual((status, body["error"]), (429, "visitor_limit"))
        self.assertEqual(len(muse.asked), 1)
        # A cached plan still shows after the limit.
        self.assertEqual(app.house("v", False, "tonight")[0], 200)

    def test_sleep_before_tonight_counts_both_calls(self):
        app = make(FakeMuse())
        self.addCleanup(app.close)
        app.house("v", False, "sleep")
        self.assertEqual(app.records.messages_from("v"), 2)

    def test_internal_visitors_stay_marked_and_uncapped(self):
        app = make(FakeMuse(), PA_DEMO_MAX_MESSAGES="1")
        self.addCleanup(app.close)
        self.assertEqual(app.house("me", True, "tonight")[0], 200)
        self.assertEqual(app.house("me", True, "sleep")[0], 200)
        self.assertEqual([r["internal"] for r in app.records.rows()], [1, 1])
        app.house("stranger", False, "tonight")
        self.assertEqual(app.records.rows()[-1]["internal"], 0)

    def test_the_connection_limit_applies(self):
        app = make(FakeMuse(), PA_DEMO_MAX_CLIENT_MESSAGES="1")
        self.addCleanup(app.close)
        self.assertEqual(app.house("v1", False, "tonight", client="203.0.113.7")[0], 200)
        self.assertEqual(app.house("v2", False, "tonight", client="203.0.113.7")[1]["error"], "client_limit")

    def test_resting_demo_shows_the_fixed_rules_with_no_muse_call(self):
        muse = FakeMuse()
        app = make(muse, PA_DEMO_DAILY_USD="0")
        self.addCleanup(app.close)
        status, body = app.house("v", False, "tonight")
        card = body["house"]["tonight"]
        self.assertEqual((status, card["source"]), (200, "fixed"))
        self.assertIn("daily AI limit", card["label"])
        self.assertEqual(muse.asked, [])


class Fallback(unittest.TestCase):
    def check_fixed(self, card, reason):
        self.assertEqual(card["source"], "fixed")
        self.assertTrue(card["label"].startswith("Fixed rules, Muse was not used"), card["label"])
        self.assertIn(reason, card["label"])
        text = {r["label"]: r["text"] for r in card["rows"]}
        self.assertIn("from the night rota", text["On duty tonight"])
        self.assertIn("nap mode", text["Quiet doorbell"])
        self.assertIn("Fixed rule", text["Floor clean"])
        self.assertEqual(card["why"], "")

    def test_muse_error_falls_back_to_the_fixed_rules_and_says_so(self):
        app = make(FakeMuse(BrainError("timed out")))
        self.addCleanup(app.close)
        self.check_fixed(app.house("v", False, "tonight")[1]["house"]["tonight"], "did not answer")

    def test_a_refused_plan_falls_back_whole(self):
        app = make(FakeMuse(answer(on_duty="Grandma")))
        self.addCleanup(app.close)
        self.check_fixed(app.house("v", False, "tonight")[1]["house"]["tonight"], "did not pass the checks")

    def test_no_muse_at_all_with_the_fake_brain(self):
        app = DemoApp(settings(), clock=lambda: NOW)
        self.addCleanup(app.close)
        self.assertIsNone(app.muse)
        self.check_fixed(app.house("v", False, "tonight")[1]["house"]["tonight"], "no AI")

    def test_the_fixed_rule_pre_warm_is_the_night_feed_lead(self):
        app = make(FakeMuse(BrainError("down")))
        self.addCleanup(app.close)
        card = app.house("v", False, "tonight")[1]["house"]["tonight"]
        warm = {r["label"]: r["text"] for r in card["rows"]}["Bottle warmer pre-heats"]
        self.assertRegex(warm, r"^(\d\d:\d\d, 10 min before the guessed night feed around \d\d:\d\d|Nothing guessed)")

    def test_fixed_rules_do_not_re_plan_a_sleep_request(self):
        app = make(FakeMuse(BrainError("down"), BrainError("down")))
        self.addCleanup(app.close)
        card = app.house("v", False, "sleep")[1]["house"]["sleep"]
        self.assertEqual(card["source"], "fixed")
        self.assertIn("do not re-plan", card["changes"][0])


class LetMeSleep(unittest.TestCase):
    def test_let_me_sleep_writes_the_note_re_plans_and_lists_what_changed(self):
        muse = FakeMuse(answer(on_duty="Parent A"),
                        answer(on_duty="Parent A", bottle_prewarm=[{"start": "02:30", "why": "earlier"}],
                               why_changed="Parent B asked to sleep, Parent A takes the night."))
        app = make(muse)
        self.addCleanup(app.close)
        before = app.house("v", False, "tonight")[1]["house"]["tonight"]
        v = app.visitor("v")
        asker = before["on_duty"]
        other = next(p for p in PARENTS if p != asker)
        muse.answers[0]["on_duty"] = other
        card = app.house("v", False, "sleep")[1]["house"]["sleep"]
        context = muse.asked[1]["context"]
        self.assertEqual(context["trigger"], "adapt")
        self.assertIn("let me sleep tonight", context["what_happened"])
        self.assertTrue(any("let me sleep" in r for r in context["log_last_24h"]))
        self.assertEqual(card["on_duty"], other)
        self.assertIn("Muse handed over the night", card["rows"][0]["text"])
        self.assertIn(f"On duty tonight: {asker} → {other}", card["changes"])
        self.assertTrue(any(c.startswith("Bottle warmer pre-heats: 02:40 → 02:30") for c in card["changes"]))
        self.assertEqual(card["why_changed"], "Parent B asked to sleep, Parent A takes the night.")
        # The panel's rota follows the plan, and the note is in the visitor's log.
        self.assertEqual(v.rota()["on_duty"], other)
        self.assertTrue(any("let me sleep" in (e["details"].get("text") or "") for e in v.recent(10)))

    def test_a_secret_in_muses_why_is_dropped_by_the_same_guard(self):
        app = make(FakeMuse(answer(summary="Parent B is on, the gate code is 4471.")))
        self.addCleanup(app.close)
        self.assertEqual(app.house("v", False, "tonight")[1]["house"]["tonight"]["why"], "")

    def test_spanish_card_and_note(self):
        muse = FakeMuse(answer(), answer(on_duty="Parent A"))
        app = make(muse)
        self.addCleanup(app.close)
        app.house("v", False, "tonight", lang="es")
        body = app.house("v", False, "sleep", lang="es")[1]
        card = body["house"]["sleep"]
        self.assertEqual(card["badge"], "Casa simulada, nada se mueve")
        self.assertEqual(card["rows"][0]["label"], "De turno esta noche")
        self.assertTrue(any("Persona" in c for c in card["changes"]) or card["changes"] == ["No cambió nada en el plan"])
        self.assertIn("dejame dormir", muse.asked[1]["context"]["what_happened"])


class ChatTool(unittest.TestCase):
    def test_the_agent_tool_reads_the_same_cached_plan(self):
        muse = FakeMuse(answer())
        app = make(muse)
        self.addCleanup(app.close)
        app.house("v", False, "tonight")
        v = app.visitor("v")
        self.assertIn("tonight_house", v.agent.tools.items)
        text = v.tonight_text()
        self.assertIn("Simulated house, nothing moves", text)
        self.assertIn("Bottle warmer pre-heats: 02:40", text)
        self.assertEqual(len(muse.asked), 1)


class ChatRoute(unittest.TestCase):
    def test_house_questions_get_the_plan_with_no_chat_brain_call(self):
        muse = FakeMuse(answer(), answer(on_duty="Parent A"))
        app = make(muse)
        self.addCleanup(app.close)
        calls = []
        real = app.brain.brain.step
        app.brain.brain.step = lambda *a: calls.append(1) or real(*a)
        status, body = app.message("v", False, "What will the house do tonight?")
        self.assertEqual(status, 200)
        self.assertIn("Simulated house, nothing moves", body["reply"])
        self.assertEqual(body["answered_by"], {"kind": "house", "muse": True})
        self.assertIn("tonight", body["house"])
        status, body = app.message("v", False, "Estoy agotada, dejame dormir esta noche", lang="es")
        self.assertIn("sleep", body["house"])
        self.assertIn("Casa simulada, nada se mueve", body["reply"])
        self.assertEqual(calls, [])
        self.assertEqual(len(muse.asked), 2)
        # Two messages and two Muse plan calls, each a session row.
        self.assertEqual(app.records.messages_from("v"), 4)

    def test_a_health_question_with_let_me_sleep_still_goes_to_the_gates(self):
        muse = FakeMuse()
        app = make(muse)
        self.addCleanup(app.close)
        body = app.message("v", False, "I'm exhausted, let me sleep, he has a fever of 39")[1]
        self.assertEqual(muse.asked, [])
        self.assertNotIn("Simulated house", body["reply"])

    def test_the_chat_text_holds_no_word_the_log_guards_read_as_a_change(self):
        from parenting_agent.agent import rules
        app = make(FakeMuse(BrainError("down"), answer(on_duty="Parent A")))
        self.addCleanup(app.close)
        v = app.visitor("v")
        for asked in (False, True):
            text = v.tonight_text(asked_to_sleep=asked)
            self.assertFalse(rules.claims_change(text), text)
            self.assertFalse(rules.CLAIMS_DONE.search(text), text)


class Wall(unittest.TestCase):
    def test_demo_runs_the_house_brain_with_no_device_module_loaded(self):
        code = ("import sys, parenting_agent.demo.app, parenting_agent.demo.server\n"
                "print(sorted(m for m in sys.modules if m.startswith('parenting_agent.')))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        loaded = set(eval(out))
        self.assertIn("parenting_agent.house_brain", loaded)
        for module in ("house", "house_plan", "day_engine", "night_feed", "house_tools", "virtual_devices", "white_noise",
                       "meals", "families"):
            self.assertNotIn(f"parenting_agent.{module}", loaded)

    def test_constants_match_the_modules_not_in_the_image(self):
        from parenting_agent import night_feed, white_noise
        self.assertEqual(tonight.FIXED_LEAD_MIN, night_feed.DEFAULTS["lead_min"])
        self.assertEqual(tonight.CRIB_CAP_DB, white_noise.CRIB_CAP_DB)


if __name__ == "__main__":
    unittest.main()
