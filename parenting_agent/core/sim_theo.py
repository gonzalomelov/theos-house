"""A simulated Theo for the home's baby log until he arrives in December: plausible feeds, diapers and sleep, day and night, each
tagged simulated. It only writes to the log, so it never wakes the agent or messages anyone, and it only runs on the test child.
It keeps no state: each step reads the last feed from the log, so a restart loses nothing and never backfills.
"""
import asyncio
import datetime
import os
import random
import zoneinfo

from ..agent.babybuddy import BabyBuddyLog
from ..agent.memory import parse_time

TZ = zoneinfo.ZoneInfo("America/Montevideo")
CHILD = "test-baby"
EVERY_S = 300
AWAKE_AFTER_FEED_MIN, AWAKE_BEFORE_FEED_MIN, SHORTEST_SLEEP_MIN = 20, 10, 30


def gap_hours(moment, rng):
    return rng.uniform(3.0, 4.0) if moment.hour >= 22 or moment.hour < 7 else rng.uniform(2.5, 3.5)


def step(log, moment, rng):
    """Writes the next feed when it is due, with the sleep before it and a diaper after it. Returns what it wrote."""
    feeds = [parse_time(e["ts"], TZ) for e in log.entries("feeding", None, 50)]
    last = max(feeds, default=None)
    if last and moment - last < datetime.timedelta(hours=gap_hours(moment, rng)):
        return []
    wrote = []
    if last and moment - last < datetime.timedelta(hours=8):
        start, end = last + datetime.timedelta(minutes=AWAKE_AFTER_FEED_MIN), moment - datetime.timedelta(minutes=AWAKE_BEFORE_FEED_MIN)
        if end - start >= datetime.timedelta(minutes=SHORTEST_SLEEP_MIN):
            log.add("sleep", {"start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds")})
            wrote.append("sleep")
    log.add("feeding", {"amount_ml": rng.choice((70, 80, 90, 100)), "method": "bottle", "type": "formula", "duration_min": rng.randint(10, 20)}, moment.isoformat(timespec="seconds"))
    wrote.append("feeding")
    log.add("diaper", {"wet": True, "solid": rng.random() < 0.35}, moment.isoformat(timespec="seconds"))
    wrote.append("diaper")
    return wrote


async def run(core):
    child = os.environ.get("PA_BABY_CHILD", CHILD)
    if child != CHILD:
        core.publish("source", name="sim_theo", status=f"off, {child} is not the test child")
        return
    log = BabyBuddyLog.from_config({"child": child, "tags": ["simulated"]})
    rng = random.Random()
    while True:
        wrote = await asyncio.to_thread(step, log, datetime.datetime.now(TZ), rng)
        if wrote:
            core.publish("source", name="sim_theo", status="wrote " + ", ".join(wrote))
        await asyncio.sleep(EVERY_S)
