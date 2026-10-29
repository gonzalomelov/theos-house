"""A fixed wall clock for tests whose code under test reads datetime.datetime.now() itself, so they pass on any date.

Everything in the process that calls datetime.datetime.now() (the agent, the Baby Buddy client and the fake Baby
Buddy server thread) sees the same moment. now() with no tz is naive local time, as
in the standard library, so .astimezone() gives the same instant.
"""
import datetime
import unittest.mock

REAL = datetime.datetime


def afternoon():
    """Mid afternoon in the process's own zone, which is the house agent's zone (deploy/compose.yml sets TZ): two
    hours back and three hours back are still today, whatever date and zone the tests run on."""
    return REAL(2026, 10, 28, 15, 0).astimezone()


def frozen(moment=None):
    """A patch that makes datetime.datetime.now() return moment (in tz when one is given)."""
    moment = moment or afternoon()

    class Fixed(REAL):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.astimezone().replace(tzinfo=None)
    return unittest.mock.patch.object(datetime, "datetime", Fixed)
