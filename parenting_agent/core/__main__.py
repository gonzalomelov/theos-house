"""python -m parenting_agent.core [--port 8780]. PA_WORLD=mock is the default, nothing real moves. Binds to 127.0.0.1."""
import argparse
import asyncio
import os

import uvicorn

from . import server, sim_theo, sources
from .runtime import Core
from .settings import part


async def main(port):
    async with Core() as core:
        jobs = [asyncio.create_task(sources.forever(core, "schedule", sources.schedule)), asyncio.create_task(sources.forever(core, "wakes", sources.wakes))] if os.environ.get("PA_SCHEDULE", "1") == "1" else []
        if part("home") == "real":
            jobs.append(asyncio.create_task(sources.forever(core, "home_assistant", sources.home_assistant)))
        if os.environ.get("PA_SIM_THEO") == "1":
            jobs.append(asyncio.create_task(sources.forever(core, "sim_theo", sim_theo.run)))
        if os.environ.get("PA_TELEGRAM_POLL") == "1":
            jobs.append(asyncio.create_task(sources.forever(core, "telegram", sources.telegram)))
        if os.environ.get("PA_ECHO_PORT"):  # Home Assistant's one way in, through the relay, only /ask and /health
            echo = uvicorn.Server(uvicorn.Config(server.echo_app(core), host="0.0.0.0", port=int(os.environ["PA_ECHO_PORT"]), log_level="warning"))
            jobs.append(asyncio.create_task(echo.serve()))
        await uvicorn.Server(uvicorn.Config(server.app(core), host=os.environ.get("PA_BIND", "127.0.0.1"), port=port, log_level="warning")).serve()
        for job in jobs:
            job.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8780)
    asyncio.run(main(parser.parse_args().port))
