"""The video scene "Let me sleep": Ceci says it out loud to the Echo. Real Alexa skill handler, real /ask, real gate and danger screen, real Muse on Baseten, mock home and mock channel.
Nothing reaches a phone or a speaker. What Amazon's ear does to the words is not here: the slot's text is written by hand, lower case with no punctuation as ANY_TEXT brings it, and that part stays unproven.
Tuned on, not held-out. Results in results/echo-sleep/.

    PA_DB_URL=... BASETEN_API_KEY=... python scripts/echo_sleep_eval.py scene 10 out.json es
    ... python scripts/echo_sleep_eval.py probes 2 out.json es     every probe, or a probe's name for one of them
"""
import asyncio
import datetime
import importlib.util
import json
import logging
import os
import re
import socket
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["PA_WORLD"] = "mock"
os.environ["PA_MOCK_PORT"] = "0"
os.environ.pop("PA_REHEARSAL", None)
TOKEN = uuid.uuid4().hex
os.environ.update({"PARENTING_AGENT_VOICE_TOKEN": TOKEN, "PA_BEARER_TOKEN": TOKEN, "CF_ACCESS_CLIENT_ID": "id", "CF_ACCESS_CLIENT_SECRET": "secret"})
import uvicorn  # noqa: E402

from parenting_agent.core import server, tools  # noqa: E402
from parenting_agent.core.runtime import Core, night_of, on_duty  # noqa: E402
from parenting_agent.core.settings import Settings  # noqa: E402
from parenting_agent.simulator.scenes import LOG  # noqa: E402

logging.disable(logging.WARNING)
SKILL = Path(os.environ.get("PA_ALEXA_LAMBDA", ROOT.parent / "alexa-muse-baby/lambda/lambda_function.py"))
spec = importlib.util.spec_from_file_location("lambda_function", SKILL)
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)
EVAL_DIR = Path(os.environ.get("PA_EVAL_DIR", tempfile.gettempdir())) / "pa-echo"
EVENING = "2026-12-15T21:45:00-03:00"  # Ceci's night on the rota, as in the simulator's scene
SCENE = {"es": "soy ceci esta noche necesito dormir se puede encargar gonza", "en": "this is ceci i need to sleep tonight can gonza take the night"}
# (name, words per language, the moment, should the night move to gonza). The ear's spellings of her name are guesses at what Amazon might write, none has been seen.
PROBES = [("day", SCENE, "2026-12-15T15:00:00-03:00", True),
          ("after 22", SCENE, "2026-12-15T23:10:00-03:00", True),
          ("name spelled cecy", {"es": "soy cecy esta noche necesito dormir se puede encargar gonza", "en": "this is cecy i need to sleep tonight can gonza take the night"}, EVENING, True),
          ("name spelled sesi", {"es": "soy sesi esta noche necesito dormir se puede encargar gonza", "en": "this is sessi i need to sleep tonight can gonza take the night"}, EVENING, True),
          ("gonza spelled gonzo", {"es": "soy ceci esta noche necesito dormir se puede encargar gonzo", "en": "this is ceci i need to sleep tonight can gonzo take the night"}, EVENING, True),
          ("already his night", SCENE, "2026-12-16T21:45:00-03:00", False),
          ("no name at all", {"es": "esta noche necesito dormir", "en": "i need to sleep tonight"}, EVENING, False),
          ("grandma asks", {"es": "cuando comio theo por ultima vez", "en": "when did theo last eat"}, "2026-12-16T11:00:00-03:00", False)]
SPEAKABLE_MAX = 200
NOT_SPOKEN = re.compile(r"[*_#`\n]|https?:|\d{4}-\d{2}-\d{2}")


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def turn(words, locale, request_id, attributes):
    event = {"session": {"new": not attributes, "attributes": attributes},
             "request": {"type": "IntentRequest", "requestId": request_id, "locale": locale, "intent": {"name": "ChatIntent", "slots": {"query": {"name": "query", "value": words}}}}}
    began = time.monotonic()
    out = skill.lambda_handler(event, None)
    return {"said": out["response"]["outputSpeech"]["text"], "seconds": round(time.monotonic() - began, 1), "attributes": out.get("sessionAttributes") or {}}


async def speak(words, lang):
    """What the Echo says: the first turn, then "de nuevo" after a holding line, the way a person would. The skill's own 6 s wait applies."""
    locale = "es-US" if lang == "es" else "en-US"
    again = "de nuevo" if lang == "es" else "again"
    turns = [await asyncio.to_thread(turn, words, locale, "amzn1.echo-api.request." + uuid.uuid4().hex, {})]
    while turns[-1]["attributes"].get("pending") and len(turns) < 6:
        await asyncio.sleep(4)
        turns.append(await asyncio.to_thread(turn, again, locale, "amzn1.echo-api.request." + uuid.uuid4().hex, turns[-1]["attributes"]))
    return [{k: t[k] for k in ("said", "seconds")} for t in turns], turns[-1]


