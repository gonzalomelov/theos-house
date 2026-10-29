"""One full glasses loop in the iOS simulator: the agent with the glasses channel, the companion app with Meta's mock
Ray-Ban Meta (DAT MockDeviceKit) playing the synthetic changing-table feed, and a summary of what happened.

    python scripts/glasses_sim_run.py --config CONFIG --udid SIM_UDID --fps 2 --watch 40 --out results/glasses/run-2fps.json
    python scripts/glasses_sim_run.py ... --video results/glasses/loop.mp4 --shots results/glasses

The app must already be installed on the booted simulator (see apps/glasses/README.md). The agent config must use
"glasses" as the changing-table source and set glasses.token, which the app gets as a launch argument. The app says
"changing time", waits --watch seconds and says "done". The feed loops every FEED_S seconds and both hands leave the
baby once per loop, so the number of hands-off moments while armed is about armed seconds / FEED_S.
"""
import argparse
import collections
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = "com.bygmv.parentingglasses"
FEED_S = 12.083  # table-onehand-01 then table-handsoff-01, 6.042 s each


def events(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def answered(rows):
    """The change is closed and the agent has answered after it."""
    closed = next((e["t"] for e in rows if e["kind"] == "skill_closed"), None)
    return closed is not None and any(e["kind"] == "reply" and e["t"] > closed for e in rows)


def summarize(rows, fps, watch):
    kinds = collections.Counter(e["kind"] for e in rows)
    armed = next((e["t"] for e in rows if e["kind"] == "skill_armed"), None)
    closed = next((e for e in rows if e["kind"] == "skill_closed"), None)
    frames = [e for e in rows if e["kind"] == "frame"]
    span = frames[-1]["stream_s"] - frames[0]["stream_s"] if len(frames) > 1 else 0
    armed_s = (closed["t"] if closed else rows[-1]["t"]) - armed if armed is not None else 0
    voices = [e for e in rows if e["kind"] == "voice"]
    chimes = {e["episode"]: e["t"] for e in rows if e["kind"] == "chime"}
    return {
        "sample_fps_set": fps,
        "watch_s": watch,
        "frames_processed": len(frames),
        "processed_fps": round((len(frames) - 1) / span, 2) if span else None,
        "reflex_ms_median": round(sorted(e["seconds"] for e in frames)[len(frames) // 2] * 1000, 1) if frames else None,
        "armed_s": round(armed_s, 1),
        "hands_off_moments_expected": int(armed_s // FEED_S),
        "chimes": kinds["chime"],
        "voices": len(voices),
        "voices_dropped": kinds["voice_dropped"],
        "chime_to_voice_s": [round(v["t"] - chimes[v["episode"]], 2) for v in voices if v.get("episode") in chimes],
        "skill_closed": bool(closed),
        "brain_calls": [{"destination": e.get("destination"), "seconds": e.get("seconds")} for e in rows if e["kind"] == "brain_call"],
        "tools": [{"name": e["name"], "status": e["status"]} for e in rows if e["kind"] == "tool"],
        "conversation": [{"t": e["t"], "who": "parent" if e["kind"] == "message" else "agent", "text": e["text"]}
                         for e in rows if e["kind"] in ("message", "reply")],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--udid", required=True)
    parser.add_argument("--fps", type=float, default=10)
    parser.add_argument("--watch", type=float, default=40)
    parser.add_argument("--out", required=True)
    parser.add_argument("--video")
    parser.add_argument("--shots")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())
    data = Path(config["data_dir"])
    log = data / "events.jsonl"
    if log.exists():
        log.unlink()
    port, token = config["glasses"].get("port", 8766), config["glasses"]["token"]
    agent = subprocess.Popen([sys.executable, "-u", "-m", "parenting_agent", "--config", args.config], cwd=ROOT,
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    recorder = None
    try:
        time.sleep(5)
        if args.video:
            recorder = subprocess.Popen(["xcrun", "simctl", "io", args.udid, "recordVideo", "--codec", "h264", "--force", args.video],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
        subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", args.udid, BUNDLE,
                        "-agentURL", f"http://127.0.0.1:{port}", "-agentToken", token, "-autoDemo", "YES",
                        "-sendFPS", str(args.fps), "-demoWatchSeconds", str(args.watch)], check=True, capture_output=True)
        started, shot = time.monotonic(), 0
        total = args.watch + 20
        while time.monotonic() - started < total:
            time.sleep(1)
            if args.shots and log.exists():
                rows = events(log)
                want = {"02-hand-spoken": lambda: any(e["kind"] == "voice" for e in rows), "03-change-logged": lambda: answered(rows)}
                for name, ready in want.items():
                    path = Path(args.shots) / f"{name}.png"
                    if not path.exists() and ready():
                        time.sleep(1.5)
                        subprocess.run(["xcrun", "simctl", "io", args.udid, "screenshot", str(path)], capture_output=True)
                first = Path(args.shots) / "01-watching.png"
                if not first.exists() and sum(e["kind"] == "frame" for e in rows) > 6:
                    subprocess.run(["xcrun", "simctl", "io", args.udid, "screenshot", str(first)], capture_output=True)
            if log.exists() and answered(events(log)):
                time.sleep(4)
                break
    finally:
        if recorder:
            recorder.send_signal(signal.SIGINT)
            recorder.wait(timeout=30)
        agent.send_signal(signal.SIGTERM)
        agent.wait(timeout=30)
    summary = summarize(events(log), args.fps, args.watch)
    Path(args.out).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "conversation"}, indent=2))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
