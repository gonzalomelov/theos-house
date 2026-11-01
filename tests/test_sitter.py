"""Sitter handover (issue #16) on the simulated week. Offline: a scripted brain, a fake sitter messenger, no network."""
import datetime
import json
import statistics
import tempfile
import unittest
from pathlib import Path

from parenting_agent import cry_reason, sitter
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.brain import Reply
from parenting_agent.rhythm import patterns
from parenting_agent.rhythm.log import FixtureLog, parse

FIXTURE = Path(__file__).parent / "fixtures" / "simweek.json"
TZ = datetime.timezone(datetime.timedelta(hours=-3))
NOW = datetime.datetime(2026, 10, 26, 18, 40, tzinfo=TZ)
SITTER_CHAT = "555"


def week():
    return FixtureLog(FIXTURE).entries()


def make_brief(now=NOW, start="19:00", end="23:00", notes=None):
    a, b = sitter.resolve_window(start, end, now, TZ)
    return sitter.brief(week(), now, "Grandma", a, b, TZ, notes or sitter.load_notes(None)), a, b


def body(text):
    """The brief without its fixed health footer, the one place the words health and pediatrician are allowed."""
    return text.split("\n\nHealth\n")[0]


def by_hand(now):
    """The same facts recomputed straight from the fixture rows, without the module under test."""
    rows = sorted(json.loads(FIXTURE.read_text()), key=lambda e: e.get("start") or e["time"])
    past = [e for e in rows if parse(e.get("start") or e["time"]) <= now]
    feeds = [e for e in past if e["kind"] == "feeding"]
    changes = [e for e in past if e["kind"] == "change"]
    midnight = now.replace(hour=0, minute=0)
    today = [e for e in feeds if parse(e["start"]) >= midnight]
    starts = [parse(e["start"]) for e in feeds]
    gap = statistics.median([(b - a).total_seconds() / 60 for a, b in zip(starts, starts[1:])][-2:])
    return {"last_feed": parse(feeds[-1]["start"]).strftime("%H:%M"), "last_amount": feeds[-1].get("amount"),
            "next_feed": (starts[-1] + datetime.timedelta(minutes=gap)).strftime("%H:%M"), "gap": round(gap),
            "feeds_today": len(today), "ml_today": round(sum(e.get("amount") or 0 for e in today)),
            "last_change": parse(changes[-1]["time"]).strftime("%H:%M"),
            "last_dirty": parse([c for c in changes if c["solid"]][-1]["time"]).strftime("%H:%M")}


class ScriptBrain:
    """Answers from a list of steps: each step is a Reply or a function of the transcript that returns one."""
    name, model, destination = "script", "script", "none (local)"

    def __init__(self, steps):
        self.steps, self.calls = list(steps), 0

    def step(self, system, transcript, tools):
        self.calls += 1
        step = self.steps.pop(0) if self.steps else Reply("OK.")
        return step(transcript) if callable(step) else step


class NoBrain:
    name, model, destination = "none", "none", "none"

    def step(self, *args):
        raise AssertionError("the brain must not be called")


class FakeMessenger:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        return len(self.sent)


def call(name, **arguments):
    return Reply(tool_calls=[{"id": f"c-{name}", "name": name, "arguments": arguments}])


