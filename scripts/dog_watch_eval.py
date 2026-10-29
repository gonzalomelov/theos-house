"""Scores the dog-near-baby watch (issue #109) on a labeled image set with SAM 3.1 on this Mac.

The set lives outside git (stock images keep their own licenses). labels.json is a list of
{"id", "file", "label": "near" | "far" | "no_baby" | "no_dog", "split": "dev" | "blind", "kind": "photo" | "composite"}.
Only "near" should alert. Every other label that alerts is a false alert.

Each image runs through SAM 3.1 once. The per-image numbers (gap, ratio, touching, seconds) go in the output, never
masks or pixels, so a threshold sweep on dev needs no second GPU pass:
    python scripts/dog_watch_eval.py --set DIR --split dev --out results/dog-near-baby/dev.json
    python scripts/dog_watch_eval.py --rescore results/dog-near-baby/dev.json --sweep
Hold the GPU lock (/tmp/pa-gpu.lock) while it runs.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent.dog_watch import DEFAULTS, decide, measure, prompts  # noqa: E402


def score(rows, cfg):
    tally = {"near": 0, "caught": 0, "missed": 0, "not_near": 0, "false_alerts": 0}
    for row in rows:
        verdict = decide(row["measure"], cfg)
        row["verdict"], row["alert"] = verdict, verdict == "near"
        if row["label"] == "near":
            tally["near"] += 1
            tally["caught" if row["alert"] else "missed"] += 1
        else:
            tally["not_near"] += 1
            tally["false_alerts"] += row["alert"]
    by_label = {}
    for row in rows:
        by_label.setdefault(row["label"], {"n": 0, "alerts": 0})
        by_label[row["label"]]["n"] += 1
        by_label[row["label"]]["alerts"] += row["alert"]
    return {**tally, "by_label": by_label}


def latency(rows):
    sam = sorted(r["sam_s"] for r in rows)
    total = sorted(r["total_s"] for r in rows)
    pct = lambda xs, q: xs[min(len(xs) - 1, int(q * len(xs)))]
    return {"sam_median_s": round(statistics.median(sam), 3), "sam_p90_s": round(pct(sam, 0.9), 3),
            "total_median_s": round(statistics.median(total), 3), "total_p90_s": round(pct(total, 0.9), 3),
            "total_max_s": round(total[-1], 3)}


def run(args, cfg):
    import cv2
    from parenting_agent.carseat.sam3_masks import Sam3Masks
    labels = [r for r in json.loads((Path(args.set) / "labels.json").read_text()) if r["split"] == args.split]
    sam = Sam3Masks({"confidence": 0.3})
    rows = []
    try:
        for item in labels:
            frame = cv2.imread(str(Path(args.set) / item["file"]))
            started = time.monotonic()
            found, sam_s = sam.masks(frame, prompts(cfg))
            m = measure(found, cfg)
            total = time.monotonic() - started
            scores = {p: [round(s, 3) for s, _ in found.get(p, [])][:3] for p in prompts(cfg)}
            rows.append({**{k: item[k] for k in ("id", "label", "kind")}, "measure": m, "scores": scores,
                         "sam_s": round(sam_s, 3), "total_s": round(total, 3)})
            print(item["id"], item["label"], decide(m, cfg), m.get("ratio"), flush=True)
    finally:
        sam.close()
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set")
    parser.add_argument("--split", default="dev")
    parser.add_argument("--out")
    parser.add_argument("--rescore")
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--near-ratio", type=float)
    args = parser.parse_args()
    cfg = {**DEFAULTS}
    if args.near_ratio is not None:
        cfg["near_ratio"] = args.near_ratio
    if args.rescore:
        report = json.loads(Path(args.rescore).read_text())
        rows = report["rows"]
    else:
        rows = run(args, cfg)
        report = {"split": args.split, "set": Path(args.set).name, "prompts": prompts(cfg)}
    if args.sweep:
        for ratio in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 1.0, 1.25, 1.5):
            s = score(rows, {**cfg, "near_ratio": ratio})
            print(f"near_ratio {ratio}: caught {s['caught']}/{s['near']}, false alerts {s['false_alerts']}/{s['not_near']}")
    report.update({"near_ratio": cfg["near_ratio"], "score": score(rows, cfg), "latency": latency(rows), "rows": rows})
    print(json.dumps({k: report[k] for k in ("near_ratio", "score", "latency")}, indent=1))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
