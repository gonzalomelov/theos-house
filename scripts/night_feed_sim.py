"""Simulated nights for the 3 AM feed (issue #110): every night of the simulated week, minute by minute.

Every push, white noise drop and light-on is also checked against when the simulated baby is awake (awake_windows):
the parent must never be pushed and the white noise never lowered while he sleeps.

For each night from 22:00 to 06:00 the log holds the simulated week up to 22:00. During the night the baby cries on
the Tapo microphone 4 minutes before each real feed in the fixture (a "sound" event, as house_sounds publishes it),
and the parent logs the feed by voice one minute after it starts, through the voice bridge over HTTP, with the fake
rule-based brain. The night feed plug-in, the house tools (no token, so dry) and the white noise run on the same
clock. Nothing leaves the machine and nothing in the house changes.

    .venv/bin/python scripts/night_feed_sim.py [--out results/night-feed]
"""
import argparse
import datetime
import json
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
from parenting_agent.house_sounds import HouseSounds  # noqa: E402
from parenting_agent.house_tools import ALONE, HouseTools  # noqa: E402
from parenting_agent.night_feed import NightFeed, predict  # noqa: E402
from parenting_agent.rhythm import patterns  # noqa: E402
from parenting_agent.rhythm.log import FixtureLog  # noqa: E402
from parenting_agent.voice_bridge import VoiceBridge  # noqa: E402

TZ = datetime.timezone(datetime.timedelta(hours=-3))
MINUTE = datetime.timedelta(minutes=1)


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


class NightLog:
    """The week before the night from the fixture, then only what the agent logged during the night."""

    def __init__(self, before, agent_log):
        self.before, self.agent_log = before, agent_log

    def entries(self):
        rows = list(self.before)
        for i, e in enumerate(self.agent_log.entries(None, None, 100_000)):
            d, ref = e["details"], f"voice#{i}"
            if e["kind"] == "feeding":
                rows.append({"kind": "feeding", "start": e["ts"], "method": d.get("method"), "amount": d.get("amount_ml"), "ref": ref})
            elif e["kind"] == "note":
                rows.append({"kind": "note", "time": e["ts"], "note": d.get("text", ""), "ref": ref})
        return rows


def utterance(feed):
    if feed.get("method") == "bottle":
        return f"baby agent, fed {feed.get('amount') or 90} ml bottle"
    return f"baby agent, fed {feed.get('method')}"


def post(url, token, text):
    request = urllib.request.Request(url, data=json.dumps({"text": text, "source": "echo", "person": "parent"}).encode(),
                                     method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def run_night(rows, start, tmp, cries_on=True, brain_factory=None, extra_before=()):
    """brain_factory(agent, feed, white_noise) returns a house brain (house_brain.HouseBrain) that ticks each minute
    before the night feed and explains the night at the end. extra_before adds log rows before the night."""
    end = start + datetime.timedelta(hours=8)
    truth = [r for r in rows if r["kind"] == "feeding" and start <= patterns.when(r) < end]
    before = [r for r in rows if patterns.when(r) < start] + list(extra_before)
    clock = Clock(start)
    with mock.patch.object(memory_mod, "now", lambda: clock.moment.isoformat(timespec="seconds")):
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": [],
                       "house": {"live": False, "ha_token_env": "NO_TOKEN_IN_THE_SIM"},
                       "voice_bridge": {"port": 0, "host": "127.0.0.1", "token_file": str(Path(tmp) / "voice-token")}})
        config["allowed_tools"] = config["allowed_tools"] + list(ALONE)
        agent = build(config)
        agent.bus.subscribe(lambda e: e.__setitem__("sim_at", clock.moment.isoformat()))
        log = NightLog(before, agent.baby_log)
        house = HouseTools(agent, config)
        sounds = HouseSounds(agent, config, log=log, clock=clock)
        feed = NightFeed(agent, config, log=log, clock=clock)
        bridge = VoiceBridge(agent, config, token="sim-token-" + "x" * 16)
        agent.plugins = [house, sounds, feed, bridge]
        agent.start()
        bridge.start()
        url = f"http://127.0.0.1:{bridge.port}/ask"
        sounds.device.on("bedtime, before the night starts")
        brain = brain_factory(agent, feed, sounds.device) if brain_factory else None
        duty = []
        agent.bus.subscribe(lambda e: duty.append({"at": clock.moment, "to": e["on_duty"], "rota": rota(log, clock.moment)})
                            if e.get("step") == "prepare" else None, ["night_feed"])
        cries = {patterns.when(f) - datetime.timedelta(minutes=4): f for f in truth} if cries_on else {}
        logs = {patterns.when(f) + MINUTE: f for f in truth}
        spoken = []
        try:
            while clock.moment < end:
                now = clock.moment
                if brain is not None:  # the brain runs all along, so it has seen the log before a cry at this minute
                    brain.tick(log.entries(), now, None)
                if now in cries:
                    agent.bus.publish("sound", label="cry", phase="start", episode=len(spoken) + 1, seconds=0, source="sim")
                feed.tick(now)
                if now in logs:
                    answer = post(url, bridge.token, utterance(logs[now]))
                    spoken.append({"at": patterns.hhmm(now), "said": utterance(logs[now]), "reply": answer["reply"]})
                    parent = (feed.episode or {}).get("parent") or feed.on_duty(now)
                    agent.baby_log.add("note", {"text": f"Night wake-up handled by {parent}"})
                clock.moment = now + MINUTE
            if brain is not None:
                brain.explain(end, force=True)
        finally:
            bridge.stop()
            agent.stop()
        history = [e for e in agent.bus.history if e["kind"] in ("night_feed", "virtual_device", "house_call", "white_noise",
                                                                 "house_plan", "house_brain_fallback", "house_explain",
                                                                 "notify")]
        agent.close()
    return truth, history, spoken, duty, brain


