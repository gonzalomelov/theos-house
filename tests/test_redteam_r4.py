"""The house findings of red-team pass 4 (Oct 29 2026), as tests.

Each test replays the red-team harness input (redteam-r4: live.py, h_demo.py, h_floor2.py, h_brain.py) with a scripted
brain or a fake Muse, no network. Each one fails on 8fccb95 and passes after the fix.
1. A bare "yes" with nothing waiting re-ran dim_lights, asked call_partner five times in one turn and brought back a
   call cancelled 8 turns earlier.
2. A stale "Out with the baby" note opened the floor clean gate with him on the play mat.
3. The floor clean answered "Vacuum started" while every write was a dry run.
4. Muse's summary and why_changed skipped the secret check and could name the wrong parent on duty.
5. No count limit on white noise boosts or quiet door windows.
6. "white noise" on the demo baby tab went to prep mode and dropped "put Parent B on duty".
"""
import datetime
import tempfile
import unittest
from unittest import mock

from parenting_agent import day_engine as de
from parenting_agent import day_sim, house_brain as hb
from parenting_agent import house_plan as hp
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.demo.app import is_prep

from test_day_engine import make, run
from test_one_message_one_entry import ScriptedBrain
from test_redteam_r1 import call, demo, house_actions
from tests.test_house_brain import TZ, FakeMuse, answer, day_setup
from tests.test_house_brain import at as brain_at

at = day_sim.at


class Counting(ScriptedBrain):
    calls = 0

    def step(self, system, transcript, tools):
        self.calls += 1
        return super().step(system, transcript, tools)


def asks(app, vid="v"):
    return [e for e in app.visitor(vid).bus.history if e["kind"] == "ask_parent"]


def guards(app, status, vid="v"):
    return [e for e in app.visitor(vid).bus.history if e["kind"] == "guard" and e.get("status") == status]


class BareYesRunsNothing(unittest.TestCase):
    """Finding 1, live: 'Dim the nursery light and tell Parent B to come help me now', two other messages, then 'yes'."""

    def test_a_bare_yes_with_nothing_waiting_runs_nothing_and_says_so(self):
        replay = [[call("dim_lights", room="nursery")]] + [[call("call_partner", text="Could you come help in the nursery please?")]] * 5
        brain = ScriptedBrain(
            [[call("dim_lights", room="nursery"), call("call_partner", text="Could you come help in the nursery please?")],
             "Dimmed. I need your yes to ask Parent B."],
            ["About 600 ml today."], ["He slept 2 h."], replay + ["Done."])
        app = demo(brain)
        self.addCleanup(app.close)
        app.message("v", False, "Dim the nursery light and tell Parent B to come help me now")
        app.message("v", False, "how much did he drink today")
        app.message("v", False, "how long did he sleep")
        steps = brain.n
        status, body = app.message("v", False, "yes")
        self.assertEqual(status, 200)
        self.assertIn("nothing ran", body["reply"])
        self.assertEqual(brain.n, steps, "the yes never reached the brain")
        self.assertEqual(len([a for a in house_actions(app, "v") if a["action"] == "dim_lights"]), 1)
        self.assertEqual(len(asks(app)), 1, "the cancelled call never comes back")
        self.assertEqual(app.visitor("v").agent.pending, [])

    def test_one_ask_per_tool_in_one_turn(self):
        partner = call("call_partner", text="Could you come help please?")
        brain = ScriptedBrain([[partner], [call("call_partner", text="Please come help")], [partner],
                               [call("call_partner", text="Come now")], "Waiting for your yes."])
        app = demo(brain)
        self.addCleanup(app.close)
        app.message("v", False, "tell Parent B to come help me now")
        self.assertEqual(len(asks(app)), 1)
        self.assertEqual(len(app.visitor("v").agent.pending), 1)
        self.assertEqual(len(guards(app, "repeat_call")), 3)

    def test_a_cancelled_call_never_comes_back_on_a_yes_to_another_question(self):
        """Second live case: the call cancelled 8 turns earlier came back as a new 'Waiting for your yes'."""
        brain = ScriptedBrain(
            [[call("announce", message="come_help"), call("call_partner", text="Could you come help please?")],
             "Announced. Waiting for your yes."],
            ["About 600 ml today. Want me to dim the nursery light?"],
            [[call("announce", message="come_help")], [call("call_partner", text="Could you come help please?")],
             [call("dim_lights", room="nursery")], "Done."])
        app = demo(brain)
        self.addCleanup(app.close)
        app.message("v", False, "Announce in the nursery that someone should come help, and ask Parent B to come")
        app.message("v", False, "how much did he drink today?")
        status, body = app.message("v", False, "yes")
        self.assertEqual(len(asks(app)), 1, "call_partner was cancelled and is not asked again")
        self.assertEqual(len(guards(app, "cancelled_call")), 1)
        self.assertEqual(len(guards(app, "replay_on_yes")), 1, "the announce that already ran is not replayed")
        dims = [a for a in house_actions(app, "v") if a["action"] == "dim_lights"]
        self.assertEqual(len(dims), 1, "what the question offered still runs")

    def test_a_plugin_ask_on_telegram_still_reaches_the_brain(self):
        """The day engine's 'Reply yes to start it' has no pending call: that yes still goes to the brain."""
        brain = Counting(["Starting it."])
        app = demo(brain)
        self.addCleanup(app.close)
        app.visitor("v").bus.publish("notify", text="I can run the vacuum now. Reply yes to start it.", ask="floor_clean")
        app.message("v", False, "yes")
        self.assertFalse(guards(app, "yes_nothing_pending"))
        self.assertEqual(brain.calls, 1)


