"""The Ear's false alarms, measured: every 40 ms frame of every window against the cry, rival and background prompts, cached as numbers.

    .venv-hearing/bin/python scripts/ear_fa_eval.py frames --set tune       # tune cries and tune negatives
    python scripts/ear_fa_eval.py tune                                      # choices from tune only, results/ear-false-alarms/tune.json
    .venv-hearing/bin/python scripts/ear_fa_eval.py path --set held_out     # once, after tune.json is committed: the real worker, Ear and sink
    .venv-hearing/bin/python scripts/ear_fa_eval.py path --set tune         # the same path on the tune side, to check the cached choice

Audio goes through the Tapo channel (hearing.from_file) and the real Ear, one second at a time. Only numbers are written.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "parenting_agent"))

from parenting_agent import hearing  # noqa: E402

OUT = REPO / "results/ear-false-alarms"
CACHE = Path.home() / "Engineering/gonza/pa-senses/.models/ear-false-alarms"
DONATE = Path.home() / "Engineering/gonza/pa-senses/.models/donateacry/src/donateacry_corpus_cleaned_and_updated_data"
HEARING_ROOT = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic"
MODEL = Path.home() / "Engineering/gonza/pa-senses/.models/pe-a-frame-small"
RIVALS = ["an adult speaking loudly", "a person shouting", "a person yelling", "a person laughing", "a person singing",
          "a person humming", "a person sighing", "an adult groaning", "a person clearing their throat", "a man's voice",
          "a woman's voice", "a door slamming", "dishes clattering"]
CRY_PROMPTS = hearing.PROMPTS["cry"]
LONG_CRIES = {"tune": ["audio/cry-01.wav", "audio/cry-03.wav"], "held_out": ["audio/cry-02.wav", "audio/cry-04.wav"]}
FREE_MIN = 25
REPORT_S = 8


def free_percent():
    text = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout
    return int(re.search(r"free percentage: (\d+)%", text).group(1))


def worklist(side):
    """Every item of one side, cries first: (key, path, start, seconds, truth, meta)."""
    cries = json.loads((REPO / "results/sounds/meta-hearing/split.json").read_text())["items"]
    negs = json.loads((OUT / "split.json").read_text())
    out = []
    for item in cries:
        if item["split"] == side and item["truth"] == "cry":
            root = HEARING_ROOT if item["root"] == "hearing" else DONATE
            out.append((f"cry-{item['id']}", root / item["file"], item["start"], item["seconds"], "cry", item["root"]))
    for rel in LONG_CRIES[side]:
        out.append((f"longcry-{Path(rel).stem}", HEARING_ROOT / rel, 0.0, None, "longcry", "hearing"))
    root = Path(os.path.expanduser(negs["root"]))
    for item in negs["items"]:
        if item["split"] == side:
            out.append((f"neg-{item['id']}", root / item["file"], 0.0, None, "neg", item["kind"]))
    return out


class Frames:
    """Stands in the Ear's listener place: keeps the frame logits of each window and fires nothing."""

    def __init__(self, encoder):
        self.encoder, self.windows = encoder, []

    def score(self, samples):
        self.windows.append(self.encoder.frame_logits(samples).astype(np.float16))
        return {"scores": {}}


class NullBus:
    def publish(self, topic, **fields):
        return fields


def frames(args):
    import hearing_worker
    cfg = {"model_dir": str(MODEL), "prompts": {"cry": CRY_PROMPTS}, "background": RIVALS + hearing.BACKGROUND, "device": args.device}
    encoder = hearing_worker.Encoder(cfg)
    work = worklist(args.set)
    CACHE.mkdir(parents=True, exist_ok=True)
    done, started = {}, time.monotonic()
    for n, (key, path, start, seconds, truth, meta) in enumerate(work):
        if n % 25 == 0:
            free = free_percent()
            print(f"{args.set} {n}/{len(work)} free {free}% {time.monotonic() - started:.0f}s", flush=True)
            if free < FREE_MIN:
                raise SystemExit("memory under 25% free, stopping")
        recorder = Frames(encoder)
        hearing.play(hearing.Ear(recorder, NullBus(), {"thresholds": {}}), hearing.from_file(path, start, seconds))
        done[key] = np.stack(recorder.windows)
    np.savez(CACHE / f"frames-{args.set}.npz", **done)
    print(json.dumps({"set": args.set, "items": len(done), "windows": sum(len(v) for v in done.values()), "wall_s": round(time.monotonic() - started)}))


