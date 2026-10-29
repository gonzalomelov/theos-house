"""A fixed wall clock for tests whose code under test reads datetime.datetime.now() itself, so they pass on any date.

Everything in the process that calls datetime.datetime.now() (the agent, the Baby Buddy client and the fake Baby
Buddy server thread) sees the same moment. now() with no tz is naive local time, as
in the standard library, so .astimezone() gives the same instant.
"""
import datetime
import unittest.mock

MONTEVIDEO = datetime.timezone(datetime.timedelta(hours=-3))
# Mid afternoon: two hours back and three hours back are still today, whatever date the tests run on.
AFTERNOON = datetime.datetime(2026, 10, 28, 15, 0, tzinfo=MONTEVIDEO)
REAL = datetime.datetime


def frozen(moment=AFTERNOON):
    """A patch that makes datetime.datetime.now() return moment (in tz when one is given)."""
    class Fixed(REAL):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.astimezone().replace(tzinfo=None)
    return unittest.mock.patch.object(datetime, "datetime", Fixed)
