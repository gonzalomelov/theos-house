"""Two parents on the family agent (Oct 30): Ceci's questions, the night rota by name, and pushes to the right parent.

Offline: a scripted brain, a fake Telegram messenger and the night rota over a fixed log. Chat ids are made up.
"""
import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

from parenting_agent.agent import build, rules
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.people import People
from parenting_agent.channels.push import FamilyPush, recipients
from parenting_agent.channels.router import Router
from parenting_agent.channels.telegram import Telegram
from parenting_agent.night_feed import NightFeed
from parenting_agent.prep import Prep
from parenting_agent.reminders import Reminders
from tests.test_channels import FakeMessenger
from tests.test_home_automations import Clock, ListLog
from test_one_message_one_entry import ScriptedBrain

TZ = datetime.timezone(datetime.timedelta(hours=-3))
GONZA, CECI = "5001", "5002"
ENV = {"TELEGRAM_CHAT_ID": GONZA, "TELEGRAM_CECI_CHAT_ID": CECI}
PEOPLE = {"gonza": {"name": "Gonza", "rota": "Parent A", "chat_ids_env": "TELEGRAM_CHAT_ID"},
          "ceci": {"name": "Ceci", "rota": "Parent B", "chat_ids_env": "TELEGRAM_CECI_CHAT_ID"}}
# What Muse answered Ceci one morning, reproduced locally on a copy of the agent's memory.
MUSE_0723 = "Hola Ceci. No tengo registro de quién está de turno esta noche. Si me decís, lo recuerdo para la próxima."


def at(day, hh, mm):
    return datetime.datetime(2026, 10, day, hh, mm, tzinfo=TZ)


def wakeup(day, hh, who, n):
    return {"kind": "note", "time": at(day, hh, 0).isoformat(), "note": f"Night wake-up handled by {who}", "ref": f"note#{n}"}


class Family:
    """The family agent as on the Vostro: Telegram with both parents, the night feed, reminders and the family push."""

    def __init__(self, tmp, now, rows=(), brain=None, plugins=("night", "reminders", "push"), extra=None):
        self.env = mock.patch.dict(os.environ, ENV)
        self.env.start()
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "house": {},
                       "plugins": [], "people": PEOPLE,
                       "telegram": {"allowed_chat_ids_env": "TELEGRAM_CHAT_ID"}, **(extra or {})})
        config["allowed_tools"] = config["allowed_tools"] + ["night_rota", "remind_me"]
        self.config = config
        self.agent = build(config)
        if brain is not None:
            self.agent.brain = brain
        self.clock = Clock(now)
        self.messenger = FakeMessenger()
        self.telegram = Telegram(self.agent, config, messenger=self.messenger)
        self.agent.plugins = [self.telegram]
        if "night" in plugins:
            self.night = NightFeed(self.agent, config, log=ListLog(list(rows)), clock=self.clock)
            self.agent.plugins.append(self.night)
        if "reminders" in plugins:
            self.reminders = Reminders(self.agent, config, clock=self.clock)
            self.agent.plugins.append(self.reminders)
        if "push" in plugins:
            self.push = FamilyPush(self.agent, config, clock=self.clock)
            self.agent.plugins.append(self.push)

    def say(self, chat, text):
        person = self.telegram.person_of(chat)
        event = self.agent.bus.publish("message", channel="telegram", text=text, chat_id=chat, person=person, voice=False)
        self.agent.current_event = event
        try:
            self.agent.handle(event)
        finally:
            self.agent.current_event = None
            self.agent.turn(event, answered=True)

    def sent_to(self, chat):
        return [text for c, text in self.messenger.sent if c == chat]

    def close(self):
        self.agent.close()
        self.env.stop()


