"""Daily baby laundry (issue #111): cycle detection on synthetic washer profiles, then two simulated days.

1. Detection: N synthetic washes (seeded), each a fill, a heat, drum turns with quiet pauses, a spin and standby,
   plus door-lock blips. The power shapes are an assumption written below, not a measured washer: the real plug
   has to be checked against one real wash once it is bought. Also a sweep of end_min, the quiet that ends a cycle.
2. Two days on the same clock, minute by minute: Oct 21 (one household load, never marked, so the 19:00 reminder
   fires) and Oct 22 (a load marked "baby load" by voice through the voice bridge with the fake brain, so no reminder
   and the bodysuits count clean again). Spit-up and blowout notes are added to the simulated week's log, labeled.

    .venv/bin/python scripts/laundry_sim.py [--out results/laundry] [--washes 300]
"""
import argparse
import datetime
import json
import random
import statistics
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent.agent import build  # noqa: E402
from parenting_agent.agent import config as config_mod  # noqa: E402
from parenting_agent.agent import memory as memory_mod  # noqa: E402
from parenting_agent.house_tools import ALONE, HouseTools  # noqa: E402
from parenting_agent.laundry import DEFAULTS, Laundry, Washer  # noqa: E402
from parenting_agent.rhythm.log import FixtureLog  # noqa: E402
from parenting_agent.voice_bridge import VoiceBridge  # noqa: E402

TZ = datetime.timezone(datetime.timedelta(hours=-3))
MINUTE = datetime.timedelta(minutes=1)


def wash(rng, start):
    """Minute readings of one synthetic wash and the minute it really ended. Assumed shape: fill 2-5 min at 5-15 W,
    heat 0-25 min at 1800-2200 W, 4-8 drum phases of 5-12 min at 80-500 W each followed by a quiet pause of 1-5 min
    at 0.5-4 W, a spin of 6-15 min at 250-600 W, then standby at 0.3-2 W."""
    rows, t = [], start
    def run(low, high, minutes):
        nonlocal t
        for _ in range(minutes):
            rows.append((t, rng.uniform(low, high)))
            t += MINUTE
    run(0.3, 2, 10)
    began = t
    run(5, 15, rng.randint(2, 5))
    run(1800, 2200, rng.choice([0, 0, 10, 15, 20, 25]))
    for _ in range(rng.randint(4, 8)):
        run(80, 500, rng.randint(5, 12))
        run(0.5, 4, rng.randint(1, 5))
    run(250, 600, rng.randint(6, 15))
    ended = t
    run(0.3, 2, 30)
    return rows, began, ended


def blip(rng, start):
    rows = [(start + i * MINUTE, rng.uniform(0.3, 2)) for i in range(5)]
    rows += [(start + (5 + i) * MINUTE, rng.uniform(20, 40)) for i in range(rng.randint(1, 4))]
    t = rows[-1][0]
    rows += [(t + (1 + i) * MINUTE, rng.uniform(0.3, 2)) for i in range(20)]
    return rows


def detect(rows, s):
    washer, out = Washer(s), []
    for moment, watts in rows:
        change = washer.feed(watts, moment)
        if change:
            out.append((change, moment, washer.ended if change != "started" else washer.started))
    return out


def detection(washes, seed, end_min):
    rng = random.Random(seed)
    s = {**DEFAULTS, "end_min": end_min}
    exact, false_end, missed, start_delay, end_delay, blips_counted = 0, 0, 0, [], [], 0
    for i in range(washes):
        rows, began, ended = wash(rng, datetime.datetime(2026, 10, 21, 9, 0, tzinfo=TZ))
        found = detect(rows, s)
        kinds = [k for k, _, _ in found]
        if kinds == ["started", "finished"]:
            exact += 1
            start_delay.append((found[0][1] - began).total_seconds() / 60)
            end_delay.append((found[1][1] - ended).total_seconds() / 60)
        elif "finished" not in kinds:
            missed += 1
        else:
            false_end += 1
        if [k for k, _, _ in detect(blip(rng, datetime.datetime(2026, 10, 21, 9, 0, tzinfo=TZ)), s)].count("finished"):
            blips_counted += 1
    return {"end_min": end_min, "washes": washes, "one_start_one_finish": exact, "ended_too_early": false_end,
            "missed": missed, "blips_counted_as_a_load": blips_counted,
            "start_seen_after_min_median": statistics.median(start_delay) if start_delay else None,
            "finish_pushed_after_min_median": statistics.median(end_delay) if end_delay else None}


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


class DayLog:
    def __init__(self, rows):
        self.rows = rows

    def entries(self):
        return self.rows


