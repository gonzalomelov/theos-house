"""The Meta hearing swap, measured: Meta Perception Encoder Audio and plain signal processing.

    python scripts/meta_hearing_eval.py scores --listener meta --split tune      # window scores, cached as numbers
    python scripts/meta_hearing_eval.py tune                                     # choices from tune only, tune.json
    python scripts/meta_hearing_eval.py scores --listener meta --split held_out  # only after tune.json is committed
    python scripts/meta_hearing_eval.py test                                     # once, eval.json

Listeners: "meta" is
parenting_agent.hearing.MetaListener, the worker the agent runs, in HEARING_PYTHON. "signal" is cry_signal.py in this
process. The items and the rules were committed first (results/sounds/meta-hearing/split.json). Every item is decoded
on a pipe through the camera channel and fed into the real Ear one second at a time, as at home. Only numbers are
written: scores in .models/meta-hearing (git ignored), choices and results in results/sounds/meta-hearing.
"""
import argparse
import datetime
import itertools
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from parenting_agent import cry_signal, hearing  # noqa: E402

OUT = REPO / "results/sounds/meta-hearing"
SPLIT = OUT / "split.json"
TUNE = OUT / "tune.json"
EVAL = OUT / "eval.json"
CACHE = Path.home() / "Engineering/gonza/parenting-agent/.models/meta-hearing"
LABELS = ("cry", "doorbell", "dog", "splash")
GRID = {"level_dbfs": [-55, -50, -45, -40, -35, -30], "voiced_share": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
        "longest_s": [0.1, 0.2, 0.3, 0.5, 0.75, 1.0], "harmonicity": [0.45, 0.5, 0.6, 0.7, 0.8, 0.9]}
FA_COST = 3


class NullBus:
    def publish(self, kind, **fields):
        return {"kind": kind, **fields}


class Recorder:
    """Wraps a listener: the Ear calls score() as at home, every reply is kept for the item."""

    def __init__(self, listener):
        self.listener, self.replies = listener, []

    def score(self, samples):
        reply = self.listener.score(samples)
        self.replies.append(reply)
        return reply


def split():
    return json.loads(SPLIT.read_text())


def item_audio(data, item):
    root = Path(os.path.expanduser(data["roots"][item["root"]]))
    return hearing.from_file(root / item["file"], item["start"], item["seconds"], camera_channel=True)


def summarize(name, replies):
    if name == "meta":
        return {label: {mode: max((r["raw"][label][mode] for r in replies if "raw" in r), default=-99.0)
                        for mode in ("logit", "margin")} for label in LABELS}
    return [r["cry_signal"] for r in replies]


def make_listener(name):
    if name == "meta":
        return hearing.MetaListener({"labels": list(LABELS), "device": os.environ.get("HEARING_DEVICE", "cpu")})
    return hearing.SignalListener()