class CeciQuestionBugA(unittest.TestCase):
    """"Test: hola, soy Ceci. ¿Quién está de turno esta noche?" got "No mandé nada, no se hizo nada"."""

    def test_an_offer_on_a_condition_is_no_claim(self):
        self.assertEqual(rules.unmet_claims(MUSE_0723, set()), set())
        self.assertEqual(rules.unmet_claims("Si me decís quién queda, lo recuerdo.", set()), set())
        self.assertEqual(rules.unmet_claims("If you tell me, I'll remember it.", set()), set())

    def test_a_claim_without_a_condition_still_needs_its_tool(self):
        self.assertEqual(rules.unmet_claims("Listo, lo recuerdo.", set()), {"lo recuerdo"})
        self.assertEqual(rules.unmet_claims("I told her.", set()), {"told"})
        self.assertEqual(rules.unmet_claims("Listo, lo recuerdo.", {"remind_me"}), set())

    def test_the_test_prefix_is_for_the_scorer_only(self):
        self.assertTrue(rules.is_test("Test: hola"))
        self.assertTrue(rules.is_test("  test:hola"))
        self.assertFalse(rules.is_test("Testing the bottle"))
        self.assertEqual(rules.without_test_prefix("Test: hola, soy Ceci."), "hola, soy Ceci.")
        self.assertEqual(rules.without_test_prefix("Test:"), "Test:")

    def test_muse_answer_of_0723_reaches_ceci_as_it_was_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = ScriptedBrain([MUSE_0723])
            family = Family(tmp, at(30, 7, 23), brain=brain, plugins=())
            try:
                family.say(CECI, "Test: hola, soy Ceci. ¿Cómo va la lista de compras?")
                self.assertEqual(family.sent_to(CECI), [MUSE_0723])
                guards = [e["status"] for e in family.agent.bus.history if e["kind"] == "guard"]
                self.assertNotIn("claimed_action", guards)
                turn = [e for e in family.agent.bus.history if e["kind"] == "turn"][-1]
                self.assertEqual((turn["person"], turn["test"]), ("ceci", True))
            finally:
                family.close()

    def test_the_brain_sees_who_spoke_and_never_the_test_marker(self):
        seen = []

        class Recording(ScriptedBrain):
            def step(self, system, transcript, tools):
                seen.append(transcript[-1]["text"])
                return super().step(system, transcript, tools)

        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 7, 23), brain=Recording(["Hola Ceci."]), plugins=())
            try:
                family.say(CECI, "Test: hola, ¿cómo va la lista?")
                self.assertIn("Ceci: hola, ¿cómo va la lista?", seen[0])
                self.assertNotIn("Test:", seen[0])
            finally:
                family.close()


