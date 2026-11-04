"""The live glasses HUD run: the mock Meta Ray-Ban Display's camera streams our clips through DAT to the iPhone app, the
app streams frames to a real local agent, the agent runs MediaPipe, SAM 3.1 and Muse Spark Open on them, logs the diaper
to Baby Buddy and reads it back, and its events draw the HUD through DAT's Display API in Meta's MockDisplayKit.

    python scripts/glasses_hud_live.py --build-feed          # writes HUD/hud-live.json and MockFeed/hud-live-feed.mp4
    # build and install the app (apps/glasses/README.md), then:
    python scripts/glasses_hud_live.py --udid SIM --out-dir results/glasses-live --name run \\
        --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-live.mp4
    # --hands sam3_only runs the camera skills on SAM 3.1 alone (no MediaPipe), the "hands" setting in hands.py

Mocked, because it does not exist here: the glasses hardware and their lens (DAT MockDeviceKit and MockDisplayKit),
the camera picture (our synthetic clips and one licensed photo), the baby, and the parent's words (typed by the app at
the feed times below). Everything behind them runs: the agent (config/agent.glasses-live.json), MediaPipe and one
SAM 3.1 process on this Mac under the GPU lock, Muse on Baseten, Baby Buddy with the test child. Telegram goes to a
capture file and the house runs dry: the script blanks every Telegram and Home Assistant variable for the agent.
"""
import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
GLASSES = ROOT / "apps" / "glasses" / "ParentingGlasses"
SCRIPT_OUT = GLASSES / "HUD" / "hud-live.json"
FEED_NAME = "hud-live-feed"
FEED_OUT = GLASSES / "MockFeed" / f"{FEED_NAME}.mp4"
SYNTH = Path.home() / "Engineering" / "gonza" / "meta-hackathon-2026-synthetic"
HANDSOFF = SYNTH / "kt" / "clips" / "handsoff" / "table-handsoff-02.mp4"
HOVER = SYNTH / "hover" / "fresh" / "table-a-hover-2.5cm.mp4"
HELD = SYNTH / "hover" / "held-blind2" / "table-a-hold-hover-diaper-both-s0.mp4"
DOG = Path.home() / "Engineering" / "gonza" / "pa-local-data" / "dog-near-baby" / "commons" / "c009.jpg"
DOG_CREDIT = "Photo: Wang Yu Ching, Office of the President (Taiwan), CC BY 2.0, Wikimedia Commons"
CONFIG = "config/agent.glasses-live.json"
BUNDLE = "com.bygmv.parentingglasses"
GPU_LOCK = Path("/tmp/pa-gpu.lock")
# Never reach Telegram or Home Assistant from this run: blank, so the env file's values are not loaded (setdefault).
BLANKED = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_FAMILIES_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_CECI_CHAT_ID", "HA_MCP_TOKEN",
           "HA_TOKEN", "HA_URL")