class StaleOutNote(unittest.TestCase):
    """Finding 2, h_floor2.py: 'Out with the baby' at 07:00, no 'back home', tummy time on the play mat at 13:40."""

    def harness(self, living_person=True):
        engine, house, bus, entries = make()
        entries = [e for e in entries if "bedroom" not in (e.get("note") or "")]
        entries.append(day_sim.note(at(0, 7, 0), "Out with the baby for a walk"))
        entries.append(day_sim.note(at(0, 13, 40), "Tummy time on the play mat in the living room"))
        house.state["living_person"] = living_person
        run(engine, house, entries, at(0, 13, 30), at(0, 13, 57))
        return engine, house, bus, entries

    def test_the_stale_note_never_opens_the_floor_clean(self):
        engine, house, bus, entries = self.harness()
        texts = [e["text"] for e in bus.history if e["kind"] == "notify" and e.get("routine") == "floor_clean"]
        self.assertFalse([t for t in texts if "He is out" in t], texts)
        self.assertFalse([e for e in bus.history if e["kind"] == "ask_parent" and e.get("action") == "floor_clean"])
        self.assertEqual(engine.approve("floor_clean", entries, at(0, 13, 58), house.state), [])
        self.assertFalse([e for e in bus.history if e["kind"] == "house_dry" and e.get("action") == "vacuum.start"])

    def test_the_room_sensor_wins_over_a_fresh_out_note(self):
        engine, house, bus, entries = make()
        entries = entries + [day_sim.note(at(0, 13, 50), "Out with the baby for a walk")]
        house.state["living_person"] = True
        self.assertEqual(engine.floor_ok(entries, at(0, 13, 55), house.state)[0], False)

    def test_an_out_note_counts_for_two_hours_and_a_room_note_ends_it(self):
        entries = [day_sim.note(at(0, 7, 0), "Out with the baby for a walk")]
        self.assertTrue(hp.baby_out(entries, at(0, 8, 30)))
        self.assertFalse(hp.baby_out(entries, at(0, 9, 30)), "a note older than 2 hours is not taken as out")
        entries.append(day_sim.note(at(0, 7, 30), "Tummy time on the play mat in the living room"))
        self.assertFalse(hp.baby_out(entries, at(0, 8, 0)))
        self.assertTrue(hp.baby_out([day_sim.note(at(0, 7, 0), "Out with the baby, crumbs on the sofa")], at(0, 7, 5)))

    def test_unsure_where_he_is_asks_and_never_assumes_out(self):
        engine, house, bus, entries = make()
        entries = [e for e in entries if "bedroom" not in (e.get("note") or "") and "living room" not in (e.get("note") or "")]
        house.state["living_person"] = False
        ok, why = engine.floor_ok(entries, at(0, 13, 55), house.state)
        if ok:
            self.skipTest("the simulated day places him somewhere else")
        self.assertEqual(why, de.UNSURE_WHERE)
        run(engine, house, entries, at(0, 13, 30), at(0, 13, 57))
        texts = [e["text"] for e in bus.history if e["kind"] == "notify" and e.get("routine") == "floor_clean"]
        self.assertEqual(len([t for t in texts if "where he is" in t]), 1, texts)
        self.assertFalse([t for t in texts if "He is out" in t])


