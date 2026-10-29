"""Latency and cost of the brain calls a run made, from the JSON lines PA_BRAIN_LOG wrote (issue #4).

    PA_BRAIN_LOG=results/muse/calls-x.jsonl python scripts/voice_log_run.py
    python scripts/brain_calls_stats.py results/muse/calls-*.jsonl [--turns N]
"""
import argparse
import json
import statistics
import sys


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    k = (len(values) - 1) * q
    low, high = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[low] + (values[high] - values[low]) * (k - low), 2)


def stats(lines, turns=None):
    muse = [c for c in lines if not c.get("fallback")]
    out = {"calls": len(lines), "fallbacks": len(lines) - len(muse),
           "models": sorted({c["model"] for c in lines}),
           "p50_s": percentile([c["seconds"] for c in muse], 0.5), "p90_s": percentile([c["seconds"] for c in muse], 0.9),
           "mean_input_tokens": round(statistics.mean(c.get("input_tokens", 0) for c in lines)) if lines else None,
           "mean_output_tokens": round(statistics.mean(c.get("output_tokens", 0) for c in lines)) if lines else None,
           "mean_reasoning_tokens": round(statistics.mean(c.get("reasoning_tokens") or 0 for c in lines)) if lines else None,
           "usd": round(sum(c.get("usd") or 0 for c in lines), 4)}
    out["usd_per_call"] = round(out["usd"] / len(lines), 5) if lines else None
    if turns:
        out["turns"], out["usd_per_turn"] = turns, round(out["usd"] / turns, 5)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--turns", type=int)
    args = parser.parse_args(argv)
    lines = [json.loads(line) for path in args.files for line in open(path) if line.strip()]
    print(json.dumps(stats(lines, args.turns), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
