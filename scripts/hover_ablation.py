"""Touch versus hover ablation: the reflex alone against the reflex plus SAM 3.1, on the same labelled moments.

    python scripts/hover_ablation.py --set ~/Engineering/gonza/meta-hackathon-2026-synthetic/hover/set \
        --split test --confirm none --out runs/hover/test-none.json

Each moment (see scripts/hover_render.py and labels.json in the set) streams in real time through a fresh skill:
the MediaPipe reflex, the alarm, and the confirm stage with the skill's provider, or none. House actions and
the baby log are off. A hover moment must speak "hand" (no hand touches the baby) within 2.5 s of the cue. A touch
moment must stay silent from start to end. Latency is wall time from the cue on screen to the spoken word.
--confirm-wait-s sets alarm.confirm_wait_s, the bounded wait for SAM 3.1 on a near (ambiguous) reflex reading.
--wait-without-confirm is the control: the same wait with the reflex alone, so the wait is not credited to SAM 3.1.
--lift on|off overrides lift.enabled, the lift check that measures how far a hand the reflex reads on rose above
the baby (parenting_agent/lift.py). Per moment it reports the median seconds per frame of the reflex and the lift check.
"""
import argparse
import copy
import datetime
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent import config as config_mod  # noqa: E402
from parenting_agent import confirm as confirm_mod  # noqa: E402
from parenting_agent.bus import Bus  # noqa: E402
from parenting_agent.reflex import MediaPipeReflex  # noqa: E402
from parenting_agent.skill import Skill, watch  # noqa: E402
from parenting_agent.sources import VideoSource  # noqa: E402

SKILLS = {"changing_table": "skills/changing-table.json", "bath": "skills/bath.json"}
SPEAK_WITHIN_S, EARLY_TOLERANCE_S = 2.5, 0.25


class Shared:
    """One SAM 3.1 worker for every moment: the skill's close must not stop it."""

    def __init__(self, detector):
        self.detector, self.name = detector, detector.name

    @property
    def masks(self):
        return self.detector.masks

    def judge(self, frame_bgr):
        started = time.monotonic()
        verdict = self.detector.judge(frame_bgr)
        self.last_seconds = time.monotonic() - started
        return verdict


def skill_config(scene, confirm_wait_s, lift=None, lift_cfg=None, alarm_cfg=None):
    cfg = copy.deepcopy(config_mod.load(SKILLS[scene]))
    cfg["alarm"].update(alarm_cfg or {})
    if lift is not None:
        cfg.setdefault("lift", {})["enabled"] = lift == "on"
    cfg.setdefault("lift", {}).update(lift_cfg or {})
    cfg["house"] = {"allowed": {}, "on_armed": [], "on_voice": [], "on_closed": []}
    cfg["tracking"] = {"provider": "none", "on_closed": None}
    if confirm_wait_s is not None:
        cfg["alarm"]["confirm_wait_s"] = confirm_wait_s
    return cfg


