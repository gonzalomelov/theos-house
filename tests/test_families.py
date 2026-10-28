"""Tests for the families service: the invite gate, onboarding, isolation between families, the walled-off config,
the scorer rows, delete-my-data, the health refusal, caps, reminders and the bot loop. Fake brain and a fake
Telegram adapter, no network.
"""
import datetime
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import time
import unittest
import urllib.request
import zoneinfo
from contextlib import redirect_stdout
from pathlib import Path

from parenting_agent.agent import brain as brain_mod
from parenting_agent.agent import rules
from parenting_agent.channels import telegram as telegram_mod
from parenting_agent.channels.messaging import Incoming, MessagingError, Messenger
from parenting_agent.families import babylog, export_sessions, service as service_mod
from parenting_agent.families import settings as settings_mod
from parenting_agent.families.bot import FamiliesBot
from parenting_agent.families.service import Families
from parenting_agent.families.store import visitor_id
from parenting_agent.families.texts import EN, ES

ROOT = Path(__file__).resolve().parent.parent
FAMILIES_DIR = ROOT / "parenting_agent" / "families"
DEPLOY_DIR = ROOT / "deploy" / "families"
TZ = zoneinfo.ZoneInfo("America/Montevideo")
WELCOME = EN["WELCOME"] + EN["ASK_NAME"]


def settings(**extra):
    env = {"PA_FAMILIES_BRAIN": "fake", "PA_FAMILIES_DATA_DIR": tempfile.mkdtemp()}
    env.update(extra)
    return settings_mod.load(env)


class CountingBrain:
    """Answers plainly, reports usage, counts its calls."""
    name, model, destination = "claude", "test", "api.anthropic.com"

    def __init__(self, tokens=(1000, 100)):
        self.calls, self.tokens = 0, tokens

    def step(self, system, transcript, tools):
        self.calls += 1
        self.last_system = system
        return brain_mod.Reply("Here is what the log says.", usage={"input_tokens": self.tokens[0], "output_tokens": self.tokens[1]})


def make(test, brain=None, clock=None, **extra):
    app = Families(settings(**extra), brain=brain, clock=clock)
    test.addCleanup(app.close)
    return app


def text(replies):
    return " ".join(t for _, t in replies)


def onboard(app, user, chat=None, name="Mia", partner="no", internal=False):
    """Gonza makes a code, the parent sends /start and answers the 3 questions. Returns the replies."""
    chat = chat or user
    code = app.store.create_invite(internal=internal)
    return [app.handle(user, chat, f"/start {code}"), app.handle(user, chat, name),
            app.handle(user, chat, "2026-10-12"), app.handle(user, chat, partner)]


def family_of(app, user):
    return app.store.parent(visitor_id(user))["family_id"]


class InviteGate(unittest.TestCase):
    def assert_nothing_stored(self, app):
        self.assertEqual(app.store.family_count(), 0)
        self.assertEqual(app.store.rows(), [])
        self.assertEqual(list(Path(app.s["data_dir"]).glob("family-*.sqlite")), [])

    def test_no_code_gets_a_polite_reply_and_nothing_else(self):
        app = make(self)
        for message in ("hello", "/start", "bottle 120 ml", "/summary"):
            self.assertEqual(app.handle("111", "111", message), [("111", EN["NO_CODE"])])
        self.assert_nothing_stored(app)

    def test_wrong_used_and_expired_codes_are_refused(self):
        clock = [datetime.datetime(2026, 10, 28, 10, 0, tzinfo=TZ)]
        app = make(self, clock=lambda: clock[0])
        self.assertEqual(text(app.handle("111", "111", "/start AAAAAAAA")), EN["BAD_CODE"])
        old = app.store.create_invite(days=7)
        clock[0] += datetime.timedelta(days=8)
        self.assertEqual(text(app.handle("111", "111", f"/start {old}")), EN["BAD_CODE"])
        self.assert_nothing_stored(app)
        code = app.store.create_invite()
        self.assertEqual(text(app.handle("222", "222", f"/start {code.lower()}")), WELCOME)
        self.assertEqual(text(app.handle("333", "333", f"/start {code}")), EN["BAD_CODE"])
        self.assertIsNone(app.store.parent(visitor_id("333")))

    def test_guessing_codes_stops_after_the_daily_limit(self):
        app = make(self)
        for _ in range(app.s["max_bad_codes_per_day"]):
            self.assertEqual(text(app.handle("111", "111", "/start BBBBBBBB")), EN["BAD_CODE"])
        code = app.store.create_invite()
        self.assertEqual(text(app.handle("111", "111", f"/start {code}")), EN["TOO_MANY"])
        self.assert_nothing_stored(app)

    def test_codes_are_stored_only_as_hashes(self):
        app = make(self)
        code = app.store.create_invite()
        self.assertNotIn(code.encode(), app.store.path.read_bytes())

    def test_group_chats_are_refused(self):
        app = make(self)
        code = app.store.create_invite()
        self.assertEqual(app.handle("111", "-100", f"/start {code}", chat_type="group"), [("-100", EN["GROUP"])])
        self.assert_nothing_stored(app)

    def test_the_beta_has_a_family_limit(self):
        app = make(self, PA_FAMILIES_MAX_FAMILIES="1")
        onboard(app, "111")
        code = app.store.create_invite()
        self.assertEqual(text(app.handle("222", "222", f"/start {code}")), EN["FULL"])