class NightRotaBugB(unittest.TestCase):
    """"¿Quién está de turno esta noche?" got "no tengo registrado quién está de turno esta noche"."""

    def ask(self, rows, text, chat=CECI, now=None, plan=None):
        with tempfile.TemporaryDirectory() as tmp:
            brain = ScriptedBrain(["no tengo registrado quién está de turno esta noche"])
            family = Family(tmp, now or at(30, 7, 23), rows, brain=brain, plugins=("night",))
            family.night.plan = plan
            try:
                family.say(chat, text)
                return family.sent_to(chat), family
            finally:
                family.close()

    def test_no_wakeup_in_the_log_yet_starts_with_gonza_by_name(self):
        sent, _ = self.ask([], "¿Quién está de turno esta noche?")
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith("Esta noche está de turno Gonza."), sent[0])
        self.assertIn("se levantó menos veces", sent[0])
        self.assertNotIn("Parent", sent[0])

    def test_the_rota_counts_wakeups_by_label_or_by_name(self):
        rows = [wakeup(27, 2, "Parent A", 1), wakeup(28, 3, "Gonza", 2), wakeup(29, 2, "Ceci", 3)]
        sent, _ = self.ask(rows, "Test: ¿Quién está de turno esta noche?")
        self.assertTrue(sent[0].startswith("Esta noche está de turno Ceci."), sent[0])
        self.assertIn("Gonza 2, Ceci 1", sent[0])

    def test_english_and_the_plan_that_changed_it(self):
        sent, _ = self.ask([], "Who is on duty tonight?", chat=GONZA, plan={"prewarm": None, "on_duty": "Parent B"})
        self.assertTrue(sent[0].startswith("Ceci is on duty tonight."), sent[0])
        self.assertIn("asked to sleep", sent[0])

    def test_what_counts_as_the_rota_question(self):
        for text in ("¿Quién está de turno esta noche?", "quien esta de turno hoy?", "Who is on duty tonight?",
                     "¿A quién le toca levantarse?", "Test: hola, soy Ceci. ¿Quién está de turno esta noche?"):
            self.assertTrue(rules.asks_on_duty(text), text)
        for text in ("¿Cuál es la farmacia de turno?", "Who is the doctor on duty tonight?", "Gonza está de turno.",
                     "When was the last feed?"):
            self.assertFalse(rules.asks_on_duty(text), text)

    def test_answered_without_the_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = ScriptedBrain(["should never be said"])
            family = Family(tmp, at(30, 7, 23), brain=brain, plugins=("night",))
            try:
                family.say(CECI, "¿Quién está de turno esta noche?")
                self.assertEqual([e for e in family.agent.bus.history if e["kind"] == "brain_call"], [])
                self.assertNotIn("should never be said", " ".join(family.sent_to(CECI)))
            finally:
                family.close()

    def test_night_rota_tool_for_other_wordings(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 7, 23), plugins=("night",))
            try:
                status, result = family.agent.tools.run("night_rota", {})
                self.assertEqual(status, "ran")
                self.assertTrue(result.startswith("Gonza is on duty tonight."))
            finally:
                family.close()


class Recipients(unittest.TestCase):
    people = People(PEOPLE)

    def to(self, event, night=False, on_duty="Parent B"):
        return recipients(event, self.people, on_duty, night, "gonza")[0]

    def test_routing_table(self):
        both = ["gonza", "ceci"]
        self.assertEqual(self.to({"source": "day-engine", "routine": "morning_brief"}), both)
        self.assertEqual(self.to({"source": "day-engine", "routine": "supplies"}, night=True), both)
        self.assertEqual(self.to({"source": "house-brain", "routine": "tonight", "to": "both"}), both)
        self.assertEqual(self.to({"source": "night_feed", "parent": "Parent B"}, night=True, on_duty="Parent A"), ["ceci"])
        self.assertEqual(self.to({"source": "house-brain", "routine": "plan_message", "to": "Parent A"}), ["gonza"])
        self.assertEqual(self.to({"source": "day-engine", "routine": "nap_mode"}, night=True), ["ceci"])
        self.assertEqual(self.to({"source": "day-engine", "routine": "nap_mode"}), both)
        self.assertEqual(self.to({"source": "day-engine", "routine": "floor_clean", "ask": "floor_clean"}), ["gonza"])
        self.assertEqual(self.to({"source": "day-engine", "routine": "floor_clean", "ask": "x"}, night=True), ["ceci"])
        self.assertEqual(self.to({"source": "reminders", "person": "ceci"}, night=True, on_duty="Parent A"), ["ceci"])

    def test_a_night_replan_reaches_only_the_parent_on_duty(self):
        # e2e day Nov 1: Muse's Spanish why let "Cambió el plan" out at 22:05 and 01:46, to Ceci too after she asked to sleep
        event = {"source": "house-brain", "routine": "replan", "to": "both"}
        self.assertEqual(self.to(event, night=True, on_duty="Parent A"), ["gonza"])
        self.assertEqual(self.to(event), ["gonza", "ceci"])
        self.assertEqual(self.to({"source": "house-brain", "routine": "tonight", "to": "both"}, night=True,
                                 on_duty="Parent A"), ["gonza", "ceci"])

    def test_names_replace_rota_labels(self):
        self.assertEqual(self.people.named("For Parent A: On duty tonight. Parent B sleeps."),
                         "For Gonza: On duty tonight. Ceci sleeps.")


