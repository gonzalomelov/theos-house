"""A labelled sample of the first-month book: 30 simulated days of simulated Theo in a local log, and Muse Spark Open writes the pages.
Writes results/book-sample/book.json and index.html. Nothing here is a real baby or a real month.

    BASETEN_API_KEY=... python scripts/first_month_book.py
"""
import asyncio
import datetime
import html
import json
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from parenting_agent.agent import memory as memory_module  # noqa: E402
from parenting_agent.agent.memory import LocalBabyLog, Memory  # noqa: E402
from parenting_agent.core import agent, book, sim_theo  # noqa: E402

OUT = ROOT / "results/book-sample"
START = datetime.datetime(2026, 12, 15, 8, 0, tzinfo=sim_theo.TZ)
DAYS, ART = 30, ("cover", "night", "recipe", "carseat")
NOTES = "Nights swapped between Gonza and Ceci. Grandma's pumpkin puree became a Thermomix recipe on one of the first days, kept for later."


def simulated_month():
    with tempfile.TemporaryDirectory() as folder:
        clock = [START]
        memory_module.now = lambda: clock[0].isoformat(timespec="seconds")
        log, rng = LocalBabyLog(Memory(Path(folder) / "month.sqlite")), random.Random(15)
        for minute in range(0, DAYS * 24 * 60, 5):
            clock[0] = START + datetime.timedelta(minutes=minute)
            sim_theo.step(log, clock[0], rng)
        return log.entries(None, None, 5000)


def page_html(made):
    cards = "".join(f'<figure><img src="../../parenting_agent/simulator/static/book/{ART[i % len(ART)]}.jpg" alt=""><figcaption><b>{html.escape(p["day"])}</b><br>{html.escape(p["text"])}'
                    f'<br><small>{"Written by Muse from the log" if p["by"] == "muse" else "A plain line from code"}</small></figcaption></figure>' for i, p in enumerate(made["pages"]))
    return (f'<!doctype html><meta charset="utf-8"><title>{html.escape(made["title"])}, sample</title><body style="font:16px system-ui;max-width:900px;margin:auto;padding:16px">'
            f'<h1>{html.escape(made["title"])}</h1><p><b>Sample.</b> A simulated month with a simulated baby. Text by Muse Spark Open from the log, each number checked against it by code. '
            f"Illustrations made ahead of time in Meta's Muse app, not by the agent.</p>{cards}")


async def main():
    entries = simulated_month()
    started = time.time()
    made = await book.write(agent.muse(), entries, NOTES, "en")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "book.json").write_text(json.dumps({"simulated": True, "seconds": round(time.time() - started, 1), **made}, indent=1, ensure_ascii=False))
    (OUT / "index.html").write_text(page_html(made))
    kept = sum(p["by"] == "muse" for p in made["pages"])
    print(f"{len(made['pages'])} pages, {kept} kept from Muse, {len(entries)} log entries, {time.time() - started:.0f}s")


asyncio.run(main())
