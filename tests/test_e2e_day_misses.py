"""The four misses the e2e first-month day kept from Oct 30 to Nov 1 (results/e2e-day/nov1-fix/, 30 of 34).

No next feed reminder before the 06:15, 08:15 and 10:40 feeds, and no diapers low push at 2.4 days left. Offline: fake
Telegram, fixed logs and clocks.
"""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from parenting_agent.agent.people import People
from parenting_agent.day_engine import DayEnginePlugin
from parenting_agent.rhythm.engine import RhythmPlugin
from parenting_agent.sleep_forecast import predict_feed
from tests.test_family_push import CECI, GONZA, Family, at
from tests.test_first_month_assistant import PEOPLE_ES, feeds
from tests.test_home_automations import ListLog

HISTORY = Path(__file__).parent.parent / "parenting_agent" / "e2e" / "history.json"


def history_feeds():
    rows = json.loads(HISTORY.read_text())["feedings"]
    return [{"kind": "feeding", "start": r["start"], "end": r["end"], "ref": f"history#{i}"} for i, r in enumerate(rows)]


class LogHoles(unittest.TestCase):
    def test_days_nobody_logged_do_not_stretch_the_first_guesses_of_the_day(self):
        """The history ends with 19 h and 29 h holes. Before: the 05:55 feed made the next one 10:53, after the 08:15 and
        10:40 feeds. A first-month rhythm of about 2 h 20 min puts it before 08:15."""
        rows = history_feeds() + feeds(at(29, 5, 55))
        rows[-1]["ref"] = "feeding#day"
        nxt = predict_feed(rows, at(29, 6, 0))
        self.assertLessEqual(nxt["at"], at(29, 8, 35), nxt)
        self.assertGreaterEqual(nxt["at"], at(29, 7, 45), nxt)
        rows += [{**feeds(at(29, 8, 0))[0], "ref": "feeding#day2"}]
        nxt = predict_feed(rows, at(29, 8, 20))
        self.assertLessEqual(nxt["at"], at(29, 11, 0), nxt)  # told 20 min before, by the 10:40 feed

    def test_only_holes_means_no_guess(self):
        from parenting_agent.rhythm import patterns
        self.assertIsNone(patterns.next_feed(feeds(at(27, 8, 0), at(28, 8, 0)), at(28, 9, 0)))


class Reminders(unittest.TestCase):
    def family(self, tmp, now, rows):
        family = Family(tmp, now, rows=rows, plugins=("night", "push"), extra={"people": PEOPLE_ES})
        family.agent.people = family.push.people = family.night.people = People(PEOPLE_ES)
        rhythm = RhythmPlugin(family.agent, family.config, log=ListLog(rows), clock=family.clock)
        family.agent.plugins.insert(1, rhythm)
        return family, rhythm

    def ceci_asks_to_sleep(self, family, now):
        family.clock.moment = now
        family.agent.bus.publish("message", channel="telegram", text="Esta noche necesito dormir.", chat_id=CECI,
                                 person="ceci")
        family.messenger.sent.clear()

    def test_the_first_morning_feed_is_told_to_the_parent_on_duty_only(self):
        """The 06:15 feed: expected at 05:30, still night, so before it went untold. Now Gonza, on duty, is told."""
        rows = feeds(at(29, 18, 15), at(29, 20, 45), at(29, 23, 15), at(30, 3, 0))
        with tempfile.TemporaryDirectory() as tmp:
            family, rhythm = self.family(tmp, at(29, 20, 0), rows)
            try:
                self.ceci_asks_to_sleep(family, at(29, 20, 0))
                self.assertEqual(len(rhythm.tick(at(30, 5, 10))), 1)
                self.assertEqual(rhythm.tick(at(30, 5, 20)), [])
                self.assertEqual(len(family.sent_to(GONZA)), 1)
                self.assertTrue(family.sent_to(GONZA)[0].startswith("Próxima toma en unos 20 min, cerca de las 05:30"))
                self.assertEqual(family.sent_to(CECI), [])
            finally:
                family.close()

    def test_a_feed_deep_in_the_night_is_still_the_night_feeds_job(self):
        rows = feeds(at(29, 19, 0), at(29, 21, 0), at(29, 23, 0))
        with tempfile.TemporaryDirectory() as tmp:
            family, rhythm = self.family(tmp, at(30, 0, 45), rows)
            try:
                self.assertEqual(rhythm.tick(at(30, 0, 45)), [])
                self.assertEqual(family.messenger.sent, [])
            finally:
                family.close()

    def test_after_a_parent_asked_to_sleep_the_evening_reminder_goes_to_the_other_only(self):
        rows = feeds(at(29, 13, 0), at(29, 15, 30), at(29, 18, 0))
        with tempfile.TemporaryDirectory() as tmp:
            family, rhythm = self.family(tmp, at(29, 20, 0), rows)
            try:
                self.ceci_asks_to_sleep(family, at(29, 20, 0))
                self.assertEqual(len(rhythm.tick(at(29, 20, 15))), 1)
                self.assertEqual(len(family.sent_to(GONZA)), 1)
                self.assertEqual(family.sent_to(CECI), [])
            finally:
                family.close()

    def test_by_day_both_parents_get_it(self):
        rows = feeds(at(29, 6, 0), at(29, 8, 20))
        with tempfile.TemporaryDirectory() as tmp:
            family, rhythm = self.family(tmp, at(29, 10, 30), rows)
            try:
                self.assertEqual(len(rhythm.tick(at(29, 10, 30))), 1)
                self.assertEqual((len(family.sent_to(GONZA)), len(family.sent_to(CECI))), (1, 1))
            finally:
                family.close()


class DiapersLow(unittest.TestCase):
    def test_one_push_to_both_when_the_stock_covers_under_three_days(self):
        """The e2e day: 26 at 06:20, a change every 2 to 3 h. At 16:00, 22 left at about 8 a day is 2.75 days."""
        rows = [{"kind": "note", "time": at(29, 6, 20).isoformat(), "note": "Stock: diapers 26", "ref": "notes/1"}]
        rows += [{"kind": "change", "time": at(29, h, m).isoformat(), "wet": True, "ref": f"changes/{i}"}
                 for i, (h, m) in enumerate(((6, 12), (8, 20), (10, 42), (13, 27), (16, 0), (18, 40)))]
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(29, 16, 1), plugins=("push",), extra={"people": PEOPLE_ES})
            try:
                family.agent.people = family.push.people = People(PEOPLE_ES)
                engine = DayEnginePlugin(family.agent, family.config, client=None, log=ListLog(rows), clock=family.clock)
                family.agent.plugins.append(engine)
                for now in (at(29, 13, 30), at(29, 16, 1), at(29, 18, 41)):
                    seen = [r for r in rows if datetime.datetime.fromisoformat(r["time"]) <= now]
                    engine.engine.supplies(seen, now, engine.house(now))
                for chat in (GONZA, CECI):
                    sent = family.sent_to(chat)
                    self.assertEqual(len(sent), 1, sent)
                    self.assertIn("Pañales", sent[0])
                    self.assertIn("Quedan unos 22", sent[0])
            finally:
                family.close()


if __name__ == "__main__":
    unittest.main()
