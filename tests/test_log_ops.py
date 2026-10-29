"""Muse decides the log operations (issue #77, parenting_agent/agent/log_ops.py), with a scripted brain."""
import datetime
import tempfile
import unittest
import zoneinfo

from parenting_agent.agent import log_ops
from parenting_agent.agent import memory as memory_mod
from parenting_agent.agent.brain import Reply
from parenting_agent.families import settings as settings_mod
from parenting_agent.families.service import Families
from parenting_agent.families.store import visitor_id

TZ = zoneinfo.ZoneInfo("America/Montevideo")
PARENT = 7001


class Scripted:
    """Answers each call with the next queued tool call, and keeps what it was shown."""
    name, model, destination = "scripted", "scripted-muse", "none"

    def __init__(self):
        self.queue, self.seen = [], []

    def step(self, system, transcript, tools):
        self.seen.append({"system": system, "text": transcript[-1]["text"], "tools": [t["name"] for t in tools]})
        name, arguments = self.queue.pop(0)
        return Reply("", [{"id": str(len(self.seen)), "name": name, "arguments": arguments}],
                     {"input_tokens": 10, "output_tokens": 10})


class LogOps(unittest.TestCase):
    def setUp(self):
        self.brain = Scripted()
        self.clock = {"now": datetime.datetime(2026, 10, 29, 0, 10, tzinfo=TZ)}
        self.saved_now = memory_mod.now
        memory_mod.now = lambda: self.clock["now"].isoformat(timespec="seconds")
        env = {"PA_FAMILIES_BRAIN": "fake", "PA_FAMILIES_DATA_DIR": tempfile.mkdtemp(), "PA_FAMILIES_LOG_MODE": self.mode}
        self.app = Families(settings_mod.load(env), brain=self.brain, clock=lambda: self.clock["now"])
        code = self.app.store.create_invite(internal=True)
        for text in (f"/start {code}", "Lola", "2/9/2026", "si"):
            self.app.handle(PARENT, PARENT, text, "private", "es-UY")
        self.fam = self.app.family(self.app.store.parent(visitor_id(PARENT))["family_id"])
        self.fam.agent.brain.real = self.brain

    mode = "ops"

    def tearDown(self):
        memory_mod.now = self.saved_now
        self.app.close()

    def say(self, hhmm, text, *calls, day=29):
        hour, minute = (int(x) for x in hhmm.split(":"))
        self.clock["now"] = self.clock["now"].replace(day=day, hour=hour, minute=minute)
        self.brain.queue += list(calls)
        return " ".join(t for _, t in self.app.handle(PARENT, PARENT, text, "private", "es-UY"))

    def log(self):
        return self.fam.log.entries(None, None, 100)

    @staticmethod
    def ops(*ops, reply=""):
        return "log_ops", {"ops": list(ops), "reply": reply}


