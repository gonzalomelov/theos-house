"""Muse runs the house (#116): the plan checks, the fallback, the triggers, and the routines a plan arms.

Offline: Muse is a fake that returns canned answers, the house is the simulated house of day_sim, and every write is a
dry run. The real Muse runs are in results/muse-house (scripts/muse_house_sim.py).
"""
import datetime
import json
import tempfile
import unittest

from parenting_agent import day_engine as de
from parenting_agent import day_sim, house_brain as hb, meals
from parenting_agent.agent.brain import BrainError
from parenting_agent.bus import Bus
from parenting_agent.house_tools import HouseTools
from parenting_agent.night_feed import NightFeed
from parenting_agent.white_noise import CRIB_CAP_DB, SimulatedWhiteNoise
from tests.test_home_automations import Clock, make_agent, night_log
from tests.test_home_automations import at as night_at
from tests.test_house_tools import FakeHA

at = day_sim.at
TZ = day_sim.TZ
META = {"seconds": 1.0, "usd": 0.01, "input_tokens": 100, "output_tokens": 50, "host": "fake", "model": "fake"}


def answer(**kw):
    base = {"on_duty": "Parent A", "floor_clean": [], "bottle_prewarm": [], "door_quiet": [], "white_noise_boost": [],
            "messages": [], "summary": "A plan.", "why_changed": ""}
    return {**base, **kw}


class FakeMuse:
    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def ask(self, system, text, schema, name="plan"):
        self.asked.append({"system": system, "context": json.loads(text), "schema": schema, "name": name})
        got = self.answers.pop(0) if self.answers else answer()
        if isinstance(got, Exception):
            raise got
        return got, dict(META)


def day_setup(muse, settings=None):
    house = day_sim.SimHouse(json.loads(day_sim.HOUSE_START.read_text()))
    bus = Bus()
    white = SimulatedWhiteNoise(bus)
    engine = de.DayEngine(bus, de.DayWriter(bus, mirror=house), {"utc_offset_h": -3, "supplies": {}},
                          meals.FixtureRecipes(day_sim.RECIPES), white)
    spoken = []
    brain = hb.HouseBrain(bus, muse, {"utc_offset_h": -3, **(settings or {})}, day_engine=engine, white_noise=white,
                          say=lambda text, now: spoken.append(text))
    return brain, engine, house, bus, day_sim.day_entries(), spoken


def kinds(bus, kind):
    return [e for e in bus.history if e["kind"] == kind]


