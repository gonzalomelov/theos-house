"""The per-action live allowlist (Oct 30): only the night feed's study light and nap mode's vacuum pause and dock run
for real, and only when listed in house.live_actions. Everything else stays a dry run.

Offline: Home Assistant is the recording fake from test_house_tools. No network, no house.
"""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from parenting_agent import day_engine as de
from parenting_agent import house_live as hl
from parenting_agent.bus import Bus
from parenting_agent.house_plan import DRY_NOTE, OTHERS_DRY_NOTE, dry_reply
from parenting_agent.night_feed import NightFeed
from parenting_agent.white_noise import SimulatedWhiteNoise
from tests.test_home_automations import Clock, at, events, make_agent, night_log
from tests.test_house_tools import FakeHA

ROOT = Path(__file__).resolve().parent.parent
BOTH = ["night_feed_light", "nap_mode_vacuum"]


def gate(listed=BOTH, client=None, caps=None):
    bus = Bus()
    ha = client if client is not None else FakeHA()
    return hl.LiveGate(bus, {"live_actions": listed, **({"live_caps": caps} if caps else {})}, ha), ha, bus


def live(bus, status=None):
    return [e for e in bus.history if e["kind"] == "house_live" and (status is None or e["status"] == status)]


class AllowlistTest(unittest.TestCase):
    def test_empty_by_default_so_everything_stays_dry(self):
        g, ha, bus = gate(listed=[])
        self.assertIsNone(g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {}, "test", "cry"))
        self.assertIsNone(g.write("nap_mode", "vacuum.pause", hl.VACUUM, None, "test", hl.SLEEP_START))
        self.assertEqual(ha.calls, [])
        self.assertEqual(live(bus), [])

    def test_listed_actions_run_for_real_and_are_logged(self):
        g, ha, bus = gate()
        self.assertEqual(g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {"brightness_pct": 10}, "awake", "cry")["status"], "ran")
        self.assertEqual(g.write("nap_mode", "vacuum.pause", hl.VACUUM, None, "nap", hl.SLEEP_START)["status"], "ran")
        self.assertEqual(g.write("nap_mode", "vacuum.return_to_base", hl.VACUUM, None, "nap", hl.SLEEP_START)["status"], "ran")
        self.assertEqual([c[:2] for c in ha.calls], [("light.turn_on", hl.STUDY_LIGHT), ("vacuum.pause", hl.VACUUM),
                                                     ("vacuum.return_to_base", hl.VACUUM)])
        for e in live(bus, "ran"):
            self.assertTrue(e["entity"] and e["service"] and e["reason"] and e["routine"])

    def test_the_light_goes_on_dim_and_warm_whatever_is_asked(self):
        g, ha, _ = gate()
        g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {"brightness_pct": 100, "rgb_color": [255, 0, 0]}, "x", "cry")
        self.assertEqual(ha.calls[0][2], {"brightness_pct": hl.MAX_LIGHT_PCT, "color_temp_kelvin": hl.WARM_KELVIN})

    def test_an_unlisted_action_stays_dry(self):
        g, ha, _ = gate(listed=["nap_mode_vacuum"])
        self.assertIsNone(g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {}, "awake", "cry"))
        g, ha, _ = gate(listed=["night_feed_light", "white_noise", "tv_mute"])
        self.assertIsNone(g.write("nap_mode", "vacuum.pause", hl.VACUUM, None, "nap", hl.SLEEP_START))
        for routine, service, entity in [("nap_mode", "media_player.volume_mute", "media_player.lg_webos_tv_oled55b3psa"),
                                         ("nap_mode", "switch.turn_on", de.ECHO_DND),
                                         ("door", "notify.send_message", de.ECHO_ANNOUNCE),
                                         ("supplies", "todo.add_item", de.SHOPPING),
                                         ("house_tools", "light.turn_on", hl.STUDY_LIGHT),
                                         ("nap_mode", "light.turn_on", hl.STUDY_LIGHT)]:
            self.assertIsNone(g.write(routine, service, entity, None, "x", "cry"), (routine, service))
        self.assertEqual(ha.calls, [])

    def test_a_guess_never_turns_the_light_on(self):
        g, ha, bus = gate()
        for signal in (None, "rhythm", "plan", "prewarm", "wind_down"):
            self.assertIsNone(g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {}, "guess", signal))
        self.assertEqual(ha.calls, [])
        self.assertEqual(len(live(bus, "refused")), 5)

    def test_start_and_resume_of_the_vacuum_are_always_refused(self):
        g, ha, bus = gate()
        for routine in ("nap_mode", "floor_clean"):
            for service in ("vacuum.start", "vacuum.clean_area"):
                self.assertIsNone(g.write(routine, service, hl.VACUUM, None, "x", hl.SLEEP_START))
        # the catalog itself never names a start
        self.assertNotIn("vacuum.start", sum((list(s["services"]) for s in hl.CATALOG.values()), []))
        self.assertEqual(ha.calls, [])
        self.assertEqual(len(live(bus, "refused")), 4)

    def test_the_vacuum_only_pauses_when_a_sleep_starts(self):
        g, ha, _ = gate()
        self.assertIsNone(g.write("nap_mode", "vacuum.pause", hl.VACUUM, None, "asked", None))
        self.assertEqual(ha.calls, [])

    def test_rate_limits(self):
        g, ha, bus = gate()
        night = at(21, 1, 0)
        ran = [g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {}, "x", "cry", night + datetime.timedelta(minutes=i))
               for i in range(8)]
        self.assertEqual(sum(1 for e in ran if e), 6)
        self.assertEqual(len(live(bus, "rate_limited")), 2)
        # 22:00 the evening before and 03:00 are the same night, the next noon starts a new one
        self.assertIsNotNone(g.write("night_feed", "light.turn_off", hl.STUDY_LIGHT, None, "x", "wind_down", at(21, 13, 0)))
        day = at(22, 9, 0)
        vac = [g.write("nap_mode", "vacuum.pause", hl.VACUUM, None, "nap", hl.SLEEP_START, day + datetime.timedelta(hours=i))
               for i in range(6)]
        self.assertEqual(sum(1 for e in vac if e), 4)
        self.assertIsNotNone(g.write("nap_mode", "vacuum.pause", hl.VACUUM, None, "nap", hl.SLEEP_START, at(23, 9, 0)))

    def test_a_config_cap_can_only_lower_the_code_cap(self):
        g, _, _ = gate(caps={"night_feed_light": 50, "nap_mode_vacuum": 2, "shopping_list_add": 99})
        self.assertEqual(g.caps, {"night_feed_light": 6, "nap_mode_vacuum": 2, "shopping_list_add": 6})

    def test_the_never_list_is_kept(self):
        g, ha, _ = gate()
        for entity in ("siren.tapo_c200_sofa_siren", "switch.shellyplusplugit_bathroom"):
            self.assertIsNone(g.write("night_feed", "light.turn_on", entity, {}, "x", "cry"))
        self.assertEqual(ha.calls, [])

    def test_an_unavailable_device_gets_nothing_sent_and_no_claim(self):
        g, ha, bus = gate()
        ha.states[hl.STUDY_LIGHT] = "unavailable"
        self.assertEqual(g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {}, "awake", "cry")["status"], "unavailable")
        self.assertEqual(ha.calls, [])
        self.assertEqual(g.claims(), [])
        self.assertIn(DRY_NOTE, dry_reply("I turned the light on.", g.claims()))

    def test_no_token_stays_dry(self):
        g = hl.LiveGate(Bus(), {"live_actions": BOTH}, None)
        self.assertIsNone(g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {}, "x", "cry"))

    def test_only_the_vostro_config_lists_live_actions_and_house_live_stays_off(self):
        for path in sorted((ROOT / "config").glob("*.json")):
            house = json.loads(path.read_text()).get("house") or {}
            self.assertIsNot(house.get("live"), True, path.name)
            expected = [*BOTH, "shopping_list_add"] if path.name == "agent.vostro.json" else []
            self.assertEqual(house.get("live_actions") or [], expected, path.name)