def window_fired(windows, threshold, margin, frames_needed):
    """Per window: do enough 40 ms frames hold the cry above the threshold and beat every rival prompt by the margin?"""
    cry = windows[:, :, :len(CRY_PROMPTS)].max(axis=2).astype(np.float32)
    rival = windows[:, :, len(CRY_PROMPTS):].max(axis=2).astype(np.float32)
    held = cry >= threshold
    if margin is not None:
        held &= (cry - rival) >= margin
    return held.sum(axis=1) >= frames_needed


def episode_sends(fired, min_fired, report_s=8, gap_s=2):
    """The stream second of each send, as hearing.Ear decides it (checked against the real Ear on the chosen rule). The first window is second 2."""
    sends, episode = [], None
    for at, hit in enumerate(fired, start=2):
        if hit:
            if episode is None:
                episode = {"start": at, "last": at, "fired": 0, "sent": False}
            episode["last"] = at
            episode["fired"] += 1
            if not episode["sent"] and at - episode["start"] + 1 >= report_s and episode["fired"] >= min_fired:
                episode["sent"] = True
                sends.append(at)
        elif episode is not None and at - episode["last"] > gap_s:
            if not episode["sent"] and episode["fired"] >= min_fired:
                sends.append(at)
            episode = None
    return sends


class Both:
    """The real listener with the rule. Keeps the bare logit of every window, so the same pass also gives the old rule."""

    def __init__(self, listener):
        self.listener, self.logits = listener, []

    def __getattr__(self, name):
        return getattr(self.listener, name)

    def score(self, samples):
        reply = self.listener.score(samples)
        self.logits.append(reply["raw"]["cry"]["logit"])
        return reply


def first(sends):
    return sends[0] if sends else None


def run_item(listener, samples):
    """One item through the real Ear and the listener's own sink, with the post counted. The second of the first post, new rule and old."""
    spec = importlib.util.spec_from_file_location("ear_listener", REPO / "scripts/ear_listener.py")
    ear_listener = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ear_listener)
    both, posts = Both(listener), []
    ear = None
    sink = ear_listener.ToCore(lambda event: posts.append(ear.second), clock=lambda: float(ear.second))
    ear = hearing.Ear(both, sink, {"cry_report_s": REPORT_S}, "nursery")
    hearing.play(ear, samples)
    old = episode_sends(np.array(both.logits) >= hearing.THRESHOLDS["cry"], 1, REPORT_S)
    return {"new": first(posts), "old": first(old), "seconds": round(samples.size / hearing.RATE, 2)}


def quieter(path, start, seconds, db, tmp):
    """A cry further from the microphone: the level lowered before the Tapo channel."""
    wav = tmp / "level.wav"
    subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", str(start), "-i", str(path), "-t", str(seconds),
                    "-af", f"volume={db}dB", "-ac", "1", "-ar", "16000", str(wav)], check=True)
    return hearing.from_file(wav)


def tally(rows, key):
    sent = [r for r in rows if r[key] is not None]
    return {"sent": len(sent), "of": len(rows)}


