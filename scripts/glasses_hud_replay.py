"""The glasses HUD replay: one mock camera feed cut from our synthetic clips, and the HUD events that go with it, taken
from recorded detector outputs, never from a model run now.

    python scripts/glasses_hud_replay.py            # writes apps/glasses/ParentingGlasses/HUD/hud-replay.json
    python scripts/glasses_hud_replay.py --feed     # also builds MockFeed/hud-feed.mp4 with ffmpeg (kept out of git)

Scenes, in order:
1. The changing table watch, armed by Muse (hero2 take 2, Oct 29, results/hero2/run.json).
2. Both hands leave the baby: the reflex reads off, the tone, then "hand" after the 1.2 s hold (same run).
3. One hand hovers 2.5 cm above the baby: the lift check raises "lifted", then "hand" (same run).
4. Both hands hold a diaper over the baby, hiding them from MediaPipe: SAM 3.1 finds the hand holding the diaper, then
   the hover is spoken (results/hover/held/blind2/after.json, clip table-a-m-hold-hover-diaper-both-s0, with the saved
   SAM 3.1 masks drawn on the frames in video-v5/rec/sam/held-masked.mp4).
5. "done, it was dirty": Muse closes the watch, the diaper goes to Baby Buddy and is read back (same hero2 run).
6. A dog next to a baby in a stroller: SAM 3.1 dog and baby masks, the dog within 0.13 baby sizes, an alert
   (results/dog-near-baby/blind.json, photo c009, saved masks in video-v5/rec/sam/dog-c009-overlay.png).

Inside scenes 1 to 3 every event keeps its recorded time against the feed. Between scenes, and inside scenes 4 to 6,
the recorded gaps are shortened so the whole replay fits in about 19 s. Each event carries the recorded number it
stands for, and the scene event says which run it comes from.
"""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLASSES = ROOT / "apps" / "glasses"
OUT = GLASSES / "ParentingGlasses" / "HUD" / "hud-replay.json"
FEED = GLASSES / "ParentingGlasses" / "MockFeed" / "hud-feed.mp4"
SYNTH = Path.home() / "Engineering" / "gonza" / "meta-hackathon-2026-synthetic"
HERO_FEED_CLIPS = SYNTH / "kt" / "clips"
HOVER_CLIP = SYNTH / "hover" / "fresh" / "table-a-hover-2.5cm.mp4"
HELD_MASKED = SYNTH / "video-v5" / "rec" / "sam" / "held-masked.mp4"
DOG_OVERLAY = SYNTH / "video-v5" / "rec" / "sam" / "dog-c009-overlay.png"
HERO_RUN = ROOT / "results" / "hero2" / "run.json"
HELD_RUN = ROOT / "results" / "hover" / "held" / "blind2" / "after.json"
HELD_ID = "table-a-m-hold-hover-diaper-both-s0"
DOG_RUN = ROOT / "results" / "dog-near-baby" / "blind.json"
DOG_ID = "c009"
# results/dog-near-baby/sources.json: the photo is CC BY 2.0, so the credit goes on screen with it.
DOG_CREDIT = "Photo: Wang Yu Ching, Office of the President (Taiwan), CC BY 2.0, Wikimedia Commons"

# Held clip: held-masked.mp4 holds frames 30 to 167 of the 30 fps clip, so it starts 1.0 s into the clip. The clip's
# cue (the hands start to rise) is 2.6 s in, the first entry of lift_series is -2.6 s.
HELD_MASKED_START_S = 30 / 30
HELD_MASKED_S = 4.6