class RepliesTest(unittest.TestCase):
    def test_a_real_write_is_never_called_a_dry_run(self):
        g, _, _ = gate()
        now = at(21, 3, 10)
        g.clock = lambda: now
        g.write("night_feed", "light.turn_on", hl.STUDY_LIGHT, {}, "awake", "cry", now)
        text = dry_reply("I turned the light on for you.", g.claims())
        self.assertIn("Done for real: the study light went on, dim and warm at 03:10.", text)
        self.assertNotIn(DRY_NOTE, text)
        both = dry_reply("Light is on and white noise turned down.", g.claims())
        self.assertIn("Done for real", both)
        self.assertIn(OTHERS_DRY_NOTE, both)

    def test_without_a_real_write_the_reply_says_written_down(self):
        g, _, _ = gate()
        self.assertIn(DRY_NOTE, dry_reply("I paused the vacuum.", g.claims()))
        self.assertIn(DRY_NOTE, dry_reply("I muted the TV and turned on white noise.", g.claims()))


class NightFeedLiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.config["house"] = {"live_actions": ["night_feed_light"]}
        self.ha = FakeHA()
        self.clock = Clock(at(21, 1, 0))
        self.log = night_log()
        self.feed = NightFeed(self.agent, self.config, log=self.log, clock=self.clock, client=self.ha)
        self.agent.plugins = [self.feed]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_a_guess_never_switches_the_light(self):
        self.feed.tick(at(21, 1, 50))  # the rhythm pre-warm
        self.feed.tick(at(21, 4, 0))  # closes quietly
        self.assertEqual(self.ha.calls, [])

    def test_a_real_awake_signal_turns_the_light_on_dim_and_off_after_the_feed(self):
        self.clock.moment = at(21, 2, 0)
        self.agent.bus.publish("message", channel="telegram", text="he's up")
        self.assertEqual(self.ha.calls, [("light.turn_on", hl.STUDY_LIGHT, {"brightness_pct": 10, "color_temp_kelvin": 2700})])
        push = events(self.agent, "night_feed", step="push")[-1]["text"]
        self.assertIn("Study light on, dim and warm: done for real.", push)
        self.assertIn("Bottle warmer on: only written down (dry run).", push)
        self.log.add_feed(at(21, 2, 5))
        for minute in range(1, 45):
            self.feed.tick(at(21, 2, 5) + datetime.timedelta(minutes=minute))
        self.assertEqual([c[0] for c in self.ha.calls], ["light.turn_on", "light.turn_off"])
        self.assertEqual([e["service"] for e in events(self.agent, "house_live", status="ran")],
                         ["light.turn_on", "light.turn_off"])
        self.assertTrue(all(e["status"] == "dry" for e in events(self.agent, "house_call")))

    def test_an_unavailable_light_is_said_plainly_in_the_push(self):
        self.ha.states[hl.STUDY_LIGHT] = "unavailable"
        self.feed.awake(at(21, 2, 0), "button", "tapped")
        self.assertEqual(self.ha.calls, [])
        self.assertIn("Study light: unavailable in Home Assistant, nothing moved.",
                      events(self.agent, "night_feed", step="push")[-1]["text"])

    def test_a_light_that_went_on_dry_is_never_switched_off_for_real(self):
        self.feed.gate.caps["night_feed_light"] = 0
        self.feed.awake(at(21, 2, 0), "button", "tapped")
        self.feed.wind_down(at(21, 2, 40), "test", None)
        self.assertEqual(self.ha.calls, [])
        self.assertIn("only written down", events(self.agent, "night_feed", step="push")[-1]["text"])


