"""Round 9: a parent's words that name nothing can't wake the other parent, even if Muse sets emergency, and a slow Muse doesn't leave a parent in silence."""
import asyncio
import datetime
import unittest

from tests import test_langgraph_core as base
from tests.test_langgraph_core import READY, call, scripted

if READY:
    from langchain_core.messages import AIMessage
    from parenting_agent.core import runtime, safety

# 03:12 on a night the rota gives Gonza, so Ceci is the one asleep.
NIGHT = next((at for at in (datetime.datetime.fromisoformat(f"2026-12-{d:02d}T03:12:00-03:00") for d in range(16, 20)) if READY and runtime.on_duty(at) == "gonza"), None)


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Words(unittest.TestCase):
    def test_a_hot_thing_names_nothing(self):
        for text in ("This bottle feels hot, I'll let it cool a bit before his feed", "La mamadera está muy caliente, la dejo enfriar", "We ran out of wipes", "The dog is barking again", "Ya le di la de las 3"):
            self.assertFalse(safety.worth_waking(text), text)

    def test_a_sign_a_fear_or_the_house_still_can(self):
        for text in ("Theo feels hot and won't feed", "He drank from a hot bottle and burned his mouth", "Theo está caliente", "I'm scared, something is wrong with him", "Smell of gas in the kitchen", "Se cortó con algo y hay sangre", "No se mueve", "Necesito ayuda"):
            self.assertTrue(safety.worth_waking(text), text)

    def test_a_reading_on_him_outranks_a_bath_beside_it(self):
        for text in ("Forehead says 38.2 but he just came out of the bath", "Frente 38,4, recién salió del baño", "38.3 under the arm after his bath"):
            self.assertEqual(safety.gate(text, base.NoScreen(), "en")[0], "urgent", text)
        for text in ("The bath water is 38,04", "His bath water was 38 degrees"):
            self.assertIsNone(safety.gate(text, base.NoScreen(), "en"), text)

    def test_every_real_danger_can_wake(self):
        for text in ("Theo no respira", "Theo se puso azul", "He fell off the changing table", "se cayó del cambiador y no reacciona", "Theo swallowed a battery"):
            self.assertTrue(safety.worth_waking(text), text)

    def test_a_tip_is_only_refused_unasked(self):
        self.assertTrue(safety.unasked_tip("Test a few drops on your wrist", "This bottle feels hot"))
        self.assertTrue(safety.unasked_tip("Probá unas gotas en la muñeca", "La mamadera está caliente"))
        self.assertFalse(safety.unasked_tip("Yes, on the wrist is what you said", "I tested it on my wrist"))


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Night(unittest.IsolatedAsyncioTestCase):
    setUp = base.CoreTest.setUp
    run_core = base.CoreTest.run_core
    event = base.CoreTest.event

    async def test_emergency_on_a_hot_bottle_doesnt_wake_her_or_open_an_alarm(self):
        core = await self.run_core(scripted(call("notify", parent="ceci", text="Gonza says the bottle is hot.", emergency=True), call("notify", parent="gonza", text="Thanks, I have it.", emergency=True), AIMessage("Told him.")))
        await self.event(core, "message", {"from": "gonza", "text": "This bottle feels hot, I'll let it cool a bit before his feed"}, at=NIGHT.isoformat())
        self.assertEqual([m["to"] for m in core.channel.sent], ["gonza"])
        self.assertFalse([k for k in await runtime.tools_mod.facts(core.store, core.settings.home) if "alarm" in k])

    async def test_a_sign_muse_calls_an_emergency_still_wakes_her(self):
        core = await self.run_core(scripted(call("notify", parent="ceci", text="Gonza says Theo feels hot and won't feed. Please go to him.", emergency=True), call("notify", parent="gonza", text="Call his pediatrician.", emergency=True), AIMessage("Told both.")))
        await self.event(core, "message", {"from": "gonza", "text": "Theo feels hot and won't feed"}, at=NIGHT.isoformat())
        self.assertIn("ceci", [m["to"] for m in core.channel.sent])


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Slow(unittest.IsolatedAsyncioTestCase):
    setUp = base.CoreTest.setUp
    run_core = base.CoreTest.run_core
    event = base.CoreTest.event

    async def slow_core(self, *replies):
        core = await self.run_core(scripted(*replies))
        core.hold_s = 0.05
        decide = core.decide

        async def slowly(event, started):
            await asyncio.sleep(0.3)
            return await decide(event, started)
        core.decide = slowly
        return core

    async def test_a_slow_muse_gets_one_holding_line_then_its_answer(self):
        core = await self.slow_core(call("notify", parent="gonza", text="At 03:00."), AIMessage("Answered."))
        await self.event(core, "message", {"from": "gonza", "text": "When did he last eat?"}, at=NIGHT.isoformat())
        said = [m["text"] for m in core.channel.sent if m["to"] == "gonza"]
        self.assertEqual(said, [runtime.HOLDING["es"], "At 03:00."])
        self.assertFalse([m for m in core.channel.sent if m["to"] == "ceci"])

    async def test_a_fast_muse_gets_none(self):
        core = await self.run_core(scripted(call("notify", parent="gonza", text="At 03:00."), AIMessage("Answered.")))
        core.hold_s = 5
        await self.event(core, "message", {"from": "gonza", "text": "When did he last eat?"}, at=NIGHT.isoformat())
        self.assertEqual([m["text"] for m in core.channel.sent], ["At 03:00."])

    async def test_no_holding_line_for_a_reading_or_the_echo(self):
        core = await self.slow_core(AIMessage("Nothing needed."))
        await self.event(core, "state_changed", {"entity_id": "sensor.nursery_climate_humidity", "state": "55"}, at=NIGHT.isoformat())
        self.assertFalse(core.channel.sent)