def post(url, token, text):
    request = urllib.request.Request(url, data=json.dumps({"text": text, "source": "assist", "person": "parent"}).encode(),
                                     method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def two_days(seed):
    rng = random.Random(seed)
    rows = [r for r in FixtureLog(ROOT / "tests" / "fixtures" / "simweek.json").entries()]
    extra = [("2026-10-21T08:40:00-03:00", "note", "[simulated laundry] Spit up after the feed"),
             ("2026-10-21T13:15:00-03:00", "change", "[simulated laundry] blowout"),
             ("2026-10-21T17:50:00-03:00", "note", "[simulated laundry] Spit up on the bodysuit"),
             ("2026-10-22T07:30:00-03:00", "note", "[simulated laundry] Changed his outfit, small leak")]
    for i, (when, kind, text) in enumerate(extra):
        rows.append({"kind": kind, "time": when, ("note" if kind == "note" else "notes"): text, "ref": f"laundry-extra#{i}"})
    start = datetime.datetime(2026, 10, 21, 7, 0, tzinfo=TZ)
    clock = Clock(start)
    loads = {datetime.datetime(2026, 10, 21, 9, 0, tzinfo=TZ): False, datetime.datetime(2026, 10, 22, 10, 0, tzinfo=TZ): True}
    power = {}
    for at, _ in loads.items():
        readings, _, _ = wash(rng, at)
        power.update({m: w for m, w in readings})
    timeline = []
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(memory_mod, "now", lambda: clock.moment.isoformat(timespec="seconds")):
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": [],
                       "house": {"live": False, "ha_token_env": "NO_TOKEN_IN_THE_SIM"},
                       "voice_bridge": {"port": 0, "host": "127.0.0.1", "token_file": str(Path(tmp) / "voice-token")}})
        config["allowed_tools"] = config["allowed_tools"] + list(ALONE) + ["laundry_status", "mark_baby_load", "set_clean_bodysuits"]
        agent = build(config)
        agent.bus.subscribe(lambda e: e.__setitem__("sim_at", clock.moment.isoformat()))
        house = HouseTools(agent, config)
        laundry = Laundry(agent, config, log=DayLog(rows), clock=clock)
        bridge = VoiceBridge(agent, config, token="sim-token-" + "y" * 16)
        agent.plugins = [house, laundry, bridge]
        agent.start()
        bridge.start()
        url = f"http://127.0.0.1:{bridge.port}/ask"
        counts = {}
        try:
            while clock.moment < start + datetime.timedelta(hours=40):
                now = clock.moment
                laundry.reading(power.get(now, 0.8), now)
                laundry.tick(now)
                for at, baby in loads.items():
                    if baby and now == at + 20 * MINUTE:
                        answer = post(url, bridge.token, "baby agent, baby load")
                        timeline.append({"at": now.isoformat(), "said": "baby agent, baby load", "reply": answer["reply"]})
                if now.minute == 0 and now.hour in (8, 12, 18, 22):
                    counts[now.isoformat()] = laundry.clean_bodysuits(now)["count"]
                clock.moment = now + MINUTE
            status = post(url, bridge.token, "baby agent, laundry status")
            status_tool = laundry.status_text()
        finally:
            bridge.stop()
            agent.stop()
        for e in agent.bus.history:
            if e["kind"] == "laundry":
                timeline.append({k: v for k, v in e.items() if k not in ("t", "ts", "unix", "kind")})
        pushes = [e for e in agent.bus.history if e["kind"] == "house_call" and e.get("action") == "push_gonza"]
        live = sum(1 for e in agent.bus.history if e["kind"] == "house_call" and e.get("live"))
        agent.close()
    timeline.sort(key=lambda e: e.get("sim_at") or e.get("at"))
    return {"timeline": timeline, "bodysuits": counts, "pushes": len(pushes),
            "pushes_dry": sum(1 for p in pushes if p["status"] == "dry"), "live_house_calls": live,
            "status_by_voice_fake_brain": status["reply"], "status_tool": status_tool}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "results" / "laundry"))
    parser.add_argument("--washes", type=int, default=300)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sweep = [detection(args.washes, 29, m) for m in (2, 3, 4, 5, 6, 8)]
    days = two_days(29)
    (out / "detection.json").write_text(json.dumps(sweep, indent=1) + "\n")
    (out / "two-days.json").write_text(json.dumps(days, indent=1, default=str) + "\n")
    for row in sweep:
        print(row)
    for e in days["timeline"]:
        print(e)
    print("bodysuits", days["bodysuits"], "pushes", days["pushes"], "dry", days["pushes_dry"], "live", days["live_house_calls"])
    print("status", days["status_by_voice_fake_brain"], "|", days["status_tool"])


if __name__ == "__main__":
    main()
