"""The persistent agent on the real home: Muse decides and the real dehumidifier plug moves, nothing else can. Channel and baby
log stay mock, so nobody gets a message. The plug goes back to off after each run. Also listens to Home Assistant's real WebSocket.
Run: HA_URL=... HA_MCP_TOKEN=... BASETEN_API_KEY=... PA_DB_URL=... python scripts/core_real_test.py [N] [results file]"""
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(PA_WORLD="mock", PA_HOME="real", PA_ALLOWED_DEVICES="Tapo P110 - Dehumidifier")
from parenting_agent.core import sources  # noqa: E402
from parenting_agent.core.runtime import Core  # noqa: E402
from parenting_agent.core.settings import Settings  # noqa: E402
from parenting_agent.house import HomeAssistant  # noqa: E402

logging.disable(logging.WARNING)
PLUG = "switch.study_tapo_p110_dehumidifier"
SENSOR = "sensor.nursery_climate_humidity"
WARMER = "switch.study_tapo_p110_bottle_warmer"


async def state(ha, entity):
    return (await asyncio.to_thread(ha._call, f"/api/states/{entity}"))["state"]


async def plug_off(ha):
    await asyncio.to_thread(ha.service, "switch.turn_off", PLUG)
    await asyncio.sleep(2)
    return await state(ha, PLUG)


class Recorder:
    """Stands in for the core: the listener's events are only written down, Muse is not called."""
    def __init__(self, settings):
        self.settings, self.seen, self.status = settings, [], []

    def publish(self, kind, **fields):
        self.status.append(fields)

    async def dispatch(self, type, payload, source=None, at=None):
        self.seen.append(payload)


async def main(n, path):
    settings = Settings(home="real-" + uuid.uuid4().hex[:8], mock_port=0, data_dir=str(Path(os.environ.get("PA_EVAL_DIR", "/tmp")) / "pa-core-real"))
    ha = HomeAssistant(settings.ha_url, settings.ha_token)
    results = {"warmer_before": await state(ha, WARMER), "runs": []}
    assert await plug_off(ha) == "off"
    for run in range(n):
        s = Settings(home=f"{settings.home}-{run}", mock_port=0, data_dir=settings.data_dir)
        async with Core(s) as core:
            reading = await state(ha, SENSOR)
            before = await state(ha, PLUG)
            _, done = await core.dispatch("state_changed", {"entity_id": SENSOR, "state": reading}, source="test")
            out = await done
            await asyncio.sleep(2)
            after = await state(ha, PLUG)
            calls = [(a["tool"], a["arguments"]) for a in await core.actions() if a["tool"].startswith("Hass")]
            # Same event again with the plug on, from a new process's point of view.
        async with Core(s) as core:
            event_id, done = await core.dispatch("state_changed", {"entity_id": SENSOR, "state": reading}, source="test")
            again = await done
            repeats = [a for a in await core.actions(limit=20) if a["tool"] == "HassTurnOn" and a["event_id"] == event_id]
            still = await state(ha, PLUG)
        off = await plug_off(ha)
        results["runs"].append({"reading": reading, "before": before, "after": after, "calls": calls, "outcome": out["outcome"], "after_restart": again["outcome"], "still": still, "returned": off, "repeats": len(repeats)})
        print(json.dumps(results["runs"][-1], ensure_ascii=False, default=str)[:600], flush=True)
    recorder = Recorder(settings)
    task = asyncio.create_task(sources.home_assistant(recorder, {SENSOR: 0.1, "sensor.nursery_climate_temperature": 0.1}))
    for _ in range(36):
        await asyncio.sleep(5)
        if recorder.seen:
            break
    task.cancel()
    results["websocket"] = {"connected": any(s.get("status") == "connected" for s in recorder.status), "events": recorder.seen[:3]}
    results["warmer_after"] = await state(ha, WARMER)
    results["plug_final"] = await state(ha, PLUG)
    print(json.dumps({k: results[k] for k in ("websocket", "warmer_before", "warmer_after", "plug_final")}, default=str))
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3, sys.argv[2] if len(sys.argv) > 2 else None))