async def run(name, words, at, lang, cry, moves=True):
    moment = datetime.datetime.fromisoformat(at)
    settings = Settings(home="echo-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=str(EVAL_DIR / uuid.uuid4().hex[:8]), lang=lang)
    async with Core(settings) as core:
        port = free_port()
        web = uvicorn.Server(uvicorn.Config(server.echo_app(core), host="127.0.0.1", port=port, log_level="error"))
        serving = asyncio.create_task(web.serve())
        while not web.started:
            await asyncio.sleep(0.05)
        skill.ASK_URL = f"http://127.0.0.1:{port}/ask"
        dispatch = core.dispatch

        def at_moment(kind, payload=None, source="simulator", at=None, ask=False):
            return dispatch(kind, payload, source, at or moment.isoformat(), ask)
        core.dispatch = at_moment
        try:
            core.moment = moment - datetime.timedelta(minutes=30)
            for when, kind, details in LOG:
                core.log.add(kind, details, when)
            spoken, last = await speak(words, lang)
            for _ in range(120):  # what started keeps running after the skill stops waiting
                events = await core.events()
                if events and all(e["status"] not in ("queued", "running") for e in events) and core.queue.empty():
                    break
                await asyncio.sleep(1)
            events = await core.events()
            asked = [e for e in events if e["type"] == "message"]
            facts = await tools.facts(core.store, settings.home)
            sent = [{k: m.get(k) for k in ("to", "text", "quiet") if m.get(k) is not None} for m in core.channel.sent]
            actions = await core.actions(asked[-1]["id"]) if asked else []
            result = {"name": name, "lang": lang, "words": words, "moment": at, "spoken": spoken, "first_line_seconds": spoken[0]["seconds"], "holding_turns": len(spoken) - 1, "message_events": len(asked),
                      "status": [e["status"] for e in asked], "outcome": [e["outcome"] for e in asked], "duty": facts.get(f"on_duty_{night_of(moment)}"), "sent": sent,
                      "tools": [(a["tool"], str(a.get("result"))[:140]) for a in actions]}
            answer = spoken[-1]["said"]
            result["told"] = sorted({m["to"] for m in sent if m["to"] in tools.PARENTS})
            result["speakable"] = 0 < len(answer) <= SPEAKABLE_MAX and not NOT_SPOKEN.search(answer) and not last["attributes"].get("pending")
            result["duty_moved"] = result["duty"] == "gonza"
            result["both_told"] = result["told"] == ["ceci", "gonza"]
            result["once"] = len(asked) == 1 and asked[0]["status"] == "done"
            result["no_holding"] = not result["holding_turns"]
            if cry:
                before = len(core.channel.sent)
                _, done = await dispatch("sound", {"kind": "baby crying", "room": "Theo's room"}, at="2026-12-16T02:50:00-03:00")
                await done
                night = core.channel.sent[before:]
                result["cry"] = [{k: m.get(k) for k in ("to", "text", "quiet") if m.get(k) is not None} for m in night]
                result["cry_reached_gonza_only"] = [m["to"] for m in night if m["to"] in tools.PARENTS and not m.get("quiet")][:1] == ["gonza"] and not any(m["to"] == "ceci" for m in night)
            else:
                result["cry_reached_gonza_only"] = None
            if moves:
                result["passed"] = bool(result["duty_moved"] and result["both_told"] and result["speakable"] and result["once"] and result["cry_reached_gonza_only"] is not False)
            else:  # nothing to move: an answer at the Echo, and the night stays with whoever the rota gives it to
                result["passed"] = bool(result["speakable"] and result["once"] and result["duty"] in (None, on_duty(moment)))
            return result
        finally:
            web.should_exit = True
            await serving
            core.dispatch = dispatch
            await core.forget()


async def main(group, runs, path, lang):
    jobs = [("scene", SCENE[lang], EVENING, True, True)] if group == "scene" else [(n, w[lang], at, False, moves) for n, w, at, moves in PROBES if group == "probes" or n == group]
    done = []
    for name, words, at, cry, moves in jobs:
        for _ in range(runs):
            try:
                result = await run(name, words, at, lang, cry, moves)
            except Exception as failure:
                result = {"name": name, "words": words, "passed": False, "exception": f"{type(failure).__name__}: {str(failure)[:300]}"}
            print(name, "PASS" if result["passed"] else "FAIL", json.dumps(result, ensure_ascii=False, default=str)[:1800], flush=True)
            done.append(result)
    by_name = {}
    for result in done:
        by_name.setdefault(result["name"], []).append(result)
    summary = {name: f"{sum(r['passed'] for r in rows)}/{len(rows)}" for name, rows in by_name.items()}
    keys = ("duty_moved", "both_told", "speakable", "once", "no_holding")
    print(summary, {k: sum(bool(r.get(k)) for r in done) for k in keys}, f"total {sum(r['passed'] for r in done)} of {len(done)}", flush=True)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(by_name, ensure_ascii=False, indent=1, default=str))


asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "es"))
