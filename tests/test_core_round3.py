"""What the third round of judges found (Nov 3): the ladder only spoke when something else happened, alarms left out of the morning, wakes
lost in a clock jump, homes that locked people out, promises nobody could keep."""
import datetime
import time
import unittest

from tests import test_langgraph_core as base
from tests.test_langgraph_core import READY, NoScreen, call, scripted

if READY:
    import httpx
    from langchain_core.messages import AIMessage
    from parenting_agent.core import runtime, safety, tools as tools_mod
    from parenting_agent.simulator import gateway, sessions as sessions_mod
    from tests.test_simulator import served


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Words(unittest.TestCase):
    def test_not_an_emergency_never_covers_a_sign_with_or_without_the_model(self):
        for text in ("Not an emergency, but his lips look bluish", "No es una emergencia pero está morado", "not urgent, he went limp"):
            self.assertEqual(safety.gate(text, NoScreen())[0], "emergency", text)
        for text in ("Not an emergency: breathing fine, lips not blue", "no es urgente, no está morado"):
            self.assertIsNone(safety.gate(text, NoScreen()), text)

    def test_a_gated_message_only_carries_on_for_an_errand(self):
        self.assertEqual(safety.rest_of("Theo tiene fiebre 38,6. Tiene 3 semanas de vida"), "")
        self.assertIn("pañales", safety.rest_of("Theo tiene fiebre 38,6. También agregá pañales a la lista"))

    def test_a_parent_reporting_a_feed_is_told_apart_from_a_question(self):
        for text in ("Gave him a bottle at eleven last night", "Le di una mamadera de 90 ml a las tres", "He drank 60 ml"):
            self.assertTrue(safety.reports_feed(text), text)
        for text in ("Did he eat?", "¿Comió a las tres?", "Turn on the light"):
            self.assertFalse(safety.reports_feed(text), text)


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Ladder(unittest.TestCase):
    def setUp(self):
        self.core = runtime.Core.__new__(runtime.Core)
        self.feed = datetime.datetime.fromisoformat("2026-12-16T03:00:00-03:00")

    def at(self, hours):
        return self.feed + datetime.timedelta(hours=hours)

    def test_each_step_comes_due_by_itself_once(self):
        self.assertIsNone(self.core.gap_due(self.feed, {}, self.at(1), self.at(7)))
        self.assertEqual(self.core.gap_due(self.feed, {}, self.at(1), self.at(14)), self.at(8))
        told = {"feed_gap_told": f"{self.feed.isoformat()}|8"}
        self.assertEqual(self.core.gap_due(self.feed, told, self.at(8), self.at(14)), self.at(12))
        self.assertIsNone(self.core.gap_due(self.feed, told, self.at(8), self.at(11)))

    def test_a_late_start_says_the_step_it_is_at_not_every_one_before(self):
        self.assertEqual(self.core.gap_due(self.feed, {}, self.at(20), self.at(20)), self.at(20))

    def test_no_feed_or_a_new_feed_means_nothing_is_due(self):
        self.assertIsNone(self.core.gap_due(None, {}, self.at(1), self.at(30)))
        newer = self.at(9)
        self.assertEqual(self.core.gap_due(newer, {"feed_gap_told": f"{self.feed.isoformat()}|8"}, self.at(9), self.at(18)), self.at(17))


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Core(unittest.IsolatedAsyncioTestCase):
    setUp = base.CoreTest.setUp
    run_core = base.CoreTest.run_core
    event = base.CoreTest.event

    async def test_alarms_reach_the_next_checks_and_the_log(self):
        core = await self.run_core(scripted(AIMessage("Told them.")))
        await self.event(core, "message", {"from": "ceci", "channel": "phone", "text": "Theo no respira y está morado"}, at="2026-11-04T04:10:00-03:00")
        facts = await tools_mod.facts(core.store, core.settings.home)
        self.assertTrue(any(k.startswith("alarm_") for k in facts))
        self.assertIn("no respira", runtime.alarm_note({"type": "schedule"}, facts))
        self.assertIsNone(runtime.alarm_note({"type": "message"}, facts))
        self.assertTrue(any("no respira" in str(e["details"]) for e in core.log.entries("note", None, 5)))

    async def test_a_reported_feed_goes_in_before_any_gap_is_raised(self):
        core = await self.run_core(scripted(call("log_baby_event", kind="feeding", details={"amount_ml": 90}), call("notify", parent="gonza", text="Anotado."), AIMessage("Logged.")))
        core.log.add("feeding", {"amount_ml": 80}, "2026-11-03T12:00:00-03:00")
        await self.event(core, "message", {"from": "gonza", "channel": "phone", "text": "Le di una mamadera de 90 ml"}, at="2026-11-04T05:00:00-03:00")
        self.assertFalse([a for a in await core.actions() if a["tool"] == "gap_message"])

    async def test_the_ladder_speaks_with_nothing_else_happening(self):
        core = await self.run_core(scripted(AIMessage("Nothing.")))
        core.log.add("feeding", {"amount_ml": 80}, "2026-11-03T12:00:00-03:00")
        moment = datetime.datetime.fromisoformat("2026-11-03T21:00:00-03:00")
        await (await core.tick_gap(moment))[1]
        self.assertEqual(len([a for a in await core.actions() if a["tool"] == "gap_message"]), 1)
        self.assertIsNone(await core.tick_gap(moment + datetime.timedelta(minutes=5)))

    async def test_one_wake_about_the_air_at_a_time(self):
        core = await self.run_core(scripted(AIMessage("Nothing.")))
        moment = datetime.datetime.fromisoformat("2026-11-04T15:00:00-03:00")
        await core.add_wake(moment, "check the dehumidifier")
        await core.add_wake(moment + datetime.timedelta(minutes=1), "check the humidity")
        await core.add_wake(moment + datetime.timedelta(minutes=30), "something else")
        await core.add_wake(moment, "warm a bottle")
        self.assertEqual(len(await core.wakes()), 3)

    async def test_forget_really_forgets_a_night_and_says_when_it_cannot(self):
        core = await self.run_core(scripted(AIMessage("Nothing.")))
        tool = next(t for t in core.tools if t.name == "forget")
        await core.store.aput((*tools_mod.FACTS, core.settings.home), "on_duty_2026-12-15", {"value": "gonza"})
        self.assertEqual(await tool.ainvoke({"key": "on_duty_2026-12-15"}), "Forgotten.")
        self.assertNotIn("on_duty_2026-12-15", await tools_mod.facts(core.store, core.settings.home))
        self.assertIn("Nothing is remembered", await tool.ainvoke({"key": "on_duty_2026-12-15"}))

    async def test_promises_the_home_cant_keep_and_the_wrong_number_are_refused(self):
        core = await self.run_core(scripted(AIMessage("Nothing.")))
        for text in ("I won't message you tonight", "No te escribo más", "I'll alert both of you", "Call 112 now"):
            self.assertTrue(core.claims(text), text)
        self.assertIsNone(core.claims("Call 911 now"))

    async def test_a_medical_question_gets_one_reply_and_the_one_on_duty_hears(self):
        moment = "2026-11-04T15:00:00-03:00"
        day = datetime.datetime.fromisoformat(moment)
        off = "ceci" if runtime.on_duty(day) == "gonza" else "gonza"
        core = await self.run_core(scripted(AIMessage("Should not run.")))
        await self.event(core, "message", {"from": off, "channel": "phone", "text": "What dose of paracetamol can I give him?"}, at=moment)
        self.assertEqual([m["to"] for m in core.channel.sent].count(off), 1)
        self.assertIn(runtime.on_duty(day), [m["to"] for m in core.channel.sent])

    async def test_changing_a_night_for_someone_else_reaches_them(self):
        moment = "2026-11-04T15:00:00-03:00"
        night = str(runtime.night_of(datetime.datetime.fromisoformat(moment)))
        core = await self.run_core(scripted(call("set_on_duty", night=night, parent="gonza"), call("notify", parent="ceci", text="Dale, cambiado."), AIMessage("Changed."),
                                            call("notify", parent="gonza", text="Ceci dijo que hoy te toca, avisá si no."), AIMessage("Told.")))
        await self.event(core, "message", {"from": "ceci", "channel": "phone", "text": "Gonza dijo que hoy se queda él"}, at=moment)
        self.assertIn("gonza", [m["to"] for m in core.channel.sent])


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Simulator(unittest.TestCase):
    def setUp(self):
        runtime.Core.screen = NoScreen()
        self.addCleanup(setattr, runtime.Core, "screen", None)
        runtime.Core.retry_waits = (0, 0)
        self.addCleanup(setattr, runtime.Core, "retry_waits", runtime.RETRY_WAITS)

    def visitor(self, url):
        visitor = httpx.Client(base_url=url, trust_env=False, timeout=60)
        self.addCleanup(visitor.close)
        self.assertEqual(visitor.post("/api/session", json={}).status_code, 200)
        return visitor

    def wait(self, session, count):
        for _ in range(300):
            if sum(i["kind"] == "done" for i in session.core.recent) >= count and all(f[1].done() for f in session.core.running.values()):
                return
            time.sleep(0.02)
        self.fail("nothing finished")

    def test_a_wake_fires_at_its_own_moment_in_a_long_jump(self):
        app = gateway.app(scripted(call("wake_me_at", at="2026-12-15T23:40:00-03:00", why="warm the bottle"), *[AIMessage("Nothing.") for _ in range(12)]))
        with served(app) as url:
            visitor = self.visitor(url)
            session = app.state.sessions.get(visitor.cookies["pa_sim"])
            visitor.post("/api/scene", json={"id": "evening"})
            self.wait(session, 1)
            visitor.post("/api/scene", json={"id": "cry"})
            self.wait(session, 3)
            events = [(e["type"], e["happened_at"]) for e in session.core.recent if e["kind"] == "event"]
            self.assertIn(("wake", "2026-12-15T23:40:00-03:00"), events)
            self.assertLess(events.index(("wake", "2026-12-15T23:40:00-03:00")), [t for t, _ in events].index("sound"))

    def test_theo_eats_through_the_day_and_nothing_alarms_until_the_feeds_stop(self):
        app = gateway.app(scripted(*[AIMessage("Nothing.") for _ in range(40)]))
        with served(app) as url:
            visitor = self.visitor(url)
            session = app.state.sessions.get(visitor.cookies["pa_sim"])
            for _ in range(3):
                visitor.post("/api/clock", json={"minutes": 360})
            self.assertFalse([e for e in session.core.recent if e["kind"] == "gate"])
            fed = [e["ts"] for e in session.log.entries("feeding", None, 50) if e["details"].get("simulated")]
            self.assertTrue(fed)
            self.assertEqual(len(fed), len(set(fed)))
            self.assertFalse(visitor.post("/api/feeds", json={"on": False}).json()["feeds_on"])
            for _ in range(3):
                visitor.post("/api/clock", json={"minutes": 360})
            gates = [e for e in session.core.recent if e["kind"] == "gate" and e["gate"] == "feed_gap"]
            self.assertGreaterEqual(len(gates), 2)

    def test_changing_language_keeps_the_home(self):
        app = gateway.app(scripted(AIMessage("Nothing.")))
        with served(app) as url:
            visitor = self.visitor(url)
            home = app.state.sessions.get(visitor.cookies["pa_sim"]).settings.home
            self.assertEqual(visitor.post("/api/lang", json={"lang": "es"}).json()["lang"], "es")
            self.assertEqual(app.state.sessions.get(visitor.cookies["pa_sim"]).settings.home, home)

    def test_start_over_counts_once_and_a_full_house_makes_room(self):
        app = gateway.app(scripted(AIMessage("Nothing.")))
        with served(app) as url:
            visitor = self.visitor(url)
            before = visitor.get("/api/state").json()["starts_left"]
            after = visitor.post("/api/reset", json={}).json()["starts_left"]
            self.assertEqual(after, before - 1)
            sessions = app.state.sessions
            for session in sessions.live.values():
                session.last_seen = time.monotonic() - sessions_mod.EVICT_IDLE_S - 1
            limit, sessions_mod.MAX_SESSIONS = sessions_mod.MAX_SESSIONS, 1
            self.addCleanup(setattr, sessions_mod, "MAX_SESSIONS", limit)
            other = httpx.Client(base_url=url, trust_env=False, timeout=60)
            self.addCleanup(other.close)
            self.assertEqual(other.post("/api/session", json={}).status_code, 200)
            third = httpx.Client(base_url=url, trust_env=False, timeout=60)
            self.addCleanup(third.close)
            refused = third.post("/api/session", json={})
            self.assertEqual(refused.status_code, 503)
            self.assertIn("in use", refused.json()["error"])

    def test_the_page_shows_what_each_meta_model_did(self):
        with served(gateway.app(scripted(AIMessage("Nothing.")))) as url:
            page = httpx.get(url + "/", trust_env=False).text
            for card in ("m-muse", "m-pe", "m-sam", "m-gadget", "m-tts", "/static/architecture.svg"):
                self.assertIn(card, page)
            self.assertEqual(httpx.get(url + "/static/senses/mms-coach-en.m4a", trust_env=False).status_code, 200)
