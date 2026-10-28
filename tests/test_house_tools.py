"""Home Assistant tools (issue #9): dry by default, alone tools live behind house.live, ask first, never refused.

Offline: Home Assistant is a fake that records calls. No network, no house.
"""
import json
import tempfile
import unittest
from pathlib import Path

from parenting_agent import house as house_mod
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.brain import Reply
from parenting_agent.bus import Bus
from parenting_agent.house import House, HomeAssistant, never_reason
from parenting_agent.house_tools import ALONE, ASK_FIRST, HouseTools

ROOT = Path(__file__).resolve().parent.parent
NEVER = ["switch.shellyplusplugit_bathroom", "siren.tapo_c200_sofa_siren", "switch.tapo_c200_sofa_privacy",
         "switch.tapo_c200_barbacue_privacy_zones", "number.refrigerator_fridge_temperature",
         "switch.refrigerator_express_mode", "update.shellyplusplugit_bathroom_firmware"]


class FakeHA:
    """Records every service call and moves states the way Home Assistant would."""

    def __init__(self):
        self.calls = []
        self.states = {"light.wiz_824512_192_0_2_10": "off", "switch.gonza_s_echo_dot_do_not_disturb": "off",
                       "vacuum.xiaomi_ov71gl_0681_robot_cleaner": "docked", "media_player.gonza_s_echo_dot": "idle"}

    def service(self, service, entity_id, data=None):
        self.calls.append((service, entity_id, dict(data or {})))
        moves = {"light.turn_on": "on", "light.turn_off": "off", "switch.turn_on": "on", "switch.turn_off": "off",
                 "vacuum.start": "cleaning", "vacuum.pause": "paused", "vacuum.return_to_base": "returning"}
        if service in moves and entity_id:
            self.states[entity_id] = moves[service]
        return []

    def state(self, entity_id):
        return self.states.get(entity_id, "unknown")

    def attributes(self, entity_id):
        return {"volume_level": 0.47} if entity_id == "media_player.gonza_s_echo_dot" else {}


class ScriptBrain:
    name, model, destination = "script", "script", "none (local)"

    def __init__(self, steps):
        self.steps = list(steps)

    def step(self, system, transcript, tools):
        return self.steps.pop(0) if self.steps else Reply("OK.")


def make(tmp, house=None, steps=(), allowed_extra=(), client=None):
    config = config_mod.load()
    config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "house": house or {}})
    config["allowed_tools"] = config["allowed_tools"] + list(ALONE) + list(allowed_extra)
    agent = build(config)
    agent.brain = ScriptBrain(steps)
    ha = client if client is not None else FakeHA()
    plugin = HouseTools(agent, config, client=ha)
    return agent, plugin, ha


def calls_logged(agent):
    return [e for e in agent.bus.history if e["kind"] == "house_call"]


def ask(name, **arguments):
    return Reply(tool_calls=[{"id": "c1", "name": name, "arguments": arguments}])


class DryByDefault(unittest.TestCase):
    def test_nothing_reaches_the_house_while_live_is_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, ha = make(tmp)
            self.assertFalse(plugin.live)
            self.assertIn("dry run (house.live is off)", plugin.study_light(on=True))
            plugin.vacuum_pause()
            plugin.push_gonza("Test: hello")
            self.assertEqual(ha.calls, [])
            self.assertEqual([e["status"] for e in calls_logged(agent)], ["dry", "dry", "dry"])
            agent.close()

    def test_live_must_be_exactly_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, ha = make(tmp, house={"live": "true"})
            plugin.study_light(on=True)
            self.assertEqual(ha.calls, [])
            agent.close()

    def test_no_token_stays_dry_even_when_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load()
            config.update({"data_dir": tmp, "env_file": "/nonexistent", "house": {"live": True, "ha_token_env": "PA_TEST_NO_TOKEN"}})
            agent = build(config)
            plugin = HouseTools(agent, config)
            self.assertIsNone(plugin.client)
            self.assertIn("no Home Assistant token", plugin.study_light(on=True))
            self.assertIn("nothing read", plugin.status())
            agent.close()

    def test_no_config_in_the_repo_turns_the_house_live(self):
        for path in sorted((ROOT / "config").glob("*.json")):
            house = json.loads(path.read_text()).get("house") or {}
            self.assertIsNot(house.get("live"), True, f"{path.name} must leave house.live off, Gonza turns it on")


