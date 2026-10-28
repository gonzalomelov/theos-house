"""Cries on the simulated week where the true reason is known, for the cry-reason evaluation (issue #32).

The truth is what the week does next, the way a parent learns it: a cry just before a feed was hunger, a cry just
before the diaper change that follows a feed was the diaper, a cry just before he falls asleep was tiredness. The
cry time is a few random minutes before that event, and the reasoner only sees the log up to the cry.
"""
import datetime
import random

from parenting_agent.rhythm.log import parse, when

WARMUP_FEEDS = 4


def candidates(entries, seed=7):
    rng = random.Random(seed)
    rows = sorted(entries, key=when)
    feeds = [e for e in rows if e["kind"] == "feeding"]
    out = []
    for feed in feeds[WARMUP_FEEDS:]:
        out.append({"truth": "hungry", "at": when(feed) - datetime.timedelta(minutes=rng.randint(1, 12)),
                    "resolved_by": feed["ref"]})
    started = when(feeds[WARMUP_FEEDS])
    for i, e in enumerate(rows):
        if when(e) < started:
            continue
        if e["kind"] == "change":
            before = [f for f in feeds if when(f) <= when(e)]
            if before and before[-1].get("end") and when(e) - parse(before[-1]["end"]) <= datetime.timedelta(minutes=15):
                at = max(when(e) - datetime.timedelta(minutes=rng.randint(1, 3)), parse(before[-1]["end"]))
                out.append({"truth": "diaper", "at": at, "resolved_by": e["ref"]})
        elif e["kind"] == "sleep":
            earlier = [r for r in rows[:i] if r["kind"] in ("feeding", "change")]
            last = max((parse(r.get("end") or r.get("time") or r["start"]) for r in earlier), default=None)
            at = when(e) - datetime.timedelta(minutes=rng.randint(1, 8))
            if last is not None and at > last:
                out.append({"truth": "tired", "at": at, "resolved_by": e["ref"]})
    return sorted(out, key=lambda c: c["at"])


def sample(cases, seed=7, per_reason=None):
    """A fixed, stratified pick: 4 hungry, 3 tired, 3 diaper by default."""
    per_reason = per_reason or {"hungry": 4, "tired": 3, "diaper": 3}
    rng = random.Random(seed)
    picked = []
    for reason, n in per_reason.items():
        pool = [c for c in cases if c["truth"] == reason]
        picked += rng.sample(pool, n)
    return sorted(picked, key=lambda c: c["at"])
