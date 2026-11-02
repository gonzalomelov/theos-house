"""Blind review round B7 (Nov 2), on baby.bygmv.com and the family agent. Each test fails on the code before the fix.

1. "napped about 40 minutes" was logged as a 1 minute sleep, and "quedó dormido" was not logged at all.
"""
import datetime
import unittest

from test_blind_b6 import NIGHT, night_demo
from test_one_message_one_entry import ScriptedBrain
from test_redteam_r1 import call

from parenting_agent.agent.memory import place_sleep


def sleeps(app):
    v = app.visitor("v")
    return v.baby_log.entries("sleep", (NIGHT - datetime.timedelta(hours=3)).isoformat(), 50)


def minutes(entry):
    d = entry.get("details") or {}
    return d.get("duration_min")


class SleepLength(unittest.TestCase):
    def test_a_length_said_closes_the_open_sleep_with_that_length(self):
        app, clock = night_demo(ScriptedBrain([[call("log_baby_event", kind="sleep", details={"action": "start"})], "Ok."],
                                              [[call("log_baby_event", kind="sleep", details={"action": "end"})], "Ok."]))
        self.addCleanup(app.close)
        app.message("v", False, "he fell asleep")
        clock.now += datetime.timedelta(minutes=1)
        app.message("v", False, "he napped about 40 minutes")
        self.assertEqual(round(minutes(sleeps(app)[-1])), 40)
        self.assertIsNone(app.visitor("v").baby_log.open_sleep())

    def test_a_length_said_right_after_a_bottle_keeps_its_length(self):
        start = (NIGHT - datetime.timedelta(minutes=40)).isoformat()
        app, clock = night_demo(ScriptedBrain(
            [[call("log_baby_event", kind="feeding", details={"amount_ml": 90, "method": "bottle"})], "Ok."],
            [[call("log_baby_event", kind="sleep", details={"start": start, "end": NIGHT.isoformat()})], "Ok."]))
        self.addCleanup(app.close)
        app.message("v", False, "bottle 90 ml")
        clock.now += datetime.timedelta(minutes=1)
        app.message("v", False, "he napped about 40 minutes")
        self.assertGreaterEqual(round(minutes(sleeps(app)[-1])), 39)

    def test_place_sleep_moves_a_told_nap_before_the_feed(self):
        end = NIGHT
        feed = (end - datetime.timedelta(minutes=10), end - datetime.timedelta(minutes=1))
        start, stop = place_sleep(end - datetime.timedelta(minutes=40), end, [feed])
        self.assertEqual(stop, feed[0])
        self.assertEqual(stop - start, datetime.timedelta(minutes=40))

    def test_quedo_dormido_starts_a_sleep_when_the_brain_logged_nothing(self):
        for text in ("quedó dormido", "se quedó dormido"):
            with self.subTest(text=text):
                app, _ = night_demo(ScriptedBrain(["Anotado."]))
                self.addCleanup(app.close)
                v = app.visitor("v")
                v.baby_log.sleep_started = None
                v.baby_log.upcoming = [r for r in v.baby_log.upcoming if r["kind"] != "sleep"]
                body = app.message("v", False, text, lang="es")[1]
                self.assertIsNotNone(v.baby_log.open_sleep(), body["reply"])


if __name__ == "__main__":
    unittest.main()


from parenting_agent.agent import final_guard, rules  # noqa: E402
from parenting_agent.agent.brain import OpenAICompatibleBrain  # noqa: E402
from parenting_agent.rhythm import patterns  # noqa: E402


class CountsFromCode(unittest.TestCase):
    def test_feeds_since_22_come_from_the_log_and_a_wrong_count_is_dropped(self):
        app, _ = night_demo(ScriptedBrain(["Since 22:00 he had 4 feeds totaling 120 ml."]))
        self.addCleanup(app.close)
        v = app.visitor("v")
        since = NIGHT.replace(hour=22, minute=0) - datetime.timedelta(days=1)
        feeds = [e for e in v.baby_log.entries("feeding", (since - datetime.timedelta(hours=3)).isoformat(), 300)
                 if datetime.datetime.fromisoformat((e.get("details") or {}).get("start") or e["ts"]) >= since]
        reply = app.message("v", False, "how many feeds since 22:00?")[1]["reply"]
        self.assertIn(f"Since 22:00: {len(feeds)} feed", reply)
        self.assertNotIn("4 feeds totaling 120 ml", reply)

    def test_diapers_at_night_say_their_unit(self):
        app, _ = night_demo(ScriptedBrain(["Van varios."]))
        self.addCleanup(app.close)
        reply = app.message("v", False, "¿cuántos pañales lleva hoy?", lang="es")[1]["reply"]
        self.assertNotRegex(reply, r"\(\d+ desde las 22:00\)")
        self.assertRegex(reply, r"Desde las 22:00: \d+ pañal")

    def test_a_feed_count_question_is_a_log_question(self):
        self.assertEqual(rules.log_questions("¿cuántas tomas lleva esta noche?"), ["feeds"])


class HoursFormat(unittest.TestCase):
    def test_duration_words(self):
        self.assertEqual(patterns.duration_words(66), "1 h 6 min")
        self.assertEqual(patterns.duration_words(45), "45 min")
        self.assertEqual(patterns.hours_words(12.3), "12 h 18 min")

    def test_no_decimal_hours_in_any_reply(self):
        self.assertEqual(final_guard.plain_hours("longest sleep 1.1 h, 12,3 horas"), "longest sleep 1 h 6 min, 12 h 18 min")

    def test_longest_sleep_is_the_same_on_two_reads(self):
        app, clock = night_demo()
        self.addCleanup(app.close)
        rows = app.visitor("v").baby_log.rhythm_rows()
        a = patterns.night_summary(rows, NIGHT, NIGHT.tzinfo, ["A", "B"], current=True)
        b = patterns.night_summary(rows, NIGHT + datetime.timedelta(seconds=40), NIGHT.tzinfo, ["A", "B"], current=True)
        self.assertEqual(a["longest_min"], b["longest_min"])
        self.assertNotRegex(a["text"], r"\d[.,]\d h")


class CutReplies(unittest.TestCase):
    def test_a_reply_cut_by_max_tokens_keeps_whole_sentences(self):
        reply = OpenAICompatibleBrain.parse({"choices": [{"finish_reason": "length", "message": {
            "content": "Anotado. La próxima toma es cerca de las"}}]})
        self.assertEqual(reply.text, "Anotado.")

    def test_a_cut_sentence_said_again_is_said_once(self):
        text = "Hola. Le di la teta a las 3 y despues se dur Le di la teta a las 3 y despues se durmio. Ok."
        self.assertEqual(final_guard.no_repeats(text), "Hola. Le di la teta a las 3 y despues se durmio. Ok.")