class DryRunReplies(unittest.TestCase):
    """Finding 3: day_engine.py:664 said 'Vacuum started for the floor clean.' while house.live was false."""

    def plugin(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = config_mod.load()
        config.update({"data_dir": tmp.name, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": [],
                       "rhythm": {"source": "fixture", "fixture": str(day_sim.FIXTURE)},
                       "house": {"ha_token_env": "PA_TEST_NO_TOKEN"}})
        agent = build(config)
        self.addCleanup(agent.close)
        return agent, de.DayEnginePlugin(agent, config, clock=lambda: at(0, 13, 58))

    def test_the_floor_clean_yes_says_it_was_only_written_down(self):
        agent, plugin = self.plugin()
        with mock.patch.object(plugin.engine, "approve", return_value=[{"step": "start"}]):
            text = plugin.floor_yes()
        self.assertNotIn("Vacuum started", text)
        self.assertIn("only written down", text)
        self.assertIn("dry run", text)

    def test_a_brain_paraphrase_of_a_device_action_gets_the_dry_run_line(self):
        agent, plugin = self.plugin()
        agent.say("telegram", "Vacuum started for the floor clean.")
        last = [e["text"] for e in agent.bus.history if e["kind"] == "reply"][-1]
        self.assertIn(hp.DRY_NOTE, last)
        agent.say("telegram", "Logged a feed of 120 ml.")
        last = [e["text"] for e in agent.bus.history if e["kind"] == "reply"][-1]
        self.assertNotIn("Dry run", last)


class MuseTexts(unittest.TestCase):
    """Finding 4, h_brain.py H2: a code in summary and why_changed reached Telegram, and the summary named Parent B on
    duty while the plan said Parent A."""

    def test_codes_never_reach_telegram_and_the_summary_agrees_on_duty(self):
        brain, engine, house, bus, entries, spoken = day_setup(FakeMuse(answer(
            summary="Parent B is on, alarm code 4471 for grandma.",
            why_changed="Grandma arrives, the gate code is 4471 so the door stays quiet.")))
        told = []
        brain.tell = lambda text, now: told.append(text)
        brain.ask([], brain_at(0, 21, 0), house.state, "bedtime", "a visitor note")
        self.assertTrue(told)
        self.assertFalse([t for t in told if "4471" in t], told)

    def test_a_summary_that_names_the_other_parent_on_duty_is_dropped(self):
        s = {**hb.DEFAULTS, "utc_offset_h": -3}
        plan, errors, refused, dropped = hb.validate(answer(on_duty="Parent A", summary="Parent B is on duty tonight."),
                                                     brain_at(0, 21, 55), TZ, s, [])
        self.assertEqual(plan["summary"], "")
        self.assertTrue([d for d in dropped if d["to"] == "summary"])
        plan, *_ = hb.validate(answer(on_duty="Parent A", summary="Parent A takes the night, Parent B sleeps."),
                               brain_at(0, 21, 55), TZ, s, [])
        self.assertEqual(plan["summary"], "Parent A takes the night, Parent B sleeps.")

    def test_a_phone_number_in_why_changed_is_dropped(self):
        s = {**hb.DEFAULTS, "utc_offset_h": -3}
        plan, *_ = hb.validate(answer(why_changed="Grandma arrives at 22:00, call her at 099 123 456."),
                               brain_at(0, 21, 55), TZ, s, [])
        self.assertEqual(plan["why_changed"], "")


class WindowCaps(unittest.TestCase):
    """Finding 5, h_brain.py H1: twelve 60 min boosts and three 4 h door_quiet windows were all accepted."""

    def test_twelve_boosts_and_twelve_quiet_door_hours_are_refused(self):
        s = {**hb.DEFAULTS, "utc_offset_h": -3}
        noise = [{"start": f"{h:02d}:00", "end": f"{h:02d}:59", "why": "x"} for h in [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1]]
        door = [{"start": "14:00", "end": "18:00", "why": "x"}, {"start": "18:00", "end": "22:00", "why": "x"},
                {"start": "22:00", "end": "01:55", "why": "x"}]
        plan, errors, refused, _ = hb.validate(answer(white_noise_boost=noise, door_quiet=door), brain_at(0, 13, 56), TZ, s, [])
        self.assertEqual(errors, [])
        self.assertIn("white_noise_boost", refused)
        self.assertIn("door_quiet", refused)
        self.assertIsNone(plan["white_noise_boost"])
        self.assertIsNone(plan["door_quiet"])

    def test_two_boosts_and_one_quiet_door_window_stand(self):
        s = {**hb.DEFAULTS, "utc_offset_h": -3}
        noise = [{"start": "14:00", "end": "14:45", "why": "x"}, {"start": "16:00", "end": "16:30", "why": "x"}]
        plan, _, refused, _ = hb.validate(answer(white_noise_boost=noise, door_quiet=[{"start": "15:00", "end": "17:00", "why": "x"}]),
                                          brain_at(0, 13, 56), TZ, s, [])
        self.assertEqual(refused, {})
        self.assertEqual(len(plan["white_noise_boost"]), 2)
        self.assertEqual(len(plan["door_quiet"]), 1)


class BabyTabHouseWords(unittest.TestCase):
    """Finding 6, live on the baby tab: the message went to prep mode and the duty request was dropped."""

    TEXT = "I'm exhausted, let me sleep tonight. Put Parent B on duty and set the white noise to 90 dB for the night"

    def test_house_words_stay_on_the_baby_agent_and_the_duty_request_runs(self):
        self.assertFalse(is_prep(self.TEXT))
        self.assertTrue(is_prep("add a white noise machine to the nursery list"))
        brain = ScriptedBrain([[call("set_on_duty", parent="Parent B"), call("white_noise", level_db=90)],
                               "Parent B is on duty tonight. White noise at 50 dB, the cap."])
        app = demo(brain)
        self.addCleanup(app.close)
        status, body = app.message("v", False, self.TEXT)
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "baby")
        visitor = app.visitor("v")
        self.assertEqual(visitor.rota()["on_duty"], "Parent B")
        noise = [a for a in house_actions(app, "v") if a["action"] == "white_noise"]
        self.assertEqual([a["arguments"]["level_db"] for a in noise], [50.0])


if __name__ == "__main__":
    unittest.main()
