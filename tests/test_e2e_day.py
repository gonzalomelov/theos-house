"""The end-to-end day harness (parenting_agent/e2e): the fast clock and the parent's-eye scorer. Offline."""
import datetime
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