class Onboarding(unittest.TestCase):
    def test_three_questions_then_logging_in_under_two_minutes(self):
        app = make(self)
        started = time.monotonic()
        replies = onboard(app, "111", name="Mia")
        self.assertEqual(text(replies[0]), WELCOME)
        self.assertIn("When was Mia born?", text(replies[1]))
        self.assertIn("3 of 3", text(replies[2]))
        self.assertIn("All set for Mia", text(replies[3]))
        self.assertIn("logged", text(app.handle("111", "111", "bottle 120 ml")).lower())
        f = app.family(family_of(app, "111"))
        self.assertEqual(f.log.entries("feeding")[-1]["details"]["amount_ml"], 120.0)
        self.assertEqual(f.fact("baby_name"), "Mia")
        self.assertEqual(f.fact("birth_date"), "2026-10-12")
        self.assertLess(time.monotonic() - started, 120)
        self.assertEqual(len(app.store.rows()), 5)

    def test_bad_birth_dates_are_asked_again(self):
        app = make(self)
        code = app.store.create_invite()
        app.handle("111", "111", f"/start {code}")
        app.handle("111", "111", "Leo")
        for bad in ("next tuesday", "2030-01-01", "1990-01-01"):
            self.assertEqual(text(app.handle("111", "111", bad)), EN["BAD_BORN"])
        self.assertIn("3 of 3", text(app.handle("111", "111", "12/10/2026")))

    def test_the_other_parent_joins_the_same_log(self):
        app = make(self)
        replies = onboard(app, "111", name="Mia", partner="yes")
        code = re.search(r"\b([A-Z2-9]{8})\b", text(replies[3])).group(1)
        app.handle("111", "111", "bottle 90 ml")
        welcome = text(app.handle("222", "222", f"/start {code}"))
        self.assertIn("You joined Mia's log", welcome)
        self.assertEqual(family_of(app, "222"), family_of(app, "111"))
        answer = text(app.handle("222", "222", "how much did she drink today?"))
        self.assertIn("90 ml", answer)


class FamilyLog(unittest.TestCase):
    def test_feeds_diapers_sleep_and_baths_by_text(self):
        app = make(self)
        onboard(app, "111")
        for message in ("bottle 120 ml", "wet and dirty diaper", "she just fell asleep", "she woke up", "just gave her a bath"):
            app.handle("111", "111", message)
        f = app.family(family_of(app, "111"))
        kinds = [e["kind"] for e in f.log.entries()]
        self.assertEqual(kinds, ["feeding", "diaper", "sleep", "bath"])
        self.assertTrue(f.log.entries("diaper")[0]["details"]["solid"])

    def test_questions_are_answered_from_the_familys_own_log(self):
        app = make(self)
        onboard(app, "111")
        app.handle("111", "111", "bottle 120 ml")
        app.handle("111", "111", "bottle 80 ml")
        self.assertIn("200 ml", text(app.handle("111", "111", "how much did she drink today?")))
        self.assertIn("Today for Mia: 2 feeds, 200 ml", text(app.handle("111", "111", "/summary")))

    def test_the_brain_sees_the_babys_name_and_no_bookkeeping(self):
        brain = CountingBrain()
        app = make(self, brain=brain)
        onboard(app, "111", name="Theo")
        app.family(family_of(app, "111")).memory.remember("_reminded_for", "feeding#1")
        app.handle("111", "111", "hello there")
        self.assertIn("The baby is Theo", brain.last_system)
        facts = json.loads(re.search(r"Facts you were told: (.*)", brain.last_system).group(1))
        self.assertEqual(facts, {"baby_name": "Theo", "birth_date": "2026-10-12"})
        self.assertIn("no house tools", brain.last_system)

    def test_only_log_tools_and_no_house_tools(self):
        app = make(self)
        onboard(app, "111")
        f = app.family(family_of(app, "111"))
        self.assertEqual(f.agent.tools.names(), sorted(service_mod.ALLOWED))
        self.assertEqual(f.log.name, "family")


