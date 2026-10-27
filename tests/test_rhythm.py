"""Daily rhythm and night shifts on the simulated week (issue #7). No network: the week comes from the fixture."""
import collections
import datetime
import statistics
import tempfile
import unittest
from pathlib import Path

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.rhythm import patterns
from parenting_agent.rhythm.engine import Rhythm, deliver
from parenting_agent.rhythm.log import FixtureLog

FIXTURE = Path(__file__).parent / "fixtures" / "simweek.json"
TZ = datetime.timezone(datetime.timedelta(hours=-3))
PARENTS = ["Parent A", "Parent B"]


def week():
    return FixtureLog(FIXTURE).entries()


class NextFeed(unittest.TestCase):
    def test_estimate_within_30_min_on_the_simulated_week(self):
        errors = patterns.backtest_next_feed(week())
        for row in errors:
            print(f"  next-feed error {row['error_min']:5.1f} min  {row['feed']}")
        mean = statistics.mean(e["error_min"] for e in errors)
        print(f"  {len(errors)} feeds, mean error {mean:.1f} min, median {statistics.median(e['error_min'] for e in errors):.1f} min")
        self.assertLessEqual(mean, 30)

    def test_needs_two_feeds(self):
        one = [e for e in week() if e["kind"] == "feeding"][:1]
        self.assertIsNone(patterns.next_feed(one, patterns.when(one[0])))


class UnusualDays(unittest.TestCase):
    def test_cluster_day_and_short_night_are_noted_without_advice(self):
        notes = patterns.unusual_notes(week(), TZ)
        texts = [n["text"] for n in notes]
        for text in texts:
            print("  note:", text)
            self.assertTrue(patterns.no_advice(text), text)
        self.assertTrue(any("57 min apart" in t for t in texts), "the evening cluster day is noted")
        self.assertTrue(any("1 h 27 min apart" in t for t in texts), "the short night is noted")
        self.assertTrue(all(n["computed_from"] for n in notes))

    def test_advice_words_are_caught(self):
        for text in ["You should call the pediatrician.", "Try feeding more often.", "This looks normal.",
                     "She may have a fever.", "We recommend a shorter nap."]:
            self.assertFalse(patterns.no_advice(text), text)
        self.assertTrue(patterns.no_advice("Fri 23: feeds came 57 min apart around 22:04, usually at least 2 h 06 min."))


class NightShifts(unittest.TestCase):
    def test_shifts_alternate_fairly_across_seven_nights(self):
        wakes = patterns.night_wakeups(week(), TZ)
        assigned = patterns.split_nights([w["at"] for w in wakes], PARENTS)
        per_night = collections.defaultdict(collections.Counter)
        for wake, parent in zip(wakes, assigned):
            key = wake["at"].date() if wake["at"].hour >= 22 else wake["at"].date() - datetime.timedelta(days=1)
            per_night[key][parent] += 1
        for night, counts in sorted(per_night.items()):
            print(f"  night of {night}: " + ", ".join(f"{p} {counts[p]}" for p in PARENTS))
        totals = collections.Counter(assigned)
        print("  week: " + ", ".join(f"{p} {totals[p]}" for p in PARENTS))
        self.assertGreaterEqual(len(per_night), 7)
        self.assertLessEqual(abs(totals["Parent A"] - totals["Parent B"]), 1)
        self.assertTrue(all(a != b for a, b in zip(assigned, assigned[1:])), "wake-ups alternate")

    def test_next_on_duty_balances_and_breaks_ties(self):
        self.assertEqual(patterns.next_on_duty([], PARENTS), "Parent A")
        self.assertEqual(patterns.next_on_duty(["Parent A"], PARENTS), "Parent B")
        self.assertEqual(patterns.next_on_duty(["Parent A", "Parent A", "Parent B"], PARENTS), "Parent B")

    def test_night_summary_names_who_is_on_duty(self):
        summary = patterns.night_summary(week(), datetime.datetime(2026, 10, 26, 7, 31, tzinfo=TZ), TZ, PARENTS)
        print("  summary:", summary["text"])
        self.assertIn("Next on duty: Parent", summary["text"])
        self.assertTrue(summary["computed_from"])
        self.assertTrue(patterns.no_advice(summary["text"]))


class Engine(unittest.TestCase):
    def test_feed_warning_fires_once_before_the_next_feed(self):
        entries = week()
        last = max(patterns.when(e) for e in entries)
        nxt = patterns.next_feed(entries, last)
        rhythm = Rhythm(FixtureLog(FIXTURE))
        early = rhythm.tick(nxt["at"] - datetime.timedelta(minutes=45))
        self.assertFalse([r for r in early if r["kind"] == "next_feed"])
        first = [r for r in rhythm.tick(nxt["at"] - datetime.timedelta(minutes=10)) if r["kind"] == "next_feed"]
        again = [r for r in rhythm.tick(nxt["at"] - datetime.timedelta(minutes=5)) if r["kind"] == "next_feed"]
        self.assertEqual(len(first), 1)
        self.assertEqual(again, [])
        self.assertEqual(first[0]["channel"], "telegram")
        self.assertTrue(first[0]["computed_from"])

    def test_unknown_channel_is_refused(self):
        with self.assertRaises(ValueError):
            Rhythm(FixtureLog(FIXTURE), {"channel": "fax"})

    def test_delivery_goes_through_the_agent_unasked(self):
        agent = build({**config_mod.load(), "data_dir": tempfile.mkdtemp(prefix="rhythm-test-"), "env_file": "/nonexistent"})
        replies = []
        agent.bus.subscribe(replies.append, ["reply"])
        event = deliver(agent, {"kind": "next_feed", "text": "Next feed in about 10 min, around 23:53.",
                                "computed_from": ["feeding@x"], "channel": "partner_phone"})
        self.assertFalse(event["asked"])
        self.assertEqual(replies[0]["channel"], "partner_phone")
        self.assertEqual(agent.memory.recent_messages(1)[0]["text"], "Next feed in about 10 min, around 23:53.")
        agent.close()


if __name__ == "__main__":
    unittest.main()
