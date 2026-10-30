"""Muse runs the house, replayed and scored against the fixed routines (issue #116).

Three parts, each run once with the fixed routines and once with Muse Spark Open planning (house_brain.py):

1. The simulated day of results/house-day (Sat Oct 24 06:00 to Sun 07:00, parenting_agent/day_sim.py).
2. The six simulated nights of results/night-feed (Oct 20 to 26, 22:00 to 06:00, scripts/night_feed_sim.py), with
   the cry on the microphone, and the morning explanation at the end of each night.
3. Four adaptation cases the fixed rules do not handle: a nap 40 min longer than usual, a parent asking to sleep, a
   dog barking during a nap, a visitor ringing just before a nap.

Every house write is a dry run, house.live is false, there is no Home Assistant token. The only call that leaves the
machine is Muse on Baseten (BASETEN_API_KEY from the environment), with a hard budget.

    .venv/bin/python scripts/muse_house_sim.py [--out results/muse-house] [--budget 2.5] [--runs 1]

--brain haiku asks Claude Haiku the same prompts with the same schema instead of Muse (results/muse-vs-haiku), on
ANTHROPIC_API_KEY, thinking off as the agent's Claude brain runs it, the same 6000 token cap.
"""
import argparse
import datetime
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import night_feed_sim  # noqa: E402
from parenting_agent import day_sim  # noqa: E402
from parenting_agent.agent.brain import BrainError, post_json, without_thinking  # noqa: E402
from parenting_agent.day_engine import ECHO_ANNOUNCE, PUSH, VACUUM, DayWriter, tummy_times  # noqa: E402
from parenting_agent.house_brain import MUSE, HouseBrain, MuseAnswerError, MuseClient  # noqa: E402
from parenting_agent.rhythm import patterns  # noqa: E402
from parenting_agent.rhythm.log import FixtureLog, parse  # noqa: E402

TZ = datetime.timezone(datetime.timedelta(hours=-3))
PARENTS = ["Parent A", "Parent B"]
SETTINGS = {"utc_offset_h": -3, "parents": PARENTS}


HAIKU = {"model": "claude-haiku-5-5", "max_tokens": MUSE["max_tokens"], "timeout_s": MUSE["timeout_s"],
         "price_in_per_mtok": 0.10, "price_out_per_mtok": 0.50}


