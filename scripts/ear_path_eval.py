"""Recorded cries and other sounds through the ear's whole path on this Mac: the Tapo channel, the Ear, the listener's own sink, with the
post counted and not sent. The held-out clips of results/sounds/meta-hearing, frozen on Oct 31, so this checks the path and is not a new test."""
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from parenting_agent import hearing  # noqa: E402

spec = importlib.util.spec_from_file_location("ear_listener", REPO / "scripts/ear_listener.py")
ear_listener = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ear_listener)
data = json.loads((REPO / "results/sounds/meta-hearing/split.json").read_text())
roots = {k: Path(v).expanduser() for k, v in data["roots"].items()}
listener = hearing.default_listener({"device": "mps"})
rows, times = [], []
for item in (i for i in data["items"] if i["split"] == "held_out"):
    sent = []
    sink = ear_listener.ToCore(sent.append)
    samples = hearing.from_file(roots[item["root"]] / item["file"], item.get("start", 0.0), item.get("seconds"))
    t = time.time()
    hearing.play(hearing.Ear(listener, sink, {"cry_report_s": 8}, "living room"), samples)
    times.append(time.time() - t)
    rows.append({"id": item["id"], "truth": item["truth"], "sent": len(sent)})
listener.close()
cries = [r for r in rows if r["truth"] == "cry"]
others = [r for r in rows if r["truth"] != "cry"]
out = {"cries_sent": sum(r["sent"] > 0 for r in cries), "cries": len(cries), "others_sent": sum(r["sent"] > 0 for r in others), "others": len(others),
       "false": [r for r in others if r["sent"]], "missed_ids": [r["id"] for r in cries if not r["sent"]], "seconds_per_clip": round(sum(times) / len(times), 2)}
print(json.dumps(out, indent=1))
(REPO / "results/ear-path").mkdir(exist_ok=True)
(REPO / "results/ear-path/recordings.json").write_text(json.dumps(out, indent=1) + "\n")
