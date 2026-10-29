"""The recorded hero run: the changing-table loop through the Ray-Ban Meta glasses app in the iOS simulator, with
Muse Spark Open as the brain, SAM 3.1 on (hand masks for the lift check and the confirm frame), the real Baby Buddy,
the screen recorded and the app's spoken lines muxed onto the recording.

    python scripts/glasses_hero_run.py --udid SIM --out-dir results/hero --name hero --mux
    python scripts/glasses_hero_run.py --udid SIM --out-dir runs/first-hover --name run1 --feed table-a-hover-2.5cm --watch 20

The app must be built and installed with the mock feeds (apps/glasses/README.md). The script starts the agent with
config/agent.glasses.json and a fresh pairing token, launches the app with -recordSpeech YES, and after the run pulls
the app's speech WAV files and their play log out of the simulator. The simulator's screen recording has no audio,
so --mux places each spoken line and the chime at the Unix time the app played it, counted from the moment
simctl said the recording started. Feeds loop from the first frame the agent receives, so a moment's place in the
feed is its stream time modulo the feed length.
"""
import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BUNDLE = "com.bygmv.parentingglasses"
TONE = "tone.wav"  # the alert tone the app generates in code (AlertTone in Voice.swift) and saves next to the speech

# Each feed as (moment, start s, end s, cue s or None) inside one loop. The cues come from the synthetic set
# (kt/clips/cues.json and hover/fresh/labels.json). A cue is when the hands leave or the hover starts.
FEEDS = {
    "hero-feed": [("one hand on", 0.0, 6.042, None), ("both hands off", 6.042, 12.083, 6.042 + 3.2),
                  ("one hand resting", 12.083, 16.583, None), ("hover 2.5 cm", 16.583, 21.458, 16.583 + 0.5)],
    # the feed before the rest was padded (results/hero/cut-feed): the hover clip right after the hands-off clip
    "hero-feed-cut": [("one hand on", 0.0, 6.042, None), ("both hands off", 6.042, 12.083, 6.042 + 3.2),
                      ("hover 2.5 cm", 12.083, 18.958, 12.083 + 2.5)],
    "table-a-hover-2.5cm": [("hover 2.5 cm", 0.0, 6.958, 2.5)],
}