# The feed, in order: (scene, clip, from s, to s, cue s inside the part or None, played backwards).
# The cues come from the synthetic set (kt/clips/cues.json, hover/fresh/labels.json, results/hover/held): the held diaper
# rises 2.6 s into the held clip, the hands leave 2.2 s into table-handsoff-02 and stay away, the hover starts 2.5 s into
# the hover clip. table-handsoff-01 was dropped: its hands leave for under a second and come back holding a diaper over
# the baby, and SAM 3.1 read that frame as a hand on (Oct 30 rehearsal 6).
# A real head camera has no cuts, our spliced feed does. A cut while a resting hand is anchored reads as a lift (Oct 30
# rehearsal: a 3.1 cm "hover" and "hand" at a cut), so every cut falls where the hands are gone or the watch is not yet
# armed, and a resting stretch is made longer by playing it forwards then backwards, never by a jump.
# The run starts with the hands already holding a fresh diaper over the baby, so MediaPipe never sees them: the SAM 3.1
# held look has to find them (it only runs for a hand the watch never saw).
PARTS = [
    ("held diaper", "held", 0.0, 2.5, None, False),
    ("held diaper", "held", 0.0, 2.5, None, True),
    ("held diaper", "held", 0.0, 2.5, None, False),
    ("held diaper", "held", 0.0, 2.5, None, True),
    ("held diaper", "held", 0.0, 7.0, 2.6, False),
    ("both hands off", "handsoff", 0.0, 2.9, None, True),
    ("both hands off", "handsoff", 0.0, 6.042, 2.2, False),
    ("one hand on", "hover", 0.0, 2.5, None, False),
    ("one hand on", "hover", 0.0, 2.5, None, True),
    ("one hand on", "hover", 0.0, 2.5, None, False),
    ("one hand on", "hover", 0.0, 2.5, None, True),
    ("hover 2.5 cm", "hover", 0.0, 6.958, 2.5, False),
    ("done", "hover", 0.0, 6.958, None, True),
    ("dog near the baby", "dog", 0.0, 12.0, None, False),
]
SOURCES = {
    "held diaper": "Muse arms the watch, the hands hold a diaper: SAM 3.1 finds them, then the hover",
    "both hands off": "The hands come back, rest, then both leave: MediaPipe, the tone, then \u201chand\u201d",
    "one hand on": "One hand rests on the baby: silent",
    "hover 2.5 cm": "One hand hovers 2.5 cm: SAM 3.1 hand masks and the lift check",
    "done": "\u201cdone, it was dirty\u201d: Muse closes the watch, Baby Buddy read back",
    "dog near the baby": "SAM 3.1 dog and baby masks on the glasses frame",
}
SAY = [(1.0, "changing time", "held diaper"), (0.3, "done, it was dirty", "done")]  # (seconds into the scene, words, scene)


def timeline():
    """The scenes with their feed times, each scene's cues, and the parent's lines at feed times."""
    scenes, cues, at = [], [], 0.0
    for name, _, start, end, cue, _ in PARTS:
        if cue is not None:
            cues.append({"scene": name, "feed_s": round(at + cue, 3)})
        if not scenes or scenes[-1]["name"] != name:
            scenes.append({"name": name, "source": SOURCES[name], "at": round(at, 3), "length": 0.0,
                           **({"credit": DOG_CREDIT} if name == "dog near the baby" else {})})
        at += end - start
        scenes[-1]["length"] = round(at - scenes[-1]["at"], 3)
    start_of = {s["name"]: s["at"] for s in scenes}
    say = [{"at": round(start_of[scene] + offset, 3), "text": text} for offset, text, scene in SAY]
    return {"feed": FEED_NAME, "duration_s": round(at, 3), "scenes": scenes, "say": say, "cues": cues}


def build_feed(out=FEED_OUT):
    """One HEVC feed at 30 fps (MockDeviceKit plays 30 frames per second whatever the file says), 1280 x 704."""
    fit = "scale=1280:704:force_original_aspect_ratio=decrease,pad=1280:704:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    files = {"handsoff": HANDSOFF, "hover": HOVER, "held": HELD}
    inputs, index = [], {}
    for key, path in files.items():
        index[key] = len(index)
        inputs += ["-i", str(path)]
    index["dog"] = len(index)
    inputs += ["-loop", "1", "-framerate", "30", "-t", "12", "-i", str(DOG)]
    uses = {key: sum(part[1] == key for part in PARTS) for key in index}
    graph = [f"[{index[key]}:v]{fit},split={uses[key]}" + "".join(f"[{key}{n}]" for n in range(uses[key]))
             for key in index if uses[key]]
    taken = {key: 0 for key in index}
    for i, (_, key, start, end, _, backwards) in enumerate(PARTS):
        graph.append(f"[{key}{taken[key]}]trim={start}:{end},setpts=PTS-STARTPTS{',reverse' if backwards else ''}[p{i}]")
        taken[key] += 1
    graph.append("".join(f"[p{i}]" for i in range(len(PARTS))) + f"concat=n={len(PARTS)}:v=1:a=0[v]")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[v]",
                    "-c:v", "libx265", "-tag:v", "hvc1", "-preset", "medium", "-crf", "26", "-x265-params", "log-level=error",
                    "-pix_fmt", "yuv420p", "-an", str(out)], check=True)
    return out


