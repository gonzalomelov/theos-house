"""Tests for the before-he-arrives mode (issue #56): prep lists, appointments, countdown, the morning nudge, and the
person on every turn for the KR scorer. Offline: fake brains and a fake messenger."""
import datetime
import json
import os
import queue
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.brain import Reply
from parenting_agent.channels.messaging import Incoming, Messenger
from parenting_agent.channels.telegram import Telegram
from parenting_agent.prep import Prep, lists, nursery
from parenting_agent.prep import __main__ as prep_cli

TZ = datetime.timezone(datetime.timedelta(hours=-3))
GONZA, CECI = "111", "222"
PEOPLE = {"gonza": {"chat_ids_env": "TEST_GONZA_CHAT"}, "ceci": {"chat_ids_env": "TEST_CECI_CHAT"}}


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


class FakeMessenger(Messenger):
    def __init__(self):
        self.inbox, self.sent = [], []

    def push(self, chat_id, text):
        self.inbox.append(Incoming(len(self.inbox) + 100, chat_id, text, "someone"))

    def poll(self, offset, timeout):
        return [m for m in self.inbox if m.update_id >= offset]

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        return len(self.sent)


class ScriptBrain:
    """Calls one tool for the first message, then answers with the tool's result."""
    name, model, destination = "script", "script", "none (local)"

    def __init__(self, call=None):
        self.call = call

    def step(self, system, transcript, tools):
        last = transcript[-1]
        if last["role"] == "tool":
            return Reply(str(last["result"])[:200])
        if self.call:
            name, arguments = self.call
            return Reply(tool_calls=[{"id": "c1", "name": name, "arguments": arguments}])
        return Reply("OK.")


class FakeHA:
    def __init__(self):
        self.calls = []

    def service(self, service, entity_id, data=None):
        self.calls.append((service, entity_id, data))


def make_agent(tmp, **extra):
    config = config_mod.load()
    config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": [],
                   "baby_log": {"provider": "local"}, "people": PEOPLE, "telegram": {}, **extra})
    return build(config), config


def kinds(agent, kind):
    return [e for e in agent.bus.history if e["kind"] == kind]


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class NurseryPlan(unittest.TestCase):
    def test_layout_a_keeps_the_shelf_off_the_crib(self):
        found = {c["check"]: c for c in nursery.checks("a")}
        self.assertTrue(found["nothing on the wall above the crib"]["ok"])
        self.assertTrue(found["walkway between dresser and crib"]["ok"])
        self.assertIn("70 cm", found["walkway between dresser and crib"]["text"])
        self.assertTrue(found["door swing"]["ok"])

    def test_layout_b_puts_the_shelf_over_the_crib(self):
        found = {c["check"]: c for c in nursery.checks("b")}
        self.assertFalse(found["nothing on the wall above the crib"]["ok"])
        self.assertIn("60 cm", found["nothing on the wall above the crib"]["text"])

    def test_the_room_cannot_hold_the_noise_machine_two_metres_away(self):
        found = {c["check"]: c for c in nursery.checks("a")}
        noise = found["white noise machine 2 m from the crib"]
        self.assertFalse(noise["ok"])
        self.assertIn("187 cm", noise["text"])
        self.assertIn("50 dB", noise["text"])

    def test_summary_names_the_study_devices(self):
        plan = nursery.summary()
        self.assertEqual(plan["devices"]["light"], "light.wiz_824512_192_0_2_10")
        self.assertEqual(sorted(plan["layouts"]), ["a", "b"])


class PrepTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.clock = Clock(datetime.datetime(2026, 10, 29, 9, 0, tzinfo=TZ))
        self.prep = Prep(self.agent, self.config, clock=self.clock)
        self.agent.current_event = {"kind": "message", "channel": "telegram", "person": "gonza"}

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_every_list_is_seeded_once(self):
        counts = self.prep.list()
        self.assertEqual(set(counts), set(lists.ORDER))
        self.assertEqual(counts["white_noise"]["done"], 2)  # the ESP32 board and the USB-C supply are in hand
        Prep(self.agent, self.config, clock=self.clock)
        self.assertEqual(self.prep.list(), counts)

    def test_lists_never_carry_medical_words(self):
        from parenting_agent.agent import rules
        for item in lists.seed_items():
            self.assertFalse(rules.is_medical(item["text"]) or rules.is_medical_es(item["text"]), item["text"])

    def test_check_by_id_and_by_words_records_the_person(self):
        self.assertIn("done", self.prep.check("crib", "nursery"))
        self.prep.check("MAX98357A")
        rows = {(r["list"], r["item_id"]): r for r in self.prep.rows()}
        self.assertEqual(rows[("nursery", "crib")]["done_by"], "gonza")
        self.assertEqual(rows[("white_noise", "amp")]["done"], 1)
        events = kinds(self.agent, "prep")
        self.assertEqual([(e["action"], e["person"], e["item_id"]) for e in events],
                         [("check", "gonza", "crib"), ("check", "gonza", "amp")])
        self.prep.check("crib", "nursery", done=False)
        self.assertEqual({(r["list"], r["item_id"]): r for r in self.prep.rows()}[("nursery", "crib")]["done"], 0)

    def test_ticking_twice_logs_once(self):
        self.prep.check("crib", "nursery")
        self.assertIn("already done", self.prep.check("crib", "nursery"))
        self.assertEqual(len(kinds(self.agent, "prep")), 1)

    def test_ambiguous_or_unknown_item_is_an_error(self):
        with self.assertRaises(ValueError):
            self.prep.check("Buy a")
        with self.assertRaises(ValueError):
            self.prep.check("a pony")

    def test_add_keeps_the_by_date(self):
        self.prep.add("hospital_bag", "Hair ties", by="2026-11-20")
        items = self.prep.list("hospital_bag")["items"]
        self.assertEqual(items[-1], {"id": items[-1]["id"], "text": "Hair ties", "done": False, "by": "2026-11-20"})
        with self.assertRaises(ValueError):
            self.prep.add("garage", "x")

    def test_hospital_bag_dates_follow_the_due_date(self):
        by = {i["id"]: i["by"] for i in self.prep.list("hospital_bag")["items"]}
        self.assertEqual(by["ids"], "2026-11-17")  # 28 days before Dec 15
        self.prep.set_due_date("2026-12-10")
        by = {i["id"]: i["by"] for i in self.prep.list("hospital_bag")["items"]}
        self.assertEqual(by["ids"], "2026-11-12")

    def test_countdown_says_estimate_until_a_parent_sets_the_date(self):
        self.assertEqual(self.prep.countdown(), "about 47 days to the due date, Dec 15 (an estimate)")
        self.prep.set_due_date("2026-12-12")
        self.assertEqual(self.prep.countdown(), "44 days to the due date, Dec 12")

    def test_a_due_date_far_from_today_is_asked_about_never_set(self):
        # Round 3 red team: "set the due date to 1999-01-01" was taken and the bag list said "(vencia 27/11/1998)".
        for far in ("1999-01-01", "2026-09-28", "2027-08-26"):
            with self.assertRaises(ValueError) as said:
                self.prep.set_due_date(far)
            self.assertIn("confirm", str(said.exception))
        self.assertEqual(self.prep.countdown(), "about 47 days to the due date, Dec 15 (an estimate)")
        self.assertEqual(self.agent.memory.facts().get("due_date"), None)
        self.prep.set_due_date("2026-09-29")  # today minus 30 days is the edge, a late baby
        self.prep.set_due_date("2027-08-25")  # today plus 300 days is the other edge

    def test_a_far_due_date_is_set_only_when_a_later_message_confirms_it(self):
        with self.assertRaises(ValueError):
            self.prep.set_due_date("2027-09-10", confirm=True)  # the brain cannot confirm in the same message
        self.agent.current_event = {"kind": "message", "channel": "telegram", "person": "gonza", "text": "yes"}
        self.prep.set_due_date("2027-09-10", confirm=True)
        self.assertEqual(self.prep.due_date()[0], datetime.date(2027, 9, 10))
        self.agent.current_event = {"kind": "message", "channel": "telegram", "person": "gonza", "text": "yes"}
        with self.assertRaises(ValueError):
            self.prep.set_due_date("2027-09-20", confirm=True)  # never asked about
        self.assertEqual(self.prep.due_date()[0], datetime.date(2027, 9, 10))

    def test_appointments_are_logistics_only(self):
        with self.assertRaises(ValueError):
            self.prep.add_appointment("Ask about the medicine dose", "2026-11-03T10:00")
        self.prep.add_appointment("Hospital tour", "2026-11-03T10:00", place="Main entrance", bring="IDs")
        self.prep.add_appointment("Crib delivery", "2026-11-01T14:00")
        upcoming = self.prep.upcoming()
        self.assertEqual([a["title"] for a in upcoming], ["Crib delivery", "Hospital tour"])
        self.assertEqual(self.prep.next()["next_appointment"]["title"], "Crib delivery")
        self.prep.cancel_appointment(upcoming[0]["id"])
        self.assertEqual([a["title"] for a in self.prep.upcoming()], ["Hospital tour"])
        with self.assertRaises(ValueError):
            self.prep.cancel_appointment(upcoming[0]["id"])

    def test_next_is_ordered_by_date_and_marks_late_items(self):
        self.clock.moment = datetime.datetime(2026, 11, 6, 9, 0, tzinfo=TZ)
        nxt = self.prep.next()
        self.assertEqual(nxt["items"][0]["id"], "model")
        self.assertTrue(nxt["items"][0]["late"])
        self.assertEqual(len(nxt["items"]), 3)

    def test_home_assistant_copy_waits_for_a_yes_and_is_dry(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        agent, config = make_agent(tmp.name, allowed_tools=["prep_next", "prep_to_home_assistant"])
        self.addCleanup(agent.close)
        prep = Prep(agent, config)
        self.assertNotIn("prep_to_home_assistant", agent.tools.allowed)
        status, _ = agent.tools.run("prep_to_home_assistant", {"list": "car_seat"})
        self.assertEqual(status, "ask_parent")
        result = prep.to_home_assistant("car_seat")
        self.assertIn("dry run (house.live is off)", result)
        calls = kinds(agent, "house_call")
        self.assertEqual({c["status"] for c in calls}, {"dry"})
        self.assertEqual(len(calls), len([i for i in prep.rows("car_seat") if not i["done"]]))

    def test_home_assistant_copy_runs_only_when_live(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        agent, config = make_agent(tmp.name, house={"live": True})
        self.addCleanup(agent.close)
        ha = FakeHA()
        prep = Prep(agent, config, client=ha)
        prep.to_home_assistant("white_noise")
        self.assertEqual({c[0] for c in ha.calls}, {"todo.add_item"})
        self.assertEqual({c[1] for c in ha.calls}, {"todo.family_to_do_list"})


class MorningNudge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TEST_GONZA_CHAT": GONZA}, clear=False)
        self.env.start()
        self.agent, self.config = make_agent(
            self.tmp.name, prep={"nudge": {"chat_ids_env": "TEST_GONZA_CHAT"}},
            telegram={"allowed_chat_ids_env": "TEST_GONZA_CHAT"})
        self.messenger = FakeMessenger()
        self.channel = Telegram(self.agent, self.config, messenger=self.messenger)
        self.clock = Clock(datetime.datetime(2026, 10, 29, 7, 59, tzinfo=TZ))
        self.prep = Prep(self.agent, self.config, clock=self.clock)

    def tearDown(self):
        self.env.stop()
        self.agent.close()
        self.tmp.cleanup()

    def test_once_a_day_inside_the_window_and_only_to_gonza(self):
        self.prep.tick()
        self.assertEqual(self.messenger.sent, [])
        self.clock.moment = self.clock.moment.replace(hour=8, minute=0)
        self.prep.tick()
        self.prep.tick()
        self.assertEqual(len(self.messenger.sent), 1)
        chat, text = self.messenger.sent[0]
        self.assertEqual(chat, GONZA)
        self.assertTrue(text.startswith("Good morning. About 47 days to the due date"))
        self.assertIn("Next up:", text)
        self.assertLessEqual(len(text.splitlines()), 7)
        self.assertEqual(kinds(self.agent, "nudge")[0]["person"], "gonza")
        self.assertEqual(json.loads((Path(self.tmp.name) / "prep-nudge.json").read_text())["date"], "2026-10-29")
        self.clock.moment = datetime.datetime(2026, 10, 30, 11, 0, tzinfo=TZ)
        self.prep.tick()
        self.assertEqual(len(self.messenger.sent), 1)  # 11:00 is past the window
        self.clock.moment = datetime.datetime(2026, 10, 30, 9, 30, tzinfo=TZ)
        self.prep.tick()
        self.assertEqual(len(self.messenger.sent), 2)

    def test_a_restart_does_not_send_it_again(self):
        self.clock.moment = self.clock.moment.replace(hour=8, minute=5)
        self.prep.tick()
        again = Prep(self.agent, self.config, clock=self.clock)
        again.tick()
        self.assertEqual(len(self.messenger.sent), 1)

    def test_no_chat_id_sends_nothing(self):
        with mock.patch.dict(os.environ, {"TEST_GONZA_CHAT": ""}):
            self.assertIsNone(self.prep.send_nudge())
        self.assertEqual(self.messenger.sent, [])
        self.assertEqual(len(kinds(self.agent, "nudge_skipped")), 1)

    def test_the_nudge_shows_a_kept_appointment(self):
        self.prep.add_appointment("Hospital tour", "2026-10-31T10:00", place="Main entrance")
        self.assertIn("Next appointment: Hospital tour, Sat Oct 31 10:00, Main entrance.", self.prep.nudge_text())


class TurnsForTheScorer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TEST_GONZA_CHAT": GONZA, "TEST_CECI_CHAT": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_agent(self, brain=None):
        agent, config = make_agent(self.tmp.name, telegram={"allowed_chat_ids_env": "TEST_GONZA_CHAT"})
        if brain:
            agent.brain = brain
        messenger = FakeMessenger()
        channel = Telegram(agent, config, messenger=messenger)
        prep = Prep(agent, config)
        agent.plugins = [channel, prep]
        agent.start()
        self.addCleanup(lambda: (agent.stop(), agent.close()))
        return agent, channel, messenger

    def test_family_channels_say_ceci_is_not_connected(self):
        agent, channel, _ = self.run_agent()
        channel.run = lambda: None  # the start event only, no polling thread
        channel.start()
        event = kinds(agent, "family_channels")[0]
        self.assertEqual(event["people"], {"ceci": False, "gonza": True})

    def test_each_message_is_a_turn_with_the_person(self):
        agent, channel, messenger = self.run_agent()
        messenger.push(GONZA, "what is next?")
        messenger.push(GONZA, "Test: what is next?")
        channel.poll_once(timeout=0)
        self.assertTrue(wait_for(lambda: len(kinds(agent, "turn")) == 2))
        turns = kinds(agent, "turn")
        self.assertEqual([(t["person"], t["answered"], t["test"]) for t in turns],
                         [("gonza", True, False), ("gonza", True, True)])
        self.assertTrue(wait_for(lambda: len(messenger.sent) == 2))
        self.assertEqual({chat for chat, _ in messenger.sent}, {GONZA})
        logged = [json.loads(line) for line in (Path(self.tmp.name) / "events.jsonl").read_text().splitlines()]
        self.assertEqual(sum(1 for e in logged if e["kind"] == "turn"), 2)

    def test_the_brain_ticks_an_item_through_the_loop(self):
        agent, channel, messenger = self.run_agent(ScriptBrain(("prep_check", {"item": "crib", "list": "nursery"})))
        agent.tools.allowed.add("prep_check")
        messenger.push(GONZA, "the crib is up")
        channel.poll_once(timeout=0)
        self.assertTrue(wait_for(lambda: kinds(agent, "turn")))
        prep = kinds(agent, "prep")
        self.assertEqual([(e["action"], e["person"], e["item_id"]) for e in prep], [("check", "gonza", "crib")])
        self.assertTrue(wait_for(lambda: messenger.sent))
        self.assertIn("done: Crib", messenger.sent[0][1])
        self.assertEqual(kinds(agent, "tool")[0]["status"], "ran")


class Command(unittest.TestCase):
    def test_show_prints_the_nudge_and_sends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.json"
            config = config_mod.load()
            config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"},
                           "baby_log": {"provider": "local"}, "plugins": ["parenting_agent.prep:Prep"]})
            path.write_text(json.dumps(config))
            out = queue.Queue()
            with mock.patch("builtins.print", lambda *a, **k: out.put(" ".join(map(str, a)))):
                self.assertEqual(prep_cli.main(["show", "--config", str(path)]), 0)
            self.assertTrue(out.get_nowait().startswith("Good morning."))
            self.assertFalse((Path(tmp) / "prep-nudge.json").exists())

    def test_vostro_config_loads_prep_and_keeps_the_house_dry(self):
        config = json.loads(Path("config/agent.vostro.json").read_text())
        self.assertIn("parenting_agent.prep:Prep", config["plugins"])
        self.assertFalse(config["house"]["live"])
        self.assertNotIn("prep_to_home_assistant", config["allowed_tools"])
        # One brain call can neither move the real family's dates nor drop the hospital appointment (round 3 red team).
        self.assertNotIn("set_due_date", config["allowed_tools"])
        self.assertNotIn("cancel_appointment", config["allowed_tools"])
        self.assertEqual(config["prep"]["nudge"]["chat_ids_env"], "TELEGRAM_CHAT_ID")
        self.assertEqual(config["people"]["ceci"]["chat_ids_env"], "TELEGRAM_CECI_CHAT_ID")


