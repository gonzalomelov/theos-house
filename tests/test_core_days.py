"""Days of the real core through its one event path, with a scripted model, a simulated clock and faults on purpose. 14 days take
about 20 s. Needs requirements-core.txt and PostgreSQL at PA_DB_URL, and skips without them. scripts/core_days_eval.py runs real Muse."""
import asyncio
import datetime
import logging
import os
import unittest

try:
    from parenting_agent.channels.messaging import MessagingError
    from parenting_agent.core import days, sources
    from parenting_agent.core.runtime import on_duty
    READY = bool(os.environ.get("PA_DB_URL"))
except ImportError:
    READY = False


def night_of(parent):
    """A night the rota gives this parent, at 03:00."""
    return next(m for m in (days.START + datetime.timedelta(days=d, hours=3) for d in range(4)) if on_duty(m) == parent)


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Case(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ["PA_WORLD"] = "mock"
        for name in ("PA_HOME", "PA_CHANNEL", "PA_LOG"):
            os.environ.pop(name, None)
        logging.disable(logging.ERROR)
        self.addCleanup(logging.disable, logging.NOTSET)


class Fortnight(Case):
    async def test_fourteen_days_with_every_fault_break_no_invariant_and_stay_bounded(self):
        async with days.Run(14) as run:
            report = await run.live()
            rows = report["daily"]
        self.assertEqual(report["violations"], [])
        self.assertEqual(set(report["faults"]), {"misbehave", "brain_down", "db_cut", "restart", "home_down", "crash", "telegram_down", "burst", "brain_gone", "empty", "malformed"})
        self.assertGreater(report["counts"]["events"], 200)
        self.assertGreater(report["counts"]["trims"], 10, "the thread never reached the trim, so this proved nothing about it")
        self.assertEqual(report["counts"]["recovered"], report["counts"]["crashes"] * 3)
        self.assertGreater(report["counts"]["crashes"], 0)
        limit = days.agent_mod.MAX_HISTORY_TOKENS + days.THREAD_SLACK
        self.assertTrue(all(r["thread_tokens"] <= limit for r in rows))
        self.assertLess(max(r["db_kb"] for r in rows[7:]), 60_000, "checkpoints are not being pruned")
        self.assertLess(max(r["tasks"] for r in rows), 20)
        self.assertLessEqual(max(r["recent"] for r in rows), 500)
        self.assertLess(rows[-1]["rss_mb"] - rows[1]["rss_mb"], 150)


class TheChecksCanFail(Case):
    """Each invariant, with its guard taken away, has to report. A harness that can't fail proves nothing."""

    async def test_without_the_night_check_waking_the_other_parent_is_reported(self):
        at = night_of("gonza")
        step = days.Step(at, "sound", {"kind": "cry", "room": "Theo's room"})
        async with days.Run(1, faults=False) as run:
            original = days.tools_mod.channel_tools
            run.model.misbehave = [{"tool": "notify", "args": {"parent": "ceci", "text": "Se despertó."}}]
            await run.stop()
            days.tools_mod.channel_tools = lambda channel, s, log=None, heard=lambda: "", night_check=None, claims=lambda text: None, said=lambda parent, asked, out: None, repeats=lambda parent, text: None, hushed=lambda: False: original(channel, s, log, heard, None, claims)
            self.addCleanup(setattr, days.tools_mod, "channel_tools", original)
            await run.start()
            await run.event(0, step)
            self.assertTrue(any("woken at night" in v for v in run.violations), run.violations)

    async def test_an_unsourced_claim_past_the_check_is_reported(self):
        step = days.Step(days.START + datetime.timedelta(hours=8), "schedule", {"name": "morning"})
        async with days.Run(1, faults=False) as run:
            await run.check_claims(0, step, [{"to": "gonza", "text": "Durmió bien toda la noche."}])
            self.assertTrue(any("unsourced" in v for v in run.violations), run.violations)

    async def test_a_plug_left_on_in_a_dry_room_is_reported(self):
        step = days.Step(days.START + datetime.timedelta(hours=10), "state_changed", {"entity_id": days.HUMIDITY, "state": "45.0"})
        async with days.Run(1, faults=False) as run:
            run.core.mock.set_state(days.PLUG, "on")
            run.check_plug(0, step, {"status": "done"})
            self.assertTrue(any("the plug is on" in v for v in run.violations))

    async def test_a_lost_event_is_reported(self):
        step = days.Step(days.START + datetime.timedelta(hours=10), "sound", {"kind": "cry"})
        async with days.Run(1, faults=False) as run:
            async with run.core.pool.connection() as db:
                await db.execute("insert into events (home, happened_at, type, source, payload) values (%s, %s, 'sound', 'days', '{}')", (run.settings.home, step.at))
            run.settings.home, real = run.settings.home, run.settings.home
            await run.day_end(0, step)
            self.assertTrue(any("still queued" in v for v in run.violations), run.violations)
            async with run.core.pool.connection() as db:
                await db.execute("update events set status = 'done' where home = %s", (real,))


class Faults(Case):
    async def test_a_trim_doesnt_put_old_calls_on_this_events_record(self):
        """The trim's update carries the kept history, which was read as new calls: replayed on the record, and the second ask defeated (found by these days, Nov 3)."""
        step = days.Step(days.START + datetime.timedelta(hours=12), "message", {"from": "gonza", "channel": "telegram", "text": "¿a quién le toca hoy?"})
        async with days.Run(1, faults=False) as run:
            for _ in range(60):
                await (await run.send(step))[1]
            old = days.agent_mod.MAX_HISTORY_TOKENS
            days.agent_mod.MAX_HISTORY_TOKENS = 1000
            self.addCleanup(setattr, days.agent_mod, "MAX_HISTORY_TOKENS", old)
            calls = run.model.calls
            event_id, done = await run.send(step)
            await done
            rows = [a for a in await run.core.actions(event_id, 500) if a["tool"] != "muse_note"]
            self.assertLessEqual(len(rows), run.model.calls - calls)
            self.assertEqual(len(rows), 1)

    async def test_a_red_flag_reaches_the_other_parent_with_a_phone_failing(self):
        step = days.Step(days.START + datetime.timedelta(hours=15), "message", {"from": "ceci", "channel": "telegram", "text": "no respira y esta azul"})
        async with days.Run(1, faults=False) as run:
            run.channel.failing = 2
            _, done = await run.send(step)
            self.assertEqual((await done)["status"], "gated")
            self.assertEqual([m["to"] for m in run.channel.sent], ["ceci"])
            actions = await run.core.actions()
            self.assertEqual(sum(a["result"].startswith("Failed") for a in actions), 2)

    async def test_a_cry_with_the_brain_gone_still_reaches_the_parent_on_duty(self):
        at = night_of("ceci")
        step = days.Step(at, "sound", {"kind": "cry", "room": "Theo's room"})
        async with days.Run(1, faults=False) as run:
            run.faults.down = 99
            _, done = await run.send(step)
            out = await done
            self.assertEqual(out["status"], "failed")
            self.assertIn("Told without Muse: ceci", out["outcome"])
            self.assertEqual([m["to"] for m in run.channel.sent], ["ceci"])

    async def test_an_alarm_with_the_brain_gone_reaches_both_and_a_reading_reaches_nobody(self):
        at = night_of("ceci")
        async with days.Run(1, faults=False) as run:
            run.faults.down = 99
            await (await run.send(days.Step(at, "sound", {"kind": "smoke alarm", "room": "kitchen"})))[1]
            self.assertEqual(sorted(m["to"] for m in run.channel.sent), ["ceci", "gonza"])
            run.channel.sent.clear()
            await (await run.send(days.Step(at, "state_changed", {"entity_id": days.HUMIDITY, "state": "70"})))[1]
            self.assertEqual(run.channel.sent, [])

    async def test_a_dropped_database_connection_loses_no_event(self):
        step = days.Step(days.START + datetime.timedelta(hours=8), "schedule", {"name": "morning"})
        async with days.Run(1, faults=False) as run:
            await (await run.send(step))[1]
            await run.cut_db()
            self.assertEqual((await (await run.send(step))[1])["status"], "done")

    async def test_home_assistant_away_is_told_to_the_model_and_the_run_ends(self):
        step = days.Step(days.START + datetime.timedelta(hours=10), "state_changed", {"entity_id": days.HUMIDITY, "state": "70.0"})
        async with days.Run(1, faults=False) as run:
            await run.home_down()
            out = await (await run.send(step))[1]
            self.assertEqual(out["status"], "done")
            self.assertTrue(any(a["result"].startswith("Error: the home") for a in await run.core.actions()))
            run.home_back()
            run.core.mock.set_state(days.PLUG, "off")
            await (await run.send(step))[1]
            self.assertEqual(run.core.mock.state(days.PLUG), "on")

    async def test_an_event_from_before_the_cut_too_old_to_matter_is_on_record_as_missed(self):
        step = days.Step(days.START + datetime.timedelta(hours=10), "sound", {"kind": "cry"})
        async with days.Run(1, faults=False) as run:
            async with run.core.pool.connection() as db:
                row = await (await db.execute("insert into events (home, at, happened_at, type, source, payload) values (%s, now() - interval '1 hour', %s, 'sound', 'days', '{}') returning id",
                                              (run.settings.home, step.at))).fetchone()
            await run.stop()
            await run.start()
            self.assertEqual(await run.statuses([row["id"]]), {row["id"]: "missed"})
            self.assertEqual(run.channel.sent, [])

    async def test_old_rota_entries_go_and_tonights_stays(self):
        async with days.Run(1, faults=False) as run:
            store, home = run.core.store, run.settings.home
            for day in range(1, 110):
                await store.aput((*days.tools_mod.FACTS, home), f"on_duty_2026-{1 + day // 31:02d}-{1 + day % 28:02d}", {"value": "ceci"})
            run.core.moment = datetime.datetime(2026, 11, 10, 3, tzinfo=days.TZ)
            await store.aput((*days.tools_mod.FACTS, home), "on_duty_2026-11-09", {"value": "gonza"})
            await store.aput((*days.tools_mod.FACTS, home), "plan", {"value": "kept"})
            await run.core.prune()
            facts = await days.tools_mod.facts(store, home)
            self.assertEqual(facts, {"on_duty_2026-11-09": "gonza", "plan": "kept"})


class Sources(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
    async def test_a_source_that_breaks_comes_back(self):
        runs = []

        async def job(core):
            runs.append(1)
            if len(runs) < 3:
                raise OSError("away")
            return "fine"

        class Core:
            published = []

            def publish(self, kind, **fields):
                self.published.append(fields["status"])
        core = Core()
        self.assertEqual(await sources.forever(core, "x", job, wait=0), "fine")
        self.assertEqual(len(runs), 3)
        self.assertEqual(core.published, ["restarting after OSError", "restarting after OSError"])

    @unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
    async def test_telegram_failing_doesnt_stop_the_poll_and_nothing_is_lost(self):
        class Update:
            update_id, chat_id, text, voice_file_id = 5, "1", "hola", None

        calls, got = [], []

        class Bot:
            def __init__(self, token):
                pass

            def poll(self, offset, timeout):
                calls.append(offset)
                if len(calls) == 1:
                    raise MessagingError("Telegram failed")
                if len(calls) == 2:
                    return [Update()]
                raise asyncio.CancelledError

        class Core:
            def publish(self, kind, **fields):
                pass

            async def dispatch(self, *a, **kw):
                got.append(a)
        original, wait = sources.TelegramMessenger, sources.asyncio.sleep
        sources.TelegramMessenger = Bot
        self.addCleanup(setattr, sources, "TelegramMessenger", original)
        os.environ["TELEGRAM_CHAT_ID"] = "1"
        self.addCleanup(os.environ.pop, "TELEGRAM_CHAT_ID", None)

        async def no_wait(_):
            return await wait(0)
        sources.asyncio.sleep = no_wait
        self.addCleanup(setattr, sources.asyncio, "sleep", wait)
        with self.assertRaises(asyncio.CancelledError):
            await sources.telegram(Core())
        self.assertEqual(calls[:3], [None, None, 6])
        self.assertEqual(got[0][1]["text"], "hola")


if __name__ == "__main__":
    unittest.main()