def rota(log, moment):
    """The parent the night rota names at a moment, from the wake-up notes in the log (the fixed rule)."""
    handled = [w["parent"] for w in patterns.night_wakeups(log.entries(), TZ) if w["at"] < moment]
    return patterns.next_on_duty(handled, ["Parent A", "Parent B"])


def state_at(history, moment):
    """The study light and the warmer as the events left them at a moment, and since when the warmer was on."""
    light, warmer, warm_since = "off", "off", None
    for e in history:
        if datetime.datetime.fromisoformat(e["sim_at"]) > moment:
            break
        if e["kind"] == "house_call" and e.get("action") == "study_light":
            light = "on" if e["service"] == "light.turn_on" else "off"
        elif e["kind"] == "virtual_device":
            if e["state"] == "on" and warmer == "off":
                warm_since = datetime.datetime.fromisoformat(e["sim_at"])
            elif e["state"] == "off":
                warm_since = None
            warmer = e["state"]
    return light, warmer, warm_since


def summarize(truth, history):
    out = []
    for f in truth:
        start = patterns.when(f)
        light, warmer, since = state_at(history, start)
        out.append({"feed": patterns.hhmm(start.astimezone(TZ)), "method": f.get("method"), "light_on": light == "on",
                    "warmer_on": warmer == "on",
                    "warm_min": round((start - since).total_seconds() / 60) if since else None})
    return out


AWAKE_BEFORE = datetime.timedelta(minutes=4)  # the simulated cry, 4 min before the feed
AWAKE_AFTER = datetime.timedelta(minutes=45)  # awake through the feed and the burp


def awake_windows(truth):
    """When the simulated baby is awake: from 4 min before each real feed to 45 min after it starts. Outside these
    windows he is asleep. The same windows hold with or without the cry on the microphone: he wakes either way."""
    return [(patterns.when(f) - AWAKE_BEFORE, patterns.when(f) + AWAKE_AFTER) for f in truth]


def asleep_actions(truth, history):
    """What reached the parent or the nursery while the simulated baby slept, and the warmer's minutes that night."""
    windows = awake_windows(truth)
    asleep = lambda moment: not any(a <= moment < b for a, b in windows)
    pushes, noise_down, light_on, last_level = [], [], [], None
    warm_min, warm_since = 0.0, None
    for e in history:
        moment = datetime.datetime.fromisoformat(e["sim_at"])
        if e["kind"] == "night_feed" and e.get("step") == "push" and asleep(moment):
            pushes.append({"at": patterns.hhmm(moment), "text": e["text"]})
        elif e["kind"] == "white_noise":
            if e["action"] == "level" and last_level is not None and e["level"] < last_level and asleep(moment):
                noise_down.append(patterns.hhmm(moment))
            last_level = e["level"] if e.get("on") else None
        elif e["kind"] == "house_call" and e.get("action") == "study_light" and e.get("service") == "light.turn_on" and asleep(moment):
            light_on.append(patterns.hhmm(moment))
        elif e["kind"] == "virtual_device":
            if e["state"] == "on" and warm_since is None:
                warm_since = moment
            elif e["state"] == "off" and warm_since is not None:
                warm_min += (moment - warm_since).total_seconds() / 60
                warm_since = None
    return {"pushes_while_asleep": pushes, "noise_down_while_asleep": noise_down, "light_on_while_asleep": light_on,
            "warmer_min": round(warm_min)}


