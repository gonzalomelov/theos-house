"""Real run for issues #14 and #32: licensed test clips through PANNs and the agent, numbers and labels only.

    python scripts/sounds_run.py                     # writes results/sounds/run.json and results/sounds/cry-eval.json
    python scripts/sounds_run.py --camera-seconds 60 # also listens to the living room camera, writes results/sounds/camera.json

One cry and one doorbell from the meta-hackathon-2026 hearing set (licenses in hearing_sources.json) are decoded by
ffmpeg on a pipe into memory, squeezed through the camera's 8 kHz A-law channel, and fed one second at a time into
the Ear, as the Tapo stream would be. The cry is heard at a moment of the simulated week whose true reason is known.
The doorbell rings while the changing-table skill is armed. Nothing plays, no audio is written, the house is dry run.
"""
import argparse
import datetime
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent import cry_reason, hearing  # noqa: E402
from parenting_agent.agent import build  # noqa: E402
from parenting_agent.agent import config as config_mod  # noqa: E402
from parenting_agent.channels.router import Router  # noqa: E402
from parenting_agent.house_sounds import HouseSounds  # noqa: E402
from parenting_agent.rhythm.log import FixtureLog  # noqa: E402
from simweek import cries  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MEDIA = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic"
SOURCES = Path.home() / "Engineering/gonza/meta-hackathon-2026/muse/data/hearing_sources.json"
FIXTURE = REPO / "tests/fixtures/simweek.json"
TZ = datetime.timezone(datetime.timedelta(hours=-3))
KEEP = ("sound", "cry_reason", "notify", "routed", "house_sound", "observation", "white_noise")


class ArmedSkill:
    kind, name = "skill", "changing-table"

    def __init__(self):
        self.skill = None


def clean(event):
    return {k: v for k, v in event.items() if k not in ("t",)}


def cry_eval(entries):
    cases = cries.candidates(entries)
    rows = []
    for case in cries.sample(cases):
        result = cry_reason.explain(entries, case["at"], TZ)
        rows.append({"at": case["at"].isoformat(), "truth": case["truth"], "guess": result["top"],
                     "right": result["top"] == case["truth"], "text": result["text"], "resolved_by": case["resolved_by"]})
    week = [cry_reason.explain(entries, c["at"], TZ)["top"] == c["truth"] for c in cases]
    per = {}
    for case, ok in zip(cases, week):
        per.setdefault(case["truth"], [0, 0])
        per[case["truth"]][0] += ok
        per[case["truth"]][1] += 1
    return {"ten": {"right": sum(r["right"] for r in rows), "of": len(rows), "cases": rows},
            "whole_week": {"right": sum(week), "of": len(week), "per_reason": {k: f"{a} of {b}" for k, (a, b) in per.items()}},
            "how": "simweek/cries.py: the truth is what the simulated week does next (feed, diaper change, sleep), "
                   "the cry is 1 to 12 min before it, the reasoner reads only the log up to the cry"}


