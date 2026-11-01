"""Runs the frozen held-out set through the family agent, one item per fresh run of the e2e harness.

    .venv/bin/python results/heldout-first-month/run.py --set heldout.json --child heldout-baby-a --shard 0/3

Each item is its own run of parenting_agent/e2e/harness.py: config/agent.vostro.json with every plug-in, Muse Spark
Open on Baseten, the capturing messenger (nothing reaches Telegram), house.live false and every Home Assistant write
refused, the voice bridge (the Alexa path, it would listen on the LAN) left out, a fresh data dir (no memory of other items). The Baby Buddy child is one of the held-out children (made for
this eval, nothing else writes to them), reset before each item to the item's own log_before. Setup messages and the
scored message go in through the Telegram channel's poll, the path a real message takes. Virtual day: Oct 22 2026.

Nothing in parenting_agent/ is changed: the harness's child slug, its history file and its Baby Buddy client are
swapped from here, for this process only.
"""
import argparse
import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent.e2e import harness  # noqa: E402

DAY = datetime.date(2026, 10, 22)
TZ = harness.TZ


def moment(text):
    day = DAY
    if text.startswith("-1d "):
        day, text = DAY - datetime.timedelta(days=1), text[4:]
    h, m = map(int, text.split(":"))
    return datetime.datetime.combine(day, datetime.time(h, m), TZ)


def utc(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed(log_before):
    """The item's log_before as Baby Buddy rows, tagged heldout-seed."""
    rows = {"feedings": [], "changes": [], "sleep": [], "notes": [], "timers": []}
    tag = ["heldout-seed"]
    for e in log_before:
        kind = e["kind"]
        if kind == "feeding":
            start = moment(e["at"])
            breast = "breast" in e["method"] and e["method"] != "bottle"
            end = start + datetime.timedelta(minutes=e.get("minutes") or 15)
            row = {"start": utc(start), "end": utc(end), "method": e["method"],
                   "type": e.get("type") or ("breast milk" if breast else "formula"), "tags": tag}
            if e.get("amount"):
                row["amount"] = e["amount"]
            rows["feedings"].append(row)
        elif kind == "change":
            row = {"time": utc(moment(e["at"])), "wet": bool(e.get("wet")), "solid": bool(e.get("solid")), "tags": tag}
            if e.get("color"):
                row["color"] = e["color"]
            rows["changes"].append(row)
        elif kind == "sleep":
            rows["sleep"].append({"start": utc(moment(e["start"])), "end": utc(moment(e["end"])), "tags": tag})
        elif kind == "sleep_open":
            rows["timers"].append({"name": "sleep", "start": utc(moment(e["start"]))})
        elif kind == "bath":
            rows["notes"].append({"note": "Bath", "time": utc(moment(e["at"])), "tags": tag})
        else:
            raise ValueError(f"unknown log_before kind {kind}")
    return {k: v for k, v in rows.items() if v}


class SeededBabyBuddy(harness.BabyBuddy):
    """The harness's client, keeping the seed rows it wrote so the scorer can see seed entries changed or deleted."""
    last_seed = {}

    def reset(self, child, history):
        if not child["slug"].startswith("heldout-baby-"):
            raise RuntimeError(f"held-out: refusing to reset {child['slug']!r}")
        harness.E2E_CHILD = child["slug"]
        removed, written = super().reset(child, history)
        SeededBabyBuddy.last_seed = {ep: [self.call("GET", f"/api/{ep}/{i}/") for i in ids] for ep, ids in written.items()}
        return removed, written


def episode(item, child_slug, out_dir):
    steps = [{"at": moment(s["now"]), "do": "message", "who": s["who"], "text": s["text"], "setup": True}
             for s in item.get("setup", [])]
    steps.append({"at": moment(item["now"]), "do": "message", "who": item["who"], "text": item["text"], "scored": True})
    start = min(s["at"] for s in steps) - datetime.timedelta(minutes=2)
    end = max(s["at"] for s in steps) + datetime.timedelta(minutes=3)
    tmp = Path(tempfile.mkdtemp(prefix="heldout-seed-"))
    history = tmp / "history.json"
    history.write_text(json.dumps(seed(item.get("log_before", []))))
    harness.E2E_CHILD = child_slug
    harness.HISTORY = history
    harness.BabyBuddy = SeededBabyBuddy
    config = json.loads((ROOT / "config/agent.vostro.json").read_text())
    # The voice bridge (the Alexa path) would listen on the LAN for the run: it is not on the message path, so it is
    # left out. Every other plug-in runs as deployed.
    plugins = [p for p in config["plugins"] if not p.endswith(":VoiceBridge")]
    run = harness.Run(item["id"], ROOT / "config/agent.vostro.json", out_dir, start, end, steps,
                      {"baby.born": True, "plugins": plugins})
    try:
        result = run.execute()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bb = SeededBabyBuddy(harness.os.environ["BABYBUDDY_URL"], harness.os.environ["BABYBUDDY_TOKEN"])
    child = bb.child(child_slug)
    now_rows = {(r["endpoint"], r["id"]): r for r in bb.entries(child["id"])}
    seed_after = []
    for endpoint, rows in SeededBabyBuddy.last_seed.items():
        for row in rows:
            after = now_rows.get((endpoint, row["id"]))
            seed_after.append({"endpoint": endpoint, "before": row, "after": after})
    events = [json.loads(line) for line in (out_dir / "data/events.jsonl").read_text().splitlines() if line.strip()]
    keep = [e for e in events if e["kind"] in ("reply", "turn", "brain_fallback", "brain_call", "final_guard", "log",
                                               "baby_log", "error", "action", "tool", "tool_call", "refused")]
    record = {"id": item["id"], "child": child_slug, "created": result["baby_buddy"], "seed_after": seed_after,
              "sent": result["sent"], "steps": result["steps"], "brain_usd": result["brain_usd"],
              "brain_calls": result["brain_calls"], "refused": result["refused"], "tunnel_down": result["tunnel_down"],
              "over_budget": result["over_budget"], "chats": result["chats"],
              "fallbacks": sum(1 for e in events if e["kind"] == "brain_fallback"), "events": keep}
    shutil.rmtree(out_dir, ignore_errors=True)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="heldout.json")
    parser.add_argument("--child", required=True)
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--only", default="")
    parser.add_argument("--out", default=str(HERE / "run-1"))
    args = parser.parse_args()
    items = json.loads((HERE / args.set).read_text())
    k, n = map(int, args.shard.split("/"))
    items = [i for x, i in enumerate(items) if x % n == k]
    if args.only:
        items = [i for i in items if i["id"] in args.only.split(",")]
    out = Path(args.out) / "items"
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"heldout-{args.child}-"))
    for item in items:
        target = out / f"{item['id']}.json"
        if target.exists():
            continue
        record = episode(item, args.child, work / item["id"])
        target.write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str))
        replies = [s["text"] for s in record["sent"] if "text" in s]
        print(item["id"], f"{record['brain_usd']:.4f}", f"fallbacks={record['fallbacks']}",
              len(record["created"]), "|", " / ".join(replies)[:160].replace("\n", " "), flush=True)
        if record["tunnel_down"] or record["over_budget"]:
            target.unlink()
            print("stopping: tunnel down or budget", record["tunnel_down"], flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
