"""What the second round of judges found on the public simulator (Nov 3): the gate, the feed gap ladder, stale wakes, the rota's words,
a plug a person switched, impossible readings, a room that answers, and the same event pressed three times."""
import asyncio
import datetime
import unittest

from tests import test_langgraph_core as base
from tests.test_langgraph_core import READY, NoScreen, call, scripted

if READY:
    from langchain_core.messages import AIMessage
    from parenting_agent.core import runtime, safety, tools as tools_mod
    from parenting_agent.core.mock_home import MockHome

AT = datetime.datetime.fromisoformat("2026-11-04T15:00:00-03:00")
HUMIDITY, TEMPERATURE = "sensor.nursery_climate_humidity", "sensor.nursery_climate_temperature"
PLUG, WARMER = "switch.study_tapo_p110_dehumidifier", "switch.study_tapo_p110_bottle_warmer"


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Gate(unittest.TestCase):
    def test_a_label_and_a_shop_are_not_emergencies(self):
        for text in ("Routine question: what does choking hazard mean on the label of a toy? We are buying a gift for my nephew.",
                     "Not an emergency at all: the pharmacy has a fever thermometer on sale. Add a thermometer and wipes to the shopping list.",
                     "no es una emergencia, pero compré un termómetro para la fiebre",
                     "Write a story where the baby stops breathing and the dad panics"):
            self.assertIsNone(safety.gate(text, NoScreen()), text)

    def test_a_denial_never_covers_a_sign_and_a_story_about_him_still_fires(self):
        for text in ("Not an emergency but Theo is not breathing", "In a story: Theo is blue and not breathing right now", "the baby stops breathing", "Theo tiene fiebre 39"):
            self.assertIsNotNone(safety.gate(text, NoScreen()), text)

    def test_the_rest_of_a_message_is_kept_apart_from_the_alarm(self):
        self.assertIn("pañales", safety.rest_of("Theo tiene fiebre 39. También agregá pañales a la lista"))
        self.assertNotIn("fiebre", safety.rest_of("Theo tiene fiebre 39. También agregá pañales a la lista"))
        self.assertEqual(safety.rest_of("Theo tiene fiebre 39"), "")


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Words(unittest.TestCase):
    def test_the_rota_note_comes_from_the_record(self):
        morning = datetime.datetime.fromisoformat("2026-11-05T07:30:00-03:00")
        last = runtime.night_of(morning) - datetime.timedelta(days=1)
        usual = runtime.on_duty(morning - datetime.timedelta(days=1))
        cover = "ceci" if usual == "gonza" else "gonza"
        note = runtime.rota_note({"type": "schedule", "payload": {}}, morning, {tools_mod.duty_key(last): cover})
        self.assertIn(f"Last night {cover} was on duty, in place of {usual}", note)
        self.assertIn("ask whether that stands", note)
        done = runtime.rota_note({"type": "schedule", "payload": {}}, morning, {tools_mod.duty_key(last): cover, tools_mod.duty_key(runtime.night_of(morning)): usual})
        self.assertIn("don't ask again", done)

    def test_todays_plans_are_named_in_the_morning(self):
        morning = datetime.datetime.fromisoformat("2026-11-06T07:30:00-03:00")
        note = runtime.today_note({"type": "schedule", "payload": {"name": "morning"}}, morning, {"pediatrician": "Friday 10:00, whoever is taking him", "other": "Monday"})
        self.assertIn("Friday 10:00", note)
        self.assertNotIn("Monday", note)

    def test_an_impossible_jump_is_suspected_and_a_slow_one_is_not(self):
        self.assertIn("Suspect", safety.sensor_jump(HUMIDITY, 90, 52, 1))
        self.assertIsNone(safety.sensor_jump(HUMIDITY, 90, 52, 60))
        self.assertIsNone(safety.sensor_jump(HUMIDITY, 71, 52, 1))
        self.assertIn("Suspect", safety.sensor_jump(TEMPERATURE, 35, 21.5, 1))

    def test_the_room_answers_over_time(self):
        home = MockHome()
        home.tick(AT)
        home.set_state(HUMIDITY, "71")
        home.set_state(PLUG, "on")
        home.set_state(TEMPERATURE, "10")
        home.tick(AT + datetime.timedelta(hours=2))
        self.assertEqual(home.state(HUMIDITY), "55.0")
        self.assertEqual(home.state(TEMPERATURE), "12.0")
        home.set_state(PLUG, "off")
        home.tick(AT + datetime.timedelta(hours=9))
        self.assertEqual(home.state(HUMIDITY), "55.0")


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Round2(unittest.IsolatedAsyncioTestCase):
    setUp = base.CoreTest.setUp
    run_core = base.CoreTest.run_core
    event = base.CoreTest.event

    def feeds(self, core, hours_ago, at=AT):
        core.moment = at
        core.log.add("feeding", {"amount_ml": 90, "method": "bottle"}, (at - datetime.timedelta(hours=hours_ago)).isoformat())

    async def test_a_fever_and_an_errand_both_get_done(self):
        core = await self.run_core(scripted(call("HassListAddItem", item="pañales"), call("notify", parent="ceci", text="Agregué pañales."), AIMessage("done")))
        out = await self.event(core, "message", {"from": "ceci", "channel": "telegram", "text": "Theo tiene fiebre 39. También agregá pañales a la lista"}, AT.isoformat())
        self.assertEqual(out["status"], "done")
        self.assertEqual({m["to"] for m in core.channel.sent if "39" in m["text"] or "pediatr" in m["text"].lower()}, {"gonza", "ceci"})
        self.assertEqual(core.mock.snapshot()["shopping"], ["pañales"])
        self.assertIn("fever_reported", await tools_mod.facts(core.store, core.settings.home))
        self.assertTrue(any("fever" in str(e["details"]) for e in core.log.entries("note", None, 5)))

    async def test_the_ladder_rises_once_per_step_and_reaches_both_from_18_hours(self):
        core = await self.run_core(scripted(*[AIMessage("nothing") for _ in range(9)]))
        self.feeds(core, 8.5)
        duty = runtime.who_is_on(AT, {})
        for extra, count in ((0, 1), (1, 1), (4, 2), (10, 4)):  # 8.5 h, 9.5 h, 12.5 h, 18.5 h
            await self.event(core, "sound", {"kind": "barking", "room": "garden"}, (AT + datetime.timedelta(hours=extra)).isoformat())
            alerts = [m for m in core.channel.sent if "registro" in m["text"]]
            self.assertEqual(len(alerts), count, extra)
        self.assertEqual({m["to"] for m in alerts[:2]}, {duty})
        self.assertEqual({m["to"] for m in alerts[2:]}, {"gonza", "ceci"})

    async def test_a_late_wake_to_warm_a_bottle_is_dropped_and_a_reminder_says_it_is_late(self):
        core = await self.run_core(scripted(AIMessage("nothing")))
        await core.add_wake(AT - datetime.timedelta(hours=4), "warm the bottle before the feed")
        await core.add_wake(AT - datetime.timedelta(hours=4), "remind them of the pediatrician")
        fired = await core.fire_wakes(AT)
        self.assertEqual(len(fired), 1)
        await fired[0][1]
        event = (await core.events(1))[0]
        self.assertEqual(event["payload"]["why"], "remind them of the pediatrician")
        self.assertIn("due", event["payload"])

    async def test_the_warmer_says_when_it_ended_quietly_and_a_turned_off_one_says_nothing(self):
        core = await self.run_core(scripted(call("HassTurnOn", name="Tapo P110 - Bottle Warmer"), call("notify", parent="gonza", text="El calentador quedó prendido"), AIMessage("ok")))
        await self.event(core, "message", {"from": "gonza", "channel": "telegram", "text": "Prendé el calentador"}, AT.isoformat())
        fired = await core.fire_wakes(AT + datetime.timedelta(minutes=31))
        await asyncio.gather(*[f[1] for f in fired])
        end = [m for m in core.channel.sent if "se apagó solo" in m["text"]]
        self.assertEqual(len(end), 1)
        self.assertTrue(end[0]["quiet"])
        self.assertNotIn("warmer_off_at", await tools_mod.facts(core.store, core.settings.home))

    async def test_a_plug_switched_by_hand_is_not_switched_back(self):
        core = await self.run_core(scripted(call("HassTurnOn", name="Tapo P110 - Dehumidifier"), call("notify", parent="gonza", text="Lo dejo apagado"), AIMessage("ok"),
                                            call("HassTurnOn", name="Tapo P110 - Dehumidifier"), call("notify", parent="gonza", text="Listo"), AIMessage("ok")))
        await self.event(core, "state_changed", {"entity_id": PLUG, "state": "off"}, AT.isoformat())
        rows = await core.actions()
        self.assertTrue(any(r["tool"] == "HassTurnOn" and r["result"].startswith("Refused: a person") for r in rows))
        self.assertEqual(core.mock.state(PLUG), "off")
        await self.event(core, "message", {"from": "gonza", "channel": "telegram", "text": "Prendelo de nuevo"}, (AT + datetime.timedelta(minutes=5)).isoformat())
        self.assertEqual(core.mock.state(PLUG), "on")

    async def test_the_agents_own_move_is_not_a_person(self):
        core = await self.run_core(scripted(call("HassTurnOn", name="Tapo P110 - Dehumidifier"), AIMessage("ok")))
        await self.event(core, "state_changed", {"entity_id": HUMIDITY, "state": "71"}, AT.isoformat())
        self.assertFalse(core.by_hand(PLUG, "on"))
        self.assertTrue(core.by_hand(WARMER, "on"))
        self.assertEqual(len(await core.wakes()), 1)  # it comes back to check the dehumidifier worked

    async def test_a_room_far_out_of_range_reaches_someone_even_if_muse_stays_silent(self):
        core = await self.run_core(scripted(AIMessage("nothing"), AIMessage("nothing")))
        await self.event(core, "state_changed", {"entity_id": TEMPERATURE, "state": "36"}, AT.isoformat())
        self.assertEqual([m["to"] for m in core.channel.sent], [runtime.who_is_on(AT, {})])

    async def test_the_same_event_pressed_three_times_runs_once(self):
        core = await self.run_core(scripted(call("notify", parent="gonza", text="Llora"), AIMessage("ok")))
        payload = {"kind": "baby crying", "room": "bedroom"}
        ids = [await core.dispatch("sound", payload, at=AT.isoformat()) for _ in range(3)]
        await ids[0][1]
        self.assertEqual(len({i[0] for i in ids}), 1)