class NapModeLiveTest(unittest.TestCase):
    def engine(self, listed=BOTH):
        bus, ha = Bus(), FakeHA()
        g = hl.LiveGate(bus, {"live_actions": listed}, ha)
        engine = de.DayEngine(bus, de.DayWriter(bus, client=ha, live=False, gate=g), {"utc_offset_h": -3, "supplies": {}},
                              None, SimulatedWhiteNoise(bus))
        return engine, ha, bus

    def house(self, vacuum):
        house = de.empty_house()
        house["vacuum"] = vacuum
        house["tvs"]["media_player.lg_webos_tv_oled55b3psa"] = {"on": True, "muted": False}
        return house

    def sleep_from(self, moment, end=None):
        return [{"kind": "sleep", "start": moment.isoformat(), "end": end.isoformat() if end else None, "ref": "sleep#1"}]

    def test_a_nap_pauses_and_docks_for_real_and_everything_else_stays_dry(self):
        engine, ha, bus = self.engine()
        start = at(22, 10, 0)
        engine.tick(self.sleep_from(start), start + datetime.timedelta(minutes=1), self.house("cleaning"))
        self.assertEqual([c[0] for c in ha.calls], ["vacuum.pause", "vacuum.return_to_base"])
        dry = {e["action"] for e in bus.history if e["kind"] == "house_dry"}
        self.assertEqual(dry, {"media_player.volume_mute", "switch.turn_on"})

    def test_a_docked_vacuum_gets_nothing(self):
        engine, ha, bus = self.engine()
        start = at(22, 10, 0)
        engine.tick(self.sleep_from(start), start + datetime.timedelta(minutes=1), self.house("docked"))
        self.assertEqual(ha.calls, [])
        self.assertFalse([e for e in bus.history if e["kind"] == "house_dry" and e["entity"] == de.VACUUM])

    def test_waking_never_resumes_the_vacuum_for_real(self):
        engine, ha, bus = self.engine()
        start, end = at(22, 10, 0), at(22, 10, 40)
        house = self.house("cleaning")
        house["vacuum_left_min"] = 10
        engine.tick(self.sleep_from(start), start + datetime.timedelta(minutes=1), house)
        house["vacuum"] = "docked"
        engine.tick(self.sleep_from(start, end), end + datetime.timedelta(minutes=1), house)
        self.assertNotIn("vacuum.start", [c[0] for c in ha.calls])
        self.assertTrue([e for e in bus.history if e["kind"] == "house_dry" and e["action"] == "vacuum.start"])
        self.assertTrue(live(bus, "refused"))

    def test_unlisted_nap_mode_stays_dry(self):
        engine, ha, _ = self.engine(listed=[])
        start = at(22, 10, 0)
        engine.tick(self.sleep_from(start), start + datetime.timedelta(minutes=1), self.house("cleaning"))
        self.assertEqual(ha.calls, [])


if __name__ == "__main__":
    unittest.main()
