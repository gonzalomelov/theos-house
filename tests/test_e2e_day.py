"""The end-to-end day harness (parenting_agent/e2e): the fast clock and the parent's-eye scorer. Offline."""
import datetime
import json
import threading
import unittest

try:
    import freezegun  # noqa: F401
    HAVE_FREEZEGUN = True
except ImportError:
    HAVE_FREEZEGUN = False

from parenting_agent.e2e import score

TZ = datetime.timezone(datetime.timedelta(hours=-3))


@unittest.skipUnless(HAVE_FREEZEGUN, "freezegun is not installed")
class VirtualClockTest(unittest.TestCase):
    def test_every_way_to_read_the_time_agrees(self):
        import time
        from parenting_agent.e2e.clock import VirtualClock
        clock = VirtualClock(datetime.datetime(2026, 10, 29, 6, 0, tzinfo=TZ), TZ)
        try:
            self.assertEqual(datetime.datetime.now(TZ).isoformat(), "2026-10-29T06:00:00-03:00")
            self.assertEqual(datetime.datetime.now().strftime("%H:%M"), "06:00")
            self.assertEqual(datetime.datetime.fromtimestamp(time.time(), TZ).strftime("%H:%M"), "06:00")
            clock.advance(90)
            self.assertEqual(clock.now().strftime("%H:%M:%S"), "06:01:30")
        finally:
            clock.stop()

    def test_a_loop_waits_in_virtual_time_and_the_step_is_quiet_when_it_waits_again(self):
        from parenting_agent.e2e.clock import VirtualClock
        clock = VirtualClock(datetime.datetime(2026, 10, 29, 6, 0, tzinfo=TZ), TZ)
        ticks = []
        event = clock.event("loop")

        def loop():
            while not event.is_set():
                ticks.append(clock.now().strftime("%H:%M"))
                event.wait(60)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        try:
            self.assertEqual(clock.quiet(5), [])
            for _ in range(3):
                clock.advance(60)
                self.assertEqual(clock.quiet(5), [])
            self.assertEqual(ticks, ["06:00", "06:01", "06:02", "06:03"])
        finally:
            clock.stop()
            thread.join(2)


class ScoreTest(unittest.TestCase):
    def test_english_is_found_sentence_by_sentence(self):
        self.assertFalse(score.english("Registrado: mamadera de 80 ml."))
        self.assertTrue(score.english("Buen día, Gonza.\nLa casa de noche: At 07:00 the plan was armed for the nap."))
        self.assertFalse(score.english("«Le di 90 ml» Anotado."))  # the parent's own heard words do not count

    def test_a_repeated_confirmation_is_no_duplicate_a_repeated_push_is(self):
        run = {"steps": [], "chats": {}}
        rows = [{"at": "2026-10-29T06:12:00-03:00", "to": "gonza", "text": "Pañal mojado registrado.", "proactive": False},
                {"at": "2026-10-29T08:12:00-03:00", "to": "gonza", "text": "Pañal mojado registrado.", "proactive": False},
                {"at": "2026-10-29T08:15:00-03:00", "to": "ceci", "text": "Próxima toma cerca de las 10:40.", "proactive": True},
                {"at": "2026-10-29T09:15:00-03:00", "to": "ceci", "text": "Próxima toma cerca de las 10:40.", "proactive": True}]
        judged = score.judge_messages(rows, run, [])
        self.assertEqual([r["problems"] for r in judged], [[], [], [], ["duplicate"]])

    def test_internal_words_are_noise(self):
        rows = [{"at": "2026-10-29T07:30:00-03:00", "to": "ceci", "proactive": True,
                 "text": "La casa de noche: invalid answer, not a JSON object (finish_reason length)."}]
        self.assertIn("internal text", score.judge_messages(rows, {"steps": [], "chats": {}}, [])[0]["problems"][0])


if __name__ == "__main__":
    unittest.main()


class MemoryBabyBuddy:
    """The harness's Baby Buddy client over an in-memory store with two children, filtered by child like the server."""

    def __init__(self):
        from parenting_agent.e2e import harness
        self.children = [{"id": 1, "first_name": "Test", "slug": harness.SHARED_CHILD},
                         {"id": 2, "first_name": "E2E", "slug": harness.E2E_CHILD}]
        self.rows, self.next_id = {e: {} for e in harness.ENDPOINTS}, 1000
        self.client = harness.BabyBuddy("http://babybuddy.invalid", "no-token")
        self.client.call = self.call

    def add(self, endpoint, child, **row):
        self.next_id += 1
        self.rows[endpoint][self.next_id] = {"id": self.next_id, "child": child, **row}
        return self.next_id

    def call(self, method, path, body=None):
        parts = [p for p in path.split("?")[0].split("/") if p]
        if parts[1] == "children":
            return {"results": self.children}
        endpoint = parts[1]
        if method == "GET":
            child = int(path.split("child=")[1].split("&")[0])
            return {"results": [r for r in self.rows[endpoint].values() if r["child"] == child]}
        if method == "POST":
            return self.rows[endpoint][self.add(endpoint, **body)]
        if method == "DELETE":
            del self.rows[endpoint][int(parts[2])]
            return None