def run_moment(moment, clip, cfg, reflex, detector, wait_without_confirm=False):
    bus = Bus()
    skill = Skill(cfg, bus, reflex, confirm_detector=detector or confirm_mod.NoConfirm())
    if wait_without_confirm:  # control: the same longer hold on a near reading, with nobody to answer it
        skill.alarm.waits_for_confirm = cfg["alarm"].get("confirm_wait_s") is not None
    source = VideoSource(str(clip), loops=False)
    while source.started is None and not source.stopped:
        time.sleep(0.005)
    heard = []
    bus.subscribe(lambda e: heard.append({"stream_s": e["stream_s"], "mono": time.monotonic(), "reason": e["reason"],
                                          "episode": e["episode"]}), ["voice"])
    skill.arm()
    worker = threading.Thread(target=watch, args=(skill, source), daemon=True)
    worker.start()
    worker.join()
    skill.close()
    events = list(bus.history)
    frames = [e for e in events if e["kind"] == "frame"]
    lift_times = sorted(e["lift_s"] for e in frames if e.get("lift_s") is not None)
    reflex_times = sorted(e["seconds"] for e in frames)
    cue_mono = source.started + moment["cue_s"]
    if moment["kind"] == "hover":
        early = [v for v in heard if v["stream_s"] < moment["cue_s"] - EARLY_TOLERANCE_S]
        late = [v for v in heard if v["stream_s"] >= moment["cue_s"] - EARLY_TOLERANCE_S]
        latency = round(late[0]["mono"] - cue_mono, 3) if late else None
        spoken = latency is not None and latency <= SPEAK_WITHIN_S
    else:
        early, late, latency, spoken = heard, [], None, bool(heard)
    raised = {e["episode"]: e["stream_s"] for e in events if e["kind"] == "alarm" and e.get("action") == "raise"}
    # strict: the voice that counts belongs to an alarm raised after the cue, not one left over from the rest
    strict = spoken and moment["kind"] == "hover" and raised.get(late[0]["episode"], -1) >= moment["cue_s"] - EARLY_TOLERANCE_S
    return {
        "id": moment["id"], "scene": moment["scene"], "kind": moment["kind"], "lift_cm": moment.get("lift_cm"),
        "held": moment.get("held"), "object": moment.get("object"), "hands": moment.get("hands"),
        "confirm_s": confirm_seconds(events),
        "spoken": spoken, "spoken_strict": strict, "latency_s": latency, "voices_before_cue": len(early) if moment["kind"] == "hover" else None,
        "voice_reasons": [v["reason"] for v in heard],
        "chimes": sum(1 for e in events if e["kind"] == "chime"),
        "cancels": sum(1 for e in events if e["kind"] == "alarm" and e.get("action") == "cancel"),
        "confirms": [e["verdict"] for e in events if e["kind"] == "confirm"],
        "reflex": "".join("h" if e.get("held") == "on" else {"on": "1", "off": "0", "unknown": "?", "near": "~", "lifted": "^"}.get(e["state"], "x")
                          for e in frames),
        "held_looks": [e["verdict"] for e in events if e["kind"] == "confirm" and any(
            r["kind"] == "confirm_request" and r.get("check") == "held" and r["episode"] == e["episode"] for r in events)],
        "max_lift_cm_after_cue": max((e["lift_cm"] for e in frames if e.get("lift_cm") is not None
                                      and e["stream_s"] >= moment["cue_s"]), default=None),
        "frames": len(frames),
        "lift_series": [[round(e["stream_s"] - moment["cue_s"], 2), e.get("lift_cm")] for e in frames],
        "reflex_s_median": reflex_times[len(reflex_times) // 2] if reflex_times else None,
        "lift_s_median": lift_times[len(lift_times) // 2] if lift_times else None,
    }


def confirm_seconds(events):
    """Request to answer of each SAM 3.1 confirm, the wait behind a running anchor included."""
    asked, out = [], []
    for e in events:
        if e["kind"] == "confirm_request":
            asked.append(e["t"])
        elif e["kind"] in ("confirm", "confirm_error") and asked:
            out.append(round(e["t"] - asked.pop(0), 3))
    return out


def summarize(rows):
    hover = [r for r in rows if r["kind"] == "hover"]
    touch = [r for r in rows if r["kind"] == "touch"]
    lat = sorted(r["latency_s"] for r in hover if r["spoken"])
    return {
        "hover_moments": len(hover),
        "hover_spoken_within_2_5_s": sum(r["spoken"] for r in hover),
        "hover_missed": sum(not r["spoken"] for r in hover),
        "hover_spoken_strict": sum(bool(r.get("spoken_strict")) for r in hover),
        "hovers_with_a_voice_during_the_rest": sum(1 for r in hover if r["voices_before_cue"]),
        "touch_moments": len(touch),
        "touch_false_voices": sum(r["spoken"] for r in touch),
        "touch_chimes": sum(r["chimes"] for r in touch),
        "hover_voices_before_cue": sum(r["voices_before_cue"] or 0 for r in hover),
        "cancels": sum(r["cancels"] for r in rows),
        "latency_median_s": lat[len(lat) // 2] if lat else None,
        "latency_max_s": lat[-1] if lat else None,
        "confirm_s_median": percentile([v for r in rows for v in r.get("confirm_s", [])], 0.5),
        "confirm_s_p90": percentile([v for r in rows for v in r.get("confirm_s", [])], 0.9),
        "lift_s_median_of_moments": median([r["lift_s_median"] for r in rows if r["lift_s_median"] is not None]),
        "reflex_s_median_of_moments": median([r["reflex_s_median"] for r in rows if r["reflex_s_median"] is not None]),
    }


def percentile(values, q):
    values = sorted(values)
    return values[min(int(len(values) * q), len(values) - 1)] if values else None


def median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "test"], default=None)
    parser.add_argument("--confirm", choices=["none", "sam3_local"], required=True)
    parser.add_argument("--confirm-wait-s", type=float, default=None)
    parser.add_argument("--wait-without-confirm", action="store_true", help="control for --confirm none")
    parser.add_argument("--lift", choices=["on", "off"], default=None, help="override lift.enabled")
    parser.add_argument("--lift-cfg", type=json.loads, default=None, help="JSON merged into the lift config, for dev tuning")
    parser.add_argument("--alarm-cfg", type=json.loads, default=None, help="JSON merged into the alarm config")
    parser.add_argument("--confirm-cfg", type=json.loads, default=None, help="JSON merged into the SAM 3.1 confirm config")
    parser.add_argument("--splits", default=None, help="comma separated, overrides --split (the wave 2 dev set is dev,test)")
    parser.add_argument("--only", default=None, help="comma separated moment ids")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    root = args.set.expanduser()
    labels = json.loads((root / "labels.json").read_text())["moments"]
    splits = (args.splits or args.split).split(",")
    moments = [m for m in labels if m["split"] in splits]
    if args.only:
        moments = [m for m in moments if m["id"] in args.only.split(",")]
    base = config_mod.load(SKILLS["changing_table"])
    reflex = MediaPipeReflex(base["contact"])
    detector = Shared(confirm_mod.build({**base["confirm"], **(args.confirm_cfg or {})})) if args.confirm == "sam3_local" else None
    rows = []
    try:
        for moment in moments:
            cfg = skill_config(moment["scene"], args.confirm_wait_s, args.lift, args.lift_cfg, args.alarm_cfg)
            rows.append(run_moment(moment, root / f"{moment['id']}.mp4", cfg, reflex, detector, args.wait_without_confirm))
            print(json.dumps({k: rows[-1][k] for k in ("id", "spoken", "latency_s", "chimes", "cancels", "confirms",
                                                       "max_lift_cm_after_cue", "lift_s_median")}), flush=True)
    finally:
        if detector:
            detector.detector.close()
    result = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "split": ",".join(splits), "confirm": args.confirm, "wait_without_confirm": args.wait_without_confirm,
        "lift": {scene: skill_config(scene, args.confirm_wait_s, args.lift, args.lift_cfg).get("lift") for scene in SKILLS},
        "alarm": {k: v for k, v in skill_config("changing_table", args.confirm_wait_s, alarm_cfg=args.alarm_cfg)["alarm"].items()
                  if k != "voice_text"},
        "confirm_cfg": args.confirm_cfg,
        "summary": summarize(rows),
        "by_scene": {scene: summarize([r for r in rows if r["scene"] == scene]) for scene in SKILLS},
        "moments": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
