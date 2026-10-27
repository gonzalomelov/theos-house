import datetime
import json
import unittest
from pathlib import Path

from simweek import TAG
from simweek.babybuddy import FIELDS
from simweek.generate import CLUSTER_DAY, TZ, generate, out_of_range, summarize

ANCHOR = datetime.datetime(2026, 10, 27, tzinfo=TZ)
FIXTURE = Path(__file__).parent / "fixtures" / "simweek.json"


def stamp(entry):
    return datetime.datetime.fromisoformat(entry.get("start") or entry["time"])


class Determinism(unittest.TestCase):
    def test_same_seed_same_week(self):
        self.assertEqual(generate(7, ANCHOR), generate(7, ANCHOR))

    def test_other_seed_other_week(self):
        self.assertNotEqual(generate(7, ANCHOR), generate(8, ANCHOR))


class Shape(unittest.TestCase):
    def setUp(self):
        self.week = generate(7, ANCHOR)

    def test_seven_days_all_in_the_past(self):
        days = {stamp(e).astimezone(TZ).date() for e in self.week}
        self.assertEqual(len(days), 7)
        self.assertTrue(all(stamp(e) < ANCHOR for e in self.week))
        self.assertTrue(all(datetime.datetime.fromisoformat(e["end"]) < ANCHOR for e in self.week if "end" in e))

    def test_every_entry_is_tagged_and_fits_baby_buddy(self):
        for e in self.week:
            self.assertEqual(e["tags"], [TAG])
            self.assertIn(e["kind"], FIELDS)

    def test_daily_totals_inside_newborn_ranges(self):
        self.assertEqual(out_of_range(summarize(self.week)), [])

    def test_night_wakeups_split_between_both_parents(self):
        notes = [e["note"] for e in self.week if e["kind"] == "note" and "Night wake-up" in e["note"]]
        a = sum("Parent A" in n for n in notes)
        b = sum("Parent B" in n for n in notes)
        self.assertGreater(a, 0)
        self.assertLessEqual(abs(a - b), 1)

    def test_baths_and_unusual_days_present(self):
        totals = list(summarize(self.week).values())
        self.assertGreaterEqual(sum(t["baths"] for t in totals), 2)
        self.assertGreater(totals[CLUSTER_DAY]["feeds"], min(t["feeds"] for t in totals))
        self.assertTrue(any("Unusual" in e.get("note", "") for e in self.week))

    def test_no_real_child_data(self):
        text = json.dumps(self.week)
        for word in ("Theo", "Gonza"):
            self.assertNotIn(word, text)


class Fixture(unittest.TestCase):
    def test_fixture_is_a_valid_week(self):
        week = json.loads(FIXTURE.read_text())
        self.assertEqual(out_of_range(summarize(week)), [])
        self.assertTrue(all(e["tags"] == [TAG] for e in week))


if __name__ == "__main__":
    unittest.main()
