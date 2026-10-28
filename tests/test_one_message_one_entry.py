"""One message from a parent logs one entry, in English and in Spanish, for feeds, diapers and sleep.

The families bot once logged "mamadera 120 ml" as 2 feeds of 120 ml. The brain failed after the log tool ran, the
turn ended with no answer kept, and the next turn logged the same message again. These tests script the brain's
tool calls, so they run with no network: a brain that repeats a call, a brain that fails after logging, and the same
Telegram update delivered twice. The shared loop is also checked through the demo and a plain agent.
"""
import datetime
import unittest

from parenting_agent.agent import brain as brain_mod
from parenting_agent.agent.loop import Agent
from parenting_agent.agent.memory import LocalBabyLog, Memory
from parenting_agent.agent.tools import core_tools
from parenting_agent.bus import Bus
from parenting_agent.channels.messaging import Incoming
from parenting_agent.demo.app import DemoApp
from parenting_agent.families.bot import FamiliesBot
from parenting_agent.families.texts import EN, ES

import test_demo
from test_families import TZ, FakeTelegram, family_of, make
from test_families_spanish import onboard

FAIL = "fail"


def log(kind, details, ts=None):
    arguments = {"kind": kind, "details": details}
    if ts:
        arguments["ts"] = ts
    return {"name": "log_baby_event", "arguments": arguments}


class ScriptedBrain:
    """Plays one plan per parent message: each step is a list of tool calls, FAIL (the brain errors) or the answer."""
    name, model, destination = "claude", "scripted", "api.anthropic.com"

    def __init__(self, *plans):
        self.plans, self.steps, self.n = list(plans), [], 0

    def step(self, system, transcript, tools):
        if transcript[-1]["role"] == "user":
            self.steps = list(self.plans.pop(0)) if self.plans else ["OK."]
        step = self.steps.pop(0) if self.steps else "Logged."
        if step == FAIL:
            raise brain_mod.BrainError("timed out")
        if isinstance(step, str):
            return brain_mod.Reply(step, usage={"input_tokens": 10, "output_tokens": 5})
        calls = []
        for call in step:
            self.n += 1
            calls.append({"id": f"call-{self.n}", **call})
        return brain_mod.Reply("", calls, usage={"input_tokens": 10, "output_tokens": 5})


class Clock:
    def __init__(self):
        self.now = datetime.datetime(2026, 10, 28, 15, 0, tzinfo=TZ)

    def __call__(self):
        return self.now


BOTTLE = {"amount_ml": 120, "method": "bottle"}
REPEATS = {
    # A repeated call in the same reply, then the same feed again with an extra field in the next step.
    "feeding": [[log("feeding", BOTTLE), log("feeding", BOTTLE)], [log("feeding", {**BOTTLE, "type": "formula"})], "Logged."],
    "diaper": [[log("diaper", {"wet": True, "solid": True}), log("diaper", {"wet": True, "solid": True})], "Logged."],
    "sleep": [[log("sleep", {"start": "2026-10-28T13:00:00-03:00", "end": "2026-10-28T14:00:00-03:00"})],
              [log("sleep", {"start": "2026-10-28T13:00:00-03:00", "end": "2026-10-28T14:00:00-03:00", "nap": True})], "Logged."],
}
NOTES = {"en": {"feeding": "bottle 120 ml", "diaper": "wet and dirty diaper", "sleep": "she napped from 13 to 14"},
         "es": {"feeding": "mamadera 120 ml", "diaper": "pañal mojado y sucio", "sleep": "durmió la siesta de 13 a 14"}}
LANG_CODE = {"en": "en", "es": "es-UY"}