def backtest(rows):
    """For each night feed, the error of the prediction made right after the feed before it (the folded rhythm)."""
    feeds = patterns.feeds(rows)
    errors = []
    for prev, cur in zip(feeds, feeds[1:]):
        start = patterns.when(cur)
        if not patterns.is_night(start.astimezone(TZ)):
            continue
        nxt = predict([r for r in rows if patterns.when(r) <= patterns.when(prev)], patterns.when(prev))
        if nxt:
            errors.append(round((start - nxt["at"]).total_seconds() / 60))
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "results" / "night-feed"))
    parser.add_argument("--no-cry", action="store_true", help="the rhythm alone, no cry on the microphone")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = FixtureLog(ROOT / "tests" / "fixtures" / "simweek.json").entries()
    nights, timelines = [], {}
    for day in range(20, 26):
        start = datetime.datetime(2026, 10, day, 22, 0, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as tmp:
            truth, history, spoken, _, _ = run_night(rows, start, tmp, cries_on=not args.no_cry)
        feeds = summarize(truth, history)
        nights.append({"night": f"Oct {day} to {day + 1}", "feeds": feeds, "voice": spoken, **asleep_actions(truth, history),
                       "prepares": sum(1 for e in history if e["kind"] == "night_feed" and e["step"] == "prepare"),
                       "prewarms": sum(1 for e in history if e["kind"] == "night_feed" and e["step"] == "prewarm"),
                       "skips": sum(1 for e in history if e["kind"] == "night_feed" and e["step"] == "skip"),
                       "pushes": [e["text"] for e in history if e["kind"] == "night_feed" and e["step"] == "push"],
                       "rewarms": sum(1 for e in history if e["kind"] == "night_feed" and e["step"] == "rewarm"),
                       "warmer_on": sum(1 for e in history if e["kind"] == "virtual_device" and e["action"] == "on"),
                       "live_calls": sum(1 for e in history if e["kind"] == "house_call" and e.get("live"))})
        timelines[f"{day}"] = [{k: v for k, v in e.items() if k not in ("t", "ts", "unix")} for e in history]
    all_feeds = [f for n in nights for f in n["feeds"]]
    errors = backtest(rows)
    abs_err = sorted(abs(e) for e in errors)
    report = {
        "nights": nights,
        "feeds": len(all_feeds),
        "light_on_at_feed_start": sum(1 for f in all_feeds if f["light_on"]),
        "bottle_feeds": sum(1 for f in all_feeds if f["method"] == "bottle"),
        "bottle_feeds_warmer_on_at_start": sum(1 for f in all_feeds if f["method"] == "bottle" and f["warmer_on"]),
        "warmer_on_for_breast_feeds": sum(1 for f in all_feeds if f["method"] != "bottle" and f["warmer_on"]),
        "warm_min_median": statistics.median([f["warm_min"] for f in all_feeds if f["warm_min"] is not None] or [0]),
        "warm_min_all": [f["warm_min"] for f in all_feeds if f["warm_min"] is not None],
        "prepares": sum(n["prepares"] for n in nights),
        "prewarms": sum(n["prewarms"] for n in nights),
        "rewarms": sum(n["rewarms"] for n in nights),
        "cry_skips": sum(n["skips"] for n in nights),
        "voice_logs": sum(len(n["voice"]) for n in nights),
        "voice_logs_answered_done": sum(1 for n in nights for v in n["voice"] if v["reply"].startswith("Done")),
        "live_house_calls": sum(n["live_calls"] for n in nights),
        "pushes": sum(len(n["pushes"]) for n in nights),
        "pushes_while_asleep": sum(len(n["pushes_while_asleep"]) for n in nights),
        "noise_down_while_asleep": sum(len(n["noise_down_while_asleep"]) for n in nights),
        "light_on_while_asleep": sum(len(n["light_on_while_asleep"]) for n in nights),
        "warmer_min_per_night": [n["warmer_min"] for n in nights],
        "predictor_night_errors_min": errors,
        "predictor_abs_error_median_min": statistics.median(abs_err) if abs_err else None,
        "predictor_within_10_min": sum(1 for e in abs_err if e <= 10),
        "predictor_within_20_min": sum(1 for e in abs_err if e <= 20),
    }
    name = "sim-no-cry" if args.no_cry else "sim"
    (out / f"{name}.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    if not args.no_cry:
        (out / "timeline-oct-20.json").write_text(json.dumps(timelines["20"], indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "nights"}, default=str))
    for n in nights:
        print(n["night"], [(f["feed"], f["method"], f["light_on"], f["warmer_on"], f["warm_min"]) for f in n["feeds"]],
              "skips", n["skips"], "warmer", n["warmer_on"])


if __name__ == "__main__":
    main()
