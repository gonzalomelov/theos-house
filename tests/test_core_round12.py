"""Round 12: "let me sleep" said out loud at the Echo. The Echo can't tell who spoke, Alexa waits 8 seconds and asks again with the same id, and both parents hear about the night."""
import asyncio
import datetime
import os
import tempfile
import unittest
import uuid
from unittest import mock

from tests.test_langgraph_core import READY, NoScreen, call, scripted

if READY:
    import httpx
    from langchain_core.messages import AIMessage
    from parenting_agent.core import server, tools as tools_mod
    from parenting_agent.core.runtime import Core, recipe_shown
    from parenting_agent.core.settings import Settings

TOKEN, SKILL = "t" * 32, "s" * 32
EVENING = "2026-12-15T21:45:00-03:00"
NIGHT = "2026-12-15T23:10:00-03:00"
WORDS = "soy ceci esta noche necesito dormir se puede encargar gonza"
NIGHT_KEY = "on_duty_2026-12-15"


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class AtTheEcho(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"PARENTING_AGENT_VOICE_TOKEN": TOKEN, "PARENTING_AGENT_SKILL_TOKEN": SKILL})
        patch.start()
        self.addCleanup(patch.stop)

    async def core(self, model, at=EVENING):
        core = Core(Settings(home="t-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=tempfile.mkdtemp()), model)
        await core.__aenter__()
        self.addAsyncCleanup(core.__aexit__, None, None, None)
        self.addAsyncCleanup(core.forget)
        core.screen = NoScreen()
        dispatch = core.dispatch
        core.dispatch = lambda kind, payload=None, source="simulator", when=None, ask=False: dispatch(kind, payload, source, when or at, ask)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.echo_app(core)), base_url="http://echo")
        self.addAsyncCleanup(client.aclose)
        return core, client

    @staticmethod
    def post(client, token=TOKEN, **body):
        return client.post("/ask", json={"text": WORDS, "source": "echo", **body}, headers={"Authorization": "Bearer " + token}, timeout=30)

    async def test_the_skill_has_its_own_token_and_only_known_tokens_get_in(self):
        _, client = await self.core(scripted(call("say_on_echo", text="Hola."), AIMessage("Answered.")))
        self.assertEqual((await self.post(client, "x" * 32)).status_code, 401)
        self.assertEqual((await self.post(client, SKILL)).json()["reply"], "Hola.")

    async def test_with_no_tokens_set_nobody_gets_in(self):
        _, client = await self.core(scripted(AIMessage("Answered.")))
        with mock.patch.dict(os.environ, {"PARENTING_AGENT_VOICE_TOKEN": "", "PARENTING_AGENT_SKILL_TOKEN": ""}):
            closed = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.echo_app(_)), base_url="http://echo")
            self.addAsyncCleanup(closed.aclose)
            self.assertEqual((await closed.post("/ask", json={"text": "hola"}, headers={"Authorization": "Bearer "})).status_code, 401)

    async def test_the_same_id_asked_again_gets_the_first_answer_and_runs_nothing_twice(self):
        core, client = await self.core(scripted(call("say_on_echo", text="Gonza esta noche."), AIMessage("Answered.")))
        first = await self.post(client, request_id="r1")
        again = await self.post(client, request_id="r1")
        self.assertEqual((first.json()["reply"], again.json()["reply"]), ("Gonza esta noche.", "Gonza esta noche."))
        self.assertEqual(len([e for e in await core.events() if e["type"] == "message"]), 1)

    async def test_the_echo_speaks_as_soon_as_it_is_said_and_the_phones_can_come_after(self):
        gate = asyncio.Event()

        class Slow(type(scripted())):
            async def _agenerate(self, messages, *args, **kwargs):
                if len(self.calls) >= 1:
                    await gate.wait()
                return self._generate(messages, *args, **kwargs)
        model = Slow(messages=iter([call("say_on_echo", text="Gonza esta noche."), call("notify", parent="gonza", text="Te toca a vos esta noche."), AIMessage("Done.")]), calls=[])
        core, client = await self.core(model)
        answer = await asyncio.wait_for(self.post(client), 20)
        self.assertEqual(answer.json()["reply"], "Gonza esta noche.")
        self.assertFalse(any(m["to"] == "gonza" for m in core.channel.sent))
        gate.set()
        while core.current is None or not core.queue.empty() or any(e["status"] in ("queued", "running") for e in await core.events()):
            await asyncio.sleep(0.05)

    async def test_an_echo_left_with_nothing_is_asked_once_and_never_silent(self):
        _, client = await self.core(scripted(AIMessage("Nothing needed."), call("say_on_echo", text="Acá estoy."), AIMessage("Answered.")))
        self.assertEqual((await self.post(client)).json()["reply"], "Acá estoy.")
        _, client = await self.core(scripted(AIMessage("Nothing needed."), AIMessage("Still nothing.")))
        self.assertEqual((await self.post(client)).json()["reply"], server.NOTHING_TO_SAY["es"])

    async def test_a_night_changed_at_the_echo_reaches_both_with_no_garbled_name(self):
        core, client = await self.core(scripted(call("set_on_duty", night="2026-12-15", parent="gonza"), call("say_on_echo", text="Esta noche Gonza."), AIMessage("Done."), AIMessage("Done."), AIMessage("Done.")))
        await self.post(client)
        await self.wait_done(core)
        facts = await tools_mod.facts(core.store, core.settings.home)
        self.assertEqual(facts[NIGHT_KEY], "gonza")
        told = {m["to"]: m["text"] for m in core.channel.sent if m["to"] != "echo"}
        self.assertEqual(sorted(told), ["ceci", "gonza"])
        self.assertIn("te toca a vos", told["gonza"])
        self.assertIn("se encarga Gonza", told["ceci"])
        self.assertNotIn("someone", " ".join(told.values()).lower())

    async def test_after_22_both_can_be_told_and_the_one_off_duty_makes_no_sound(self):
        core, client = await self.core(scripted(call("set_on_duty", night="2026-12-15", parent="gonza"), call("notify", parent="gonza", text="Dijeron en el Echo que esta noche te toca a vos."), call("say_on_echo", text="Esta noche Gonza."), AIMessage("Done."), AIMessage("Done."), AIMessage("Done.")), NIGHT)
        await self.post(client)
        await self.wait_done(core)
        ceci = [m for m in core.channel.sent if m["to"] == "ceci"]
        self.assertEqual(len(ceci), 1)
        self.assertTrue(ceci[0]["quiet"])
        self.assertTrue(any(m["to"] == "gonza" and not m.get("quiet") for m in core.channel.sent))

    @staticmethod
    async def wait_done(core):
        for _ in range(400):
            if core.queue.empty() and all(e["status"] not in ("queued", "running") for e in await core.events()):
                return
            await asyncio.sleep(0.05)
        raise TimeoutError


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class OneCryMessage(unittest.IsolatedAsyncioTestCase):
    async def first_prompt(self, *feeds):
        model = scripted(AIMessage("ok"), AIMessage("ok"))
        async with Core(Settings(home="t-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=tempfile.mkdtemp()), model) as core:
            core.screen = NoScreen()
            core.moment = datetime.datetime.fromisoformat("2026-12-16T02:00:00-03:00")
            for feed in feeds:
                core.log.add("feeding", {"amount_ml": 90}, feed)
            _, done = await core.dispatch("sound", {"kind": "baby crying"}, at="2026-12-16T02:50:00-03:00")
            await done
            await core.forget()
        return str(model.calls[0])

    async def test_a_feed_due_gives_the_warmer_end_before_the_switch_so_one_message_can_carry_it(self):
        self.assertIn("it turns itself off at 03:20", await self.first_prompt("2026-12-15T20:40:00-03:00"))

    async def test_just_fed_the_cry_is_told_the_warmer_stays_off(self):
        words = await self.first_prompt("2026-12-15T17:20:00-03:00", "2026-12-15T20:20:00-03:00", "2026-12-15T23:20:00-03:00", "2026-12-16T02:20:00-03:00")
        self.assertIn("The warmer stays off for this cry", words)
        self.assertNotIn("it turns itself off", words)


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class EmptyIsntZero(unittest.IsolatedAsyncioTestCase):
    async def test_the_echo_cant_say_zero_minutes_for_nothing_written_down(self):
        model = scripted(call("say_on_echo", text="Hoy no hay sueño anotado, cero minutos."), call("say_on_echo", text="Hoy no hay sueño anotado."), AIMessage("Done."))
        async with Core(Settings(home="t-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=tempfile.mkdtemp()), model) as core:
            core.screen = NoScreen()
            _, done = await core.dispatch("message", {"from": "someone in the kitchen, you can't tell who", "channel": "the kitchen Echo", "text": "cuánto durmió"}, at="2026-12-15T16:00:00-03:00", ask=True)
            out = await done
            await core.forget()
        self.assertEqual(out["said"], ["Hoy no hay sueño anotado."])


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class RecipeWithNoPreview(unittest.IsolatedAsyncioTestCase):
    async def test_a_recipe_with_amounts_and_no_preview_is_asked_for_it_once(self):
        model = scripted(call("notify", parent="ceci", text="Anotado."), AIMessage("Done."), AIMessage("Done."), AIMessage("Done."))
        async with Core(Settings(home="t-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=tempfile.mkdtemp()), model) as core:
            core.screen = NoScreen()
            _, done = await core.dispatch("message", {"from": "ceci", "channel": "WhatsApp", "text": "Mi receta de sopa: 500 g de boniato, 18 min/100°C/vel 1"}, at="2026-12-15T16:00:00-03:00")
            await done
            await core.forget()
        self.assertTrue(any("preview_family_recipe. Call it now" in str(c) for c in model.calls))

    def test_naming_the_soup_doesnt_show_the_recipe(self):
        preview = {"ingredients": ["500 g sweet potato", "300 g stock"], "steps": [{"text": "Cook sweet potato with stock 18 min/100°C"}, {"text": "Blend sweet potato 30 sec/speed 8"}]}
        self.assertFalse(recipe_shown(preview, "Got your neighbour's sweet potato soup as a Thermomix recipe, I can't send it to Cookidoo."))
        self.assertTrue(recipe_shown(preview, "Soup\n500 g sweet potato\n300 g stock\nCook sweet potato with stock 18 min/100°C\nBlend sweet potato 30 sec/speed 8"))

    async def test_a_recipe_named_with_no_amounts_isnt_pushed(self):
        model = scripted(call("notify", parent="ceci", text="¿Cuál?"), AIMessage("Done."), AIMessage("Done."))
        async with Core(Settings(home="t-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=tempfile.mkdtemp()), model) as core:
            core.screen = NoScreen()
            _, done = await core.dispatch("message", {"from": "ceci", "channel": "WhatsApp", "text": "¿Tenés alguna receta para hoy?"}, at="2026-12-15T16:00:00-03:00")
            await done
            await core.forget()
        self.assertFalse(any("preview_family_recipe. Call it now" in str(c) for c in model.calls))


if __name__ == "__main__":
    unittest.main()
