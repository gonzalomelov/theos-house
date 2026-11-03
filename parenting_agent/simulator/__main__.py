"""python -m parenting_agent.simulator [--port 8781]. Always mock: real-world settings and tokens are removed before anything loads."""
import argparse
import logging
import os

for name in list(os.environ):
    if name.startswith(("HA_", "TELEGRAM", "BABYBUDDY")) or name in ("PA_HOME", "PA_CHANNEL", "PA_LOG"):
        del os.environ[name]
os.environ["PA_WORLD"] = "mock"

import uvicorn  # noqa: E402

from . import gateway  # noqa: E402

if __name__ == "__main__":
    for noisy in ("httpx", "mcp"):  # one line per tool call otherwise
        logging.getLogger(noisy).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8781)
    port = parser.parse_args().port
    uvicorn.run(gateway.app(), host=os.environ.get("PA_BIND", "127.0.0.1"), port=port, log_level="warning")
