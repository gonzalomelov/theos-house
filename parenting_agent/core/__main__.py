"""python -m parenting_agent.core [--port 8780]. PA_WORLD=mock is the default, nothing real moves. Binds to 127.0.0.1."""
import argparse
import asyncio
import os

import uvicorn

from . import server, sources
from .runtime import Core
from .settings import part


async def main(port):
    async with Core() as core:
        jobs = [asyncio.create_task(sources.schedule(core))] if os.environ.get("PA_SCHEDULE", "1") == "1" else []
        if part("home") == "real":
            jobs.append(asyncio.create_task(sources.home_assistant(core)))
        if os.environ.get("PA_TELEGRAM_POLL") == "1":
            jobs.append(asyncio.create_task(sources.telegram(core)))
        await uvicorn.Server(uvicorn.Config(server.app(core), host=os.environ.get("PA_BIND", "127.0.0.1"), port=port, log_level="warning")).serve()
        for job in jobs:
            job.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8780)
    asyncio.run(main(parser.parse_args().port))