class Families(unittest.TestCase):
    def family(self, brain, lang, user=7):
        clock = Clock()
        app = make(self, brain=brain, clock=clock)
        onboard(app, user, LANG_CODE[lang])
        return app, app.family(family_of(app, user)), clock

    def test_one_message_logs_one_entry_in_both_languages(self):
        for lang in ("en", "es"):
            for kind, plan in REPEATS.items():
                with self.subTest(lang=lang, kind=kind):
                    app, f, _ = self.family(ScriptedBrain(plan), lang)
                    app.handle(7, 7, NOTES[lang][kind], "private", LANG_CODE[lang])
                    self.assertEqual(len(f.log.entries(kind)), 1)
                    self.assertEqual(len(f.log.entries()), 1)

    def test_a_brain_failure_after_logging_keeps_one_entry_and_says_so(self):
        for lang, table in (("en", EN), ("es", ES)):
            with self.subTest(lang=lang):
                brain = ScriptedBrain([[log("feeding", BOTTLE)], FAIL],
                                      [[log("diaper", {"wet": True})], "Logged."])
                app, f, _ = self.family(brain, lang)
                reply = app.handle(7, 7, NOTES[lang]["feeding"], "private", LANG_CODE[lang])[0][1]
                self.assertEqual(reply, table["SAVED_BEFORE_FAIL"].format(entries=table["ENTRY_FEEDING_ML"].format(ml="120")))
                last = f.memory.recent_messages(2)
                self.assertEqual([m["role"] for m in last], ["user", "assistant"])
                self.assertEqual(last[-1]["text"], reply)
                app.handle(7, 7, "pañal mojado" if lang == "es" else "wet diaper", "private", LANG_CODE[lang])
                self.assertEqual(len(f.log.entries("feeding")), 1)
                self.assertEqual(len(f.log.entries("diaper")), 1)

    def test_a_brain_failure_before_logging_is_kept_as_answered(self):
        app, f, _ = self.family(ScriptedBrain([FAIL]), "es")
        self.assertEqual(app.handle(7, 7, "mamadera 120 ml", "private", "es-UY")[0][1], ES["THINK_FAIL"])
        self.assertEqual([m["role"] for m in f.memory.recent_messages(2)], ["user", "assistant"])
        self.assertEqual(f.log.entries(), [])

    def test_a_second_real_feed_minutes_later_is_logged(self):
        for lang in ("en", "es"):
            with self.subTest(lang=lang):
                app, f, clock = self.family(ScriptedBrain([[log("feeding", BOTTLE)], "Logged."],
                                                          [[log("feeding", BOTTLE)], "Logged."]), lang)
                app.handle(7, 7, NOTES[lang]["feeding"], "private", LANG_CODE[lang])
                clock.now += datetime.timedelta(minutes=4)
                app.handle(7, 7, NOTES[lang]["feeding"], "private", LANG_CODE[lang])
                feeds = f.log.entries("feeding")
                self.assertEqual([e["details"]["amount_ml"] for e in feeds], [120.0, 120.0])

    def test_two_feeds_at_different_times_in_one_message_are_both_logged(self):
        brain = ScriptedBrain([[log("feeding", BOTTLE, "2026-10-28T11:00:00-03:00"),
                                log("feeding", BOTTLE, "2026-10-28T14:00:00-03:00")], "Logged."])
        app, f, _ = self.family(brain, "es")
        app.handle(7, 7, "mamadera de 120 a las 11 y otra de 120 a las 14", "private", "es-UY")
        self.assertEqual(len(f.log.entries("feeding")), 2)

    def test_sleep_start_and_wake_from_two_messages_log_one_sleep(self):
        brain = ScriptedBrain([[log("sleep", {"action": "start"}), log("sleep", {"action": "start"})], "OK."],
                              [[log("sleep", {"action": "end"}), log("sleep", {"action": "end"})], "OK."])
        app, f, clock = self.family(brain, "es")
        app.handle(7, 7, "se durmió", "private", "es-UY")
        clock.now += datetime.timedelta(minutes=40)
        app.handle(7, 7, "se despertó", "private", "es-UY")
        sleeps = f.log.entries("sleep")
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(sleeps[0]["details"]["duration_min"], 40)

    def test_the_same_telegram_update_twice_is_handled_once(self):
        brain = ScriptedBrain([[log("feeding", BOTTLE)], "Logged."], [[log("feeding", BOTTLE)], "Logged."])
        app, f, _ = self.family(brain, "es")
        update = Incoming(41, "7", "mamadera 120 ml", user_id="7", chat_type="private", language_code="es-UY")
        bot = FamiliesBot(app, FakeTelegram([[update], [update]]))
        self.assertEqual(bot.poll_once(), 1)
        self.assertEqual(bot.poll_once(), 0)
        self.assertEqual(len(f.log.entries("feeding")), 1)


class SharedLoop(unittest.TestCase):
    """The demo and Gonza's family agent use the same decide loop as the families bot."""

    def test_plain_agent_logs_one_entry_per_message(self):
        for kind, plan in REPEATS.items():
            with self.subTest(kind=kind):
                memory = Memory(":memory:")
                self.addCleanup(memory.close)
                baby_log = LocalBabyLog(memory)
                agent = Agent(Bus(None), memory, baby_log, core_tools(memory, baby_log, ["log_baby_event"]), ScriptedBrain(plan))
                agent.handle({"kind": "message", "channel": "test", "text": NOTES["en"][kind]})
                self.assertEqual(len(baby_log.entries(kind)), 1)

    def test_plain_agent_answers_with_what_it_kept_when_the_brain_fails(self):
        memory = Memory(":memory:")
        self.addCleanup(memory.close)
        baby_log = LocalBabyLog(memory)
        bus = Bus(None)
        replies = []
        bus.subscribe(replies.append, ["reply"])
        agent = Agent(bus, memory, baby_log, core_tools(memory, baby_log, ["log_baby_event"]),
                      ScriptedBrain([[log("feeding", BOTTLE)], FAIL]))
        agent.handle({"kind": "message", "channel": "test", "text": "bottle 120 ml"})
        self.assertEqual(replies[-1]["text"], "I could not finish my answer, but I logged a feed of 120 ml. No need to send it again.")
        self.assertEqual(len(baby_log.entries("feeding")), 1)

    def test_demo_logs_one_feed_per_message(self):
        app = DemoApp(test_demo.settings(), brain=ScriptedBrain(REPEATS["feeding"], [[log("feeding", BOTTLE)], FAIL]))
        self.addCleanup(app.close)
        before = len(app.visitor("v").baby_log.entries("feeding", limit=100_000))
        self.assertEqual(app.message("v", False, "bottle 120 ml")[0], 200)
        self.assertEqual(app.message("v", False, "bottle 120 ml")[0], 200)
        self.assertEqual(len(app.visitor("v").baby_log.entries("feeding", limit=100_000)), before + 2)


if __name__ == "__main__":
    unittest.main()