def report_times(rows, key):
    times = sorted(r[key] for r in rows if r[key] is not None)
    return {"median_s": times[len(times) // 2], "p95_s": times[int(0.95 * len(times))], "max_s": times[-1]} if times else None


def path(args):
    listener = hearing.MetaListener({"labels": ["cry"], "device": args.device, "model_dir": str(MODEL), "cry_rule": hearing.CRY_RULE})
    kinds = {f"neg-{i['id']}": i for i in json.loads((OUT / "split.json").read_text())["items"]}
    rows, started, tmp = [], time.monotonic(), Path(tempfile.mkdtemp())
    work = worklist(args.set)
    for n, (key, source, start, seconds, truth, meta) in enumerate(work):
        if n % 25 == 0:
            free = free_percent()
            print(f"{args.set} {n}/{len(work)} free {free}% {time.monotonic() - started:.0f}s", flush=True)
            if free < FREE_MIN:
                raise SystemExit("memory under 25% free, stopping")
        row = run_item(listener, hearing.from_file(source, start, seconds))
        rows.append({"key": key, "truth": truth, "meta": meta, **row})
    levels = {}
    if args.set == "held_out":
        cries = [w for w in work if w[4] == "cry" and w[5] == "donateacry"][::4]
        for db in (-12, -24):
            level_rows = [run_item(listener, quieter(w[1], w[2], w[3], db, tmp)) for w in cries]
            levels[f"{db} dB"] = {"new": tally(level_rows, "new"), "old": tally(level_rows, "old")}
            print(db, levels[f"{db} dB"], flush=True)
    listener.close()
    cry_rows = [r for r in rows if r["truth"] == "cry"]
    neg_rows = [r for r in rows if r["truth"] == "neg"]
    long_rows = [r for r in rows if r["truth"] == "longcry"]
    by_kind = {}
    for r in neg_rows:
        item = kinds[r["key"]]
        group = by_kind.setdefault(f"{item['kind']}/{item['variant']}", {"items": 0, "old": 0, "new": 0, "seconds": 0.0})
        group["items"] += 1
        group["seconds"] = round(group["seconds"] + r["seconds"], 1)
        group["old"] += r["old"] is not None
        group["new"] += r["new"] is not None
    hours = sum(r["seconds"] for r in neg_rows) / 3600
    groups = {"human": lambda k: kinds[k]["kind"] not in ("room", "dog", "doorbell", "splash"), "room and house": lambda k: kinds[k]["kind"] in ("room", "dog", "doorbell", "splash")}
    out = {"set": args.set, "rule": hearing.CRY_RULE, "report_after_s": REPORT_S,
           "cries": {"new": tally(cry_rows, "new"), "old": tally(cry_rows, "old"),
                     "report_second_from_clip_start": {"new": report_times(cry_rows, "new"), "old": report_times(cry_rows, "old")},
                     "new_missed": [r["key"] for r in cry_rows if r["new"] is None], "old_missed": [r["key"] for r in cry_rows if r["old"] is None]},
           "long_cries": long_rows,
           "negatives": {"new": tally(neg_rows, "new"), "old": tally(neg_rows, "old"), "hours": round(hours, 3),
                         "new_per_hour": round(sum(r["new"] is not None for r in neg_rows) / hours, 1),
                         "old_per_hour": round(sum(r["old"] is not None for r in neg_rows) / hours, 1),
                         "groups": {name: {"new": tally([r for r in neg_rows if f(r["key"])], "new"), "old": tally([r for r in neg_rows if f(r["key"])], "old")} for name, f in groups.items()},
                         "by_kind": by_kind,
                         "new_sent": [{"kind": kinds[r["key"]]["kind"], "variant": kinds[r["key"]]["variant"], "source": kinds[r["key"]]["source"]} for r in neg_rows if r["new"] is not None]},
           "quieter_cries_every_4th_donateacry": levels, "wall_s": round(time.monotonic() - started)}
    name = {"held_out": "eval.json", "tune": "tune-path.json"}[args.set]
    (OUT / name).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "negatives"}, indent=1), json.dumps(out["negatives"], indent=1, ensure_ascii=False))


def auc(pos, neg):
    pos, neg = np.asarray(pos)[:, None], np.asarray(neg)[None, :]
    return float((pos > neg).mean() + 0.5 * (pos == neg).mean())