def rows(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def latencies(app):
    """Frame to card, from the app's log: the agent received the frame (frame_unix) to the display accepted the card."""
    out = {}
    for row in app:
        if row["kind"] == "sent" and row.get("frame_unix"):
            out.setdefault(row["cause"], []).append(round(row["unix"] - row["frame_unix"], 3))
    return out


def first_sent(app, after_unix, match):
    return next((row for row in app if row["kind"] == "sent" and row["unix"] >= after_unix and match(row)), None)


def words_to_card(app):
    """The parent's words to the card that answers them: armed by Muse, and the diaper logged and read back."""
    said = {row["text"]: row["unix"] for row in app if row["kind"] == "say"}
    out = {}
    if "changing time" in said:
        armed = first_sent(app, said["changing time"], lambda r: "armed by Muse" in r.get("meta", ""))
        out["changing_time_to_armed_card_s"] = armed and round(armed["unix"] - said["changing time"], 3)
    done = next((unix for text, unix in said.items() if text.startswith("done")), None)
    if done:
        logged = first_sent(app, done, lambda r: r["title"] == "Logged")
        replied = first_sent(app, done, lambda r: r["title"] == "Logged" and r.get("detail"))
        out["done_to_logged_card_s"] = logged and round(logged["unix"] - done, 3)
        out["done_to_muse_line_on_card_s"] = replied and round(replied["unix"] - done, 3)
    return out


def scenes(agent, plan):
    """What each scene did, from the agent's own events, placed on the feed by stream_s (the agent's clock from the
    first frame it got, within a few tenths of a second of the feed's)."""
    bounds = {s["name"]: (s["at"], s["at"] + s["length"]) for s in plan["scenes"]}
    cue = {c["scene"]: c["feed_s"] for c in plan["cues"]}
    inside = lambda e, name, pad=0.5: e.get("stream_s") is not None and bounds[name][0] - pad <= e["stream_s"] < bounds[name][1] + pad
    kinds = lambda kind, name, pad=0.5: [e for e in agent if e["kind"] == kind and inside(e, name, pad)]
    armed = next((e for e in agent if e["kind"] == "changing_armed"), None)
    out = {
        "armed": {"by": armed and armed["via"], "words_to_armed_s": armed and armed.get("since_words_s"),
                  "first_frame_watched_s": next((e["stream_s"] for e in agent if e["kind"] == "frame"), None),
                  "tools": [e["name"] for e in agent if e["kind"] == "tool"]},
        "one hand on": {"frames": len(kinds("frame", "one hand on", 0)), "voices": len(kinds("voice", "one hand on", 0)),
                        "chimes": len(kinds("chime", "one hand on", 0))},
    }
    for name in ("held diaper", "both hands off", "hover 2.5 cm"):
        voices = [v for v in kinds("voice", name) if v["stream_s"] >= cue[name] - 0.5]
        frames = kinds("frame", name, 0)
        # wall clock: a voice decided by SAM 3.1 carries the stream time of the frame SAM was asked about, not of the
        # moment it spoke, so the delay is the voice's publish time minus the publish time of the first frame at the cue
        at_cue = next((f for f in frames if f["stream_s"] >= cue[name]), None)
        out[name] = {"cue_s": cue[name], "spoken": bool(voices),
                     "cue_to_voice_s": round(voices[0]["unix"] - at_cue["unix"], 3) if voices and at_cue else None,
                     "voices_before_cue": len([v for v in kinds("voice", name, 0) if v["stream_s"] < cue[name] - 0.5]),
                     "chimes_before_cue": len([c for c in kinds("chime", name, 0) if c["stream_s"] < cue[name]]),
                     "alarms": [e.get("state") for e in kinds("alarm", name) if e.get("action") == "raise"],
                     "max_lift_cm": max((f["lift_cm"] for f in frames if f.get("lift_cm") is not None), default=None)}
    out["held diaper"]["held_looks"] = [{k: e.get(k) for k in ("stream_s", "based", "objects")}
                                        for e in kinds("anchor", "held diaper") if e.get("held")]
    back = next((e for e in agent if e["kind"] == "change_read_back"), None)
    out["done"] = {"read_back": back and {k: back.get(k) for k in ("id", "time", "wet", "solid")},
                   "tracked": [{k: e.get(k) for k in ("kind", "entry", "id")} for e in agent if e["kind"] in ("tracked", "track_dry", "track_error")]}
    dogs = [e for e in agent if e["kind"] == "dog_watch"]
    near = [e for e in dogs if e["verdict"] == "near" and inside(e, "dog near the baby", 0)]
    out["dog near the baby"] = {
        "looks": len(dogs), "verdicts": sorted({e["verdict"] for e in dogs}),
        "near_on_dog_frames": len(near), "near_elsewhere": len([e for e in dogs if e["verdict"] == "near"]) - len(near),
        "first_near": near[0] and {k: near[0].get(k) for k in ("stream_s", "ratio", "dog_score", "baby_score", "sam_s")} if near else None,
        "scene_start_to_first_near_frame_s": round(near[0]["stream_s"] - bounds["dog near the baby"][0], 3) if near else None,
        "sam_s": [e["sam_s"] for e in dogs],
        "alerts": [{k: e.get(k) for k in ("text", "telegram", "announce")} for e in agent if e["kind"] == "dog_alert"],
    }
    return out


def gpu_lock(wait_s=1800):
    deadline = time.monotonic() + wait_s
    while True:
        try:
            GPU_LOCK.mkdir()
            return
        except FileExistsError:
            if time.monotonic() > deadline:
                raise SystemExit("the GPU lock stayed taken")
            print("GPU lock taken, waiting 60 s", flush=True)
            time.sleep(60)


def run(args):
    plan = json.loads(SCRIPT_OUT.read_text())
    config = json.loads((ROOT / CONFIG).read_text())
    data = ROOT / config["data_dir"]
    data.mkdir(exist_ok=True)
    config_path = CONFIG
    if args.hands:  # the same config with the "hands" setting, written next to the run's data, out of git
        config["hands"] = args.hands
        config_path = str((data / "agent.json").relative_to(ROOT))
        (ROOT / config_path).write_text(json.dumps(config, indent=1) + "\n")
    for stale in ("events.jsonl", "telegram-captured.jsonl"):
        (data / stale).unlink(missing_ok=True)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(12)
    env = {**os.environ, "PARENTING_AGENT_GLASSES_TOKEN": token, "PYTHONUNBUFFERED": "1", **{k: "" for k in BLANKED}}
    gpu_lock()
    agent = recorder = None
    video_start = {}
    raw = Path(os.path.expanduser(args.video)).with_name(Path(args.video).stem + "-raw.mp4") if args.video else None
    try:
        with (data / "agent.log").open("w") as agent_log:  # stays in the data dir, out of git
            agent = subprocess.Popen([sys.executable, "-u", "-m", "parenting_agent", "--config", config_path], cwd=ROOT, env=env,
                                     stdin=subprocess.PIPE, stdout=agent_log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 180
        while not any(e["kind"] == "confirm_ready" for e in rows(data / "events.jsonl")):
            if time.monotonic() > deadline or agent.poll() is not None:
                raise SystemExit("SAM 3.1 did not load, see the agent log in the data dir")
            time.sleep(1)
        subprocess.run(["xcrun", "simctl", "terminate", args.udid, BUNDLE], capture_output=True)
        container = Path(subprocess.run(["xcrun", "simctl", "get_app_container", args.udid, BUNDLE, "data"], capture_output=True,
                                        text=True, check=True).stdout.strip())
        (container / "Documents" / "hud-live.jsonl").unlink(missing_ok=True)  # a log left by an earlier run
        if raw:
            raw.parent.mkdir(parents=True, exist_ok=True)
            recorder = subprocess.Popen(["xcrun", "simctl", "io", args.udid, "recordVideo", "--codec", "h264", "--force", str(raw)],
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
            time.sleep(0.5)
        port = config["glasses"].get("port", 8766)
        subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", args.udid, BUNDLE,
                        "-agentURL", f"http://127.0.0.1:{port}", "-agentToken", token, "-hudLive", "YES", "-hudLog", "YES",
                        "-sendFPS", str(args.fps), "-recordSpeech", "YES"], check=True, capture_output=True)
        deadline = time.monotonic() + 90
        while not any(r["kind"] == "feed_start" for r in rows(container / "Documents" / "hud-live.jsonl")):
            if time.monotonic() > deadline:
                raise SystemExit("the app never got a camera frame")
            time.sleep(0.5)
        feed_start = next(r["unix"] for r in rows(container / "Documents" / "hud-live.jsonl") if r["kind"] == "feed_start")
        time.sleep(max(0.0, feed_start + plan["duration_s"] + 1.5 - time.time()))  # stop before the mock feed loops
    finally:
        if recorder:
            recorder.send_signal(signal.SIGINT)
            recorder.wait(timeout=60)
        if agent:
            agent.send_signal(signal.SIGTERM)
            try:
                agent.wait(timeout=60)
            except subprocess.TimeoutExpired:
                agent.kill()
        GPU_LOCK.rmdir()
    app = rows(container / "Documents" / "hud-live.jsonl")
    events = rows(data / "events.jsonl")
    import glasses_hero_run as hero
    speech_dir = out / f"{args.name}-speech"
    speech = hero.pull_speech(args.udid, speech_dir)
    brains = hero.brain_calls(events)
    result = {
        "name": args.name, "date": time.strftime("%Y-%m-%d %H:%M %z"), "config": CONFIG, "plan": plan,
        "hands": next((e.get("mode") for e in events if e["kind"] == "hands_mode"), None),
        "models": {"brain": sorted({f"{b['model']} on {b['destination']}" for b in brains}),
                   "vision": next(({k: e.get(k) for k in ("provider", "repo", "device")} for e in events if e["kind"] == "confirm_model"), None),
                   "sam3_processes": "one (sam3_local, kept between changes, shared with the dog look)"},
        "sam3_load_s": next((e.get("load_s") for e in events if e["kind"] == "confirm_ready"), None),
        "scenes": scenes(events, plan),
        "frame_to_card_s": latencies(app),
        "words_to_card_s": words_to_card(app),
        "baby_log": hero.readback(config, events),
        "telegram_captured": rows(data / "telegram-captured.jsonl"),
        "house": [e for e in events if e["kind"].startswith("house")],
        "summary": {"frames_processed": sum(e["kind"] == "frame" for e in events),
                    "brain_calls": len(brains), "brain_destinations": sorted({b["destination"] for b in brains}),
                    "brain_seconds": [b["seconds"] for b in brains], "cards_sent": sum(r["kind"] == "sent" for r in app),
                    "sam_calls": len(hero.sam_calls(events)) + sum(e["kind"] == "dog_watch" for e in events)},
        "conversation": [{"unix": e.get("unix"), "who": "parent" if e["kind"] == "message" else "agent", "text": e["text"]}
                         for e in events if e["kind"] in ("message", "reply")],
        "cards": [r for r in app if r["kind"] == "sent"],
        "app_log": app,
        "brain_calls": brains,
        "events": events,
    }
    if raw and raw.exists() and video_start:
        video = Path(os.path.expanduser(args.video))
        clips = hero.audio_clips(speech, speech_dir, video_start["unix"], speech_dir / hero.TONE)
        if clips:
            hero.mux(raw, clips, video, crf=26)
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-c:v", "libx264", "-crf", "26", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(video)], check=True)
        result["video"] = {"file": str(video), "bytes": video.stat().st_size, "raw": str(raw), "start_unix": video_start["unix"]}
    (out / f"{args.name}.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: result[k] for k in ("scenes", "frame_to_card_s", "words_to_card_s", "baby_log", "telegram_captured",
                                             "summary")}, indent=1))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--build-feed", action="store_true", help="write the live script and build the mock camera feed")
    parser.add_argument("--udid")
    parser.add_argument("--fps", type=float, default=10)
    parser.add_argument("--out-dir", default="results/glasses-live")
    parser.add_argument("--name", default="run")
    parser.add_argument("--video", help="where the muxed screen recording goes")
    parser.add_argument("--hands", choices=("auto", "sam3_only"), help="the hand detector, default the config's")
    args = parser.parse_args()
    if args.build_feed:
        plan = timeline()
        SCRIPT_OUT.write_text(json.dumps(plan, indent=1) + "\n")
        print(f"{SCRIPT_OUT.relative_to(ROOT)}: {len(plan['scenes'])} scenes, {plan['duration_s']} s")
        print(build_feed())
        return
    if not args.udid:
        parser.error("--udid is needed for a run")
    run(args)


if __name__ == "__main__":
    main()