def hero_segment(run, start_s, end_s, loop):
    """Recorded hero2 events whose feed time falls in [start_s, end_s) of the given feed loop, as HUD events with the
    time since the segment start. Frame events become hand states only where the alarm level state changes."""
    feed_s = run["feed_s"]
    lo, hi = start_s + loop * feed_s, end_s + loop * feed_s
    out = []
    for event in run["events"]:
        stream_s = event.get("stream_s")
        if stream_s is None or not lo <= stream_s < hi:
            continue
        t = round(stream_s - lo, 3)
        kind = event["kind"]
        if kind == "frame":
            out.append({"t": t, "kind": "reflex", "state": event["state"], "hands": event["hands"],
                        "lift_cm": event.get("lift_cm")})
        elif kind == "alarm" and event["action"] == "raise":
            out.append({"t": t, "kind": "alarm", "state": event["state"], "episode": event["episode"]})
        elif kind == "alarm" and event["action"] == "clear":
            out.append({"t": t, "kind": "clear", "episode": event["episode"]})
        elif kind == "chime":
            out.append({"t": t, "kind": "chime", "episode": event["episode"]})
        elif kind == "voice":
            out.append({"t": t, "kind": "voice", "text": event["text"], "episode": event["episode"]})
        elif kind == "confirm":
            out.append({"t": t, "kind": "confirm", "verdict": event["verdict"], "episode": event["episode"],
                        "model": "SAM 3.1"})
    return out


def held_segment(held):
    """The held diaper hover from the blind2 run. The recorded numbers are the cue, the spoken latency and the SAM 3.1
    held look's verdict. The look's own time is not in the record, so it is placed at the clip start."""
    cue = 2.6 - HELD_MASKED_START_S
    out = [{"t": 0.2, "kind": "held", "object": held["object"], "verdict": held["held_looks"][0], "model": "SAM 3.1"}]
    if held["spoken"]:
        out.append({"t": round(cue, 3), "kind": "alarm", "state": "lifted", "episode": 1})
        out.append({"t": round(cue + held["latency_s"], 3), "kind": "voice", "text": "hand", "episode": 1,
                    "latency_s": held["latency_s"]})
    return out


def find(rows, key, value):
    match = next((row for row in rows if row.get(key) == value), None)
    if match is None:
        raise SystemExit(f"{value} not found")
    return match


def build(hero, held_run, dog_run):
    held = find(held_run["moments"], "id", HELD_ID)
    dog = find(dog_run["rows"], "id", DOG_ID)
    arming = hero["arming"]
    agent_lines = [line["text"] for line in hero["conversation"] if line["who"] == "agent"]
    parent_lines = [line["text"] for line in hero["conversation"] if line["who"] == "parent"]
    read_back = hero["baby_log"]["read_back"]
    contents = [name for name, on in (("wet", read_back["details"]["wet"]), ("dirty", read_back["details"]["solid"])) if on]

    scenes = [
        {"name": "armed", "source": "hero2 take 2, Oct 29", "feed": {"clip": "hero", "from": 3.0, "to": 5.0},
         "events": [
             {"t": 0.0, "kind": "parent", "text": parent_lines[0]},
             {"t": 0.1, "kind": "armed", "by": arming["armed_by"], "tool": arming["tool_calls"][0]["name"],
              "seconds": arming["words_to_armed_s"]},
             {"t": 0.1, "kind": "reply", "text": agent_lines[0]},
             *hero_segment(hero, 3.0, 5.0, loop=1)]},
        {"name": "hands off", "source": "hero2 take 2, Oct 29", "feed": {"clip": "hero", "from": 8.0, "to": 11.6},
         "events": hero_segment(hero, 8.0, 11.6, loop=0)},
        {"name": "hover", "source": "hero2 take 2, Oct 29", "feed": {"clip": "hero", "from": 16.6, "to": 20.0},
         "events": hero_segment(hero, 16.6, 20.0, loop=0)},
        {"name": "held diaper", "source": "held blind2, Oct 29, SAM 3.1 masks", "feed": {"clip": "held", "from": 0.0,
                                                                                          "to": HELD_MASKED_S},
         "events": held_segment(held)},
        {"name": "logged", "source": "hero2 take 2, Oct 29", "feed": {"clip": "hero", "from": 0.0, "to": 2.4},
         "events": [
             {"t": 0.0, "kind": "parent", "text": parent_lines[1]},
             {"t": 0.0, "kind": "closed"},
             {"t": 0.5, "kind": "logged", "what": read_back["kind"], "at": read_back["ts"][11:16],
              "contents": contents, "entry": read_back["id"], "seconds": arming["words_to_closed_s"]},
             {"t": 0.9, "kind": "reply", "text": agent_lines[1]}]},
        {"name": "dog", "source": "dog blind set, photo c009, Oct 29, SAM 3.1 masks",
         "credit": DOG_CREDIT, "feed": {"clip": "dog", "from": 0.0, "to": 3.0},
         "events": [{"t": 0.4, "kind": "dog", "verdict": dog["verdict"], "ratio": dog["measure"]["ratio"],
                     "alert": dog["alert"], "dog_score": dog["scores"]["dog"][0],
                     "baby_score": dog["scores"]["baby"][0], "seconds": dog["sam_s"], "model": "SAM 3.1"}]},
    ]
    timeline, at = [], 0.0
    for scene in scenes:
        length = round(scene["feed"]["to"] - scene["feed"]["from"], 3)
        timeline.append({"t": round(at, 3), "kind": "scene", "name": scene["name"], "source": scene["source"]})
        timeline += [{**event, "t": round(at + event["t"], 3)} for event in scene["events"]]
        scene["at"], scene["length"] = round(at, 3), length
        at += length
    timeline.sort(key=lambda event: event["t"])  # stable, so a scene event stays before its own events
    return {"duration_s": round(at, 3),
            "note": "Recorded detector outputs replayed on our synthetic clips. Gaps between scenes are shortened.",
            "scenes": [{key: scene[key] for key in ("name", "source", "credit", "feed", "at", "length") if key in scene}
                       for scene in scenes],
            "events": timeline}