def events(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def feed_length(feed):
    return FEEDS[feed][-1][2]


def moments(rows, feed):
    """Every feed moment that played whole while the skill watched, and whether "hand" was spoken for it.

    The feed's phase against the stream clock is known to within about a second (the mock glasses start playing
    before the first frame reaches the agent), so a moment with a cue owns the voices from 0.5 s before its cue to
    0.5 s after it ends, and a moment without one owns the voices from 0.5 s after it starts to its end.
    """
    frames = [e for e in rows if e["kind"] == "frame"]
    if not frames:
        return []
    first, last = frames[0]["stream_s"], frames[-1]["stream_s"]
    length = feed_length(feed)
    voices = [e for e in rows if e["kind"] == "voice"]
    chimes = [e for e in rows if e["kind"] == "chime"]
    found = []
    for loop in range(int(last // length) + 1):
        for name, start, end, cue in FEEDS[feed]:
            a, b = loop * length + start, loop * length + end
            if a < first or b > last:
                continue
            at = None if cue is None else loop * length + cue
            lo, hi = (a + 0.5, b) if at is None else (at - 0.5, b + 0.5)
            spoken = [v for v in voices if lo <= v["stream_s"] < hi]
            rang = [c for c in chimes if lo <= c["stream_s"] < hi]
            first_chime = rang[0]["stream_s"] if rang else None
            found.append({"moment": name, "loop": loop, "from_s": round(a, 2), "to_s": round(b, 2),
                          "cue_s": None if at is None else round(at, 2), "hand_spoken": bool(spoken),
                          "chimes": len(rang), "voice_reason": spoken[0].get("reason") if spoken else None,
                          "first_chime_to_hand_s": round(spoken[0]["stream_s"] - first_chime, 2) if spoken and first_chime is not None else None,
                          "cue_to_hand_s": round(spoken[0]["stream_s"] - at, 2) if spoken and at is not None else None})
    return found


def sam_calls(rows):
    """Each SAM 3.1 request with its answer: confirms (one frame, on or off) and lift anchors (hand and baby masks)."""
    calls, open_confirm, open_anchor = [], {}, []
    for e in rows:
        if e["kind"] == "confirm_request":
            open_confirm[e["episode"]] = e
        elif e["kind"] in ("confirm", "confirm_error") and e.get("episode") in open_confirm:
            asked = open_confirm.pop(e["episode"])
            calls.append({"use": "confirm", "episode": e["episode"], "frame_stream_s": asked["stream_s"], "asked_t": asked["t"],
                          "answered_t": e["t"], "seconds": round(e["t"] - asked["t"], 3), "verdict": e.get("verdict"),
                          "error": e.get("error")})
        elif e["kind"] == "anchor_request":
            open_anchor.append(e)
        elif e["kind"] in ("anchor", "anchor_error") and open_anchor:
            asked = open_anchor.pop(0)
            calls.append({"use": "lift anchor", "frame_stream_s": asked["stream_s"], "asked_t": asked["t"], "answered_t": e["t"],
                          "seconds": round(e["t"] - asked["t"], 3), "hands": e.get("hands"), "based": e.get("based"),
                          "error": e.get("error")})
    return sorted(calls, key=lambda c: c["asked_t"])


def arming(rows):
    """Who armed the watch and closed it, and how long each took from the parent's words, from the agent's events."""
    said = lambda text: next((e for e in rows if e["kind"] == "message" and e.get("text") == text), None)
    armed = next((e for e in rows if e["kind"] == "changing_armed"), None)
    start = said("changing time")
    watching = next((e for e in rows if e["kind"] == "skill_armed"), None)
    tools = [{"t": e["t"], "name": e["name"], "status": e["status"]} for e in rows if e["kind"] == "tool"]
    closed = next((e for e in rows if e["kind"] == "skill_closed"), None)
    back = next((e for e in rows if e["kind"] == "change_read_back"), None)
    return {
        "armed_by": armed and armed["via"],
        "words_to_armed_s": armed and armed.get("since_words_s"),
        "words_to_watching_s": round(watching["t"] - start["t"], 3) if watching and start else None,
        "phrase_fallbacks": [{k: e.get(k) for k in ("t", "action", "text")} for e in rows if e["kind"] == "phrase_fallback"],
        "tool_calls": tools,
        "read_back_event": back,
        "words_to_closed_s": None if not closed else next((round(closed["t"] - e["t"], 3) for e in reversed(rows)
                                                            if e["kind"] == "message" and e["t"] < closed["t"]), None),
    }


def brain_calls(rows):
    keys = ("t", "provider", "model", "destination", "seconds", "tool_calls", "input_tokens", "output_tokens",
            "reasoning_tokens", "usd", "fallback")
    return [{k: e.get(k) for k in keys} for e in rows if e["kind"] == "brain_call"]


def readback(config, rows):
    """Reads the change the skill logged back from Baby Buddy, the way the parent's app would see it."""
    from parenting_agent.agent import config as config_mod
    from parenting_agent.agent.babybuddy import BabyBuddyLog
    tracked = [e for e in rows if e["kind"] == "tracked" and e.get("entry") == "changes"]
    if not tracked:
        return {"logged": False, "events": [e for e in rows if e["kind"] in ("track_dry", "track_error")]}
    config_mod.load_env(config["env_file"])
    log = BabyBuddyLog.from_config(config["baby_log"])
    entry = log.get("diaper", tracked[-1]["id"])
    return {"logged": True, "host": log.destination, "child": config["baby_log"]["child"], "id": tracked[-1]["id"],
            "read_back": entry}


def pull_speech(udid, into):
    container = subprocess.run(["xcrun", "simctl", "get_app_container", udid, BUNDLE, "data"], capture_output=True,
                               text=True, check=True).stdout.strip()
    source = Path(container) / "Documents" / "speech"
    if into.exists():
        shutil.rmtree(into)
    shutil.copytree(source, into)
    return events(into / "log.jsonl") if (into / "log.jsonl").exists() else []


def audio_clips(speech, speech_dir, video_start, chime_file):
    """Each sound the app played as (file, seconds into the recording, seconds to keep or None for all)."""
    clips, played = [], {}
    for row in speech:
        if row["kind"] == "started":
            played[row["file"]] = row["t"]
        elif row["kind"] in ("finished", "cancelled") and row["file"] in played:
            start = played.pop(row["file"])
            wav = speech_dir / row["file"]
            if wav.exists():
                keep = round(row["t"] - start, 3) if row["kind"] == "cancelled" else None
                clips.append((wav, round(start - video_start, 3), keep))
        elif row["kind"] == "chime" and chime_file and chime_file.exists():
            clips.append((chime_file, round(row["t"] - video_start, 3), None))
    for name, start in played.items():  # still playing when the recording stopped: the recording's end cuts it
        if (speech_dir / name).exists():
            clips.append((speech_dir / name, round(start - video_start, 3), None))
    return sorted((c for c in clips if c[1] >= 0), key=lambda c: c[1])


def mux(video, clips, out, crf=30):
    """The screen recording with the app's sounds laid on it at their play times, re-encoded small enough to share."""
    seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                                   capture_output=True, text=True, check=True).stdout.strip())
    inputs, filters = ["-i", str(video)], []
    for i, (path, at, keep) in enumerate(clips, start=1):
        inputs += ["-i", str(path)]
        trim = f"atrim=0:{keep}," if keep else ""
        ms = int(at * 1000)
        filters.append(f"[{i}:a]{trim}aformat=sample_rates=48000:channel_layouts=mono,adelay={ms}|{ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(1, len(clips) + 1))
    filters.append(f"{mix}amix=inputs={len(clips)}:normalize=0:duration=longest,apad=whole_dur={seconds:.3f},atrim=0:{seconds:.3f}[aout]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
                    "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-vf", "scale=-2:1280",
                    "-c:a", "aac", "-b:a", "96k", "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(out)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/agent.glasses.json")
    parser.add_argument("--udid", required=True)
    parser.add_argument("--fps", type=float, default=10)
    parser.add_argument("--watch", type=float, default=50, help="seconds between \"changing time\" and \"done\"")
    parser.add_argument("--feed", default="hero-feed", choices=sorted(FEEDS))
    parser.add_argument("--done", default="done", help="the parent's closing line, for example \"done, it was dirty\"")
    parser.add_argument("--regions", choices=("sam3", "mediapipe"), help="override the lift check's hand regions")
    parser.add_argument("--no-sam", action="store_true", help="rehearsal without the GPU: no SAM 3.1 confirm, MediaPipe regions")
    parser.add_argument("--ask", default="", help="one more question after \"done\", answered from the baby log")
    parser.add_argument("--ask-after", type=float, default=14)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--name", default="run")
    parser.add_argument("--mux", action="store_true", help="record the screen and mux the app's spoken lines onto it")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / args.config).read_text())
    if args.regions or args.no_sam:  # a variant of the skill file in the data dir, out of git
        skill = json.loads((ROOT / config["changing_table"]["skill"]).read_text())
        skill["lift"]["regions"] = "mediapipe" if args.no_sam else args.regions
        if args.no_sam:
            skill["confirm"] = {"provider": "none"}
            config["changing_table"]["preload_confirm"] = False
        (ROOT / config["data_dir"]).mkdir(exist_ok=True)
        variant = ROOT / config["data_dir"] / "skill-variant.json"
        variant.write_text(json.dumps(skill))
        config["changing_table"]["skill"] = str(variant)
        args.config = str(ROOT / config["data_dir"] / "agent-variant.json")
        Path(args.config).write_text(json.dumps(config))
    log = ROOT / config["data_dir"] / "events.jsonl"
    if log.exists():
        log.unlink()
    token = secrets.token_urlsafe(12)
    port = config["glasses"].get("port", 8766)
    env = {**os.environ, "PARENTING_AGENT_GLASSES_TOKEN": token, "PYTHONUNBUFFERED": "1"}
    agent_log = (ROOT / config["data_dir"] / "agent.log").open("w")  # stays in the data dir, out of git
    agent = subprocess.Popen([sys.executable, "-u", "-m", "parenting_agent", "--config", args.config], cwd=ROOT, env=env,
                             stdin=subprocess.PIPE, stdout=agent_log, stderr=subprocess.STDOUT)
    raw_video = out / f"{args.name}-screen.mp4"
    recorder, video_start = None, {}
    try:
        time.sleep(6)
        if args.mux:
            recorder = subprocess.Popen(["xcrun", "simctl", "io", args.udid, "recordVideo", "--codec", "h264", "--force", str(raw_video)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

            def started():
                for line in recorder.stderr:
                    if "Recording started" in line and "unix" not in video_start:
                        video_start["unix"] = time.time()
            threading.Thread(target=started, daemon=True).start()
            for _ in range(100):
                if "unix" in video_start:
                    break
                time.sleep(0.05)
            time.sleep(1)
        launched = time.time()
        subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", args.udid, BUNDLE,
                        "-agentURL", f"http://127.0.0.1:{port}", "-agentToken", token, "-autoDemo", "YES",
                        "-sendFPS", str(args.fps), "-demoWatchSeconds", str(args.watch), "-mockFeed", args.feed, "-demoDone", args.done,
                        "-recordSpeech", "YES", *(["-demoAsk", args.ask, "-demoAskAfterSeconds", str(args.ask_after)] if args.ask else [])],
                        check=True, capture_output=True)
        deadline = time.monotonic() + args.watch + args.ask_after + 60
        while time.monotonic() < deadline:
            time.sleep(1)
            rows = events(log) if log.exists() else []
            closed = next((e["t"] for e in rows if e["kind"] == "skill_closed"), None)
            asked = next((e["t"] for e in rows if e["kind"] == "message" and args.ask and e.get("text") == args.ask), None)
            after = asked if args.ask else closed
            if closed is not None and after is not None and any(e["kind"] == "reply" and e["t"] > after for e in rows):
                time.sleep(15)  # the app speaks the last reply
                break
    finally:
        if recorder:
            recorder.send_signal(signal.SIGINT)
            recorder.wait(timeout=60)
        agent.send_signal(signal.SIGTERM)
        agent.wait(timeout=60)

    rows = events(log)
    speech_dir = out / f"{args.name}-speech"
    speech = pull_speech(args.udid, speech_dir)
    chime = speech_dir / TONE
    found = moments(rows, args.feed)
    sams = sam_calls(rows)
    brains = brain_calls(rows)
    chimes = {e["episode"]: e for e in rows if e["kind"] == "chime"}
    voices = [e for e in rows if e["kind"] == "voice"]
    model = next((e for e in rows if e["kind"] == "confirm_model"), {})
    run = {
        "name": args.name,
        "date": time.strftime("%Y-%m-%d %H:%M %z"),
        "feed": args.feed, "feed_s": feed_length(args.feed), "sample_fps_set": args.fps, "watch_s": args.watch,
        "models": {
            "brain": sorted({f"{b['model']} on {b['destination']}" for b in brains}),
            "vision": f"SAM 3.1 ({model.get('repo')}, {model.get('device')}, this Mac)" if model else None,
            "hand_reflex": "MediaPipe Hands (Google, this Mac)",
            "voice": "iOS AVSpeechSynthesizer en-US, in the companion app",
            "alert_tone": "two sine notes generated in the app's code (AlertTone, Voice.swift), no sound asset",
        },
        "lift_regions": json.loads(Path(config["changing_table"]["skill"] if Path(config["changing_table"]["skill"]).is_absolute()
                                        else ROOT / config["changing_table"]["skill"]).read_text())["lift"]["regions"],
        "arming": arming(rows),
        "baby_log": readback(config, rows),
        "moments": found,
        "summary": {
            "frames_processed": sum(e["kind"] == "frame" for e in rows),
            "chimes": len(chimes), "voices": len(voices), "voices_dropped": sum(e["kind"] == "voice_dropped" for e in rows),
            "chime_to_voice_s": [round(v["t"] - chimes[v["episode"]]["t"], 2) for v in voices if v["episode"] in chimes],
            "brain_calls": len(brains), "brain_fallbacks": sum(bool(b["fallback"]) for b in brains),
            "brain_destinations": sorted({b["destination"] for b in brains}),
            "brain_seconds": [b["seconds"] for b in brains],
            "sam_calls": len(sams), "sam_confirms": [c["verdict"] for c in sams if c["use"] == "confirm"],
            "sam_seconds": [c["seconds"] for c in sams],
        },
        "conversation": [{"t": e["t"], "unix": e.get("unix"), "who": "parent" if e["kind"] == "message" else "agent", "text": e["text"]}
                         for e in rows if e["kind"] in ("message", "reply")],
        "brain_calls": brains,
        "sam_calls": sams,
        "speech": speech,
        "video_start_unix": video_start.get("unix"),
        "app_launched_unix": round(launched, 3),
        "events": rows,
    }
    if args.mux and raw_video.exists() and video_start:
        clips = audio_clips(speech, speech_dir, video_start["unix"], chime)
        muxed = out / f"{args.name}.mp4"
        mux(raw_video, clips, muxed)
        run["video"] = {"file": muxed.name, "bytes": muxed.stat().st_size,
                        "sounds": [{"file": p.name, "at_s": at, "kept_s": keep} for p, at, keep in clips]}
    (out / f"{args.name}.json").write_text(json.dumps(run, indent=1) + "\n")
    print(json.dumps({"moments": found, "summary": run["summary"], "arming": run["arming"], "baby_log": run["baby_log"],
                      "conversation": run["conversation"],
                      "video": run.get("video", {}).get("bytes")}, indent=1))


if __name__ == "__main__":
    main()
