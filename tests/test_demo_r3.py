"""Round 3 judge fixes on the public demo (issue #18): no diaper guess right after a feed, a plain "nothing likely"
answer with what to check, a next feed that agrees between the panel and the night summary, a simulated day that keeps
going, and every answer saying whether the AI model or a rule wrote it. Fake or counting brains, no network.
"""
import datetime
import sys
import unittest
from pathlib import Path

from parenting_agent import cry_reason
from parenting_agent.demo.app import TZ
from parenting_agent.rhythm import patterns

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_demo import CountingBrain  # noqa: E402
from test_demo_r2 import PAGE, at, demo  # noqa: E402


def feed(start, minutes=15, ref="f"):
    return {"kind": "feeding", "start": start.isoformat(), "end": (start + datetime.timedelta(minutes=minutes)).isoformat(),
            "ref": ref}


def change(moment, ref="c"):
    return {"kind": "change", "time": moment.isoformat(), "wet": True, "solid": False, "ref": ref}


class DiaperNeedsTime(unittest.TestCase):
    def ctx(self, since_feed, since_change):
        now = at(4, 30)
        entries = [feed(now - datetime.timedelta(hours=6), ref="f1"), feed(now - datetime.timedelta(hours=3), ref="f2"),
                   change(now - datetime.timedelta(minutes=since_change)),
                   feed(now - datetime.timedelta(minutes=since_feed), minutes=0, ref="f3")]
        return cry_reason.context(entries, now, TZ)

    def test_a_feed_just_logged_does_not_point_to_the_diaper(self):
        self.assertFalse(cry_reason.diaper_after_feed(self.ctx(0, 120)))
        self.assertFalse(cry_reason.diaper_after_feed(self.ctx(cry_reason.DIAPER_AFTER_FEED_MIN - 1, 120)))

    def test_a_change_just_done_does_not_point_to_the_diaper(self):
        self.assertFalse(cry_reason.diaper_after_feed(self.ctx(30, cry_reason.DIAPER_MIN_SINCE_CHANGE - 5)))

    def test_an_old_feed_with_no_change_after_it_does(self):
        self.assertTrue(cry_reason.diaper_after_feed(self.ctx(30, 120)))


class RightAfterABottle(unittest.TestCase):
    def ask(self, lang_text, minutes_later=0):
        brain = CountingBrain()
        app, clock = demo(brain, now=at(4, 4))
        self.addCleanup(app.close)
        app.visitor("v").baby_log.add("feeding", {"amount_ml": 90, "method": "bottle"})
        clock["now"] += datetime.timedelta(minutes=minutes_later)
        status, body = app.message("v", True, lang_text)
        self.assertEqual(status, 200)
        self.assertEqual(brain.calls, 0)
        return body

    def test_no_diaper_guess_at_zero_minutes(self):
        body = self.ask("why is he crying?")
        print("0 min after a bottle:", body["reply"])
        self.assertNotIn("Probably a diaper", body["reply"])
        self.assertNotIn("no diaper change since", body["reply"])
        self.assertIn("Nothing in the log points to a likely reason", body["reply"])
        self.assertIn("Things to check:", body["reply"])
        self.assertIn("never a diagnosis", body["reply"])

    def test_spanish_says_nothing_likely_and_what_to_check(self):
        body = self.ask("¿por qué llora?")
        print("0 min, es:", body["reply"])
        self.assertIn("no hay una razón probable", body["reply"])
        self.assertIn("Para revisar:", body["reply"])
        self.assertNotIn("capaz que es el pañal", body["reply"])
        self.assertTrue(cry_reason.no_medical(body["reply"]) and patterns.no_advice(body["reply"].split(" Es solo")[0]))

    def test_nothing_likely_text_passes_the_guards(self):
        body = self.ask("why is he crying?")
        text = body["reply"].replace(" This is only a guess from the log, never a diagnosis.", "")
        self.assertTrue(cry_reason.no_medical(text), text)
        self.assertTrue(patterns.no_advice(text), text)