class AloneRunsLive(unittest.TestCase):
    def test_each_alone_tool_calls_its_service_and_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, ha = make(tmp, house={"live": True, "read_back_interval_s": 0})
            self.assertEqual(plugin.study_light(on=True, brightness_pct=20, warm=True), "study_light: done, now on")
            self.assertEqual(plugin.study_light(on=False), "study_light: done, now off")
            plugin.echo_do_not_disturb(on=True)
            plugin.tv_mute(tv="living room", muted=True)
            plugin.vacuum_pause()
            plugin.vacuum_dock()
            plugin.push_gonza("Test: the agent can reach you", title="Parenting agent")
            plugin.add_to_list("diapers")
            self.assertEqual(ha.calls, [
                ("light.turn_on", "light.wiz_824512_192_0_2_10", {"brightness_pct": 20, "color_temp_kelvin": 2700}),
                ("light.turn_off", "light.wiz_824512_192_0_2_10", {}),
                ("switch.turn_on", "switch.gonza_s_echo_dot_do_not_disturb", {}),
                ("media_player.volume_mute", "media_player.lg_webos_tv_oled55b3psa", {"is_volume_muted": True}),
                ("vacuum.pause", "vacuum.xiaomi_ov71gl_0681_robot_cleaner", {}),
                ("vacuum.return_to_base", "vacuum.xiaomi_ov71gl_0681_robot_cleaner", {}),
                ("notify.mobile_app_gonzas_iphone", None, {"message": "Test: the agent can reach you", "title": "Parenting agent"}),
                ("todo.add_item", "todo.shopping_list", {"item": "diapers"})])
            logged = calls_logged(agent)
            self.assertEqual(len(logged), 8)
            self.assertTrue(all(e["status"] == "ran" and e["live"] for e in logged))
            self.assertTrue(logged[0]["confirmed"])
            agent.close()

    def test_announce_is_low_volume_and_the_volume_comes_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, ha = make(tmp, house={"live": True, "announce_volume": 0.9, "restore_after_s": 60})
            plugin.announce_kitchen("Dinner is ready")
            self.assertEqual(ha.calls[0], ("media_player.volume_set", "media_player.gonza_s_echo_dot", {"volume_level": 0.3}))
            self.assertEqual(ha.calls[1], ("notify.send_message", "notify.gonza_s_echo_dot_announce", {"message": "Dinner is ready"}))
            plugin.stop()
            self.assertEqual(ha.calls[2], ("media_player.volume_set", "media_player.gonza_s_echo_dot", {"volume_level": 0.47}))
            agent.close()

    def test_status_reads_without_changing_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, ha = make(tmp)
            states = plugin.status()
            self.assertEqual(states["light.wiz_824512_192_0_2_10"], "off")
            self.assertEqual(ha.calls, [])
            agent.close()

    def test_a_failed_call_is_reported_and_logged(self):
        class Down(FakeHA):
            def service(self, service, entity_id, data=None):
                raise OSError("connection refused")
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, _ = make(tmp, house={"live": True}, client=Down())
            self.assertIn("failed, connection refused", plugin.vacuum_pause())
            self.assertEqual(calls_logged(agent)[-1]["status"], "error")
            agent.close()

    def test_every_call_lands_in_the_event_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, _ = make(tmp, house={"live": True, "read_back_interval_s": 0})
            plugin.study_light(on=True)
            plugin.call("bad", "switch.turn_on", NEVER[0])
            lines = [json.loads(line) for line in (Path(tmp) / "events.jsonl").read_text().splitlines()]
            self.assertEqual([e["status"] for e in lines if e["kind"] == "house_call"], ["ran", "refused"])
            agent.close()


class AskFirst(unittest.TestCase):
    def test_start_vacuum_waits_for_the_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, ha = make(tmp, house={"live": True, "read_back_interval_s": 0},
                                     steps=[ask("start_vacuum"), Reply("Shall I start the vacuum?")])
            agent.handle({"kind": "message", "channel": "console", "text": "the floor is a mess"})
            self.assertEqual(ha.calls, [])
            self.assertEqual([e["name"] for e in agent.bus.history if e["kind"] == "ask_parent"], ["start_vacuum"])
            agent.handle({"kind": "message", "channel": "console", "text": "yes"})
            self.assertEqual(ha.calls, [("vacuum.start", "vacuum.xiaomi_ov71gl_0681_robot_cleaner", {})])
            agent.close()

    def test_ask_first_tools_cannot_be_put_on_the_allowed_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, _, ha = make(tmp, house={"live": True}, allowed_extra=ASK_FIRST,
                                steps=[ask("camera_floodlight", where="barbecue", on=True), Reply("Asked.")])
            self.assertFalse(set(ASK_FIRST) & agent.tools.allowed)
            agent.handle({"kind": "message", "channel": "console", "text": "light up the barbecue"})
            self.assertEqual(ha.calls, [])
            self.assertEqual(agent.bus.count("house_warning"), len(ASK_FIRST))
            agent.close()


class NeverRefused(unittest.TestCase):
    def test_never_entities_are_named(self):
        for entity in NEVER:
            self.assertIsNotNone(never_reason(entity), entity)
        for entity in ("light.wiz_824512_192_0_2_10", "vacuum.xiaomi_ov71gl_0681_robot_cleaner", None):
            self.assertIsNone(never_reason(entity))

    def test_tools_refuse_never_entities_even_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, ha = make(tmp, house={"live": True})
            for entity in NEVER:
                self.assertIn("refused", plugin.call("test", "switch.turn_off", entity))
            self.assertIn("refused", plugin.call("test", "light.turn_on", "light.some_other_light"))
            self.assertEqual(ha.calls, [])
            self.assertTrue(all(e["status"] == "refused" for e in calls_logged(agent)))
            agent.close()

    def test_skill_house_config_cannot_reach_a_never_entity(self):
        bus, ha = Bus(), FakeHA()
        house = House({"allowed": {"cut": {"service": "switch.turn_off", "entity_id": NEVER[0]}}, "on_armed": ["cut"]}, bus, client=ha)
        house.on_event("armed")
        house.close()
        self.assertEqual(ha.calls, [])
        self.assertEqual(bus.count("house_refused"), 1)


class HomeAssistantClient(unittest.TestCase):
    def test_a_service_without_a_target_sends_no_entity_id(self):
        sent = []
        client = HomeAssistant("http://ha.invalid", "not-a-real-token")
        client._call = lambda path, data=None: sent.append((path, data))
        client.service("notify.mobile_app_gonzas_iphone", None, {"message": "Test: hi"})
        client.service("light.turn_on", "light.wiz_824512_192_0_2_10")
        self.assertEqual(sent, [("/api/services/notify/mobile_app_gonzas_iphone", {"message": "Test: hi"}),
                                ("/api/services/light/turn_on", {"entity_id": "light.wiz_824512_192_0_2_10"})])
        self.assertTrue(house_mod.NEVER_ENTITIES)


if __name__ == "__main__":
    unittest.main()