class Pushes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def family(self, now, rows=(), **kw):
        family = Family(self.tmp.name, now, rows, **kw)
        self.addCleanup(family.close)
        return family

    def test_morning_brief_reaches_both_parents_by_name(self):
        family = self.family(at(30, 7, 30))
        family.agent.bus.publish("notify", text="Morning brief. Parent A took 1 wake-up.", channel="telegram",
                                 source="day-engine", routine="morning_brief")
        self.assertEqual(family.sent_to(GONZA), ["Morning brief. Gonza took 1 wake-up."])
        self.assertEqual(family.sent_to(CECI), ["Morning brief. Gonza took 1 wake-up."])
        pushed = [e for e in family.agent.bus.history if e["kind"] == "pushed"][-1]
        self.assertEqual((pushed["to"], pushed["reason"]), (["gonza", "ceci"], "shared"))

    def test_night_push_goes_to_the_parent_on_duty_only(self):
        rows = [wakeup(29, 2, "Gonza", 1)]
        family = self.family(at(31, 2, 10), rows)
        family.agent.bus.publish("notify", text="He is awake.", channel="telegram", source="day-engine", routine="nap_mode")
        self.assertEqual(family.sent_to(CECI), ["He is awake."])
        self.assertEqual(family.sent_to(GONZA), [])

    def test_the_night_feed_push_reaches_its_parent(self):
        rows = [wakeup(29, 2, "Gonza", 1)]
        family = self.family(at(31, 2, 10), rows)
        family.night.push(family.night.on_duty(at(31, 2, 10)), "Study light on dim. He is up.", at(31, 2, 10))
        self.assertEqual(family.sent_to(CECI), ["Study light on dim. He is up."])
        self.assertEqual(family.sent_to(GONZA), [])

    def test_quiet_and_other_channels_stay_in_the_log(self):
        family = self.family(at(30, 9, 0))
        family.agent.bus.publish("notify", text="Nap plan.", channel="telegram", source="house-brain",
                                 routine="plan_message", to="Parent A", quiet=True)
        family.agent.bus.publish("notify", text="Ear only.", channel="ear", source="skill")
        self.assertEqual(family.messenger.sent, [])

    def test_a_pushed_question_waits_for_the_yes_of_the_parent_asked(self):
        brain = ScriptedBrain(["Starting the floor clean."])
        family = self.family(at(30, 10, 0), brain=brain)
        family.agent.bus.publish("notify", text="I can run the vacuum now. Reply yes to start it.", channel="telegram",
                                 source="day-engine", routine="floor_clean", ask="floor_clean")
        self.assertEqual(len(family.sent_to(GONZA)), 1)
        self.assertEqual(family.sent_to(CECI), [])
        family.say(CECI, "sí")
        self.assertEqual(family.sent_to(CECI)[-1], "No hay nada esperando tu sí, así que no hice nada. Decime qué querés que haga.")
        family.say(GONZA, "yes")
        self.assertEqual(family.sent_to(GONZA)[-1], "Starting the floor clean.")

    def test_a_question_asked_in_one_chat_is_not_answered_from_the_other(self):
        brain = ScriptedBrain(["¿Querés que lo agregue a la lista?"], ["Agregado."])
        family = self.family(at(30, 10, 0), brain=brain)
        family.say(GONZA, "Nos faltan pañales")
        family.say(CECI, "sí")
        self.assertIn("No hay nada esperando tu sí", family.sent_to(CECI)[-1])

    def test_house_brain_tell_leaves_delivery_to_the_family_push(self):
        from parenting_agent.house_brain import HouseBrainPlugin
        family = self.family(at(30, 20, 30))
        plugin = HouseBrainPlugin(family.agent, family.config, log=ListLog([]), clock=family.clock)
        family.agent.plugins.append(plugin)
        plugin.wire()
        plugin.brain.send("Tonight's plan. On duty: Parent A.", at(30, 20, 30), "tonight")
        plugin.brain.send("For Parent B: nap at 09:00.", at(30, 20, 30), "plan_message", to="Parent B", quiet=False)
        plugin.brain.send("For Parent A: nap at 09:00.", at(30, 20, 30), "plan_message", to="Parent A")
        self.assertEqual(family.sent_to(GONZA), ["Tonight's plan. On duty: Gonza."])
        self.assertEqual(family.sent_to(CECI), ["Tonight's plan. On duty: Gonza.", "For Ceci: nap at 09:00."])