if __name__ == "__main__":
    unittest.main()


class SpanishNudge(unittest.TestCase):
    """A Spanish family gets the morning nudge in Uruguayan Spanish (review round 2, issue #77)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.prep = Prep(self.agent, self.config, clock=Clock(datetime.datetime(2026, 10, 29, 9, 0, tzinfo=TZ)))

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_the_family_language_picks_the_nudge(self):
        self.assertTrue(self.prep.nudge_text().startswith("Good morning. About 47 days to the due date"))
        for text in ("ya compramos la silla del auto", "¿qué nos falta?", "dale"):
            self.agent.memory.add_message("telegram", "user", text)
        text = self.prep.nudge_text()
        self.assertTrue(text.startswith("Buen día. Unos 47 días para la fecha de parto, el 15 de diciembre (estimada)."), text)
        self.assertIn("Lo que sigue:", text)
        self.assertNotIn("Next up", text)

    def test_uruguayan_words_in_the_lists(self):
        hospital = [i for i in lists.seed_items() if i["list"] == "hospital_bag" and i["item_id"] == "ids"][0]
        self.assertIn("cédulas", hospital["text"])
        self.assertIn("mutualista", lists.text_in("es", {**hospital, "id": "ids"}))
        for item in lists.seed_items():
            self.assertIn(item["item_id"], lists.ES[item["list"]], item)
        self.assertNotRegex(json.dumps(lists.ES, ensure_ascii=False), r"\b(DNI|obra social|prepaga|biber[oó]n)\b")
