"""Simulated days on real Muse on Baseten, on the mock home, with every kind of fault on purpose. No real device, no real message.
The scripted version, 14 days in about 20 s, is tests/test_core_days.py. Prices are Muse's: 1.25 in, 4.25 out, USD per million tokens.
Run: PA_DB_URL=... BASETEN_API_KEY=... python scripts/core_days_eval.py [days] [seed] [results file]"""
import asyncio
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PA_WORLD"] = "mock"
from parenting_agent.core import days  # noqa: E402

logging.disable(logging.ERROR)


def percentile(values, share):
    return sorted(values)[min(len(values) - 1, int(len(values) * share))] if values else None


async def main(count, seed, out):
    started = time.monotonic()

    def progress(row):
        print({k: row[k] for k in ("day", "events", "failed", "thread_tokens", "facts", "checkpoints", "db_kb", "rss_mb", "trims")}, f"{time.monotonic() - started:.0f}s", flush=True)
    async with days.Run(count, model=days.real_muse, seed=seed, plan=days.REAL_FAULTS, burst=6, gone=12, progress=progress) as run:
        report = await run.live()
    usage = report["usage"]
    report["summary"] = {
        "minutes": round((time.monotonic() - started) / 60, 1), "per_simulated_day_usd": None,
        "usd": round(usage["input_tokens"] * 1.25 / 1e6 + usage["output_tokens"] * 4.25 / 1e6, 2),
        "input_tokens_per_call": round(usage["input_tokens"] / max(1, usage["model_calls"])),
        "model_seconds": {"median": statistics.median(usage["model_seconds"] or [0]), "p95": percentile(usage["model_seconds"], .95), "max": max(usage["model_seconds"] or [0])},
        "event_seconds": {"median": statistics.median(report["event_seconds"] or [0]), "p95": percentile(report["event_seconds"], .95), "max": max(report["event_seconds"] or [0])},
    }
    report["summary"]["per_simulated_day_usd"] = round(report["summary"]["usd"] / count, 2)
    usage.pop("model_seconds")
    Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in ("counts", "faults", "summary", "usage")}, ensure_ascii=False))
    print("VIOLATIONS", len(report["violations"]))
    print("\n".join(v[:260] for v in report["violations"]))
    print("FINDINGS", len(report["findings"]))
    print("\n".join(v[:260] for v in report["findings"]))
    print("FAILURES", len(report["failures"]))
    print("\n".join(v[:200] for v in report["failures"]))


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5, int(sys.argv[2]) if len(sys.argv) > 2 else 101, sys.argv[3] if len(sys.argv) > 3 else "results/core-days/real-muse.json"))