class ValidateTest(unittest.TestCase):
    S = {**hb.DEFAULTS, "utc_offset_h": -3}
    NOW = at(0, 13, 56)
    NAP = [{"start": at(0, 14, 51), "end": at(0, 16, 28), "kind": "nap"}]

    def check(self, got):
        return hb.validate(got, self.NOW, TZ, self.S, self.NAP)

    def test_a_good_plan_passes_with_absolute_times(self):
        plan, errors, refused, dropped = self.check(answer(
            floor_clean=[{"start": "13:58", "end": "14:45", "why": "before the nap"}],
            bottle_prewarm=[{"start": "23:20", "why": "night feed"}], on_duty="Parent B",
            messages=[{"to": "Parent B", "text": "You are on duty tonight, warmer at 23:20."}]))
        self.assertEqual((errors, refused), ([], {}))
        self.assertEqual(plan["floor_clean"][0]["start"], at(0, 13, 58))
        self.assertEqual(plan["bottle_prewarm"][0]["start"], at(0, 23, 20))
        self.assertEqual(plan["on_duty"], "Parent B")
        self.assertEqual(len(plan["messages"]), 1)  # times like 23:20 are not a secret number

    def test_a_floor_clean_over_a_predicted_nap_is_refused_and_only_that_routine_falls_back(self):
        plan, errors, refused, _ = self.check(answer(
            floor_clean=[{"start": "14:30", "end": "15:20", "why": ""}],
            door_quiet=[{"start": "14:40", "end": "16:30", "why": "visitor"}]))
        self.assertEqual(errors, [])
        self.assertIn("overlaps the predicted nap 14:51-16:28", refused["floor_clean"][0])
        self.assertIsNone(plan["floor_clean"])  # None runs the fixed rule
        self.assertEqual(len(plan["door_quiet"]), 1)

    def test_the_clock_and_the_limits(self):
        cases = {
            "floor_clean": ({"start": "14:00", "end": "14:20", "why": ""}, "shorter than the run"),
            "door_quiet": ({"start": "14:00", "end": "19:00", "why": ""}, "longer than 240 min"),
            "white_noise_boost": ({"start": "14:00", "end": "15:30", "why": ""}, "longer than 60 min"),
        }
        for name, (item, why) in cases.items():
            plan, errors, refused, _ = self.check(answer(**{name: [item]}))
            self.assertIn(why, refused[name][0], name)
        _, _, refused, _ = self.check(answer(bottle_prewarm=[{"start": "15:00", "why": ""}]))
        self.assertIn("not at night", refused["bottle_prewarm"][0])
        _, _, refused, _ = hb.validate(answer(bottle_prewarm=[{"start": "23:20", "why": ""}]), self.NOW, TZ,
                                       {**self.S, "horizon_h": 6}, self.NAP)
        self.assertIn("more than 6 h ahead", refused["bottle_prewarm"][0])
        _, _, refused, _ = self.check(answer(bottle_prewarm=[{"start": "23:00", "why": ""}, {"start": "23:30", "why": ""}]))
        self.assertIn("less than 60 min apart", refused["bottle_prewarm"][0])
        _, _, refused, _ = self.check(answer(door_quiet=[{"start": "2pm", "end": "15:00", "why": ""}]))
        self.assertIn("is not HH:MM", refused["door_quiet"][0])

    def test_empty_and_expired_items_are_left_out_not_refused(self):
        plan, errors, refused, dropped = self.check(answer(
            floor_clean=[{"start": "", "end": "", "why": ""}], door_quiet=[{"start": "11:00", "end": "12:00", "why": ""}]))
        self.assertEqual((errors, refused), ([], {}))
        self.assertEqual((plan["floor_clean"], plan["door_quiet"]), ([], []))
        self.assertEqual([d["why"] for d in dropped], ["empty start, left out", "over already, left out"])

    def test_a_window_that_already_started_is_kept(self):
        plan, _, refused, _ = self.check(answer(door_quiet=[{"start": "13:30", "end": "15:00", "why": ""}]))
        self.assertEqual(refused, {})
        self.assertEqual(plan["door_quiet"][0]["end"], at(0, 15, 0))

    def test_a_plan_that_is_not_a_plan_is_refused_whole(self):
        for bad in (answer(on_duty="Grandma"), answer(floor_clean="soon"), ["not", "a", "dict"]):
            plan, errors, _, _ = self.check(bad)
            self.assertIsNone(plan)
            self.assertTrue(errors)

    def test_advice_and_secrets_never_reach_a_parent(self):
        plan, _, _, dropped = self.check(answer(messages=[
            {"to": "Parent A", "text": "You should call the pediatrician."},
            {"to": "Parent B", "text": "The gate code is 4471."},
            {"to": "Parent B", "text": "Warmer at 23:20."}], summary="Try to sleep early."))
        self.assertEqual([m["text"] for m in plan["messages"]], ["Warmer at 23:20."])
        self.assertEqual(plan["summary"], "")
        self.assertEqual(len(dropped), 3)

    def test_the_schema_names_routines_never_devices(self):
        schema = hb.plan_schema(["Parent A", "Parent B"])
        text = json.dumps(schema)
        for word in ("entity", "service", "vacuum.", "switch.", "notify."):
            self.assertNotIn(word, text)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(schema["properties"]["on_duty"]["enum"], ["Parent A", "Parent B"])


