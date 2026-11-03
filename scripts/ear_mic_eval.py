"""Recordings played out loud on this Mac's speakers, heard by the real Tapo microphone, through the Ear. Nothing reaches the core or any
parent: the sink only counts. A fixed list, every Nth held-out clip of results/sounds/meta-hearing, chosen before any run.

    TAPO_* in the environment; .venv-hearing/bin/python scripts/ear_mic_eval.py --per-truth 10

The Tapo's level is recorded for each clip, so a clip the camera never heard is told apart from one the model missed. Nothing stored holds
audio. The run ends itself if the camera stalls.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from parenting_agent import hearing  # noqa: E402

OUT = REPO / "results/ear-path/microphone.json"
STALL_S, QUIET_DB, GAP_S = 30, 6.0, 12


def chosen(per_truth):
    data = json.loads((REPO / "results/sounds/meta-hearing/split.json").read_text())
    roots = {k: Path(v).expanduser() for k, v in data["roots"].items()}
    held = [i for i in data["items"] if i["split"] == "held_out"]
    picks = []
    for rows in ([i for i in held if i["truth"] == "cry"], [i for i in held if i["truth"] != "cry"]):
        step = max(1, len(rows) // per_truth)
        picks += rows[::step][:per_truth]
    return [{**i, "path": str(roots[i["root"]] / i["file"])} for i in picks]


class Count:
    """Stands where the Ear's bus goes. Keeps when each label was heard and sends nothing."""

    def __init__(self):
        self.heard = []

    def publish(self, topic, **fields):
        if topic == "sound":
            self.heard.append((time.monotonic(), fields.get("label")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-truth", type=int, default=10)
    parser.add_argument("--report-after", type=int, default=8)
    args = parser.parse_args()
    clips = chosen(args.per_truth)
    # 12 s of quiet, then each clip and a gap, then a margin. Past this the run has hung, and it ends itself.
    signal.signal(signal.SIGALRM, lambda *_: os._exit(4))
    signal.alarm(int(sum((c.get("seconds") or 10) + GAP_S for c in clips)) + 180)
    listener = hearing.default_listener({"device": "mps"})
    sink = Count()
    ear = hearing.Ear(listener, sink, {"cry_report_s": args.report_after}, "living room")
    levels, last = [], [time.monotonic()]
    stop = threading.Event()

    def listen():
        for chunk in hearing.camera_seconds(hearing.camera_url()):
            last[0] = time.monotonic()
            levels.append((last[0], float(hearing.dbfs(chunk))))
            ear.feed(chunk)
            if stop.is_set():
                return

    threading.Thread(target=listen, daemon=True).start()

    def watch():
        while not stop.wait(5):
            if time.monotonic() - last[0] > STALL_S:
                print(json.dumps({"stalled_after_s": round(time.monotonic() - last[0]), "seconds": len(levels)}), flush=True)
                os._exit(5)

    time.sleep(GAP_S)
    threading.Thread(target=watch, daemon=True).start()
    quiet = sorted(v for _, v in levels)
    baseline = quiet[len(quiet) // 2] if quiet else None
    rows = []
    for clip in clips:
        seconds = clip.get("seconds") or 10
        begin = time.monotonic()
        player = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "fatal", "-ss", str(clip.get("start", 0.0)), "-t", str(seconds), "-i", clip["path"], "-f", "audiotoolbox", "-"])
        player.wait()
        end = begin + seconds
        time.sleep(GAP_S)
        during = sorted(v for t, v in levels if begin <= t <= end + 1)
        peak = during[-1] if during else None
        hits = [(t - begin, label) for t, label in sink.heard if begin <= t <= time.monotonic()]
        sink.heard.clear()
        cries = [t for t, label in hits if label == "cry"]
        rows.append({"id": clip["id"], "truth": clip["truth"], "peak_dbfs": round(peak, 1) if peak is not None else None,
                     "audible": bool(baseline is not None and peak is not None and peak - baseline >= QUIET_DB),
                     "labels": sorted({label for _, label in hits}), "cry_after_s": round(cries[0], 1) if cries else None})
        print(json.dumps(rows[-1]), flush=True)
    stop.set()
    cry = [r for r in rows if r["truth"] == "cry"]
    other = [r for r in rows if r["truth"] != "cry"]
    heard_cries = [r for r in cry if r["audible"]]
    delays = sorted(r["cry_after_s"] for r in cry if r["cry_after_s"] is not None)
    out = {"baseline_dbfs": round(baseline, 1) if baseline is not None else None, "camera_seconds": len(levels),
           "cries_played": len(cry), "cries_audible": len(heard_cries), "cries_caught": sum(r["cry_after_s"] is not None for r in cry),
           "others_played": len(other), "others_audible": sum(r["audible"] for r in other), "false_cries": sum(r["cry_after_s"] is not None for r in other),
           "cry_after_s_median": delays[len(delays) // 2] if delays else None, "cry_after_s_max": delays[-1] if delays else None, "rows": rows}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1), flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
