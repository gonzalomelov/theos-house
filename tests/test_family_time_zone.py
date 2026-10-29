"""A family's clock times are in the family's time zone, whatever zone the server process runs in."""
import datetime
import os
import tempfile
import time
import unittest
import zoneinfo

from parenting_agent.agent import rules
from parenting_agent.agent.memory import Memory
from parenting_agent.families.babylog import FamilyBabyLog

FAMILY = zoneinfo.ZoneInfo("America/Montevideo")


class ServerZoneDoesNotLeak(unittest.TestCase):
    def setUp(self):
        before = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Tokyo"
        time.tzset()
        self.addCleanup(self.restore, before)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        memory = Memory(os.path.join(folder.name, "family.sqlite"))
        self.addCleanup(memory.db.close)
        self.now = datetime.datetime(2026, 10, 29, 0, 20, tzinfo=FAMILY)
        self.log = FamilyBabyLog(memory, lambda: self.now)

    @staticmethod
    def restore(before):
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()

    def test_a_time_with_no_offset_is_the_familys_and_is_stored_and_shown_as_theirs(self):
        entry = self.log.add("feeding", {"amount_ml": 120}, ts="2026-10-29T00:05:00")
        self.assertEqual(entry["ts"], "2026-10-29T00:05:00-03:00")
        self.assertEqual(self.log.find(kind="feeding", at="00:05")["id"], entry["id"])
        summary = self.log.summary()
        self.assertEqual((summary["feedings"]["count"], summary["feedings"]["last_at"]), (1, "00:05"))
        self.assertEqual(summary["now"], "2026-10-29T00:20:00-03:00")

    def test_an_instant_in_another_zone_is_shown_on_the_family_clock(self):
        entry = self.log.add("diaper", {"wet": True}, ts="2026-10-29T03:10:00+00:00")
        self.assertEqual(entry["ts"], "2026-10-29T00:10:00-03:00")
        self.assertEqual(self.log.summary()["diapers"]["last_wet_at"], "00:10")

    def test_a_correction_keeps_the_family_clock(self):
        entry = self.log.add("feeding", {"amount_ml": 120}, ts="2026-10-29T00:05:00")
        after = self.log.update(entry["id"], {"amount_ml": 100})["after"]
        self.assertEqual(after["ts"], "2026-10-29T00:05:00-03:00")
        moved = self.log.update(entry["id"], ts="2026-10-28T23:50:00")["after"]
        self.assertEqual((moved["ts"], moved["details"]["start"]), ("2026-10-28T23:50:00-03:00", "2026-10-28T23:50:00-03:00"))


class SpanAcrossMidnight(unittest.TestCase):
    def test_a_nap_named_by_clock_times_is_the_latest_one_already_over(self):
        at = lambda h, m: datetime.datetime(2026, 10, 29, h, m, tzinfo=FAMILY)  # noqa: E731
        self.assertEqual(rules.latest_span(23, 0, 0, 0, at(2, 0)), ("2026-10-28T23:00:00-03:00", "2026-10-29T00:00:00-03:00"))
        self.assertEqual(rules.latest_span(12, 0, 13, 0, at(15, 0)), ("2026-10-29T12:00:00-03:00", "2026-10-29T13:00:00-03:00"))
        self.assertEqual(rules.latest_span(12, 0, 13, 0, at(0, 30)), ("2026-10-28T12:00:00-03:00", "2026-10-28T13:00:00-03:00"))


if __name__ == "__main__":
    unittest.main()
