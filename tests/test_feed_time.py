"""What a review agent playing a new parent found on Nov 3: Muse wrote "at three" as 03:00+01:00, the log kept it as 23:00 the evening before, a
false gap alarm followed, and being scared got the 911 line. Also what a message can't promise."""
import datetime
import tempfile
import unittest
from pathlib import Path

from tests import test_langgraph_core as base
from tests.test_langgraph_core import READY, NoScreen, call, scripted

if READY:
    from langchain_core.messages import AIMessage
    from parenting_agent.agent.memory import LocalBabyLog, Memory
    from parenting_agent.core import safety, tools as tools_mod

THREE = "2026-12-16T03:00:00"
NIGHT = "2026-12-16T03:20:00-03:00"


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class HomeTime(unittest.TestCase):
    def test_the_wall_clock_stays_whatever_offset_muse_writes(self):
        for written in (THREE + "+01:00", THREE + "Z", THREE, THREE + "-03:00", THREE + "+0100"):
            self.assertEqual(tools_mod.home_time(written), THREE + "-03:00", written)
        self.assertEqual(tools_mod.home_time("2026-12-16"), "2026-12-16")
        self.assertEqual(tools_mod.home_time("not a time"), "not a time")

    def test_two_logs_keep_their_own_clock(self):
        folder = Path(tempfile.mkdtemp())
        late = datetime.datetime.fromisoformat(NIGHT)
        early = datetime.datetime.fromisoformat("2026-12-15T23:00:00-03:00")
        one = LocalBabyLog(Memory(folder / "one.sqlite"), lambda: late)
        LocalBabyLog(Memory(folder / "two.sqlite"), lambda: early)
        self.assertEqual(one.add("feeding", {"amount_ml": 90}, THREE + "-03:00")["ts"], THREE + "-03:00")


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Worry(unittest.TestCase):
    def test_being_scared_or_tired_is_not_an_emergency(self):
        for text in ("Gonza fed him at 3am. did Theo really not eat for 8 hours?? I'm scared", "did Theo really not eat for 8 hours?",
                     "I'm scared", "im exhausted and I think im doing this all wrong", "tengo miedo, ¿de verdad no comió en 8 horas?",
                     "estoy agotada, no doy más", "¿cuándo comió por última vez? estoy preocupado"):
            self.assertIsNone(safety.gate(text, base.NoScreen()), text)
            self.assertTrue(safety.just_worry(text), text)

    def test_a_named_sign_still_fires_scared_or_not(self):
        for text in ("I'm scared, Theo is not breathing", "tengo miedo, está morado y no reacciona", "I'm scared, his lips are blue",
                     "Theo fell off the changing table, I'm scared", "I'm scared, he has a fever of 38.5", "estoy preocupada, tiene fiebre 39",
                     "he's having a seizure", "se ahoga, no respira", "Theo feels really hot and hes not waking up properly. I'm scared"):
            self.assertIsNotNone(safety.gate(text, base.NoScreen()), text)

    def test_the_screen_still_hears_a_scared_parent_who_names_something(self):
        class Yes:
            def screen(self, text):
                return True, "test"
        for text in ("I'm scared, he looks really strange", "estoy preocupado, está muy raro", "I'm scared he won't eat"):
            self.assertIsNotNone(safety.gate(text, Yes()), text)
        self.assertIsNone(safety.gate("I'm scared", Yes()))

    def test_the_urgent_line_is_short_and_its_source_is_last(self):
        kind, line = safety.gate("Theo has a fever of 38.5", base.NoScreen(), "en")
        self.assertEqual(kind, "urgent")
        words, source = line.rsplit("\n", 1)
        self.assertTrue(source.startswith("https://"))
        self.assertNotIn("http", words)
        self.assertNotIn("public guidance", words)


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Night(unittest.IsolatedAsyncioTestCase):
    setUp = base.CoreTest.setUp
    run_core = base.CoreTest.run_core
    event = base.CoreTest.event

    async def logged(self, words):
        core = await self.run_core(scripted(call("log_baby_event", kind="feeding", details={"amount_ml": 90, "method": "bottle"}, ts=THREE + "+01:00"),
                                            call("notify", parent="gonza", text="Listo"), AIMessage("logged"), AIMessage("morning")))
        await self.event(core, "message", {"from": "gonza", "channel": "a voice note", "text": words}, at=NIGHT)
        return core

    async def test_at_three_stays_at_three_in_both_languages_and_no_gap_is_raised(self):
        for words in ("I gave him a 90 ml bottle at three.", "Le di una mamadera de 90 ml a las tres."):
            core = await self.logged(words)
            feeds = [e for e in core.log.entries("feeding") if e["ts"].startswith("2026-12-16")]
            self.assertEqual(feeds[-1]["ts"], THREE + "-03:00")
            await self.event(core, "schedule", {"name": "morning"}, at="2026-12-16T07:30:00-03:00")
            self.assertEqual([a for a in await core.actions() if a["tool"] == "gap_message"], [])
            self.assertLess(core.gap_hours(), 8)

    async def test_what_a_message_cant_say(self):
        core = await self.run_core(scripted(AIMessage("ok")))
        for text in ("Per the rota Ceci is on tonight", "Bottle will be ready by 03:20", "I'll remind you before the feed", "Te aviso antes de la toma"):
            self.assertIn("Refused", core.claims(text) or "", text)
        self.assertIsNone(core.claims("Gonza is on tonight. Theo ate at 03:00."))

    async def test_a_promise_is_fine_once_the_reminder_is_set(self):
        core = await self.run_core(scripted(AIMessage("ok")))
        await core.add_wake(datetime.datetime.fromisoformat("2026-12-16T00:00:00-03:00"), "remind gonza")
        self.assertIsNone(core.claims("I'll remind you before the feed"))
        core.reminder_set = False
        await core.add_wake(datetime.datetime.fromisoformat("2026-12-16T00:00:00-03:00"), "device_end:warmer_off_at:x")
        self.assertIn("Refused", core.claims("I'll remind you before the feed"))

    async def test_the_vacuum_starts_alone_only_with_nobody_home_and_a_parent_can_ask(self):
        core = await self.run_core(scripted(call("HassVacuumStart"), AIMessage("no"), call("HassVacuumStart"), AIMessage("started")))
        await self.event(core, "schedule", {"name": "morning"}, at="2026-12-16T10:00:00-03:00")
        self.assertEqual(core.mock.state("vacuum.robot"), "docked")
        await self.event(core, "message", {"from": "gonza", "channel": "telegram", "text": "Start the vacuum"}, at="2026-12-16T10:05:00-03:00")
        self.assertEqual(core.mock.state("vacuum.robot"), "cleaning")

    async def test_the_vacuum_can_say_here_it_is_without_moving(self):
        core = await self.run_core(scripted(call("vacuum_identify"), AIMessage("done")))
        await self.event(core, "message", {"from": "ceci", "channel": "telegram", "text": "Where is the vacuum?"}, at="2026-12-16T10:05:00-03:00")
        self.assertEqual(core.mock.state("vacuum.robot"), "docked")
        self.assertEqual(core.mock.snapshot()["moves"][-1]["tool"], "vacuum_identify")

