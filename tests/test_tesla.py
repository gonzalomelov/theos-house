"""The Tesla (issue #31) on the simulated Model 3 and the synthetic drive sample. Offline: no car, no network."""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.brain import Reply
from parenting_agent.house import HomeAssistant
from parenting_agent.tesla import __main__ as demo
from parenting_agent.tesla import entities
from parenting_agent.tesla.car import Car, SimulatedTesla, Unavailable
from parenting_agent.tesla.trips import CarTrips, cabin_target, drives

STRINGS = Path(__file__).parent / "fixtures" / "tesla_fleet_strings.json"
SAMPLE = demo.SAMPLE
TZ = datetime.timezone(datetime.timedelta(hours=-3))
BEFORE_DRIVE = datetime.datetime(2026, 10, 24, 13, 45, tzinfo=TZ)
SECRET_ENV = {"HA_MCP_TOKEN": "not-a-real-token"}


class ScriptBrain:
    name, model, destination = "script", "script", "none (local)"

    def __init__(self, steps):
        self.steps = list(steps)

    def step(self, system, transcript, tools):
        return self.steps.pop(0) if self.steps else Reply("OK.")


class FakeHA:
    """Home Assistant as the real tesla_fleet car would answer: records every service call, nothing else."""
    simulated = False

    def __init__(self):
        self.calls = []
        self.ids = entities.entity_ids("Model 3")

    def service(self, service, entity_id, data=None):
        self.calls.append((service, entity_id, dict(data or {})))

    def state(self, entity_id):
        return {self.ids["shift_state"]: "p", self.ids["inside_temp"]: "14.5"}.get(entity_id, "unknown")

    def attributes(self, entity_id):
        return {"temperature": 8.0} if entity_id == "weather.forecast_home" else {}

    def calendar_events(self, entity_id, start, end):
        return []


def make(tmp, car_cfg=None, steps=(), allowed_extra=()):
    config = config_mod.load()
    config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"},
                   "car": {"backend": "simulated", "parent_channel": "console", **(car_cfg or {})}})
    config["allowed_tools"] = config["allowed_tools"] + ["cabin_ready", "car_status", *allowed_extra]
    agent = build(config)
    agent.brain = ScriptBrain(steps)
    replies = []
    agent.bus.subscribe(lambda e: replies.append(e["text"]), ["reply"])
    clock = {"now": BEFORE_DRIVE}
    plugin = CarTrips(agent, config, clock=lambda: clock["now"])
    return agent, plugin, clock, replies


def say(agent, text):
    agent.handle({"kind": "message", "channel": "console", "text": text})


def replay(plugin, clock, rows):
    for row in rows:
        clock["now"] = datetime.datetime.fromisoformat(row["t"])
        plugin.car.client.play(row)
        plugin.tick(clock["now"])


def events(agent, kind):
    return [e for e in agent.bus.history if e["kind"] == kind]


class NamesMatchTeslaFleet(unittest.TestCase):
    def setUp(self):
        self.strings = json.loads(STRINGS.read_text())["entity"]

    def test_every_entity_is_named_as_tesla_fleet_names_it(self):
        for role, (domain, suffix, key) in entities.ENTITIES.items():
            name = self.strings[domain][key]["name"].replace("[%key:component::climate::title%]", "Climate")
            self.assertEqual(entities.slugify(name), suffix, role)

    def test_entity_ids_follow_the_car_name(self):
        ids = entities.entity_ids("Model 3")
        self.assertEqual(ids["battery_level"], "sensor.model_3_battery_level")
        self.assertEqual(ids["climate"], "climate.model_3_climate")
        self.assertEqual(ids["location"], "device_tracker.model_3_location")
        self.assertEqual(ids["shift_state"], "sensor.model_3_shift_state")
        self.assertEqual(ids["seat_heater_rear_left"], "select.model_3_seat_heater_rear_left")
        self.assertEqual(entities.entity_ids("Mi Tesla")["preconditioning"], "binary_sensor.mi_tesla_preconditioning")

    def test_states_and_options_match(self):
        self.assertEqual(sorted(self.strings["sensor"]["drive_state_shift_state"]["state"]), sorted(entities.SHIFT_STATES))
        self.assertEqual(sorted(self.strings["select"]["climate_state_seat_heater_rear_left"]["state"]),
                         sorted(entities.SEAT_LEVELS))
        presets = self.strings["climate"]["driver_temp"]["state_attributes"]["preset_mode"]["state"]
        self.assertEqual(sorted(presets), sorted(entities.CLIMATE_PRESETS))

    def test_simulated_car_has_every_entity(self):
        sim = SimulatedTesla()
        for entity_id in entities.entity_ids().values():
            sim.state(entity_id)
        self.assertTrue(sim.attributes(entities.entity_ids()["battery_level"])["simulated"])