class FallbackTest(unittest.TestCase):
    def ask(self, *answers, settings=None):
        brain, engine, house, bus, entries, _ = day_setup(FakeMuse(*answers), settings)
        engine.plan = {"floor_clean": [], "door_quiet": []}
        from parenting_agent.house_plan import as_of
        event = brain.ask(as_of(entries, at(0, 13, 56)), at(0, 13, 56), house.state, "wake_up", None)
        return event, brain, engine, bus

    def test_a_muse_error_or_timeout_runs_the_fixed_routines_and_is_logged(self):
        for error in (BrainError("timed out"), TimeoutError("slow"), hb.MuseAnswerError("not a JSON object", META)):
            event, brain, engine, bus = self.ask(error)
            self.assertEqual(event["kind"], "house_brain_fallback")
            self.assertEqual(event["routines"], "fixed")
            self.assertIsNone(engine.plan)
            self.assertIsNone(brain.plan)
            self.assertEqual(brain.stats["fallbacks"], 1)

    def test_an_invalid_plan_runs_the_fixed_routines_and_both_are_logged(self):
        event, brain, engine, bus = self.ask(answer(on_duty="Grandma"))
        self.assertEqual(event["kind"], "house_brain_fallback")
        self.assertIn("plan refused", event["reason"])
        refused = kinds(bus, "house_plan")[-1]
        self.assertFalse(refused["accepted"])
        self.assertIsNone(engine.plan)

    def test_the_budget_stops_muse_calls(self):
        event, brain, engine, bus = self.ask(answer(), settings={"budget_usd": 0})
        self.assertIn("budget", event["reason"])
        self.assertEqual(brain.stats["calls"], 0)

    def test_a_refused_routine_is_a_partial_fallback_in_the_log(self):
        event, brain, engine, bus = self.ask(answer(floor_clean=[{"start": "14:30", "end": "15:20", "why": ""}]))
        self.assertTrue(event["accepted"])
        self.assertIsNone(engine.plan["floor_clean"])
        partial = kinds(bus, "house_brain_fallback")[-1]
        self.assertEqual((partial["scope"], partial["routines"]), ("routine", ["floor_clean"]))

    def test_the_rota_stays_fixed_unless_a_parent_asked_to_sleep(self):
        brain, engine, house, bus, entries, _ = day_setup(FakeMuse(answer(on_duty="Parent B"), answer(on_duty="Parent B")))
        feed = type("Feed", (), {"plan": None})()
        brain.night_feed = feed
        brain.ask([], at(0, 22, 0), house.state, "bedtime", None)
        self.assertIsNone(feed.plan["on_duty"])
        note = day_sim.note(at(0, 22, 10), "Parent A: I'm exhausted, let me sleep")
        brain.tick(entries + [note], at(0, 22, 11), house.state)
        self.assertEqual(feed.plan["on_duty"], "Parent B")

    def test_parts_left_out_of_the_settings_keep_the_fixed_rule(self):
        event, brain, engine, bus = self.ask(answer(door_quiet=[{"start": "14:00", "end": "15:00", "why": ""}]),
                                             settings={"parts": ["floor_clean"]})
        self.assertTrue(event["accepted"])
        self.assertIsNone(engine.plan["door_quiet"])


class TriggerTest(unittest.TestCase):
    def setUp(self):
        self.muse = FakeMuse()
        self.brain, self.engine, self.house, self.bus, self.entries, self.spoken = day_setup(self.muse)

    def run_until(self, t0, t1, entries=None):
        t = t0
        while t < t1:
            self.brain.tick(entries or self.entries, t, self.house.state)
            t += datetime.timedelta(minutes=1)
        return [a["context"]["trigger"] for a in self.muse.asked]

    def test_wake_up_before_nap_and_bedtime_each_once(self):
        got = self.run_until(at(0, 13, 50), at(0, 21, 0))
        self.assertIn("wake_up", got)
        self.assertIn("before_nap", got)
        self.assertEqual(got.count("bedtime"), 1)
        context = self.muse.asked[0]["context"]
        for key in ("log_last_24h", "predicted_sleeps", "next_feed_predicted", "night_rota", "house_read_only",
                    "weather", "usual_tummy_times", "floor_clean_gate", "plan_until"):
            self.assertIn(key, context)
        self.assertEqual(context["weather"]["condition"], "sunny")

    def test_a_parent_asking_to_sleep_replans_at_once(self):
        note = day_sim.note(at(0, 21, 50), "Parent A: I'm exhausted, let me sleep tonight")
        self.run_until(at(0, 21, 45), at(0, 21, 55), self.entries + [note])
        adapt = [a["context"] for a in self.muse.asked if "exhausted" in a["context"]["what_happened"]]
        self.assertEqual(len(adapt), 1)

    def test_a_dog_bark_replans_once_and_a_long_sleep_once(self):
        self.run_until(at(0, 14, 52), at(0, 14, 55))
        self.bus.publish("house_sound", label="dog", source="test")
        self.bus.publish("house_sound", label="dog", source="test")
        self.run_until(at(0, 14, 55), at(0, 14, 57))
        dogs = [a for a in self.muse.asked if "dog barking" in a["context"]["what_happened"]]
        self.assertEqual(len(dogs), 1)
        self.assertEqual(dogs[0]["context"]["trigger"], "adapt")
        long_sleep = [dict(e, end=None) if e.get("start") == at(0, 14, 51).isoformat() and e["kind"] == "sleep" else e
                      for e in self.entries
                      if not (e["kind"] == "feeding" and at(0, 14, 51) < day_sim.parse(e["start"]) < at(0, 17, 30))]
        self.run_until(at(0, 15, 0), at(0, 17, 30), long_sleep)
        longs = [a for a in self.muse.asked if "longer than the usual" in a["context"]["what_happened"]]
        self.assertEqual(len(longs), 1)

    def test_tonights_plan_goes_out_and_the_plan_is_in_the_event_log(self):
        self.muse.answers = [answer(on_duty="Parent B", bottle_prewarm=[{"start": "23:30", "why": "feed"}],
                                    summary="Parent B is on tonight.")]
        self.brain.ask([], at(0, 21, 0), self.house.state, "bedtime", None)
        tonight = [e for e in kinds(self.bus, "notify") if e["routine"] == "tonight"]
        self.assertEqual(len(tonight), 1)
        self.assertIn("On duty: Parent B", tonight[0]["text"])
        self.assertIn("23:30", tonight[0]["text"])
        logged = kinds(self.bus, "house_plan")[-1]
        self.assertEqual(logged["plan"]["bottle_prewarm"][0]["start"], "23:30")
        self.assertEqual(logged["muse"]["model"], "fake")