class BriefFromTheLog(unittest.TestCase):
    def test_numbers_match_the_log_at_18_40(self):
        made, _, _ = make_brief()
        text = made["text"]
        print("\n" + text)
        self.assertIn("Last feed at 16:53, breastfed (right side), 31 min.", text)
        self.assertIn("Next feed expected around 19:22. He has been eating about every 2 h 29 min.", text)
        self.assertIn("Today so far: 7 feeds, 170 ml from bottles.", text)
        self.assertIn("He has been asleep since 17:50.", text)
        self.assertIn("Last diaper at 17:28, wet. Last dirty one at 12:19.", text)
        self.assertIn("Bath at 18:35.", text)
        self.assertIn("thank you for looking after Theo from 19:00 to 23:00", text)

    def test_numbers_match_a_hand_count_on_other_days(self):
        for now in (datetime.datetime(2026, 10, 23, 15, 0, tzinfo=TZ), datetime.datetime(2026, 10, 24, 20, 30, tzinfo=TZ),
                    NOW):
            f = sitter.facts(week(), now, now, now + datetime.timedelta(hours=3), TZ)
            hand = by_hand(now)
            self.assertEqual(patterns.hhmm(f["last_feed"]["at"]), hand["last_feed"], now)
            self.assertEqual(f["last_feed"]["amount_ml"], hand["last_amount"], now)
            self.assertEqual(patterns.hhmm(f["next_feed"]["at"]), hand["next_feed"], now)
            self.assertEqual(f["next_feed"]["gap_min"], hand["gap"], now)
            self.assertEqual(f["today"], {"feeds": hand["feeds_today"], "bottle_ml": hand["ml_today"]}, now)
            self.assertEqual(patterns.hhmm(f["last_diaper"]["at"]), hand["last_change"], now)
            self.assertEqual(patterns.hhmm(f["last_dirty"]), hand["last_dirty"], now)

    def test_usual_evening_sleep_is_the_median_first_sleep_in_the_window(self):
        made, a, b = make_brief()
        usual = made["facts"]["usual_sleep"]
        firsts = []
        for day in range(20, 26):
            start = datetime.datetime(2026, 10, day, 19, 0, tzinfo=TZ)
            sleeps = [e for e in week() if e["kind"] == "sleep" and start <= parse(e["start"]) < start + datetime.timedelta(hours=4)]
            if sleeps:
                firsts.append(min(parse(e["start"]) for e in sleeps).strftime("%H:%M"))
        self.assertEqual(usual["days"], len(firsts))
        self.assertEqual(patterns.hhmm(usual["at"]), sorted(firsts)[len(firsts) // 2])
        self.assertIn(f"usually falls asleep around {patterns.hhmm(usual['at'])}", made["text"])

    def test_where_things_are_and_contacts_come_from_the_handover_block_only(self):
        made, _, _ = make_brief()
        self.assertIn("Diapers and wipes: the changing table in his room, top drawer.", made["text"])
        self.assertIn("Gonza: +598 9X XXX XXX.", made["text"])
        self.assertNotIn("stays with the parents", made["text"])

    def test_window_past_midnight_ends_the_next_day(self):
        a, b = sitter.resolve_window("21:00", "01:00", NOW, TZ)
        self.assertEqual((b - a), datetime.timedelta(hours=4))


class NoMedicalContent(unittest.TestCase):
    def test_brief_body_states_facts_only(self):
        for now in (NOW, datetime.datetime(2026, 10, 23, 9, 30, tzinfo=TZ), datetime.datetime(2026, 10, 25, 22, 0, tzinfo=TZ)):
            made, _, _ = make_brief(now, patterns.hhmm(now), "23:59")
            for line in body(made["text"]).splitlines():
                self.assertTrue(sitter.safe_line(line), line)
            self.assertIsNone(sitter.DOSAGE_RE.search(made["text"]), made["text"])
            self.assertIn("call us first. If you cannot reach us, call his pediatrician", made["text"])

    def test_medicine_lines_in_the_family_notes_are_left_out(self):
        notes = sitter.load_notes(None)
        notes["where"] += ["His drops are in the fridge, 2 drops at 20:00", "Paracetamol dose: 2.5 ml if he has a fever",
                           "Burp cloths: on the sofa"]
        made, _, _ = make_brief(notes=notes)
        self.assertEqual(len(made["dropped"]), 2)
        self.assertNotIn("drops", made["text"])
        self.assertNotIn("Paracetamol", made["text"])
        self.assertIn("Burp cloths: on the sofa.", made["text"])

    def test_guard_catches_doses_and_advice(self):
        for text in ["Give him 2.5 ml of paracetamol.", "The dose is on the box.", "You should wake him.",
                     "Call the doctor if he has a fever.", "His medicine is in the fridge."]:
            self.assertFalse(sitter.safe_line(text), text)

    def test_guest_health_question_gets_the_fixed_answer_without_the_brain(self):
        session = guest_session(NoBrain())
        reply = session.ask("He feels warm, how much paracetamol can I give him?")
        self.assertIn("call the parents", reply)
        self.assertIsNone(sitter.DOSAGE_RE.search(reply))
        self.assertTrue(cry_reason.no_medical(reply.replace("pediatrician", "")))
        self.assertEqual(len(session.health_questions), 1)


class FakeLog:
    def __init__(self):
        self.added = []

    def add(self, kind, details, ts=None):
        self.added.append((kind, details))
        return {"kind": kind, "details": details}

    def summary(self, since=None):
        return {"feedings": {"count": 7}}


class Bus:
    def __init__(self):
        self.events = []

    def publish(self, kind, **fields):
        self.events.append({"kind": kind, **fields})
        return self.events[-1]


def guest_session(brain, now=datetime.datetime(2026, 10, 26, 20, 0, tzinfo=TZ), log=None):
    a, b = sitter.resolve_window("19:00", "23:00", NOW, TZ)
    clock = {"now": now}
    session = sitter.GuestSession(Bus(), log or FakeLog(), brain, "Grandma", a, b, "the handover text", "911", "Theo",
                                  lambda: clock["now"])
    session.clock_box = clock
    return session


class GuestRole(unittest.TestCase):
    def test_guest_sees_only_its_tools(self):
        session = guest_session(NoBrain())
        self.assertEqual(sorted(session.tools.names()), sorted(sitter.GUEST_TOOLS))
        self.assertEqual(sorted(s["name"] for s in session.tools.specs()), sorted(sitter.GUEST_TOOLS))

    def test_forbidden_tools_never_run(self):
        ran = []
        session = guest_session(NoBrain())
        for name in ("remember", "log_baby_event", "read_baby_log", "start_changing_table", "house_action",
                     "send_handover_to_sitter", "sitter_handover"):
            status, _ = session.tools.run(name, {})
            self.assertEqual(status, "denied", name)
        # Even a tool slipped into the guest's set by mistake is refused by name.
        session.tools.add(sitter.Tool("remember", "x", sitter.schema({}), lambda: ran.append(1)))
        self.assertEqual(session.tools.run("remember", {})[0], "denied")
        self.assertEqual(ran, [])

    def test_a_brain_asking_for_forbidden_tools_is_refused(self):
        log = FakeLog()
        brain = ScriptBrain([call("remember", key="wifi", value="x"), call("log_baby_event", kind="sleep", details={}),
                             Reply("I can't do that.")])
        session = guest_session(brain, log=log)
        session.ask("Remember the wifi password and log that he is asleep")
        self.assertEqual(session.denied, ["remember", "log_baby_event"])
        self.assertEqual(log.added, [])
        self.assertEqual([e["name"] for e in session.bus.events if e["kind"] == "guest_denied"], ["remember", "log_baby_event"])

    def test_guest_logs_feeds_and_diapers_inside_the_window(self):
        log = FakeLog()
        brain = ScriptBrain([call("log_feed", amount_ml=90, method="bottle"), Reply("Logged."),
                             call("log_diaper", wet=True, solid=True), Reply("Logged.")])
        session = guest_session(brain, log=log)
        session.ask("He drank 90 ml")
        session.ask("Dirty diaper")
        self.assertEqual(log.added, [("feeding", {"method": "bottle", "type": "formula", "amount_ml": 90.0}),
                                     ("diaper", {"wet": True, "solid": True})])

    def test_nothing_runs_outside_the_window(self):
        log = FakeLog()
        session = guest_session(NoBrain(), now=datetime.datetime(2026, 10, 26, 23, 0, tzinfo=TZ), log=log)
        self.assertIn("ended", session.ask("He drank 90 ml"))
        self.assertEqual(session.tools.run("log_feed", {"amount_ml": 90})[0], "error")
        self.assertEqual(log.added, [])
        early = guest_session(NoBrain(), now=datetime.datetime(2026, 10, 26, 18, 0, tzinfo=TZ))
        self.assertFalse(early.active())


def make_agent(tmp, allowed_extra=()):
    config = config_mod.load()
    config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"},
                   "rhythm": {"source": "fixture", "fixture": str(FIXTURE)},
                   "sitter": {"family_notes": "/nonexistent", "parent_channel": "telegram"}})
    config["allowed_tools"] = config["allowed_tools"] + ["sitter_handover", *allowed_extra]
    agent = build(config)
    replies = []
    agent.bus.subscribe(replies.append, ["reply", "ask_parent"])
    return agent, config, replies