class Isolation(unittest.TestCase):
    def test_two_families_never_see_each_other(self):
        app = make(self)
        onboard(app, "111", name="Mia")
        onboard(app, "222", name="Leo")
        app.handle("111", "111", "bottle 155 ml")
        a, b = family_of(app, "111"), family_of(app, "222")
        self.assertNotEqual(a, b)
        self.assertIn("155 ml", text(app.handle("111", "111", "how much did she drink today?")))
        self.assertNotIn("155", text(app.handle("222", "222", "how much did he drink today?")))
        self.assertEqual(app.family(b).log.entries("feeding"), [])
        self.assertEqual(app.family(b).fact("baby_name"), "Leo")
        path_a, path_b = babylog.family_path(app.s["data_dir"], a), babylog.family_path(app.s["data_dir"], b)
        self.assertNotEqual(path_a, path_b)
        self.assertIn(b"155", path_a.read_bytes())
        self.assertNotIn(b"155", path_b.read_bytes())
        self.assertNotIn(b"Mia", path_b.read_bytes())

    def test_family_ids_cannot_point_outside_the_data_folder(self):
        for bad in ("../x", "abc", "", "0123456789abcdef/../../etc"):
            with self.assertRaises(ValueError):
                babylog.family_path("/tmp", bad)

    def test_registry_holds_no_baby_data_or_text(self):
        app = make(self)
        onboard(app, "111", name="Zelda")
        app.handle("111", "111", "bottle 133 ml with a secret word banana")
        registry = app.store.path.read_bytes()
        for word in (b"Zelda", b"banana", b"133", b"2026-10-12"):
            self.assertNotIn(word, registry)


