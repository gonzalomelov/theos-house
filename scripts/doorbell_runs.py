"""The full day's doorbell step N times, with Muse as the brain, after the morning bottle, on a local log.

    python scripts/doorbell_runs.py . 5 > results/redteam/round2/doorbell-muse.jsonl

Each run is a fresh agent with config/agent.muse-baseten.json, the full day's dry house tools and no Baby Buddy, so
nothing is written outside a temp folder. About 4 to 5 Muse calls and 2 US cents a run.
"""
import json, sys, tempfile
sys.path.insert(0, sys.argv[1])
from parenting_agent.agent import build, config as config_mod
from parenting_agent.fullday import day as day_mod

out = []
for run in range(int(sys.argv[2]) if len(sys.argv) > 2 else 5):
    config = config_mod.load(sys.argv[1] + "/config/agent.muse-baseten.json")
    config_mod.load_env(config["env_file"])
    config = dict(config, data_dir=tempfile.mkdtemp(prefix="door-"), plugins=[], baby_log={"provider": "local"},
                  allowed_tools=sorted(set(config["allowed_tools"]) | set(day_mod.HOUSE_TOOLS)))
    agent = build(config)
    agent.plugins = [day_mod.HouseTools(agent, config)]
    agent.start()
    day = day_mod.Day(agent, {}, "/nonexistent", tempfile.mkdtemp(), video=False)
    try:
        day.ask("ear", "bottle, 120 ml")
        step = day.doorbell()
        guards = [e for e in agent.bus.history if e["kind"] == "guard"]
        calls = [e for e in agent.bus.history if e["kind"] == "brain_call"]
        row = {"run": run + 1, "passed": step["passed"], "action": step["action"], "reply": step["reply"],
               "tools": step["evidence"]["tools"], "guards": [g["status"] for g in guards],
               "brain_calls": len(calls), "usd": round(sum(c.get("usd") or 0 for c in calls), 4)}
    finally:
        agent.stop(); agent.close()
    print(json.dumps(row, ensure_ascii=False), flush=True)
    out.append(row)
print(f"{sum(r['passed'] for r in out)} of {len(out)} passed")