def message(agent, text, channel="telegram"):
    agent.handle({"kind": "message", "channel": channel, "text": text})


class ParentDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config, self.replies = make_agent(self.tmp.name)
        self.clock = {"now": NOW}
        self.messenger = FakeMessenger()
        self.plugin = sitter.SitterHandover(self.agent, self.config, clock=lambda: self.clock["now"],
                                            sitter_messenger=self.messenger, contacts={"Grandma": SITTER_CHAT})

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def ask_for_brief(self):
        self.agent.brain = ScriptBrain([call("sitter_handover", sitter="Grandma", start="19:00", end="23:00"),
                                        Reply("Draft is in your chat.")])
        message(self.agent, "my mom is watching him tonight from 19:00 to 23:00")

    def test_draft_goes_to_the_parent_and_never_to_the_sitter(self):
        self.ask_for_brief()
        drafts = [r for r in self.replies if r["kind"] == "reply" and "Draft handover for Grandma" in r["text"]]
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["channel"], "telegram")
        self.assertIn("Next feed expected around 19:22", drafts[0]["text"])
        self.assertEqual(self.messenger.sent, [])

    def test_send_to_sitter_needs_a_yes_every_time(self):
        self.ask_for_brief()
        self.agent.brain = ScriptBrain([call(sitter.SEND_TOOL), Reply("Asked.")])
        message(self.agent, "send it to her")
        self.assertEqual(self.messenger.sent, [])
        self.assertTrue(any(r["kind"] == "ask_parent" and r["name"] == sitter.SEND_TOOL for r in self.replies))
        message(self.agent, "yes")
        self.assertEqual(len(self.messenger.sent), 1)
        self.assertEqual(self.messenger.sent[0][0], SITTER_CHAT)
        self.agent.brain = ScriptBrain([call(sitter.SEND_TOOL), Reply("Asked.")])
        message(self.agent, "send it again")
        self.assertEqual(len(self.messenger.sent), 1)
        message(self.agent, "yes")
        self.assertEqual(len(self.messenger.sent), 2)

    def test_send_tool_is_taken_off_the_allowed_list(self):
        tmp = tempfile.TemporaryDirectory()
        agent, config, _ = make_agent(tmp.name, allowed_extra=[sitter.SEND_TOOL])
        sitter.SitterHandover(agent, config, clock=lambda: NOW)
        self.assertNotIn(sitter.SEND_TOOL, agent.tools.allowed)
        self.assertEqual(agent.tools.run(sitter.SEND_TOOL, {})[0], "ask_parent")
        agent.close()
        tmp.cleanup()

    def test_without_a_sitter_adapter_nothing_is_sent(self):
        plugin = sitter.SitterHandover(self.agent, self.config, clock=lambda: NOW)
        self.assertIn("no handover draft", plugin.send_to_sitter())
        plugin.prepare("Grandma", "19:00", "23:00")
        self.assertIn("not switched on", plugin.send_to_sitter())
        # Through the agent too: the yes runs the tool outside the loop's error handling, so it must not raise.
        self.agent.tools.items[sitter.SEND_TOOL] = sitter.Tool(sitter.SEND_TOOL, "", sitter.schema({}), plugin.send_to_sitter)
        self.agent.brain = ScriptBrain([call(sitter.SEND_TOOL), Reply("Asked.")])
        message(self.agent, "send it to her")
        message(self.agent, "yes")
        self.assertIn("not switched on", self.replies[-1]["text"])
        self.assertEqual(self.messenger.sent, [])

    def test_window_ends_and_the_parents_get_a_summary(self):
        self.ask_for_brief()
        session = self.plugin.session
        self.clock["now"] = datetime.datetime(2026, 10, 26, 20, 0, tzinfo=TZ)
        session.brain = ScriptBrain([call("log_feed", amount_ml=100), Reply("Logged."),
                                     call("log_diaper", wet=True, solid=False), Reply("Logged."),
                                     call("baby_summary"), Reply("7 feeds today.")])
        session.ask("He drank 100 ml")
        session.ask("wet diaper")
        session.ask("How many feeds today?")
        session.ask("Should I give him medicine for his cough?")
        self.assertIsNone(self.plugin.tick(datetime.datetime(2026, 10, 26, 22, 59, tzinfo=TZ)))
        self.clock["now"] = datetime.datetime(2026, 10, 26, 23, 0, tzinfo=TZ)
        text = self.plugin.tick(self.clock["now"])
        print("\n" + text)
        self.assertIn("Grandma looked after Theo from 19:00 to 23:00.", text)
        self.assertIn("Logged: 1 feed (100 ml), 1 diaper: 1 wet only.", text)
        self.assertIn("Grandma asked 4 questions.", text)
        self.assertIn("I told Grandma to call you", text)
        summaries = [r for r in self.replies if r["kind"] == "reply" and r["text"] == text]
        self.assertEqual(summaries[0]["channel"], "telegram")
        self.assertIsNone(self.plugin.tick(self.clock["now"]))
        self.assertIn("ended", session.ask("He drank 50 ml"))
        self.assertEqual(self.messenger.sent, [])


if __name__ == "__main__":
    unittest.main()