class WalledOff(unittest.TestCase):
    HOUSE_ENV = {"HA_URL": "http://192.0.2.10:8123", "HA_TOKEN": "x", "HA_MCP_TOKEN": "m", "BABYBUDDY_URL": "http://127.0.0.1:18790",
                 "BABYBUDDY_TOKEN": "y", "TELEGRAM_BOT_TOKEN": "z", "TELEGRAM_CHAT_ID": "1", "DEEPSEEK_API_KEY": "k",
                 "GITHUB_TOKEN": "g", "SOME_URL": "http://vostro:8790", "TS_NODE": "100.64.0.1"}

    def test_scrub_keeps_only_the_brain_key_and_the_families_token(self):
        env = dict(self.HOUSE_ENV, ANTHROPIC_API_KEY="sk-test", TELEGRAM_FAMILIES_BOT_TOKEN="fam", PATH="/usr/bin",
                   PA_FAMILIES_BRAIN="fake", HTTPS_PROXY="http://egress:8888")
        removed = settings_mod.scrub_environment(env)
        self.assertEqual(sorted(removed), sorted(self.HOUSE_ENV))
        self.assertEqual(set(env), {"ANTHROPIC_API_KEY", "TELEGRAM_FAMILIES_BOT_TOKEN", "PATH", "PA_FAMILIES_BRAIN", "HTTPS_PROXY"})

    def test_the_family_bot_token_is_refused(self):
        self.assertTrue(settings_mod.same_bot_as_family({"TELEGRAM_BOT_TOKEN": "same", "TELEGRAM_FAMILIES_BOT_TOKEN": "same"}))
        self.assertFalse(settings_mod.same_bot_as_family({"TELEGRAM_BOT_TOKEN": "a", "TELEGRAM_FAMILIES_BOT_TOKEN": "b"}))

    def test_keys_env_file_yields_only_the_two_keys(self):
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text("BABYBUDDY_URL=http://127.0.0.1:18790\nHA_TOKEN=abc\nTELEGRAM_BOT_TOKEN=fam\nANTHROPIC_API_KEY=sk\n"
                        "TELEGRAM_FAMILIES_BOT_TOKEN=second\n")
        env = {}
        self.assertEqual(sorted(settings_mod.read_keys(path, env)), ["ANTHROPIC_API_KEY", "TELEGRAM_FAMILIES_BOT_TOKEN"])
        self.assertEqual(env, {"ANTHROPIC_API_KEY": "sk", "TELEGRAM_FAMILIES_BOT_TOKEN": "second"})

    def test_settings_hold_no_route_to_the_house(self):
        for brain in ("claude", "baseten", "fake"):
            dumped = json.dumps(settings_mod.load({"PA_FAMILIES_BRAIN": brain}), default=list)
            self.assertIsNone(settings_mod.HOUSE_VALUES.search(dumped), brain)
            urls = re.findall(r"https?://[^\"]+", dumped)
            self.assertTrue(all(u.startswith("https://inference.baseten.co") for u in urls), urls)

    def test_families_code_has_no_house_client(self):
        for path in FAMILIES_DIR.glob("*.py"):
            source = path.read_text()
            for word in ("BabyBuddyLog", "agent.babybuddy", "babybuddy import", "rhythm.log import", "HomeAssistant(",
                         "from ..house", "import house", "load_env(", "HA_URL", "BABYBUDDY_URL", "urlopen", "router",
                         "sitter", "white_noise", "agent.json", "agent.vostro"):
                self.assertFalse(word in source, f"{path.name} uses {word}")

    def test_compose_and_proxy_allow_only_the_brain_and_telegram(self):
        compose = (DEPLOY_DIR / "compose.yml").read_text()
        body = "\n".join(line for line in compose.splitlines() if not line.lstrip().startswith("#"))
        for word in ("network_mode", "extra_hosts", "host-gateway", "babybuddy", "home-assistant", "parenting-agent-internal", "ports:", "8123",
                     "8790", "HA_", "BABYBUDDY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "/var/run/docker.sock"):
            self.assertNotIn(word, body, word)
        self.assertIn("read_only: true", body)
        self.assertIn("cap_drop: [ALL]", body)
        self.assertRegex(body, r"internal:\n\s+external: true\n\s+name: pa-families-internal")
        hosts = [line for line in (DEPLOY_DIR / "egress" / "filter").read_text().splitlines() if line.strip()]
        self.assertEqual(hosts, [r"^api\.anthropic\.com$", r"^inference\.baseten\.co$", r"^api\.telegram\.org$"])
        self.assertIn("FilterDefaultDeny Yes", (DEPLOY_DIR / "egress" / "tinyproxy.conf").read_text())
        dockerfile = (DEPLOY_DIR / "Dockerfile").read_text()
        for word in ("config", ".env", "deploy/", "babybuddy-net"):
            self.assertNotIn(word, re.sub(r"#.*", "", dockerfile), word)

    def test_a_conversation_opens_no_network_connection(self):
        opened = []
        real = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError("network"))
        self.addCleanup(setattr, urllib.request, "urlopen", real)
        app = make(self)
        onboard(app, "111")
        for message in ("bottle 120 ml", "wet diaper", "when did she last eat?", "/summary", "/next"):
            app.handle("111", "111", message)
        app.tick()
        self.assertEqual(opened, [])