class NextFeedAgrees(unittest.TestCase):
    def test_panel_and_night_summary_say_the_same_next_feed_all_day(self):
        late = 0
        for minute in range(0, 24 * 60, 10):
            now = at(0) + datetime.timedelta(minutes=minute)
            app, _ = demo(CountingBrain(), now=now)
            p = app.visitor("v").proactive()
            app.close()
            nf, night = p["next_feed"], p["night_summary"]["text"]
            with self.subTest(now=f"{now:%H:%M}"):
                if nf["in_min"] < 0:
                    late += 1
                    self.assertIn(f"A feed was expected around {nf['at']}, {-nf['in_min']} min ago.", night)
                    self.assertEqual(nf["text"], f"A feed was expected around {nf['at']}, {-nf['in_min']} min ago.")
                else:
                    self.assertIn(f"Next feed expected around {nf['at']}.", night)
        print(f"fresh loads with the next feed late: {late} of 144")

    def test_a_feed_going_on_now_counts(self):
        # On this simulated day a feed runs from 04:02 to 04:19. At 04:05 the panel must not call the 02:57 estimate late.
        app, _ = demo(CountingBrain(), now=at(4, 5))
        self.addCleanup(app.close)
        p = app.visitor("v").proactive()
        print("04:05 panel:", p["next_feed"]["text"], "| night:", p["night_summary"]["text"])
        self.assertGreaterEqual(p["next_feed"]["in_min"], 0)
        self.assertNotIn("02:57", p["night_summary"]["text"])

    def test_spanish_summary_translates_a_late_feed(self):
        from parenting_agent.demo.app import night_es
        self.assertEqual(night_es("x. A feed was expected around 02:57, 68 min ago."),
                         "x. Se esperaba una toma cerca de las 02:57, hace 68 min.")


class SpanishPanelText(unittest.TestCase):
    def test_the_next_feed_text_is_spanish_for_a_spanish_page(self):
        for hour, minute in ((15, 0), (3, 30)):
            app, _ = demo(CountingBrain(), now=at(hour, minute))
            p = app.visitor("v").proactive("es")
            app.close()
            with self.subTest(at=f"{hour}:{minute}"):
                self.assertTrue(p["next_feed"]["text"].startswith(("Próxima toma", "Se esperaba una toma")), p["next_feed"]["text"])
                self.assertNotIn("Next feed", p["night_summary"]["text"])


class SimulatedDayKeepsGoing(unittest.TestCase):
    def test_entries_that_happen_while_the_visitor_reads_join_the_log(self):
        app, clock = demo(CountingBrain(), now=at(15))
        self.addCleanup(app.close)
        log = app.visitor("v").baby_log
        before = log.entries("feeding", None, 1)[-1]["ts"]
        clock["now"] = at(18)
        after = log.entries("feeding", None, 1)[-1]["ts"]
        self.assertLess(before, after)
        self.assertLessEqual(datetime.datetime.fromisoformat(after), at(18))
        self.assertGreaterEqual(app.visitor("v").proactive()["next_feed"]["in_min"], -30)

    def test_once_the_visitor_logs_the_day_is_theirs(self):
        app, clock = demo(CountingBrain(), now=at(15))
        self.addCleanup(app.close)
        log = app.visitor("v").baby_log
        log.add("feeding", {"amount_ml": 100, "method": "bottle"})
        count = len(log.entries(None, None, 500))
        clock["now"] = at(20)
        self.assertEqual(len(log.entries(None, None, 500)), count)


class AnswerSaysWhoWroteIt(unittest.TestCase):
    def test_cry_answer_is_from_the_log_and_chat_is_the_model(self):
        brain = CountingBrain()
        app, _ = demo(brain)
        self.addCleanup(app.close)
        self.assertEqual(app.message("v", True, "why is he crying?")[1]["answered_by"], {"kind": "log"})
        by = app.message("v", True, "how was his night?")[1]["answered_by"]
        self.assertEqual(by["kind"], "brain")
        self.assertFalse(by["muse"])
        self.assertGreaterEqual(brain.calls, 1)

    def test_emergency_line_is_a_fixed_reply(self):
        brain = CountingBrain()
        app, _ = demo(brain)
        self.addCleanup(app.close)
        self.assertEqual(app.message("v", True, "he is not breathing")[1]["answered_by"], {"kind": "rule"})
        self.assertEqual(brain.calls, 0)

    def test_page_shows_the_source_and_says_some_answers_are_rules(self):
        page = PAGE.read_text()
        self.assertIn("From the log, no AI", page)
        self.assertIn("Fixed reply, no AI", page)
        self.assertIn("Some come from fixed rules with no AI call", page)
        self.assertNotIn("Your messages go to the AI model for an answer", page)


if __name__ == "__main__":
    unittest.main()
