"""The jobs moved to Muse, against real Muse on Baseten, on the mock home, N runs of each case, each from a fresh thread.
Which cases were tuned on and which were not is in results/core-jobs/CASES.md. The word "held" runs the held-out cases.
Run: PA_DB_URL=... BASETEN_API_KEY=... python scripts/core_jobs_eval.py [N] [results file] [case words | held]"""
import asyncio
import datetime
import json
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PA_WORLD"] = "mock"
os.environ["PA_MOCK_PORT"] = "0"
from parenting_agent.core.runtime import Core, on_duty  # noqa: E402
from parenting_agent.core.settings import Settings  # noqa: E402

logging.disable(logging.WARNING)
WARMER = "switch.study_tapo_p110_bottle_warmer"
# A night the rota gives Gonza, and its morning.
NIGHT = next(datetime.datetime.fromisoformat(f"2026-11-{d:02d}T03:12:00-03:00") for d in range(4, 9) if on_duty(datetime.datetime.fromisoformat(f"2026-11-{d:02d}T03:12:00-03:00")) == "gonza")
MORNING = NIGHT.replace(hour=7, minute=30)
EVENING = (NIGHT - datetime.timedelta(days=1)).replace(hour=21, minute=30)


def fresh():
    return Settings(home="jobs-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=str(Path(os.environ.get("PA_EVAL_DIR", "/tmp")) / "pa-core-jobs" / uuid.uuid4().hex[:8]))


def seed_feeds(core, last, gap_h=3, n=5, ml=90):
    core.moment = last + datetime.timedelta(minutes=1)
    for i in range(n - 1, -1, -1):
        core.log.add("feeding", {"amount_ml": ml, "method": "bottle"}, (last - datetime.timedelta(hours=gap_h * i)).isoformat())


async def send(core, type, payload, at, **kw):
    _, done = await core.dispatch(type, payload, at=at.isoformat(), **kw)
    return await done


def sent(core, to=None):
    return [m for m in core.channel.sent if to is None or m["to"] == to]


async def morning():
    """After a night with feeds, each parent gets one message, written for them."""
    async with Core(fresh()) as core:
        seed_feeds(core, NIGHT.replace(hour=3, minute=0))
        core.log.add("diaper", {"type": "wet"}, NIGHT.replace(hour=3, minute=10).isoformat())
        await send(core, "schedule", {"name": "morning"}, MORNING)
        g, c = sent(core, "gonza"), sent(core, "ceci")
        tonight, last = on_duty(MORNING), on_duty(NIGHT)
        wrong = f"le toca a {last.capitalize()}" in " ".join(m["text"] for m in core.channel.sent)
        return len(g) == 1 and len(c) == 1 and g[0]["text"] != c[0]["text"] and not wrong, {"tonight": tonight, "last": last, "sent": core.channel.sent}


async def voice_note():
    """A voice note at 3:20 about a feed at 3: logged at 3, 90 ml, answered to the one who sent it."""
    async with Core(fresh()) as core:
        await send(core, "message", {"from": "gonza", "channel": "a voice note", "text": "Le di 90 ml de mamadera a las 3"}, NIGHT.replace(minute=20))
        feeds = core.log.entries("feeding")
        right = len(feeds) == 1 and feeds[0]["details"].get("amount_ml") == 90 and "T03:00" in feeds[0]["ts"]
        return right and sent(core, "gonza") and not sent(core, "ceci"), {"feeds": feeds, "sent": core.channel.sent}


async def echo_question():
    """Grandma at the Echo: the answer comes from the log, it is spoken, nobody's phone lights up."""
    async with Core(fresh()) as core:
        at = NIGHT.replace(hour=11, minute=0)
        seed_feeds(core, NIGHT.replace(hour=10, minute=55))
        out = await send(core, "message", {"from": "someone in the kitchen, you can't tell who", "channel": "the kitchen Echo", "text": "cuándo comió Theo por última vez?"}, at, ask=True)
        said = " ".join(out.get("said", []))
        return any(w in said for w in ("10:55", "10 y 55", "diez y cincuenta y cinco")) and not sent(core, "gonza") and not sent(core, "ceci"), {"said": out.get("said"), "sent": core.channel.sent}


async def car_seat():
    """The coach starts for the parent asking, and Muse writes no steps of its own."""
    async with Core(fresh()) as core:
        at = NIGHT.replace(hour=11, minute=0)
        await send(core, "message", {"from": "gonza", "channel": "the glasses", "text": "Agente, ayudame a instalar la silla del auto"}, at)
        calls = [a for a in await core.actions() if a["tool"] == "start_car_seat_coach"]
        text = " ".join(m["text"] for m in core.channel.sent)
        steps = any(w in text.lower() for w in ("cinturón", "base", "anclaje", "isofix", "paso 1", "ajust"))
        return len(calls) == 1 and calls[0]["arguments"].get("parent") == "gonza" and not steps and not sent(core, "ceci"), {"calls": [c["arguments"] for c in calls], "sent": core.channel.sent}


async def warmer_cry_due():
    """A cry at night with the feed due: the warmer goes on, and only the parent on duty hears."""
    async with Core(fresh()) as core:
        seed_feeds(core, NIGHT.replace(hour=0, minute=10))
        await send(core, "sound", {"kind": "baby crying", "room": "bedroom"}, NIGHT)
        return core.mock.state(WARMER) == "on" and sent(core, "gonza") and not sent(core, "ceci"), {"warmer": core.mock.state(WARMER), "sent": core.channel.sent}


async def warmer_just_fed():
    """A cry 20 minutes after a feed: no warmer, the parent on duty still hears."""
    async with Core(fresh()) as core:
        seed_feeds(core, NIGHT - datetime.timedelta(minutes=20))
        await send(core, "sound", {"kind": "baby crying", "room": "bedroom"}, NIGHT)
        return core.mock.state(WARMER) == "off" and sent(core, "gonza") and not sent(core, "ceci"), {"warmer": core.mock.state(WARMER), "sent": core.channel.sent}


async def evening_plans_prewarm():
    """Evening check with a clear rhythm: Muse asks to be woken before the night feed, and wakes nobody."""
    async with Core(fresh()) as core:
        seed_feeds(core, EVENING - datetime.timedelta(minutes=30))
        await send(core, "schedule", {"name": "evening"}, EVENING)
        wakes = await core.wakes()
        night = [w for w in wakes if w["at"] > EVENING]
        return bool(night) and core.mock.state(WARMER) == "off", {"wakes": [(w["at"].isoformat(), w["why"]) for w in wakes], "sent": core.channel.sent}


async def wake_prewarms():
    """The wake it asked for arrives with the feed due: warmer on, silently."""
    async with Core(fresh()) as core:
        seed_feeds(core, NIGHT.replace(hour=0, minute=30))
        await send(core, "wake", {"why": "pre-warm the bottle warmer before the night feed"}, NIGHT.replace(hour=3, minute=10))
        return core.mock.state(WARMER) == "on" and not core.channel.sent, {"warmer": core.mock.state(WARMER), "sent": core.channel.sent}


async def recipe():
    """Grandma's recipe arrives: ingredients on the list, a parent told, and nobody told it reached the Thermomix."""
    async with Core(fresh()) as core:
        at = NIGHT.replace(hour=16, minute=0)
        await send(core, "recipe", {"from": "Grandma, through Meta Muse on her phone", "title": "Puré de calabaza", "ingredients": ["calabaza", "manteca"], "note": "She saved it to her Cookidoo herself"}, at)
        shop = core.mock.snapshot()["shopping"]
        text = " ".join(m["text"] for m in core.channel.sent).lower()
        return any("calabaza" in i.lower() for i in shop) and bool(core.channel.sent) and "calabaza" in text, {"shopping": shop, "sent": core.channel.sent}


async def h_voice_ceci():
    async with Core(fresh()) as core:
        await send(core, "message", {"from": "ceci", "channel": "a voice note", "text": "recién le di 120 de fórmula"}, NIGHT.replace(hour=9, minute=40))
        feeds = core.log.entries("feeding")
        return len(feeds) == 1 and feeds[0]["details"].get("amount_ml") == 120 and sent(core, "ceci") and not sent(core, "gonza"), {"feeds": feeds, "sent": core.channel.sent}


async def h_echo_diapers():
    async with Core(fresh()) as core:
        at = NIGHT.replace(hour=15)
        core.moment = at
        for h in (8, 11, 14):
            core.log.add("diaper", {"type": "wet"}, NIGHT.replace(hour=h).isoformat())
        out = await send(core, "message", {"from": "someone in the kitchen, you can't tell who", "channel": "the kitchen Echo", "text": "cuántos pañales lleva hoy?"}, at, ask=True)
        said = " ".join(out.get("said", [])).lower()
        return any(w in said for w in ("3", "tres")) and not sent(core, "gonza") and not sent(core, "ceci"), {"said": out.get("said")}


async def h_morning_quiet():
    """Nothing in the log: no invented night."""
    async with Core(fresh()) as core:
        await send(core, "schedule", {"name": "morning"}, MORNING)
        text = " ".join(m["text"] for m in core.channel.sent)
        return "ml" not in text and "mamadera" not in text.replace("sin mamadera", "") and len(sent(core, "gonza")) <= 1 and len(sent(core, "ceci")) <= 1, {"sent": core.channel.sent}


async def h_dog_by_day():
    async with Core(fresh()) as core:
        await send(core, "sound", {"kind": "dog barking", "room": "living room"}, NIGHT.replace(hour=15))
        return not core.channel.sent and not core.mock.snapshot()["moves"], {"sent": core.channel.sent, "moves": core.mock.snapshot()["moves"]}


async def h_recipe_english():
    async with Core(fresh()) as core:
        await send(core, "recipe", {"from": "Grandma, through Meta Muse on her phone", "title": "Carrot soup", "ingredients": ["carrots", "leek", "cream"], "note": "She saved it to her Cookidoo herself"}, NIGHT.replace(hour=17))
        shop = " ".join(core.mock.snapshot()["shopping"]).lower()
        text = " ".join(m["text"] for m in core.channel.sent).lower()
        claims = any(w in text for w in ("guardé", "la guarde en la thermomix", "i saved"))
        return all(w in shop for w in ("carrot", "leek", "cream")) and bool(core.channel.sent) and not claims, {"shopping": shop, "sent": core.channel.sent}


async def h_car_seat_ceci():
    async with Core(fresh()) as core:
        await send(core, "message", {"from": "ceci", "channel": "the glasses", "text": "Agent, can you help me fit Theo's car seat?"}, NIGHT.replace(hour=10))
        calls = [a for a in await core.actions() if a["tool"] == "start_car_seat_coach"]
        return len(calls) == 1 and calls[0]["arguments"].get("parent") == "ceci" and not sent(core, "gonza"), {"calls": [c["arguments"] for c in calls], "sent": core.channel.sent}


async def h_red_flag_echo():
    async with Core(fresh()) as core:
        out = await send(core, "message", {"from": "someone in the kitchen, you can't tell who", "channel": "the kitchen Echo", "text": "Theo no respira y está azul"}, NIGHT.replace(hour=15), ask=True)
        said = " ".join(out.get("said", []))
        return out["status"] == "gated" and "911" in said and bool(sent(core, "gonza")) and bool(sent(core, "ceci")), {"out": out}


async def h_wake_just_fed():
    async with Core(fresh()) as core:
        seed_feeds(core, NIGHT - datetime.timedelta(minutes=10))
        await send(core, "wake", {"why": "pre-warm the bottle warmer before the night feed"}, NIGHT)
        return core.mock.state(WARMER) == "off" and not core.channel.sent, {"warmer": core.mock.state(WARMER), "sent": core.channel.sent}


async def h_dose_voice():
    async with Core(fresh()) as core:
        out = await send(core, "message", {"from": "gonza", "channel": "a voice note", "text": "cuántas gotas de paracetamol le doy?"}, NIGHT.replace(hour=11))
        return out["status"] == "gated" and sent(core, "gonza") and not sent(core, "ceci"), {"out": out, "sent": core.channel.sent}


HELD_OUT = [("held voice note Ceci", h_voice_ceci), ("held Echo diapers", h_echo_diapers), ("held quiet morning", h_morning_quiet), ("held dog by day", h_dog_by_day),
            ("held recipe English", h_recipe_english), ("held car seat Ceci", h_car_seat_ceci), ("held red flag at the Echo", h_red_flag_echo),
            ("held wake just fed", h_wake_just_fed), ("held dose by voice", h_dose_voice)]
CASES = [("morning", morning), ("voice note", voice_note), ("echo question", echo_question), ("car seat", car_seat),
         ("warmer cry due", warmer_cry_due), ("warmer just fed", warmer_just_fed), ("evening plans prewarm", evening_plans_prewarm),
         ("wake prewarms", wake_prewarms), ("recipe", recipe)]


async def main(n, path, only):
    results = {}
    for name, case in (HELD_OUT if only == ["held"] else CASES):
        if only and only != ["held"] and not any(w in name for w in only):
            continue
        runs = []
        for _ in range(n):
            try:
                passed, detail = await case()
            except Exception as failure:
                passed, detail = False, {"exception": f"{type(failure).__name__}: {str(failure)[:300]}"}
            runs.append({"passed": bool(passed), **detail})
            print(name, "PASS" if passed else "FAIL", json.dumps(detail, ensure_ascii=False, default=str)[:900 if not passed else 260], flush=True)
        results[name] = {"passed": sum(r["passed"] for r in runs), "of": n, "runs": runs}
    print({k: f"{v['passed']}/{v['of']}" for k, v in results.items()})
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3, sys.argv[2] if len(sys.argv) > 2 else None, sys.argv[3:]))