class BackendSwitch(unittest.TestCase):
    def test_simulated_by_default(self):
        car = Car({})
        self.assertIsInstance(car.client, SimulatedTesla)
        self.assertTrue(car.simulated)
        self.assertIn("simulated", car.label)

    def test_home_assistant_by_config_only(self):
        car = Car({"backend": "home_assistant"}, env=SECRET_ENV)
        self.assertIsInstance(car.client, HomeAssistant)
        self.assertFalse(car.simulated)
        self.assertNotIn("simulated", car.label)

    def test_home_assistant_without_env_or_unknown_backend_fails_at_start(self):
        with self.assertRaises(Unavailable):
            Car({"backend": "home_assistant"}, env={})
        with self.assertRaises(Unavailable):
            Car({"backend": "tessie"}, env=SECRET_ENV)

    def test_real_car_gets_the_same_commands_as_the_simulated_one(self):
        sim, real = Car({}), Car({"live_commands": True}, client=FakeHA())
        sim.precondition(22, keep_seat_off="rear_center")
        real.precondition(22, keep_seat_off="rear_center")
        self.assertEqual(sim.client.calls, real.client.calls)

    def test_real_car_stays_dry_until_live_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, _, _, _ = make(tmp)
            client = FakeHA()
            car = Car({}, agent.bus, client=client)
            self.assertEqual(car.precondition(22)["result"], "dry")
            self.assertEqual(client.calls, [])
            self.assertEqual(len(events(agent, "car_dry")), 2)
            self.assertEqual(car.child_left_alone()["status"], "unknown")
            agent.close()


class CabinReady(unittest.TestCase):
    def test_target_from_outside_temperature(self):
        self.assertEqual(cabin_target(3), 22.0)
        self.assertEqual(cabin_target(18), 21.0)
        self.assertEqual(cabin_target(31), 20.0)
        self.assertEqual(cabin_target(None), 21.0)

    def test_reads_weather_forecast_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, _, _ = make(tmp, {"simulated": {"outside_c": 31, "inside_c": 38}})
            text = plugin.cabin_ready(leave_in_min=15)
            self.assertIn("Cool the cabin to 20 C", text)
            self.assertIn("31 C outside", text)
            agent.close()

    def test_we_leave_in_15_waits_for_yes(self):
        call = {"id": "1", "name": "cabin_ready", "arguments": {"leave_in_min": 15}}
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, _, replies = make(tmp, steps=[Reply("", [call]), Reply("Asked."), Reply("OK.")])
            sim = plugin.car.client
            say(agent, "we leave in 15")
            self.assertEqual(sim.calls, [])
            self.assertEqual(sim.state(plugin.car.ids["climate"]), "off")
            self.assertEqual([c["name"] for c in agent.pending], ["precondition_car"])
            say(agent, "hold on")
            self.assertEqual(sim.calls, [])
            say(agent, "yes")
            self.assertEqual(sim.state(plugin.car.ids["climate"]), "heat_cool")
            self.assertEqual(sim.attributes(plugin.car.ids["climate"])["temperature"], 22.0)
            self.assertEqual(sim.state(plugin.car.ids["seat_heater_rear_center"]), "off")
            done = events(agent, "car_precondition")
            self.assertEqual(len(done), 1)
            self.assertTrue(done[0]["approved_by_parent"] and done[0]["simulated"])
            self.assertIn("simulated", replies[-1])
            agent.close()

    def test_brain_cannot_precondition_on_its_own(self):
        call = {"id": "1", "name": "precondition_car", "arguments": {"target_c": 22}}
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, _, _ = make(tmp, steps=[Reply("", [call]), Reply("Asked.")], allowed_extra=["precondition_car"])
            self.assertNotIn("precondition_car", agent.tools.allowed)
            say(agent, "warm the car")
            self.assertEqual(plugin.car.client.calls, [])
            self.assertEqual(len(events(agent, "ask_parent")), 1)
            agent.close()

    def test_calendar_trip_with_the_baby_is_proposed_once(self):
        soon = (BEFORE_DRIVE + datetime.timedelta(minutes=10)).isoformat()
        calendar = [{"summary": "Pediatrician checkup with the baby", "start": soon},
                    {"summary": "Dentist", "start": soon}]
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, _, replies = make(tmp, {"trip_calendar": "calendar.family", "simulated": {"calendar": calendar}})
            plugin.tick(BEFORE_DRIVE)
            plugin.tick(BEFORE_DRIVE + datetime.timedelta(minutes=1))
            self.assertEqual(len(events(agent, "car_proposal")), 1)
            self.assertIn("Pediatrician checkup", replies[0])
            self.assertEqual(plugin.car.client.calls, [])
            agent.close()

    def test_disabled_seat_entity_does_not_undo_the_climate(self):
        class NoSeatHA(FakeHA):
            def service(self, service, entity_id, data=None):
                if service == "select.select_option":
                    raise ValueError("400: entity disabled")
                super().service(service, entity_id, data)
        client = NoSeatHA()
        done = Car({"live_commands": True}, client=client).precondition(22, keep_seat_off="rear_center")
        self.assertEqual(done["seat_off"], "failed")
        self.assertEqual([c[0] for c in client.calls], ["climate.set_temperature", "climate.turn_on"])

    def test_seat_under_the_car_seat_is_never_heated(self):
        car = Car({"car_seat": "rear_left"})
        with self.assertRaises(ValueError):
            car.set_seat_heater("rear_left", "low")
        car.set_seat_heater("front_left", "low")