def build_feed(replay, out=FEED):
    """Cuts the scenes' feed parts from the clips and joins them into one HEVC feed for DAT's MockDeviceKit."""
    scale = "scale=1280:704:force_original_aspect_ratio=decrease,pad=1280:704:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    hero = (f"[0:v]scale=1280:704,setsar=1,fps=30[a];[1:v]scale=1280:704,setsar=1,fps=30[b];"
            f"[2:v]scale=1280:704,setsar=1,fps=30,split[c][d];[c]trim=0:2.5,setpts=PTS-STARTPTS[r];"
            f"[a][b][r][d]concat=n=4:v=1:a=0,split={sum(s['feed']['clip'] == 'hero' for s in replay['scenes'])}")
    inputs = ["-i", str(HERO_FEED_CLIPS / "onehand" / "table-onehand-01.mp4"),
              "-i", str(HERO_FEED_CLIPS / "handsoff" / "table-handsoff-01.mp4"), "-i", str(HOVER_CLIP),
              "-i", str(HELD_MASKED), "-loop", "1", "-framerate", "30", "-i", str(DOG_OVERLAY)]
    hero_labels = [f"h{i}" for i, s in enumerate(replay["scenes"]) if s["feed"]["clip"] == "hero"]
    graph = [hero + "".join(f"[{label}]" for label in hero_labels)]
    parts = []
    for i, scene in enumerate(replay["scenes"]):
        feed = scene["feed"]
        source = {"hero": f"[h{i}]", "held": "[3:v]", "dog": "[4:v]"}[feed["clip"]]
        fit = "" if feed["clip"] == "hero" else f"{scale},"
        graph.append(f"{source}{fit}trim={feed['from']}:{feed['to']},setpts=PTS-STARTPTS[s{i}]")
        parts.append(f"[s{i}]")
    graph.append("".join(parts) + f"concat=n={len(parts)}:v=1:a=0[v]")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[v]",
                    "-c:v", "libx265", "-tag:v", "hvc1", "-preset", "medium", "-crf", "26",
                    "-x265-params", "log-level=error", "-pix_fmt", "yuv420p", "-an", str(out)], check=True)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--feed", action="store_true", help="also build the mock camera feed with ffmpeg")
    args = parser.parse_args()
    replay = build(json.loads(HERO_RUN.read_text()), json.loads(HELD_RUN.read_text()), json.loads(DOG_RUN.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(replay, indent=1) + "\n")
    print(f"{args.out.relative_to(ROOT)}: {len(replay['events'])} events, {replay['duration_s']} s")
    if args.feed:
        print(build_feed(replay))


if __name__ == "__main__":
    main()
