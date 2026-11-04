"""Can the car seat coach tell a belt routed right from a belt routed wrong? Real Muse Spark Open on Baseten, through
MuseSeatCheck.look, the coach's own call. Two reference stills come in as paths, stay in memory, and only text is written.

    python scripts/carseat_routing_eval.py --right A.webp --wrong B.webp --mask-wrong 55,875 --checks lap_guides,shoulder_guide,no_twist --runs 5 --out results/carseat/routing/before.json
    python scripts/carseat_routing_eval.py --right A.webp --wrong B.webp --mask-wrong 55,875 --checks belt_routing --runs 5 --variants 3 --out results/carseat/routing/after.json

The images are third-party, used for this test only, and never go in the repo. --mask-wrong keeps only rows top to bottom,
which takes out a burned-in caption and a player bar that would give the answer away.
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent.agent.config import load_env  # noqa: E402
from parenting_agent.carseat.muse_check import SYSTEM, MuseSeatCheck  # noqa: E402
from parenting_agent.muse_senses import MuseSenses, jpeg_data_url  # noqa: E402

ENV = Path.home() / "Engineering" / "gonza" / "meta-hackathon-2026" / ".env"
LONG_SIDE = 1280
# The route question that was measured for the coach, whole view, five calls thinking harder, four of five with none against for
# a pass. It didn't tell the two apart, so the coach asks the parent instead (results/carseat/routing/README.md).
ROUTE = "belt_routing"
ROUTE_SAMPLES, ROUTE_PASS, ROUTE_FAIL = 5, 4, 3
CAREFUL = {"reasoning_effort": "high", "timeout_s": 120, "max_tokens": 8000}
ROUTE_QUESTION = ("An infant carrier sits on a car's back seat, seen from the open door. Find the guide on the carrier's rim nearest "
                  "the camera, near the buckle and the legs. Which seat belt band goes through it: the one coming down from high up "
                  "on the door pillar, or one coming from low down, from the floor or the buckle?")
ROUTE_ANSWERS = {"band_from_low_down": "pass", "band_from_high_up": "fail"}


def prepared(path, rows=None):
    """The still, cut to the rows asked for, the same long side for both so size says nothing."""
    import cv2
    frame = cv2.imread(str(path))
    if frame is None:
        raise SystemExit(f"cannot read {path}")
    if rows:
        frame = frame[rows[0]:rows[1]]
    scale = LONG_SIDE / max(frame.shape[:2])
    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def rotated(frame, degrees):
    """A tilted head: rotated and cut to the middle, so no black corners give it away."""
    import cv2
    h, w = frame.shape[:2]
    return cv2.warpAffine(frame, cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.15), (w, h), flags=cv2.INTER_LINEAR)


def cropped(frame, top, bottom, left, right):
    h, w = frame.shape[:2]
    return frame[int(h * top):int(h * bottom), int(w * left):int(w * right)]


def lit(frame, gamma, gain=1.0):
    import numpy as np
    return np.clip(255.0 * (frame / 255.0) ** gamma * gain, 0, 255).astype("uint8")


def shaken(frame):
    """A moving head: a short smear along one direction."""
    import cv2
    import numpy as np
    kernel = np.zeros((9, 9))
    np.fill_diagonal(kernel, 1 / 9)
    return cv2.filter2D(frame, -1, kernel)


VARIANTS = {
    "crop_middle": lambda f: cropped(f, 0.08, 0.92, 0.08, 0.92),
    "crop_left": lambda f: cropped(f, 0.0, 1.0, 0.0, 0.8),
    "crop_right": lambda f: cropped(f, 0.0, 1.0, 0.2, 1.0),
    "tilt_plus_8": lambda f: rotated(f, 8),
    "tilt_minus_8": lambda f: rotated(f, -8),
    "dark": lambda f: lit(f, 1.6, 0.8),
    "bright": lambda f: lit(f, 0.7),
    "shake": shaken,
}


def route_look(senses, frame):
    values = [*ROUTE_ANSWERS, "cannot_see"]
    shape = {"type": "object", "additionalProperties": False, "required": ["look", "answer", "movement_under_1_inch"],
             "properties": {"look": {"type": "string"}, "answer": {"type": "string", "enum": values}, "movement_under_1_inch": {"type": "string", "enum": ["cannot_judge"]}}}
    image = jpeg_data_url(frame, 92)
    with ThreadPoolExecutor(ROUTE_SAMPLES) as pool:
        got = list(pool.map(lambda _: senses.ask(SYSTEM, ROUTE_QUESTION, shape, image_url=image), range(ROUTE_SAMPLES)))
    results = [ROUTE_ANSWERS.get(g["answer"].get("answer"), "unseen") for g in got]
    result = "pass" if results.count("pass") >= ROUTE_PASS and "fail" not in results else "fail" if results.count("fail") >= ROUTE_FAIL else "unseen"
    return {"result": result, "samples": results, "seen": [g["answer"].get("answer") for g in got],
            "seconds": max(g["seconds"] for g in got), "usd": round(sum(g["usd"] for g in got), 6)}


def one(check, frame, check_id):
    got = route_look(check["careful"], frame) if check_id == ROUTE else check["usual"].look(frame, check_id)
    return {key: got.get(key) for key in ("result", "samples", "seen", "seconds", "usd", "error")}


def tally(rows):
    out = {}
    for name in ("pass", "fail", "unseen", "none"):
        out[name] = sum((row["result"] or "none") == name for row in rows)
    calls = [s for row in rows for s in (row.get("samples") or [])]
    out["calls"] = {name: calls.count(name) for name in ("pass", "fail", "unseen")}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--right", required=True)
    parser.add_argument("--wrong", required=True)
    parser.add_argument("--mask-wrong", default="55,875", help="rows of the wrong still to keep: top,bottom")
    parser.add_argument("--mask-right")
    parser.add_argument("--checks", default="lap_guides,shoulder_guide,no_twist")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--samples", type=int, default=3, help="calls per look, as the agent config's default")
    parser.add_argument("--variants", type=int, default=0, help="runs of each crop, tilt and light change")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    load_env(str(ENV))
    rows = lambda text: tuple(int(v) for v in text.split(",")) if text else None
    stills = {"right": prepared(args.right, rows(args.mask_right)), "wrong": prepared(args.wrong, rows(args.mask_wrong))}
    check = {"usual": MuseSeatCheck(MuseSenses(), samples=args.samples), "careful": MuseSenses(CAREFUL)}
    jobs = []
    for state, frame in stills.items():
        for check_id in args.checks.split(","):
            jobs += [(state, check_id, "base", frame)] * args.runs
            for name, change in VARIANTS.items():
                jobs += [(state, check_id, name, change(frame))] * args.variants
    with ThreadPoolExecutor(args.workers) as pool:
        got = list(pool.map(lambda job: one(check, job[3], job[1]), jobs))
    report = {"runs": args.runs, "samples": args.samples, "variant_runs": args.variants, "usd": round(sum(g.get("usd") or 0 for g in got), 4),
              "results": {}, "looks": []}
    for (state, check_id, view, _), row in zip(jobs, got):
        report["looks"].append({"state": state, "check": check_id, "view": view, **row})
    for state in stills:
        for check_id in args.checks.split(","):
            mine = [row for (s, c, _, _), row in zip(jobs, got) if s == state and c == check_id]
            base = [row for (s, c, v, _), row in zip(jobs, got) if s == state and c == check_id and v == "base"]
            report["results"].setdefault(check_id, {})[state] = {"base": tally(base), "variants": tally([r for r in mine if r not in base]) if args.variants else None,
                                                                  "by_view": {name: tally([row for (s, c, v, _), row in zip(jobs, got) if s == state and c == check_id and v == name]) for name in VARIANTS} if args.variants else None}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"usd": report["usd"], "results": {c: {s: {"base": v["base"], "variants": v["variants"]} for s, v in r.items()} for c, r in report["results"].items()}}, indent=0))


if __name__ == "__main__":
    main()