class ScorerRows(unittest.TestCase):
    def test_one_row_per_parent_message_in_the_scorer_format(self):
        app = make(self, PA_FAMILIES_INTERNAL_USERS="999")
        onboard(app, "111")
        app.handle("111", "111", "bottle 120 ml")
        onboard(app, "999", name="Test baby")
        app.handle("444", "444", "hello")  # a stranger writes no row
        rows = app.store.rows()
        self.assertEqual(len(rows), 9)
        mine = [r for r in rows if r["visitor_id"] == hashlib.sha256(b"111").hexdigest()]
        self.assertEqual(len(mine), 5)
        for r in rows:
            self.assertEqual((r["kind"], r["channel"]), ("family", "telegram"))
            self.assertRegex(r["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual({r["internal"] for r in mine}, {0})
        self.assertEqual({r["family_id"] for r in mine}, {family_of(app, "111")})
        self.assertEqual({r["internal"] for r in rows if r not in mine}, {1})

    def test_internal_invites_mark_the_parent_and_their_partner(self):
        app = make(self)
        replies = onboard(app, "111", internal=True, partner="yes")
        code = re.search(r"\b([A-Z2-9]{8})\b", text(replies[3])).group(1)
        app.handle("222", "222", f"/start {code}")
        self.assertEqual({r["internal"] for r in app.store.rows()}, {1})

    def test_export_prints_json_lines_with_family_id(self):
        app = make(self)
        onboard(app, "111")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(export_sessions.main(["--db", str(app.store.path)]), 0)
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(lines), 4)
        self.assertEqual(set(lines[0]), {"ts", "visitor_id", "channel", "kind", "internal", "family_id"})
        self.assertEqual(lines[0]["kind"], "family")

    def test_demo_export_still_has_no_family_id(self):
        from parenting_agent.demo import export_sessions as demo_export
        from parenting_agent.demo.records import Records
        records = Records(tempfile.mkdtemp())
        records.add_message("v", False)
        records.close()
        out = io.StringIO()
        with redirect_stdout(out):
            demo_export.main(["--db", str(records.path)])
        self.assertEqual(set(json.loads(out.getvalue())), {"ts", "visitor_id", "channel", "kind", "internal"})


class DeleteMyData(unittest.TestCase):
    def test_delete_wipes_the_family_and_tells_the_other_parent(self):
        app = make(self)
        replies = onboard(app, "111", partner="yes")
        code = re.search(r"\b([A-Z2-9]{8})\b", text(replies[3])).group(1)
        app.handle("222", "222", f"/start {code}")
        app.handle("111", "111", "bottle 120 ml")
        onboard(app, "333", name="Other")
        family = family_of(app, "111")
        path = babylog.family_path(app.s["data_dir"], family)
        self.assertTrue(path.exists())
        self.assertIn("Send DELETE to confirm", text(app.handle("111", "111", "/deletemydata")))
        out = app.handle("111", "111", "DELETE")
        self.assertEqual(out, [("111", EN["DELETED"]), ("222", EN["DELETED_OTHER"])])
        self.assertFalse(path.exists())
        self.assertIsNone(app.store.parent(visitor_id("111")))
        self.assertIsNone(app.store.parent(visitor_id("222")))
        self.assertEqual({r["family_id"] for r in app.store.rows()}, {family_of(app, "333")})
        self.assertNotIn(family, app.store.family_ids())
        self.assertEqual(text(app.handle("111", "111", "bottle 90 ml")), EN["NO_CODE"])
        self.assertEqual(app.family(family_of(app, "333")).fact("baby_name"), "Other")

    def test_anything_but_delete_cancels(self):
        app = make(self)
        onboard(app, "111")
        app.handle("111", "111", "bottle 120 ml")
        app.handle("111", "111", "/deletemydata")
        self.assertEqual(text(app.handle("111", "111", "no wait")), EN["DELETE_CANCELLED"])
        self.assertEqual(len(app.family(family_of(app, "111")).log.entries("feeding")), 1)
        self.assertNotEqual(text(app.handle("111", "111", "DELETE")), EN["DELETED"])

    def test_delete_works_during_onboarding(self):
        app = make(self)
        code = app.store.create_invite()
        app.handle("111", "111", f"/start {code}")
        app.handle("111", "111", "/deletemydata")
        self.assertEqual(text(app.handle("111", "111", "delete")), EN["DELETED"])
        self.assertEqual(app.store.family_count(), 0)
        self.assertEqual(app.store.rows(), [])


class Safety(unittest.TestCase):
    def test_health_questions_get_the_refusal_without_a_brain_call(self):
        brain = CountingBrain()
        app = make(self, brain=brain)
        onboard(app, "111")
        for question in ("She has a fever, should I give her paracetamol?", "Is this rash normal?", "What dose of ibuprofen?"):
            self.assertEqual(text(app.handle("111", "111", question)), rules.REFUSAL)
        self.assertEqual(brain.calls, 0)


class Caps(unittest.TestCase):
    def test_messages_per_family_per_day(self):
        app = make(self, PA_FAMILIES_MAX_MESSAGES="6")
        onboard(app, "111")
        app.handle("111", "111", "bottle 100 ml")
        app.handle("111", "111", "bottle 110 ml")
        self.assertEqual(text(app.handle("111", "111", "bottle 120 ml")), EN["FAMILY_LIMIT"])
        self.assertEqual(len(app.store.rows()), 6)
        self.assertEqual(len(app.family(family_of(app, "111")).log.entries("feeding")), 2)

    def test_family_spend_cap_falls_back_to_the_free_rules(self):
        brain = CountingBrain(tokens=(1_000_000, 0))  # $0.10 a call at Haiku prices
        app = make(self, brain=brain, PA_FAMILIES_BRAIN="claude", PA_FAMILIES_FAMILY_USD="0.25")
        onboard(app, "111")
        for _ in range(5):
            app.handle("111", "111", "bottle 100 ml")
        self.assertEqual(brain.calls, 3)
        self.assertAlmostEqual(app.store.spent_today(family_of(app, "111")), 0.30)
        # The counting brain never calls the log tool. The first bottle gets the honest "could not log" after one more
        # ask. On the second the cap is hit at the ask, so the free rules log it, and they log the 3 after the cap.
        self.assertEqual(len(app.family(family_of(app, "111")).log.entries("feeding")), 4)
        onboard(app, "222")
        app.handle("222", "222", "hello")
        self.assertEqual(brain.calls, 4)

    def test_global_spend_cap_covers_every_family(self):
        brain = CountingBrain(tokens=(1_000_000, 0))
        app = make(self, brain=brain, PA_FAMILIES_BRAIN="claude", PA_FAMILIES_DAILY_USD="0.2", PA_FAMILIES_FAMILY_USD="5")
        onboard(app, "111")
        onboard(app, "222")
        app.handle("111", "111", "hello")
        app.handle("222", "222", "hello")
        app.handle("111", "111", "bottle 90 ml")
        app.handle("222", "222", "bottle 90 ml")
        self.assertEqual(brain.calls, 2)
        self.assertEqual(len(app.family(family_of(app, "222")).log.entries("feeding")), 1)

    def test_long_messages_are_refused_without_a_row(self):
        app = make(self)
        onboard(app, "111")
        before = len(app.store.rows())
        self.assertIn("under 500", text(app.handle("111", "111", "x" * 501)))
        self.assertEqual(len(app.store.rows()), before)


class Reminders(unittest.TestCase):
    def clocked(self, start):
        clock = [start]
        app = make(self, clock=lambda: clock[0])
        onboard(app, "111", partner="yes")
        return app, clock

    def test_next_feed_reminder_once_to_every_parent(self):
        clock = [datetime.datetime(2026, 10, 28, 9, 0, tzinfo=TZ)]
        app = make(self, clock=lambda: clock[0])
        replies = onboard(app, "111", partner="yes")
        code = re.search(r"\b([A-Z2-9]{8})\b", text(replies[3])).group(1)
        app.handle("222", "222", f"/start {code}")
        f = app.family(family_of(app, "111"))
        f.log.add("feeding", {"amount_ml": 100, "start": "2026-10-28T06:00:00-03:00"}, "2026-10-28T06:15:00-03:00")
        f.log.add("feeding", {"amount_ml": 100, "start": "2026-10-28T09:00:00-03:00"}, "2026-10-28T09:15:00-03:00")
        clock[0] = datetime.datetime(2026, 10, 28, 11, 0, tzinfo=TZ)
        self.assertEqual(app.tick(), [])
        clock[0] = datetime.datetime(2026, 10, 28, 11, 52, tzinfo=TZ)
        due = app.tick()
        self.assertEqual([chat for chat, _ in due], ["111", "222"])
        self.assertIn("around 12:00, in about 8 min", due[0][1])
        self.assertEqual(app.tick(), [])
        self.assertIn("12:00", text(app.handle("111", "111", "/next")))

    def test_reminders_can_be_turned_off(self):
        app, clock = self.clocked(datetime.datetime(2026, 10, 28, 9, 0, tzinfo=TZ))
        f = app.family(family_of(app, "111"))
        f.log.add("feeding", {"start": "2026-10-28T06:00:00-03:00"}, "2026-10-28T06:15:00-03:00")
        f.log.add("feeding", {"start": "2026-10-28T09:00:00-03:00"}, "2026-10-28T09:15:00-03:00")
        app.handle("111", "111", "/reminders off")
        clock[0] = datetime.datetime(2026, 10, 28, 11, 55, tzinfo=TZ)
        self.assertEqual(app.tick(), [])

    def test_no_reminder_from_an_old_log(self):
        app, clock = self.clocked(datetime.datetime(2026, 10, 28, 9, 0, tzinfo=TZ))
        f = app.family(family_of(app, "111"))
        f.log.add("feeding", {"start": "2026-10-28T06:00:00-03:00"}, "2026-10-28T06:15:00-03:00")
        f.log.add("feeding", {"start": "2026-10-28T09:00:00-03:00"}, "2026-10-28T09:15:00-03:00")
        clock[0] = datetime.datetime(2026, 10, 29, 11, 55, tzinfo=TZ)
        self.assertFalse(any("Next feed" in t for _, t in app.tick()))

    def test_daily_summary_once_in_the_evening(self):
        app, clock = self.clocked(datetime.datetime(2026, 10, 28, 9, 0, tzinfo=TZ))
        f = app.family(family_of(app, "111"))
        f.log.add("feeding", {"amount_ml": 120}, "2026-10-28T08:30:00-03:00")
        f.log.add("diaper", {"wet": True, "solid": True}, "2026-10-28T08:45:00-03:00")
        clock[0] = datetime.datetime(2026, 10, 28, 19, 59, tzinfo=TZ)
        self.assertEqual(app.tick(), [])
        clock[0] = datetime.datetime(2026, 10, 28, 20, 1, tzinfo=TZ)
        due = app.tick()
        self.assertEqual(len(due), 1)
        self.assertIn("Today for Mia: 1 feed, 120 ml in total, the last at 08:30. 1 diaper, 1 wet and 1 dirty.", due[0][1])
        self.assertEqual(app.tick(), [])

    def test_no_summary_on_an_empty_day(self):
        app, clock = self.clocked(datetime.datetime(2026, 10, 28, 20, 30, tzinfo=TZ))
        self.assertEqual(app.tick(), [])


class FakeTelegram(Messenger):
    name = "fake"

    def __init__(self, batches):
        self.batches, self.sent, self.offsets = list(batches), [], []

    def poll(self, offset, timeout):
        self.offsets.append(offset)
        return self.batches.pop(0) if self.batches else []

    def send(self, chat_id, text):
        if chat_id == "broken":
            raise MessagingError("Telegram sendMessage HTTP 403")
        self.sent.append((chat_id, text))
        return len(self.sent)


class Bot(unittest.TestCase):
    def test_poll_answers_and_keeps_the_offset(self):
        app = make(self)
        code = app.store.create_invite()
        fake = FakeTelegram([[Incoming(10, "111", f"/start {code}", "ana", "111", "private"),
                              Incoming(11, "555", "hi", "x", "555", "private")],
                             [Incoming(12, "111", "Mia", "ana", "111", "private")]])
        bot = FamiliesBot(app, fake, poll_timeout_s=0)
        self.assertEqual(bot.poll_once(), 2)
        self.assertEqual(bot.read_offset(), 12)
        bot.poll_once()
        self.assertEqual(fake.offsets, [0, 12])
        self.assertEqual([t for _, t in fake.sent], [WELCOME, EN["NO_CODE"],
                                                     EN["ASK_BORN"].format(name="Mia")])

    def test_a_failed_send_does_not_stop_the_bot(self):
        app = make(self)
        fake = FakeTelegram([[Incoming(1, "broken", "hi", "", "777", "private"), Incoming(2, "888", "hi", "", "888", "private")]])
        bot = FamiliesBot(app, fake, poll_timeout_s=0)
        self.assertEqual(bot.poll_once(), 1)
        self.assertEqual(bot.errors, 1)

    def test_telegram_adapter_reads_the_user_id_and_chat_type(self):
        messenger = telegram_mod.TelegramMessenger("t")
        messenger._call = lambda method, params, timeout: [
            {"update_id": 5, "message": {"text": "hi", "chat": {"id": 42, "type": "private"}, "from": {"id": 42, "first_name": "A"}}}]
        item = messenger.poll(0, 0)[0]
        self.assertEqual((item.user_id, item.chat_type, item.chat_id), ("42", "private", "42"))


if __name__ == "__main__":
    unittest.main()
