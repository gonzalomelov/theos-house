"""One live look through the dog-near-baby camera path (issue #109): Home Assistant camera proxy into memory, SAM 3.1,
the rule. Read only in Home Assistant. The frame is never written to disk and is dropped when the script ends.

    python scripts/dog_watch_live.py --env PATH/.env                 # one look, prints numbers only
    python scripts/dog_watch_live.py --env PATH/.env --test-alert    # also sends one test alert to TELEGRAM_CHAT_ID

Stops at the first 401 or 403 from Home Assistant (parenting_agent.house never retries a rejected token).
Hold the GPU lock (/tmp/pa-gpu.lock) while it runs.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent.bus import Bus  # noqa: E402
from parenting_agent.dog_watch import DEFAULTS, Alerter, Gate, camera_frame, decide, measure, prompts  # noqa: E402
from parenting_agent.house import HomeAssistant  # noqa: E402


def load_env(path):
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env")
    parser.add_argument("--camera", default=DEFAULTS["camera"])
    parser.add_argument("--test-alert", action="store_true")
    args = parser.parse_args()
    if args.env:
        load_env(args.env)
    cfg = {**DEFAULTS, "camera": args.camera}
    client = HomeAssistant(cfg["ha_url"], os.environ[cfg["ha_token_env"]])
    bus = Bus()
    events = []
    bus.subscribe(events.append)
    gate_sensors = {s: client.state(s) for s in cfg["gate_sensors"]}
    gate = Gate(client, cfg["gate_sensors"], cfg["snapshot_every_s"]).why()
    started = time.monotonic()
    frame = camera_frame(client, cfg["camera"])
    fetched = time.monotonic() - started
    from parenting_agent.carseat.sam3_masks import Sam3Masks
    sam = Sam3Masks({"confidence": 0.3})
    try:
        started = time.monotonic()
        found, sam_s = sam.masks(frame, prompts(cfg))
        m = measure(found, cfg)
        look_s = time.monotonic() - started
    finally:
        sam.close()
    out = {"camera": cfg["camera"], "frame_shape": list(frame.shape), "gate_sensors": gate_sensors, "gate": gate,
           "fetch_s": round(fetched, 3), "sam_s": round(sam_s, 3), "look_s": round(look_s, 3),
           "scores": {p: [round(s, 3) for s, _ in found.get(p, [])][:3] for p in prompts(cfg)},
           "measure": m, "verdict": decide(m, cfg)}
    del frame, found
    if args.test_alert:
        alert = Alerter({**cfg, "baby_name": "Theo (test, no dog, no baby yet)"}, bus, client)
        started = time.monotonic()
        out["test_alert_telegram"] = alert({})
        out["test_alert_s"] = round(time.monotonic() - started, 3)
        out["announce"] = [e for e in events if e["kind"] in ("house_dry", "house_done")][:1]
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