class ArmTest(unittest.TestCase):
    def test_a_planned_floor_window_runs_the_vacuum_inside_it_with_the_fixed_checks(self):
        brain, engine, house, bus, entries, _ = day_setup(FakeMuse())
        brain.apply(hb.validate(answer(floor_clean=[{"start": "13:57", "end": "14:45", "why": ""}]), at(0, 13, 55), TZ,
                                {**hb.DEFAULTS}, [])[0])
        t = at(0, 13, 55)
        while t < at(0, 14, 0):
            engine.tick(entries, t, house.state)
            if engine.asks:
                engine.approve("floor_clean", entries, t, house.state)
            t += datetime.timedelta(minutes=1)
        starts = [e for e in kinds(bus, "routine") if e["name"] == "floor_clean" and e["step"] == "start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["at"], at(0, 13, 57).isoformat())

    def test_a_planned_floor_window_during_his_sleep_never_runs(self):
        brain, engine, house, bus, entries, _ = day_setup(FakeMuse())
        engine.plan = {"floor_clean": [{"start": at(0, 12, 0), "end": at(0, 13, 0), "why": "forced"}], "door_quiet": None}
        t = at(0, 12, 0)
        while t < at(0, 13, 0):
            engine.tick(entries, t, house.state)
            engine.approve("floor_clean", entries, t, house.state)
            t += datetime.timedelta(minutes=1)
        self.assertFalse([e for e in kinds(bus, "house_dry") if e["action"] == "vacuum.start"])

    def test_door_quiet_turns_the_echo_line_into_a_silent_push(self):
        brain, engine, house, bus, entries, _ = day_setup(FakeMuse())
        engine.plan = {"floor_clean": None, "door_quiet": [{"start": at(0, 14, 40), "end": at(0, 15, 30), "why": "Grandma"}]}
        house.state["door"] = [{"source": "doorbell", "at": at(0, 14, 47).isoformat()}]
        engine.tick(entries, at(0, 14, 47), house.state)
        self.assertEqual([e["action"] for e in kinds(bus, "house_dry") if e["routine"] == "door"], [de.PUSH])

    def test_white_noise_boost_stays_under_the_cap_and_goes_back(self):
        brain, engine, house, bus, entries, _ = day_setup(FakeMuse())
        engine.white_noise.on("nap")
        before = engine.white_noise.state["level"]
        brain.plan = hb.validate(answer(white_noise_boost=[{"start": "15:10", "end": "15:40", "why": "dog"}]),
                                 at(0, 15, 10), TZ, {**hb.DEFAULTS}, [])[0]
        brain.boost(at(0, 15, 10))
        self.assertLessEqual(kinds(bus, "white_noise")[-1]["crib_db"], CRIB_CAP_DB)
        self.assertGreater(engine.white_noise.state["level"], before)
        brain.boost(at(0, 15, 40))
        self.assertEqual(engine.white_noise.state["level"], before)


class NightPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.clock = Clock(night_at(21, 0, 30))
        self.log = night_log()
        self.house = HouseTools(self.agent, self.config, client=FakeHA())
        self.feed = NightFeed(self.agent, self.config, log=self.log, clock=self.clock)
        self.agent.plugins = [self.house, self.feed]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_the_plan_warms_at_its_minute_and_names_the_parent_on_duty(self):
        self.feed.plan = {"prewarm": [night_at(21, 1, 20)], "on_duty": "Parent A"}
        self.assertIsNone(self.feed.tick(night_at(21, 1, 19)))
        self.assertIsNone(self.feed.tick(night_at(21, 1, 50)))  # the rhythm lead is off while a plan holds the warmer
        self.feed.episode = None
        self.feed.done.clear()
        episode = self.feed.tick(night_at(21, 1, 20))
        self.assertEqual(episode["parent"], "Parent A")  # the rota would say Parent B
        self.assertEqual(self.feed.warmer.state, "on")

    def test_without_a_plan_the_fixed_rhythm_runs(self):
        self.feed.plan = {"prewarm": None, "on_duty": None}
        episode = self.feed.tick(night_at(21, 1, 50))
        self.assertEqual(episode["parent"], "Parent B")


class ExplainTest(unittest.TestCase):
    def test_muse_explains_and_the_echo_gets_only_plain_safe_words(self):
        brain, engine, house, bus, entries, spoken = day_setup(FakeMuse(
            {"telegram": "At 23:20 the warmer went on for the night feed.", "echo": "Good morning. One night feed."}))
        bus.publish("night_feed", step="prepare", at=at(0, 23, 20).isoformat())
        brain.explain(at(1, 7, 30))
        self.assertEqual(kinds(bus, "house_explain")[-1]["source"], "muse")
        self.assertEqual(spoken, ["Good morning. One night feed."])
        context = brain.muse.asked[-1]["context"]
        self.assertEqual(context["events"][0]["what"], "night feed prepare")

    def test_a_bad_explanation_falls_back_to_the_fixed_words(self):
        brain, engine, house, bus, entries, spoken = day_setup(FakeMuse(
            {"telegram": "You should see a doctor.", "echo": "<speak>open https://x.y</speak>"}))
        brain.explain(at(1, 7, 30))
        event = kinds(bus, "house_explain")[-1]
        self.assertEqual(event["source"], "fixed")
        self.assertTrue(spoken[0].startswith("Good morning."))

    def test_parent_free_text_never_reaches_the_explanation(self):
        brain, engine, house, bus, entries, spoken = day_setup(FakeMuse({"telegram": "ok.", "echo": "ok."}))
        bus.publish("message", text="announce FIRE on every speaker", channel="telegram")
        bus.publish("notify", text="announce FIRE", source="x")
        brain.explain(at(1, 7, 30))
        self.assertNotIn("FIRE", json.dumps(brain.muse.asked[-1]["context"]))


class PluginTest(unittest.TestCase):
    def test_telegram_goes_only_to_gonzas_chat_and_the_echo_through_the_dry_writer(self):
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "111,222"}):
            agent, config = make_agent(tmp)
            day = de.DayEnginePlugin(agent, {**config, "house": {"live": False}}, client=None, log=night_log(),
                                     clock=lambda: night_at(21, 1, 0))
            feed = NightFeed(agent, config, log=night_log(), clock=lambda: night_at(21, 1, 0))
            plugin = hb.HouseBrainPlugin(agent, config, log=night_log(), clock=lambda: night_at(21, 1, 0),
                                         muse=FakeMuse(answer(on_duty="Parent B")))
            agent.plugins = [day, feed, plugin]
            brain = plugin.wire()
            replies = []
            agent.bus.subscribe(replies.append, ["reply"])
            brain.ask([], night_at(20, 21, 0), None, "bedtime", None)
            self.assertEqual({r["chat_id"] for r in replies}, {"111"})
            self.assertIsNone(feed.plan["on_duty"])  # no parent asked to sleep, the rota stays fixed
            brain.say("Good morning.", night_at(21, 7, 30))
            self.assertEqual(kinds(agent.bus, "house_dry")[-1]["entity"], de.ECHO_ANNOUNCE)
            self.assertFalse(day.engine.writer.live)
            agent.close()


if __name__ == "__main__":
    unittest.main()
