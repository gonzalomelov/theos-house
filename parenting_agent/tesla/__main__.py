"""Replay a trip with the baby on the simulated Tesla, through the real agent loop, offline.

    python -m parenting_agent.tesla                       # prints the conversation, writes results/tesla/demo.json
    python -m parenting_agent.tesla --out /tmp/demo.json

"We leave in 15", the cabin-ready proposal, the parent's yes, 15 simulated minutes of preconditioning, the recorded
(synthetic) drive, the car-nap question and the parent's yes. Every line says simulated: no real car is involved,
the baby log is a local file in a temporary folder.
"""
import argparse
import datetime
import json
import tempfile
from pathlib import Path

from ..agent import build
from ..agent import config as config_mod
from .car import Car
from .trips import CarTrips

SAMPLE = Path(__file__).resolve().parent / "samples" / "drive-2026-10-24.synthetic.json"
ROOT = Path(__file__).resolve().parents[2]


def run(sample=SAMPLE):
    recorded = json.loads(Path(sample).read_text())
    rows = recorded["rows"]
    with tempfile.TemporaryDirectory() as tmp:
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"},
                       "car": {"backend": "simulated", "parent_channel": "console"}})
        agent = build(config)
        transcript = []
        agent.bus.subscribe(lambda e: transcript.append({"who": "agent", "text": e["text"]}), ["reply"])
        start = datetime.datetime.fromisoformat(rows[0]["t"]) - datetime.timedelta(minutes=15)
        clock = {"now": start}
        car = Car(config["car"], agent.bus)
        plugin = CarTrips(agent, config, car=car, clock=lambda: clock["now"])

        def parent(text):
            transcript.append({"who": "parent", "text": text})
            agent.handle({"kind": "message", "channel": "console", "text": text})

        transcript.append({"who": "parent", "text": "we leave in 15"})
        agent.say("console", plugin.cabin_ready(leave_in_min=15))
        parent("yes")
        car.client.advance(15)
        for row in rows:
            clock["now"] = datetime.datetime.fromisoformat(row["t"])
            car.client.play(row)
            plugin.tick(clock["now"])
        parent("yes")
        naps = [e for e in agent.baby_log.entries("sleep")]
        commands = [{"service": s, "entity_id": e, "data": d} for s, e, d in car.client.calls]
        agent.close()
    return {"label": "SIMULATED Tesla Model 3 and a SYNTHETIC drive sample, no real car", "car": car.label,
            "drive_sample": recorded["label"], "transcript": transcript, "commands": commands, "naps_logged": naps}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "results" / "tesla" / "demo.json"))
    args = parser.parse_args()
    report = run()
    print(report["label"])
    for line in report["transcript"]:
        print(f"{line['who']:>6}: {line['text']}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
