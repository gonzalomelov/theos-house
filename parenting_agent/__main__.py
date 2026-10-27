"""Run the persistent parenting agent.

    python -m parenting_agent --check                       # load everything, print skills and tools, exit
    python -m parenting_agent                               # run until stopped (Ctrl+C)
    python -m parenting_agent --config config/agent.json

The changing-table skill runs as a plug-in (parenting_agent.changing_table). parenting_agent.vision_run still runs a skill alone on a source.
"""
import argparse
import json
import signal
import threading

from .agent import build
from .agent import config as config_mod


def main(argv=None):
    parser = argparse.ArgumentParser(prog="parenting_agent")
    parser.add_argument("--config", default="config/agent.json")
    parser.add_argument("--check", action="store_true", help="load everything, print what was loaded, exit")
    args = parser.parse_args(argv)

    config = config_mod.load(args.config)
    agent = build(config)
    loaded = {
        "brain": {"provider": agent.brain.name, "model": agent.brain.model, "destination": agent.brain.destination},
        "plugins": [p.name for p in agent.plugins],
        "skills": [p.name for p in agent.plugins if getattr(p, "kind", "channel") == "skill"],
        "tools": agent.tools.names(),
        "allowed_tools": sorted(agent.tools.allowed),
        "baby_log": agent.baby_log.name,
        "data_dir": config["data_dir"],
    }
    print(json.dumps(loaded, indent=2), flush=True)
    if args.check:
        agent.close()
        return 0

    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    agent.start()
    for plugin in agent.plugins:
        plugin.start()
    agent.bus.publish("agent_started", brain=agent.brain.name, destination=agent.brain.destination)
    stopped.wait()
    for plugin in agent.plugins:
        plugin.stop()
    agent.stop()
    agent.bus.publish("agent_stopped")
    agent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