class IsolationTest(unittest.TestCase):
    """The day runs on its own child: entries written elsewhere (a demo's bottle on Test Baby, a stray entry left on
    E2E Baby) never reach the agent under test, and nothing else is configured to write to that child."""

    def test_reset_leaves_only_the_history_on_the_e2e_child_and_never_touches_test_baby(self):
        from parenting_agent.e2e import harness
        bb = MemoryBabyBuddy()
        demo_bottle = bb.add("feedings", 1, start="2026-10-31T13:40:00Z", end="2026-10-31T13:55:00Z", amount=90.0,
                             tags=["e2e"])
        demo_diaper = bb.add("changes", 1, time="2026-10-31T21:54:50Z", wet=False, solid=True)
        bb.add("feedings", 2, start="2026-10-31T13:40:00Z", end="2026-10-31T13:55:00Z", amount=90.0)
        bb.add("timers", 2, name="sleep", start="2026-10-30T06:30:00Z")
        history = json.loads(harness.HISTORY.read_text())
        e2e = bb.client.child(harness.E2E_CHILD)

        removed, written = bb.client.reset(e2e, history)
        self.assertEqual(removed, 2)
        seen = bb.client.entries(e2e["id"])
        self.assertEqual(len(seen), sum(map(len, history.values())))
        self.assertEqual(sorted(r["id"] for r in seen), sorted(i for ids in written.values() for i in ids))
        self.assertFalse([r for r in seen if r["endpoint"] == "timers"])
        self.assertEqual({r["id"] for r in bb.client.entries(1)}, {demo_bottle, demo_diaper})

        bb.client.reset(e2e, history)  # a second run starts from the same history, not from the first run's entries
        self.assertEqual(len(bb.client.entries(e2e["id"])), sum(map(len, history.values())))

    def test_reset_refuses_the_shared_test_child(self):
        from parenting_agent.e2e import harness
        bb = MemoryBabyBuddy()
        bb.add("feedings", 1, start="2026-10-31T13:40:00Z", end="2026-10-31T13:55:00Z", amount=90.0)
        with self.assertRaises(RuntimeError):
            bb.client.reset(bb.client.child(harness.SHARED_CHILD), {})
        self.assertEqual(len(bb.client.entries(1)), 1)

    def test_the_history_ends_before_the_day_and_the_agent_is_pointed_at_the_e2e_child(self):
        from parenting_agent.e2e import day, harness
        start, _ = day.window(datetime.date(2026, 10, 29))
        history = json.loads(harness.HISTORY.read_text())
        stamps = [datetime.datetime.fromisoformat((r.get("end") or r["time"]).replace("Z", "+00:00"))
                  for rows in history.values() for r in rows]
        self.assertGreater(len(stamps), 200)
        self.assertLess(max(stamps), start)
        self.assertFalse([r for rows in history.values() for r in rows if "child" in r])
        run = harness.Run("t", harness.ROOT / "config/agent.vostro.json", "/nonexistent", start, start, [])
        config = run.config({"slug": harness.E2E_CHILD, "first_name": "E2E"})
        self.assertEqual(config["baby_log"]["child"], harness.E2E_CHILD)
        self.assertEqual(config["rhythm"]["child"], "E2E")

    def test_nothing_but_the_e2e_day_writes_to_the_e2e_child(self):
        from parenting_agent.e2e import harness
        root = harness.ROOT
        allowed = {root / "parenting_agent/e2e/harness.py"}
        files = [p for d in ("config", "scripts", "simweek", "apps", "deploy", "parenting_agent", "skills")
                 for p in (root / d).rglob("*") if p.suffix in (".py", ".json", ".sh", ".js", ".ts", ".swift")
                 and "node_modules" not in p.parts and p.name != "history.json"]
        self.assertGreater(len(files), 50)
        named = [str(p.relative_to(root)) for p in files if p not in allowed and p.is_file()
                 and any(k in p.read_text(errors="ignore") for k in (harness.E2E_CHILD, "E2E_CHILD", '"E2E"'))]
        self.assertEqual(named, [])
        for config in (root / "config").glob("*.json"):
            child = json.loads(config.read_text()).get("baby_log", {}).get("child")
            self.assertNotEqual(child, harness.E2E_CHILD, config.name)
        for script in ("glasses_hud_day.py", "glasses_day_noise.py"):
            self.assertIn("bb.child(harness.SHARED_CHILD)", (root / "scripts" / script).read_text())