class HaikuClient:
    """The same ask() as MuseClient, answered by Claude Haiku with the schema as a structured output."""

    url = "https://api.anthropic.com/v1/messages"
    host = "api.anthropic.com"
    cfg = HAIKU

    def ask(self, system, text, schema, name="plan"):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise BrainError("house brain: ANTHROPIC_API_KEY is not set")
        body = {"model": self.cfg["model"], "max_tokens": self.cfg["max_tokens"], "thinking": {"type": "disabled"},
                "system": system, "messages": [{"role": "user", "content": text}],
                "output_config": {"format": {"type": "json_schema", "schema": schema}}}
        started = time.monotonic()
        reply = post_json(self.url, {"x-api-key": key, "anthropic-version": "2023-06-01",
                                     "content-type": "application/json"}, body, self.cfg["timeout_s"])
        seconds = round(time.monotonic() - started, 3)
        usage = reply.get("usage") or {}
        tin = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        tout = usage.get("output_tokens", 0)
        usd = (tin * self.cfg["price_in_per_mtok"] + tout * self.cfg["price_out_per_mtok"]) / 1_000_000
        raw = without_thinking("".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text"))
        meta = {"seconds": seconds, "usd": round(usd, 6), "input_tokens": tin, "output_tokens": tout, "host": self.host,
                "model": self.cfg["model"]}
        try:
            answer = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            answer = None
        if not isinstance(answer, dict):
            raise MuseAnswerError(f"not a JSON object (stop_reason {reply.get('stop_reason')}): {str(raw)[:120]}", meta)
        return answer, meta


class Recorder:
    """The brain client with a log of every call and a budget across the whole run."""

    def __init__(self, budget, client=None):
        self.client, self.budget, self.calls = client or MuseClient(), budget, []
        self.part = ""

    @property
    def spent(self):
        return round(sum(c["usd"] for c in self.calls), 6)

    def ask(self, system, text, schema, name="plan"):
        if self.spent >= self.budget:
            raise ValueError(f"run budget of {self.budget} USD used")
        started = time.monotonic()
        try:
            answer, meta = self.client.ask(system, text, schema, name)
        except Exception as error:
            meta = getattr(error, "meta", None) or {"seconds": round(time.monotonic() - started, 3), "usd": 0.0,
                                                    "input_tokens": 0, "output_tokens": 0}
            self.calls.append({"part": self.part, "name": name, "ok": False, "error": str(error)[:200], **meta})
            raise
        self.calls.append({"part": self.part, "name": name, "ok": True, **meta})
        return answer, meta


def brain_settings(muse):
    return {**SETTINGS, "budget_usd": max(muse.budget - muse.spent, 0)}


# 1. The day

def day_factory(muse):
    def make(bus, engine, white):
        say = lambda text, now: engine.write("house_brain", "notify.send_message", ECHO_ANNOUNCE, {"message": text},
                                             "Muse's morning explanation", now)
        return HouseBrain(bus, muse, brain_settings(muse), day_engine=engine, white_noise=white, say=say)
    return make


def asleep_at(entries, t):
    return any(e["kind"] == "sleep" and parse(e["start"]) <= t < parse(e["end"]) for e in entries if e.get("end"))


def sleep_starts(entries):
    return sorted(parse(e["start"]) for e in entries if e["kind"] == "sleep")


def day_checks(run, start, end):
    bus, entries = run["bus"], run["entries"]
    history = list(bus.history)
    starts = sleep_starts(entries)

    def near_sleep(t):
        return asleep_at(entries, t) or any(datetime.timedelta(0) <= s - t <= datetime.timedelta(minutes=15) for s in starts)

    floor_starts = [e for e in history if e["kind"] == "routine" and e["name"] == "floor_clean" and e["step"] == "start"]
    tummy = [t for t in tummy_times(entries, start, TZ) if start <= t < end]
    cleaned = sum(1 for t in tummy if any(t - datetime.timedelta(hours=3) <= parse(e["at"]) <= t for e in floor_starts))
    door_echo = [e for e in history if e["kind"] == "house_dry" and e["routine"] == "door" and e["entity"] == ECHO_ANNOUNCE]
    pushes = [e for e in history if e["kind"] == "house_dry" and e["routine"] == "door" and e["action"] == PUSH]
    return {**{k: v for k, v in run["stats"].items() if k != "cap_db"},
            "floor_cleans_started": len(floor_starts),
            "floor_cleans_while_awake": sum(1 for e in floor_starts if not asleep_at(entries, parse(e["at"]))),
            "tummy_times": len(tummy), "tummy_times_with_a_clean_before": cleaned,
            "echo_door_announcements_near_sleep": sum(1 for e in door_echo if near_sleep(parse(e["at"]))),
            "door_silent_pushes": len(pushes),
            "white_noise_boosts": sum(1 for e in history if e["kind"] == "white_noise" and "Muse plan" in str(e.get("reason"))
                                      and e["action"] == "level" and "over" not in e["reason"]),
            "white_noise_max_db": run["stats"]["white_noise_max_db"]}


def run_day(muse=None, **kw):
    start, end = kw.pop("start", day_sim.DAY), kw.pop("end", day_sim.at(1, 7, 0))
    run = day_sim.simulate_day(start=start, end=end, brain_factory=day_factory(muse) if muse else None, **kw)
    return run, day_checks(run, start, end)


# 2. The nights

def night_factory(muse):
    def make(agent, feed, device):
        writer = DayWriter(agent.bus)
        say = lambda text, now: writer.call("house_brain", "notify.send_message", ECHO_ANNOUNCE, {"message": text},
                                            "Muse's morning explanation", at=now.isoformat())
        return HouseBrain(agent.bus, muse, brain_settings(muse), night_feed=feed, white_noise=device, say=say)
    return make


def night_checks(truth, history, duty, exhausted=None):
    feeds = night_feed_sim.summarize(truth, history)
    bottle = [f for f in feeds if f["method"] == "bottle"]
    right = [d for d in duty if d["to"] == (other(exhausted) if exhausted else d["rota"])]
    return {"feeds": len(feeds), "bottle_feeds": len(bottle),
            "bottle_warm_in_time": sum(1 for f in bottle if f["warmer_on"]),
            "light_on_at_feed_start": sum(1 for f in feeds if f["light_on"]),
            "breast_feeds_warmer_on": sum(1 for f in feeds if f["method"] != "bottle" and f["warmer_on"]),
            "prepares": len(duty), "right_parent_pushed": len(right),
            "pushes_to_exhausted_parent": sum(1 for d in duty if exhausted and d["to"] == exhausted),
            "live_calls": sum(1 for e in history if e["kind"] == "house_call" and e.get("live")),
            "explanations": [e["telegram"] for e in history if e["kind"] == "house_explain"],
            "explanation_source": [e["source"] for e in history if e["kind"] == "house_explain"],
            "echo": [e["echo"] for e in history if e["kind"] == "house_explain"],
            "tonight": [e["text"] for e in history if e["kind"] == "notify" and e.get("routine") == "tonight"],
            "replans": [e["text"] for e in history if e["kind"] == "notify" and e.get("routine") == "replan"]}


def other(parent):
    return next(p for p in PARENTS if p != parent)


def run_nights(rows, muse=None, days=range(20, 26)):
    out = []
    for day in days:
        start = datetime.datetime(2026, 10, day, 22, 0, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as tmp:
            truth, history, spoken, duty, brain = night_feed_sim.run_night(
                rows, start, tmp, brain_factory=night_factory(muse) if muse else None)
        out.append({"night": f"Oct {day} to {day + 1}", **night_checks(truth, history, duty),
                    "plans": [plan_row(e) for e in history if e["kind"] in ("house_plan", "house_brain_fallback")]})
    return out


def plan_row(e):
    if e["kind"] == "house_brain_fallback":
        return {"at": e["at"][11:16], "trigger": e["trigger"], "fallback": e["reason"][:200]}
    return {"at": e["at"][11:16], "trigger": e["trigger"], "accepted": e["accepted"],
            "plan": e.get("plan") or {"errors": e.get("errors")}}


# 3. Adaptation cases

def shift_after(entries, t0, t1, minutes):
    """Entries between t0 and t1 move later by minutes, the sleep that ends at t0 ends minutes later."""
    out, delta = [], datetime.timedelta(minutes=minutes)
    for e in entries:
        e = dict(e)
        for field in ("start", "time"):
            if e.get(field) and t0 < parse(e[field]) < t1:
                e[field] = (parse(e[field]) + delta).isoformat()
                if e.get("end"):
                    e["end"] = (parse(e["end"]) + delta).isoformat()
        if e["kind"] == "sleep" and e.get("end") and parse(e["end"]) == t0:
            e["end"] = (t0 + delta).isoformat()
        out.append(e)
    return out


def quiet_script(extra):
    return lambda t: extra.get(t)


def case_long_nap(muse):
    """The 11:57 nap runs 40 min past its end (13:54 to 14:34), the rest of Saturday moves 40 min later."""
    entries = shift_after(day_sim.day_entries(), day_sim.at(0, 13, 54), day_sim.at(0, 19, 0), 40)
    run, checks = run_day(muse, start=day_sim.at(0, 11, 0), end=day_sim.at(0, 18, 0), entries=entries,
                          script_fn=quiet_script({}))
    return run, {"check": "a floor clean while he is awake before tummy time, and 0 vacuum minutes during sleep",
                 "floor_cleans_while_awake": checks["floor_cleans_while_awake"],
                 "vacuum_cleaning_while_asleep_min": checks["vacuum_cleaning_while_asleep_min"],
                 "pass": checks["floor_cleans_while_awake"] >= 1 and checks["vacuum_cleaning_while_asleep_min"] == 0}


def case_dog(muse):
    """A dog barks at 15:10, during the 14:51 to 16:28 nap."""
    t = day_sim.at(0, 15, 10)
    run, checks = run_day(muse, start=day_sim.at(0, 14, 30), end=day_sim.at(0, 17, 0), script_fn=quiet_script({}),
                          events={t: [("house_sound", {"label": "dog", "source": "sim", "peak": 0.6})]})
    boosted = [e for e in run["bus"].history if e["kind"] == "white_noise" and e["action"] == "level"
               and "Muse plan" in str(e.get("reason")) and "over" not in e["reason"]]
    in_time = any(parse(e["sim_at"]) - t <= datetime.timedelta(minutes=3) for e in boosted) if boosted else False
    return run, {"check": "white noise up within 3 min of the bark, never over the 50 dB cap",
                 "white_noise_boosts": len(boosted), "boost_within_3_min": in_time,
                 "white_noise_max_db": checks["white_noise_max_db"],
                 "pass": in_time and checks["white_noise_max_db"] <= 50.0}


def case_visitor(muse):
    """At 14:20 a parent notes that Grandma is coming over around 14:45. She rings at 14:47, four minutes before the
    14:51 nap starts."""
    note = day_sim.note(day_sim.at(0, 14, 20), "Grandma is coming over around 14:45, she will ring the bell")
    ring = day_sim.at(0, 14, 47)
    script = quiet_script({ring: ("Grandma rings the doorbell",
                                  lambda s: s["door"].append({"source": "doorbell", "at": ring.isoformat()}))})
    run, checks = run_day(muse, start=day_sim.at(0, 14, 0), end=day_sim.at(0, 17, 0),
                          entries=day_sim.day_entries() + [note], script_fn=script)
    return run, {"check": "no door announcement on the kitchen Echo within 15 min before a sleep or during it, the "
                          "parent still gets a push",
                 "echo_door_announcements_near_sleep": checks["echo_door_announcements_near_sleep"],
                 "door_silent_pushes": checks["door_silent_pushes"],
                 "pass": checks["echo_door_announcements_near_sleep"] == 0 and checks["door_silent_pushes"] >= 1}


def case_exhausted(muse, rows, day=23):
    """At 21:50 the parent the rota names for the night writes "I'm exhausted, let me sleep tonight". The hard night of
    Oct 23 to 24 (4 feeds)."""
    start = datetime.datetime(2026, 10, day, 22, 0, tzinfo=TZ)
    before = [r for r in rows if patterns.when(r) < start]
    handled = [w["parent"] for w in patterns.night_wakeups(before, TZ) if w["at"] < start]
    tired = patterns.next_on_duty(handled, PARENTS)
    note = {"kind": "note", "time": (start - datetime.timedelta(minutes=10)).isoformat(),
            "note": f"{tired}: I'm exhausted, let me sleep tonight", "ref": "note#tired"}
    with tempfile.TemporaryDirectory() as tmp:
        truth, history, spoken, duty, brain = night_feed_sim.run_night(
            rows, start, tmp, brain_factory=night_factory(muse) if muse else None, extra_before=[note])
    checks = night_checks(truth, history, duty, exhausted=tired)
    return history, {"check": f"{tired} asked to sleep: no night push to {tired}, every bottle still warm in time",
                     "exhausted_parent": tired, "prepares": checks["prepares"],
                     "pushes_to_exhausted_parent": checks["pushes_to_exhausted_parent"],
                     "bottle_warm_in_time": f"{checks['bottle_warm_in_time']} of {checks['bottle_feeds']}",
                     "replans": checks["replans"], "tonight": checks["tonight"],
                     "pushes": [{"at": d["at"].strftime("%H:%M"), "to": d["to"], "rota": d["rota"]} for d in duty],
                     "pass": checks["pushes_to_exhausted_parent"] == 0
                     and checks["bottle_warm_in_time"] == checks["bottle_feeds"]}


# Report

def brain_rows(history):
    return [plan_row(e) for e in history if e["kind"] in ("house_plan", "house_brain_fallback")]


def summary(calls):
    secs = [c["seconds"] for c in calls]
    return {"calls": len(calls), "ok": sum(1 for c in calls if c["ok"]), "usd": round(sum(c["usd"] for c in calls), 4),
            "latency_median_s": round(statistics.median(secs), 2) if secs else None,
            "latency_p90_s": round(sorted(secs)[int(0.9 * (len(secs) - 1))], 2) if secs else None,
            "latency_max_s": round(max(secs), 2) if secs else None,
            "input_tokens": sum(c["input_tokens"] for c in calls), "output_tokens": sum(c["output_tokens"] for c in calls)}


def totals(nights):
    keys = ("feeds", "bottle_feeds", "bottle_warm_in_time", "light_on_at_feed_start", "breast_feeds_warmer_on",
            "prepares", "right_parent_pushed", "live_calls")
    return {k: sum(n[k] for n in nights) for k in keys}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "results" / "muse-house"))
    parser.add_argument("--budget", type=float, default=2.5)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--only", choices=["day", "nights", "cases"], default=None)
    parser.add_argument("--brain", choices=["muse", "haiku"], default="muse")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = FixtureLog(ROOT / "tests" / "fixtures" / "simweek.json").entries()
    muse = Recorder(args.budget, HaikuClient() if args.brain == "haiku" else None)
    report = {"model": muse.client.cfg["model"], "host": muse.client.host, "budget_usd": args.budget, "runs": []}
    fixed = {}
    if args.only in (None, "day"):
        _, fixed["day"] = run_day()
    if args.only in (None, "nights"):
        fixed["nights"] = run_nights(rows)
    if args.only in (None, "cases"):
        fixed["cases"] = {name: fn(None)[1] for name, fn in (("long_nap", case_long_nap), ("dog", case_dog),
                                                             ("visitor", case_visitor))}
        fixed["cases"]["exhausted"] = case_exhausted(None, rows)[1]
    report["fixed"] = {**fixed, "nights_total": totals(fixed["nights"]) if "nights" in fixed else None}
    for i in range(args.runs):
        result = {}
        if args.only in (None, "day"):
            muse.part = f"run{i + 1}:day"
            run, result["day"] = run_day(muse)
            result["day_plans"] = brain_rows(run["bus"].history)
            result["day_messages"] = [e["text"] for e in run["bus"].history if e["kind"] == "notify"
                                      and e.get("source") == "house-brain"]
        if args.only in (None, "nights"):
            muse.part = f"run{i + 1}:nights"
            result["nights"] = run_nights(rows, muse)
            result["nights_total"] = totals(result["nights"])
        if args.only in (None, "cases"):
            result["cases"] = {}
            for name, fn in (("long_nap", case_long_nap), ("dog", case_dog), ("visitor", case_visitor)):
                muse.part = f"run{i + 1}:case:{name}"
                run, result["cases"][name] = fn(muse)
                result["cases"][name]["plans"] = brain_rows(run["bus"].history)
                result["cases"][name]["messages"] = [e["text"] for e in run["bus"].history if e["kind"] == "notify"
                                                     and e.get("source") == "house-brain"]
            muse.part = f"run{i + 1}:case:exhausted"
            history, result["cases"]["exhausted"] = case_exhausted(muse, rows)
            result["cases"]["exhausted"]["plans"] = brain_rows(history)
        result["muse"] = summary([c for c in muse.calls if c["part"].startswith(f"run{i + 1}:")])
        report["runs"].append(result)
    report["muse_all"] = summary(muse.calls)
    report["calls"] = muse.calls
    name = f"run-{args.only}.json" if args.only else "run.json"
    (out / name).write_text(json.dumps(report, indent=1, default=str) + "\n")
    print(json.dumps({"fixed": {k: v for k, v in report["fixed"].items() if k != "nights"},
                      "muse": [{k: v for k, v in r.items() if k not in ("nights", "day_plans", "day_messages")}
                               for r in report["runs"]], "muse_all": report["muse_all"]}, indent=1, default=str)[:12000])


if __name__ == "__main__":
    main()