class OpsMode(LogOps):
    def test_ounces_are_30_ml_and_the_reply_comes_from_the_log(self):
        reply = self.say("00:30", "3 onzas y media", self.ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_oz": 3.5}))
        self.assertEqual(self.log()[0]["details"]["amount_ml"], 105.0)
        self.assertIn("105 ml", reply)

    def test_a_named_clock_time_is_the_latest_such_time_not_after_now(self):
        self.say("00:50", "por fin frita, desde las 12 y 40", self.ops({"op": "sleep_start", "at": "00:40"}))
        self.assertEqual(self.fam.fact("_sleep_started")[:16], "2026-10-29T00:40")
        self.say("03:20", "she woke up at 3:10", self.ops({"op": "sleep_end", "at": "03:10"}))
        sleep = self.log()[-1]
        self.assertEqual((sleep["ts"][11:16], sleep["details"]["start"][11:16]), ("03:10", "00:40"))

    def test_a_time_after_now_is_yesterday(self):
        self.say("00:10", "le di 90 a las 23:50", self.ops({"op": "add", "kind": "feeding", "amount_ml": 90, "at": "23:50"}))
        self.assertEqual(self.log()[0]["ts"][:16], "2026-10-28T23:50")

    def test_edit_and_delete_by_id(self):
        self.say("07:15", "3 onzas de materna", self.ops({"op": "add", "kind": "feeding", "amount_oz": 3, "type": "breast milk"}))
        entry = self.log()[0]
        reply = self.say("07:17", "eran 4 onzas, no 3", self.ops({"op": "edit", "id": entry["id"], "amount_oz": 4}))
        self.assertEqual(self.log()[0]["details"]["amount_ml"], 120.0)
        self.assertIn("90 ml → 120 ml", reply)
        reply = self.say("07:20", "borrala", self.ops({"op": "delete", "id": entry["id"]}))
        self.assertEqual(self.log(), [])
        self.assertIn("Borré", reply)

    def test_a_past_nap_is_one_sleep(self):
        self.say("11:10", "durmio la siesta de 10 a 11", self.ops({"op": "add", "kind": "sleep", "start": "10:00", "end": "11:00"}))
        sleep = self.log()[0]
        self.assertEqual((sleep["ts"][11:16], sleep["details"]["start"][11:16], sleep["details"]["duration_min"]), ("11:00", "10:00", 60))

    def test_a_value_out_of_bounds_is_asked_about_and_nothing_is_logged(self):
        reply = self.say("01:00", "9000", self.ops({"op": "add", "kind": "feeding", "amount_ml": 9000}))
        self.assertEqual(self.log(), [])
        self.assertIn("9000 ml", reply)

    def test_no_ops_sends_the_brains_reply(self):
        reply = self.say("01:00", "q sueño tengo", self.ops(reply="Fuerza, ya va a pasar."))
        self.assertEqual(self.log(), [])
        self.assertEqual(reply, "Fuerza, ya va a pasar.")

    def test_the_brain_sees_the_log_with_ids_and_the_open_sleep(self):
        self.say("00:30", "110 de formula", self.ops({"op": "add", "kind": "feeding", "amount_ml": 110, "type": "formula"}))
        self.say("00:50", "se durmio", self.ops({"op": "sleep_start"}))
        self.say("00:55", "cuanto tomo?", self.ops(reply="110 ml."))
        seen = self.brain.seen[-1]["text"]
        self.assertIn("#1 Thu 00:30 feeding bottle 110 ml formula", seen)
        self.assertIn("asleep since Thu 00:50", seen)
        self.assertIn("Newest message from the parent, at 00:55: cuanto tomo?", seen)

    def test_an_emergency_never_reaches_the_brain(self):
        reply = self.say("01:00", "no respira, esta azul")
        self.assertEqual(self.brain.seen, [])
        self.assertIn("911", reply)

    def test_without_a_log_ops_answer_the_guarded_path_logs(self):
        # A brain that never answers log_ops, even when asked once more: the message still goes through the guarded loop.
        self.brain.queue.append(("log_baby_event", {"kind": "feeding", "details": {"method": "bottle", "amount_ml": 80}}))
        self.brain.queue.append(("log_baby_event", {"kind": "feeding", "details": {"method": "bottle", "amount_ml": 80}}))
        self.brain.queue.append(("log_baby_event", {"kind": "feeding", "details": {"method": "bottle", "amount_ml": 80}}))
        self.clock["now"] = self.clock["now"].replace(hour=2)
        real = self.brain.step

        def step(system, transcript, tools):
            if not self.brain.queue:
                return Reply("Anoté.", [], {"input_tokens": 1, "output_tokens": 1})
            return real(system, transcript, tools)
        self.brain.step = step
        self.app.handle(PARENT, PARENT, "le di 80 de mamadera", "private", "es-UY")
        self.assertEqual([e["details"].get("amount_ml") for e in self.log()], [80.0])


class OpsRetry(LogOps):
    def test_an_answer_without_log_ops_is_asked_once_more(self):
        self.brain.queue.append(("next_feed", {}))
        reply = self.say("11:20", "un cuarto de hora de pecho",
                         self.ops({"op": "add", "kind": "feeding", "method": "breast", "duration_min": 15}))
        self.assertEqual(self.log()[0]["details"]["duration_min"], 15)
        self.assertIn("Your last answer had no log_ops call", self.brain.seen[1]["text"])
        self.assertIn("15 min", reply)

    def test_no_em_dash_in_a_reply(self):
        reply = self.say("01:00", "hola", self.ops(reply="Hola — todo bien"))
        self.assertEqual(reply, "Hola, todo bien")


class OpsSpendCap(unittest.TestCase):
    def test_after_the_cap_the_free_rules_still_log(self):
        from test_families import CountingBrain, family_of, make, onboard
        brain = CountingBrain(tokens=(1_000_000, 0))  # $0.10 a call at Haiku prices
        app = make(self, brain=brain, PA_FAMILIES_BRAIN="claude", PA_FAMILIES_FAMILY_USD="0.15")
        onboard(app, "111")
        app.handle("111", "111", "bottle 100 ml")  # two calls: no log_ops back, then the guarded loop, now capped
        app.handle("111", "111", "bottle 130 ml")
        self.assertEqual(brain.calls, 2)
        self.assertIn(130.0, [e["details"].get("amount_ml") for e in app.family(family_of(app, "111")).log.entries("feeding")])


class OpsVerifyMode(LogOps):
    mode = "ops-verify"

    def test_the_verifier_corrects_the_proposal(self):
        self.say("00:30", "le prepare 120 y tomo la mitad",
                 self.ops({"op": "add", "kind": "feeding", "amount_ml": 120}),
                 ("verdict", {"ok": False, "ops": [{"op": "add", "kind": "feeding", "amount_ml": 60}], "reason": "half"}))
        self.assertEqual(self.log()[0]["details"]["amount_ml"], 60.0)
        self.assertEqual(self.brain.seen[1]["tools"], ["verdict"])

    def test_the_verifier_keeps_a_right_proposal(self):
        self.say("00:30", "pañal con pis", self.ops({"op": "add", "kind": "diaper", "wet": True}), ("verdict", {"ok": True}))
        self.assertEqual(len(self.log()), 1)


class GuardsMode(LogOps):
    mode = "guards"

    def test_guards_mode_never_calls_log_ops(self):
        self.brain.queue.append(("log_baby_event", {"kind": "diaper", "details": {"wet": True}}))
        real = self.brain.step

        def step(system, transcript, tools):
            if not self.brain.queue:
                return Reply("Listo.", [], {"input_tokens": 1, "output_tokens": 1})
            return real(system, transcript, tools)
        self.brain.step = step
        self.app.handle(PARENT, PARENT, "pañal con pis", "private", "es-UY")
        self.assertNotIn("log_ops", self.brain.seen[0]["tools"])


class Settings(unittest.TestCase):
    def test_ops_is_the_default_and_guards_can_be_chosen(self):
        self.assertEqual(settings_mod.load({})["log_mode"], "ops")
        self.assertEqual(settings_mod.load({"PA_FAMILIES_LOG_MODE": "guards"})["log_mode"], "guards")
        with self.assertRaises(ValueError):
            settings_mod.load({"PA_FAMILIES_LOG_MODE": "nope"})

    def test_clock_and_amount(self):
        now = datetime.datetime(2026, 10, 29, 0, 50, tzinfo=TZ)
        self.assertEqual(log_ops.clock("00:40", now).strftime("%d %H:%M"), "29 00:40")
        self.assertEqual(log_ops.clock("12:40", now).strftime("%d %H:%M"), "28 12:40")
        self.assertIsNone(log_ops.clock("25:00", now))
        self.assertEqual(log_ops.amount({"amount_oz": 2.5}), 75.0)
        self.assertEqual(log_ops.amount({"amount_ml": 88.6}), 89.0)


if __name__ == "__main__":
    unittest.main()