def tune(args):
    """Choices from tune only. Rivals: add the prompt that most separates cries from negatives, stop when it gains under 0.001 of AUC.
    Then the rule on a grid, by the frozen objective: cries sent minus 3 x negatives sent, ties to the stricter rule."""
    protocol = json.loads((OUT / "split.json").read_text())
    kinds = {f"neg-{i['id']}": f"{i['kind']}/{i['variant']}" for i in protocol["items"]}
    with np.load(CACHE / "frames-tune.npz") as cache:
        data = {k: cache[k].astype(np.float32) for k in cache.files}
    cries = [k for k in data if k.startswith("cry-")]
    negs = [k for k in data if k.startswith("neg-")]
    names = CRY_PROMPTS + RIVALS + hearing.BACKGROUND
    n_cry = len(CRY_PROMPTS)
    crying = {k: data[k][:, :, :n_cry].max(axis=2) for k in data}
    def separation(columns):
        score = lambda k: float((crying[k] - data[k][:, :, columns].max(axis=2)).max())
        return auc([score(k) for k in cries], [score(k) for k in negs])
    columns, best = [], 0.0
    while True:
        gain, column = max((separation(columns + [c]), c) for c in range(n_cry, len(names)) if c not in columns)
        if gain - best < 0.001:
            break
        columns, best = columns + [column], gain
    rivalry = {k: crying[k] - data[k][:, :, columns].max(axis=2) for k in data}
    def fires(k, floor, margin, frames_needed):
        return (((crying[k] >= floor) & (rivalry[k] >= margin)).sum(axis=1)) >= frames_needed
    rows = []
    for floor in (3, 3.5, 4, 4.43, 5, 5.5, 6, 6.5, 7):
        for margin in (0, 1, 2, 3, 4, 5, 6, 7):
            for frames_needed in (1, 2, 3, 5, 8):
                fired = {k: fires(k, floor, margin, frames_needed) for k in cries + negs}
                for min_fired in (1, 2, 3):
                    c = sum(bool(episode_sends(fired[k], min_fired)) for k in cries)
                    f = sum(bool(episode_sends(fired[k], min_fired)) for k in negs)
                    rows.append({"objective": c - 3 * f, "cries": c, "negatives": f, "floor": floor, "margin": margin,
                                 "frames": frames_needed, "min_fired_s": min_fired})
    rows.sort(key=lambda r: (r["objective"], -r["negatives"], r["min_fired_s"], r["frames"], r["margin"], r["floor"]), reverse=True)
    chosen = rows[0]
    base = {k: (data[k][:, :, :n_cry].max(axis=2).max(axis=1) >= hearing.THRESHOLDS["cry"]) for k in data}
    sent = lambda fired, keys: [k for k in keys if episode_sends(fired[k], 1)]
    now = {k: fires(k, chosen["floor"], chosen["margin"], chosen["frames"]) for k in data}
    def by_kind(keys):
        out = {}
        for k in keys:
            out[kinds[k]] = out.get(kinds[k], 0) + 1
        return out
    result = {"rule": protocol["protocol"]["tuning_rule"], "rivals": [names[c] for c in columns], "separation_auc": round(best, 4),
              "chosen": chosen, "runner_ups": rows[1:8],
              "before": {"cries": f"{len(sent(base, cries))} of {len(cries)}", "negatives": f"{len(sent(base, negs))} of {len(negs)}",
                         "negatives_by_kind": by_kind(sent(base, negs))},
              "after": {"cries": f"{len(sent(now, cries))} of {len(cries)}", "negatives": f"{len(sent(now, negs))} of {len(negs)}",
                        "negatives_by_kind": by_kind(sent(now, negs)), "missed": [k for k in cries if k not in sent(now, cries)]},
              "windows_negative_kinds": by_kind(negs)}
    (OUT / "tune.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("frames")
    f.add_argument("--set", required=True, choices=["tune", "held_out"])
    f.add_argument("--device", default="mps")
    sub.add_parser("tune")
    q = sub.add_parser("path")
    q.add_argument("--set", required=True, choices=["tune", "held_out"])
    q.add_argument("--device", default="mps")
    args = parser.parse_args()
    {"frames": frames, "tune": tune, "path": path}[args.command](args)