def scores(args):
    data = split()
    if args.split == "held_out" and not TUNE.is_file():
        raise SystemExit("tune.json first: the held-out set is scored only after every choice is written")
    items = [i for i in data["items"] if i["split"] == args.split]
    started = time.monotonic()
    listener = make_listener(args.listener)
    load_s = round(time.monotonic() - started, 2)
    rows, seconds = [], []
    try:
        for n, item in enumerate(items):
            samples = item_audio(data, item)
            recorder = Recorder(listener)
            hearing.play(hearing.Ear(recorder, NullBus(), {"thresholds": {}}), samples)
            del samples
            seconds += [r["seconds"] for r in recorder.replies if "seconds" in r]
            rows.append({"id": item["id"], "windows": len(recorder.replies), "score": summarize(args.listener, recorder.replies)})
            if n % 50 == 0:
                print(f"{args.listener} {args.split} {n}/{len(items)}", flush=True)
    finally:
        listener.close()
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {"listener": args.listener, "split": args.split, "info": getattr(listener, "info", {}), "load_s": load_s,
           "window_s": {"median": statistics.median(seconds), "p95": sorted(seconds)[int(0.95 * len(seconds))]} if seconds else None,
           "wall_s": round(time.monotonic() - started, 1), "items": rows,
           "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    (CACHE / f"{args.listener}-{args.split}.json").write_text(json.dumps(out) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "items"}))


def cached(name, which):
    path = CACHE / f"{name}-{which}.json"
    return json.loads(path.read_text()) if path.is_file() else None


def tally(items, fired):
    """fired: {id: set of labels}. Per label hits, misses, false alarms, and where the false alarms came from."""
    out = {}
    for label in LABELS:
        pos = [i for i in items if i["truth"] == label]
        neg = [i for i in items if i["truth"] != label]
        fa = [i for i in neg if label in fired.get(i["id"], set())]
        out[label] = {"items": len(pos), "hits": sum(label in fired.get(i["id"], set()) for i in pos),
                      "misses": sum(label not in fired.get(i["id"], set()) for i in pos),
                      "false_alarms": len(fa), "negatives": len(neg),
                      "false_alarms_from": sorted({f"{i['source']} ({i['truth']})" for i in fa})}
        if label == "cry":
            for root in ("hearing", "donateacry"):
                sub = [i for i in pos if i["root"] == root]
                out[label][f"hits_{root}"] = f"{sum(label in fired.get(i['id'], set()) for i in sub)} of {len(sub)}"
    return out


def objective(hits, fa):
    return hits - FA_COST * fa


def best_threshold(pos, neg):
    """Threshold on raw values with the best hits - 3 x false alarms. Ties go to the higher threshold. Returns
    (threshold midway to the next value below, hits, false alarms)."""
    values = sorted(set(pos) | set(neg), reverse=True)
    best = (objective(0, 0), math.inf, 0, 0)
    for v in values:
        hits, fa = sum(p >= v for p in pos), sum(n >= v for n in neg)
        if objective(hits, fa) > best[0]:
            best = (objective(hits, fa), v, hits, fa)
    _, v, hits, fa = best
    if v == math.inf:
        return v, 0, 0
    below = [x for x in values if x < v]
    return ((v + below[0]) / 2 if below else v - 1.0), hits, fa


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def tune(args):
    data = split()
    items = {i["id"]: i for i in data["items"] if i["split"] == "tune"}
    choices = {"written": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "rule": data["protocol"]["tuning_rule"]}
    meta = cached("meta", "tune")
    if meta:
        choices["meta"] = {}
        for label in LABELS:
            options = []
            for mode in ("logit", "margin"):
                pos = [r["score"][label][mode] for r in meta["items"] if items[r["id"]]["truth"] == label]
                neg = [r["score"][label][mode] for r in meta["items"] if items[r["id"]]["truth"] != label]
                t, hits, fa = best_threshold(pos, neg)
                options.append({"mode": mode, "raw_threshold": round(t, 4), "threshold": round(sigmoid(t), 4) if t != math.inf else 1.0,
                                "tune_hits": f"{hits} of {len(pos)}", "tune_false_alarms": f"{fa} of {len(neg)}",
                                "objective": objective(hits, fa)})
            choices["meta"][label] = max(options, key=lambda o: (o["objective"], o["mode"] == "logit"))
            choices["meta"][label]["other"] = [o for o in options if o is not choices["meta"][label]]
    signal = cached("signal", "tune")
    if signal:
        pos = [r["score"] for r in signal["items"] if items[r["id"]]["truth"] == "cry"]
        neg = [r["score"] for r in signal["items"] if items[r["id"]]["truth"] != "cry"]
        best = None
        for combo in itertools.product(*(GRID[f] for f in cry_signal.FEATURES)):
            limits = dict(zip(cry_signal.FEATURES, combo))
            hits = sum(any(cry_signal.is_cry(w, limits) for w in windows) for windows in pos)
            fa = sum(any(cry_signal.is_cry(w, limits) for w in windows) for windows in neg)
            strict = sum(GRID[f].index(limits[f]) for f in cry_signal.FEATURES)
            key = (objective(hits, fa), strict)
            if best is None or key > best[0]:
                best = (key, limits, hits, fa)
        _, limits, hits, fa = best
        choices["signal"] = {"cry_limits": limits, "tune_hits": f"{hits} of {len(pos)}",
                             "tune_false_alarms": f"{fa} of {len(neg)}", "grid": GRID}
    TUNE.write_text(json.dumps(choices, indent=1) + "\n")
    print(json.dumps(choices, indent=1))


def fired_by(name, rows, choices):
    out = {}
    for r in rows:
        if name == "meta":
            c = choices["meta"]
            out[r["id"]] = {label for label in LABELS if r["score"][label][c[label]["mode"]] >= c[label]["raw_threshold"]}
        else:
            limits = choices["signal"]["cry_limits"]
            out[r["id"]] = {"cry"} if any(cry_signal.is_cry(w, limits) for w in r["score"]) else set()
    return out


def test(args):
    data = split()
    choices = json.loads(TUNE.read_text())
    result = {"run": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "tune_choices": "tune.json"}
    for which in ("tune", "held_out"):
        items = [i for i in data["items"] if i["split"] == which]
        result[which] = {}
        for name in ("meta", "signal"):
            got = cached(name, which)
            if not got:
                continue
            result[which][name] = {"tally": tally(items, fired_by(name, got["items"], choices)),
                                   "window_s": got["window_s"], "load_s": got["load_s"], "info": got["info"]}
    EVAL.write_text(json.dumps(result, indent=1) + "\n")
    for which in ("tune", "held_out"):
        for name, r in result[which].items():
            print(which, name, {k: (v["hits"], v["items"], v["false_alarms"]) for k, v in r["tally"].items()})


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="step", required=True)
    s = sub.add_parser("scores")
    s.add_argument("--listener", choices=("meta", "signal"), required=True)
    s.add_argument("--split", choices=("tune", "held_out"), required=True)
    sub.add_parser("tune")
    sub.add_parser("test")
    args = ap.parse_args()
    {"scores": scores, "tune": tune, "test": test}[args.step](args)


if __name__ == "__main__":
    main()