class FollowUps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_reminder_comes_back_to_whoever_asked(self):
        brain = ScriptedBrain([[{"name": "remind_me", "arguments": {"text": "sacar la ropa", "minutes": 20}}],
                               "Listo, te lo recuerdo a las 10:20."])
        family = Family(self.tmp.name, at(30, 10, 0), brain=brain)
        self.addCleanup(family.close)
        family.say(CECI, "Test: recordame en 20 minutos sacar la ropa")
        self.assertEqual(family.sent_to(CECI), ["Listo, te lo recuerdo a las 10:20."])
        self.assertEqual(family.reminders.tick(at(30, 10, 19)), [])
        family.reminders.tick(at(30, 10, 20))
        self.assertEqual(family.sent_to(CECI)[-1], "Recordatorio que pediste: sacar la ropa")
        self.assertEqual(family.sent_to(GONZA), [])
        self.assertEqual(family.reminders.tick(at(30, 10, 21)), [])

    def test_reminders_survive_a_restart_and_say_when_they_were_meant(self):
        family = Family(self.tmp.name, at(30, 10, 0))
        family.agent.current_event = {"kind": "message", "channel": "telegram", "chat_id": GONZA, "person": "gonza"}
        family.reminders.remind_me("call the pharmacy about the bottles", at="10:30")
        family.close()
        again = Family(self.tmp.name, at(30, 11, 0))
        self.addCleanup(again.close)
        again.reminders.tick(at(30, 11, 0))
        self.assertEqual(again.sent_to(GONZA), ["Reminder you asked for for 10:30: call the pharmacy about the bottles"])

    def test_limits_and_refusals(self):
        family = Family(self.tmp.name, at(30, 10, 0))
        self.addCleanup(family.close)
        r = family.reminders
        for bad in ({"text": "x", "minutes": 0}, {"text": "x", "minutes": 2000}, {"text": "x"}, {"text": "", "minutes": 5},
                    {"text": "the code is 4821 9930", "minutes": 5}, {"text": "darle paracetamol 5 ml", "minutes": 5},
                    {"text": "x", "at": "25:99"}):
            with self.assertRaises(ValueError, msg=bad):
                r.remind_me(**bad)
        self.assertIn("tomorrow", r.remind_me("x", at="09:00"))
        self.assertEqual(json.loads((r.path).read_text())[0]["text"], "x")


class OtherSenders(unittest.TestCase):
    def test_prep_nudge_reaches_both_chats(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 8, 0), plugins=(),
                            extra={"prep": {"nudge": {"also_chat_ids_envs": ["TELEGRAM_CECI_CHAT_ID"]}}})
            try:
                prep = Prep(family.agent, family.config)
                text = prep.send_nudge()
                self.assertEqual(family.sent_to(GONZA), [text])
                self.assertEqual(family.sent_to(CECI), [text])
            finally:
                family.close()

    def test_router_partner_route_reaches_ceci(self):
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 10, 0), plugins=())
            try:
                router = Router(family.agent, family.config, client=None, presence=lambda: "home")
                family.agent.plugins.append(router)
                channel, result = router.deliver("Gonza needs a hand in the nursery.",
                                                 type("S", (), {"presence": "home", "skill_active": False,
                                                                "baby_asleep": False, "help_needed": True})())
                self.assertEqual((channel, result), ("partner", {"sent_to": ["ceci"]}))
                self.assertEqual(family.sent_to(CECI), ["Gonza needs a hand in the nursery."])
                self.assertEqual(family.sent_to(GONZA), [])
            finally:
                family.close()


if __name__ == "__main__":
    unittest.main()
