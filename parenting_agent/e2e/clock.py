"""The fast clock for the end-to-end day: every plug-in's own run loop, on a virtual clock the harness moves.

freezegun freezes datetime.now, time.time and time.monotonic for every thread, so the real code reads the virtual
time wherever it asks for it. Each plug-in's "stopped" event becomes a VirtualEvent: its wait(timeout) returns when the
virtual clock reaches the wake time, not after real seconds. The harness moves the clock one step, then waits until
every plug-in thread is back in its wait with a wake time in the future (quiet): the step is done.
"""
import datetime
import threading
import time

import freezegun

REAL = {"monotonic": time.monotonic}  # captured before the freeze, in a dict so freezegun does not swap it


def _now(cls, tz=None):
    """freezegun 1.5 adds tz_offset to datetime.now(tz) as well, three hours off here. An aware now is the frozen UTC
    instant in that zone, a naive now is the family's wall clock."""
    frozen = cls._time_to_freeze() or freezegun.api.real_datetime.utcnow()
    if tz is not None:
        return freezegun.api.datetime_to_fakedatetime(tz.fromutc(frozen.replace(tzinfo=tz)))
    return freezegun.api.datetime_to_fakedatetime(frozen + cls._tz_offset())


freezegun.api.FakeDatetime.now = classmethod(_now)


class VirtualClock:
    def __init__(self, start, tz):
        self.tz = tz
        offset = start.utcoffset().total_seconds() / 3600 if start.utcoffset() is not None else 0
        # tz_offset makes a naive datetime.now() the family's wall clock, as on the Vostro (TZ=America/Montevideo)
        self.freezer = freezegun.freeze_time(start, tz_offset=offset)
        self.factory = self.freezer.start()
        self.cond = threading.Condition()
        self.events = []

    def now(self):
        return datetime.datetime.now(self.tz)

    def advance(self, seconds):
        with self.cond:
            self.factory.tick(datetime.timedelta(seconds=seconds))
            self.cond.notify_all()

    def event(self, name):
        event = VirtualEvent(self, name)
        self.events.append(event)
        return event

    def busy(self):
        """The names of the plug-in loops still working on the current step."""
        now = self.now()
        return [e.name for e in self.events if not e.flag and not (e.waiting and e.wake is not None and e.wake > now)]

    def quiet(self, timeout_s=600):
        """Waits (real time) until every plug-in loop waits for a later virtual time. Returns the loops still busy."""
        end = REAL["monotonic"]() + timeout_s
        with self.cond:
            while self.busy() and REAL["monotonic"]() < end:
                self.cond.wait(0.05)
            return self.busy()

    def stop(self):
        for event in self.events:
            event.set()
        self.freezer.stop()


class VirtualEvent:
    """threading.Event for a plug-in loop: wait(timeout) counts virtual seconds."""

    def __init__(self, clock, name):
        self.clock, self.name = clock, name
        self.flag, self.waiting, self.wake = False, False, None

    def is_set(self):
        return self.flag

    def set(self):
        with self.clock.cond:
            self.flag = True
            self.clock.cond.notify_all()

    def clear(self):
        self.flag = False

    def wait(self, timeout=None):
        c = self.clock
        with c.cond:
            self.wake = c.now() + datetime.timedelta(seconds=timeout) if timeout is not None else None
            self.waiting = True
            c.cond.notify_all()
            while not self.flag and (self.wake is None or c.now() < self.wake):
                c.cond.wait(0.5)
            self.waiting = False
            return self.flag