class CarNaps(unittest.TestCase):
    def setUp(self):
        self.sample = json.loads(SAMPLE.read_text())

    def test_sample_is_labeled_synthetic(self):
        self.assertTrue(self.sample["synthetic"])
        self.assertIn("SYNTHETIC", self.sample["label"])

    def test_drives_in_the_recorded_sample(self):
        found = [{k: v.isoformat() for k, v in d.items()} for d in drives(self.sample["rows"])]
        self.assertEqual(found, self.sample["expected_drives"])

    def test_car_nap_is_proposed_and_logged_only_after_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, clock, replies = make(tmp)
            plugin.cabin_ready(leave_in_min=15)
            say(agent, "yes")
            replay(plugin, clock, self.sample["rows"])
            self.assertEqual(agent.baby_log.entries("sleep"), [])
            nap = [c for c in agent.pending if c["name"] == "log_car_nap"]
            self.assertEqual(nap[0]["arguments"], {"start": "2026-10-24T14:05-03:00", "end": "2026-10-24T14:40-03:00"})
            self.assertIn("Did the baby sleep on the drive, 14:05 to 14:40?", replies[-1])
            self.assertIn("Check the back seat", replies[-1])
            say(agent, "yes")
            sleeps = agent.baby_log.entries("sleep")
            self.assertEqual(len(sleeps), 1)
            self.assertEqual(sleeps[0]["details"]["start"], "2026-10-24T14:05-03:00")
            self.assertTrue(events(agent, "car_nap_logged")[0]["approved_by_parent"])
            agent.close()

    def test_no_nap_question_without_a_baby_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, clock, replies = make(tmp)
            replay(plugin, clock, self.sample["rows"])
            self.assertEqual(len(events(agent, "car_drive")), 1)
            self.assertEqual(replies, [])
            self.assertEqual(agent.pending, [])
            agent.close()

    def test_short_drive_gets_the_back_seat_reminder_only(self):
        rows = [r for r in self.sample["rows"] if not ("14:10" <= r["t"][11:16] < "14:38")]
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, clock, replies = make(tmp, {"nap_min_drive_min": 40})
            plugin.cabin_ready(leave_in_min=15)
            say(agent, "yes")
            replay(plugin, clock, rows)
            self.assertIn("Check the back seat", replies[-1])
            self.assertNotIn("sleep", replies[-1])
            self.assertFalse([c for c in agent.pending if c["name"] == "log_car_nap"])
            agent.close()


class ChildLeftAlone(unittest.TestCase):
    def test_off_flag_is_in_the_proposal_without_claiming_the_car_has_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, _, _ = make(tmp, {"simulated": {"child_left_alone": False}})
            text = plugin.cabin_ready(leave_in_min=15)
            self.assertIn("Child Left Alone Detection is off (simulated flag)", text)
            self.assertIn("2025.14.12 on some models only", text)
            self.assertNotIn("2027", text)
            self.assertEqual(plugin.status()["child_left_alone"]["status"], "off")
            agent.close()


class DemoIsLabeled(unittest.TestCase):
    def test_every_car_line_says_simulated(self):
        report = demo.run()
        self.assertIn("SIMULATED", report["label"])
        car_lines = [line["text"] for line in report["transcript"]
                     if line["who"] == "agent" and ("Tesla" in line["text"] or "car" in line["text"].lower())]
        self.assertTrue(car_lines)
        for text in car_lines:
            if "Tesla" in text:
                self.assertIn("simulated Tesla", text)
        self.assertEqual(len(report["naps_logged"]), 1)


if __name__ == "__main__":
    unittest.main()
