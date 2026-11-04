"""The car seat coach on the new agent's whole path, on the mock home and the mock channel. "Agente, ayudame a instalar la silla
del auto" goes in as an event, real Muse starts the tool, the Mac's listener hears it on the core's stream, the coach runs with
SAM 3.1, each line comes back through POST /coach to the parent on the mock channel. The camera is a still: the
belt routed wrong, and once the parent says so and fixes it, routed right. Stills stay in memory, only the lines are written.

    PA_DB_URL=... python scripts/carseat_core_e2e.py --right A.webp --wrong B.webp --out results/carseat/routing/e2e.json
"""
import argparse
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["PA_WORLD"] = "mock"
os.environ["PA_MOCK_PORT"] = "0"

import uvicorn  # noqa: E402
from carseat_routing_eval import ENV, prepared  # noqa: E402
from coach_listener import Direct, Listener  # noqa: E402

from parenting_agent.agent.config import load_env  # noqa: E402
from parenting_agent.carseat.coach import LINES  # noqa: E402
from parenting_agent.core import server  # noqa: E402
from parenting_agent.core.runtime import Core  # noqa: E402
from parenting_agent.core.settings import Settings  # noqa: E402

ES = LINES["es"]
ANSWERS = {"harness_pinch": "no, no sobra nada", "car_position": "sí, atrás", "buckle": "sí, hizo clic", "tension": "sí, quedó tenso", "belt_path_movement": "sí, menos de dos centímetros"}


class Stills:
    """The head camera: the newest frame is whatever the scene shows now."""
    started = None
    stopped = False

    def __init__(self, frame):
        self.frame, self.seq, self.at = frame, 0, 0.0

    def latest(self, after):
        now = time.monotonic()
        if now - self.at < 0.25 and after >= self.seq:
            return None
        self.seq, self.at = self.seq + 1, now
        return self.frame, self.seq, float(self.seq)

    def close(self):
        self.stopped = True


def closeup(frame):
    """The phone brought near the middle of the view."""
    h, w = frame.shape[:2]
    return frame[h // 4:h - h // 4, w // 4:w - w // 4]


async def scene(args):
    load_env(str(ENV))
    wrong, right = prepared(args.wrong, tuple(int(v) for v in args.mask_wrong.split(","))), prepared(args.right)
    camera = Stills(wrong)
    port = (lambda s: (s.bind(("127.0.0.1", 0)), s.getsockname()[1], s.close())[1])(socket.socket())
    said = []
    async with Core(Settings(home="e2e-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=tempfile.mkdtemp())) as core:
        web = uvicorn.Server(uvicorn.Config(server.app(core), host="127.0.0.1", port=port, log_level="error"))
        task = asyncio.create_task(web.serve())
        while not web.started:
            await asyncio.sleep(0.05)
        link = Direct(f"http://127.0.0.1:{port}")

        def make_vision():
            if args.no_sam:
                from unittest import mock
                return mock.Mock(masks=lambda frame, prompts: ({}, 0.0), close=lambda: None)
            from parenting_agent.carseat.sam3_masks import Sam3Masks
            return Sam3Masks(listener.cfg.get("sam3"))
        listener = Listener(link, "stills", make_vision=make_vision, make_source=lambda: camera)
        listener.cfg = {**listener.cfg, "closeup_timeout_s": 8.0, "step_timeout_s": 6.0, "ready_timeout_s": 90.0}
        threading.Thread(target=listener.follow, daemon=True).start()
        await asyncio.sleep(1)

        async def parent(text):
            said.append({"who": "gonza", "text": text})
            await core.dispatch("message", {"from": "gonza", "channel": "the glasses", "text": text})
        await parent("Agente, ayudame a instalar la silla del auto")
        seen, deadline, fixed = 0, time.monotonic() + args.limit, False
        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            for line in listener.lines[seen:]:
                seen += 1
                text, step = line["text"], line["step"]
                said.append({"who": "coach", "step": step, "text": text})
                if text == ES["routing"]:
                    await parent("no, lo tengo al revés")
                elif text == ES["routing_fix"]:
                    camera.frame, fixed = right, True
                    await parent("listo, ya está")
                elif text == ES["routing_again"]:
                    await parent("sí, ahora sí")
                elif text.startswith("Acercá el teléfono"):
                    camera.frame = closeup(right if fixed else wrong)
                elif text.rstrip().endswith(("Decime listo cuando termines.", "Decime listo cuando estés.")):
                    camera.frame = right if fixed else wrong
                    await parent("listo, ya está")
                elif step in ANSWERS and text.rstrip().endswith(("sí o no.", "no podés.")):
                    await parent(ANSWERS[step])
            if listener.results is not None:
                break
        await asyncio.sleep(3)
        listener.coach and listener.coach.stop()
        report = {"said": said, "results": listener.results, "channel": [dict(m) for m in core.channel.sent],
                  "tools": [{"tool": a["tool"], "arguments": a.get("arguments")} for a in await core.actions() if a["tool"] not in ("coach_line",)]}
        web.should_exit = True
        await task
        await core.forget()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--right", required=True)
    parser.add_argument("--wrong", required=True)
    parser.add_argument("--mask-wrong", default="55,875")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=float, default=420.0)
    parser.add_argument("--no-sam", action="store_true", help="no SAM 3.1: the guide steps read as not seen")
    args = parser.parse_args()
    report = asyncio.run(scene(args))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n")
    for line in report["said"]:
        print(f"{line['who']}[{line.get('step', '')}]: {line['text']}")
    print("channel extras:", [m["text"] for m in report["channel"] if m["text"] not in [s["text"] for s in report["said"]]])
    print("routing:", (report["results"] or {}).get("belt_routing"))


if __name__ == "__main__":
    main()