def listen_camera(agent, sounds, skill, args):
    """Live labels from the Tapo camera with the skill armed, so a doorbell near it goes the whole way to the ear."""
    config_mod.load_env(args.env_file)
    skill.skill = object()
    first, began, seconds, error = len(agent.bus.history), time.monotonic(), 0, None
    rows_before = len(sounds.listen().rows)
    try:
        for chunk in hearing.camera_seconds(hearing.camera_url()):
            sounds.ear.feed(chunk)
            seconds += 1
            if seconds >= args.camera_seconds:
                break
        sounds.ear.flush()
    except (ConnectionError, OSError, KeyError) as exc:
        error = hearing.mask(str(exc))[:300]
    rows = sounds.ear.rows[rows_before:]
    levels = sorted(r["dbfs"] for r in rows)
    return {"generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "camera": "Tapo C200 living room, RTSP audio track only, labels only", "seconds_heard": seconds,
            "wall_s": round(time.monotonic() - began, 1), "error": error,
            "median_dbfs": levels[len(levels) // 2] if levels else None,
            "seconds_fired": {label: sum(label in r["fired"] for r in rows) for label in hearing.THRESHOLDS},
            "events": [clean(e) for e in list(agent.bus.history)[first:] if e["kind"] in KEEP]}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cry", default="cry-04")
    parser.add_argument("--doorbell", default="doorbell-01")
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--out", default=str(REPO / "results/sounds"))
    parser.add_argument("--camera-seconds", type=int, default=0, help="then listen live to the Tapo camera, skill armed")
    parser.add_argument("--env-file", default="~/.parenting-agent.env")
    args = parser.parse_args(argv)
    sources = {s["id"]: s for s in json.loads(SOURCES.read_text())}
    entries = FixtureLog(FIXTURE).entries()
    case = next(c for c in cries.sample(cries.candidates(entries)) if c["truth"] == "hungry" and 7 <= c["at"].hour < 20)

    with tempfile.TemporaryDirectory() as tmp:
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": [],
                       "rhythm": {"source": "fixture", "fixture": str(FIXTURE)}})
        agent = build(config)
        ear_said = []
        router = Router(agent, config, presence=lambda: "home",
                        outputs={"ear": lambda text: ear_said.append(text) or {"played": False, "dry": True}})
        skill = ArmedSkill()
        started = time.monotonic()
        listener = hearing.PannsListener()
        load_s = round(time.monotonic() - started, 2)
        sounds = HouseSounds(agent, config, listener=listener, clock=lambda: case["at"])
        agent.plugins = [router, skill, sounds]
        clips = []
        for clip_id, armed in ((args.cry, False), (args.doorbell, True)):
            skill.skill = object() if armed else None
            src = sources[clip_id]
            samples = hearing.from_file(MEDIA / src["file"], 0, args.seconds, camera_channel=True)
            first = len(agent.bus.history)
            began = time.monotonic()
            hearing.play(sounds.listen(), samples)
            clips.append({"id": clip_id, "title": src["title"], "license": src["license"], "page": src["page"],
                          "split": src["split"], "seconds_of_audio": round(samples.size / hearing.RATE, 2),
                          "skill_armed": armed, "process_s": round(time.monotonic() - began, 2),
                          "events": [clean(e) for e in list(agent.bus.history)[first:] if e["kind"] in KEEP]})
        seconds_scored = len(sounds.ear.rows)
        camera = listen_camera(agent, sounds, skill, args) if args.camera_seconds else None
        sounds.stop()
        agent.close()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    reason = next(e for e in clips[0]["events"] if e["kind"] == "cry_reason")
    doorbell = [e for e in clips[1]["events"] if e["kind"] in ("sound", "routed")]
    run = {"generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "job": "licensed clips decoded on a pipe into memory, through the 8 kHz camera channel, PANNs labels, agent events",
           "audio_written": False, "listener": {**listener.info, "load_s": load_s, "thresholds": hearing.THRESHOLDS},
           "cry_heard_at": case["at"].isoformat(), "cry_true_reason": case["truth"], "cry_top_guess": reason["top"],
           "cry_text": reason["text"], "doorbell_channel": next((e["channel"] for e in doorbell if e["kind"] == "routed"), None),
           "ear_said": ear_said, "seconds_scored": seconds_scored, "clips": clips}
    (out / "run.json").write_text(json.dumps(run, indent=1, default=str) + "\n")
    if camera:
        (out / "camera.json").write_text(json.dumps(camera, indent=1, default=str) + "\n")
    evaluation = cry_eval(entries)
    (out / "cry-eval.json").write_text(json.dumps(evaluation, indent=1) + "\n")
    print(json.dumps({"cry": [(e["label"], e["phase"], e["seconds"], e["peak"]) for e in clips[0]["events"] if e["kind"] == "sound"],
                      "cry_reason": reason["text"], "truth": case["truth"],
                      "doorbell": [(e.get("label"), e.get("channel")) for e in doorbell],
                      "ten": f"{evaluation['ten']['right']} of {evaluation['ten']['of']}",
                      "week": f"{evaluation['whole_week']['right']} of {evaluation['whole_week']['of']}"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
