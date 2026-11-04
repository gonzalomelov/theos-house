"""The moments the video shows, against real Muse on Baseten, the real gate and the real danger screen, on the mock home and a mock channel. Nothing reaches a phone.
Tuned, not held-out: the scene is what the prompt was changed for. Results in results/whatsapp-video/.

    PA_DB_URL=... BASETEN_API_KEY=... python scripts/video_scene_eval.py scene 3 out.json [es|en]
    ... python scripts/video_scene_eval.py voice 1 out.json
    ... python scripts/video_scene_eval.py home 3 out.json
"""
import asyncio
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["PA_WORLD"] = "mock"
os.environ["PA_MOCK_PORT"] = "0"
os.environ.pop("PA_REHEARSAL", None)
import httpx  # noqa: E402

from parenting_agent.agent.babybuddy import BabyBuddyLog  # noqa: E402
from parenting_agent.channels.twilio_whatsapp import TwilioWhatsApp, signature  # noqa: E402
from parenting_agent.core import server, sources, tools  # noqa: E402
from parenting_agent.core.runtime import Core  # noqa: E402
from parenting_agent.core.settings import Settings  # noqa: E402
from parenting_agent.simulator.scenes import BY_ID, CRY_ROOM, LOG  # noqa: E402
from parenting_agent.voice import audio, client as voice_client  # noqa: E402
from parenting_agent.voice.ear import Ear  # noqa: E402
from tests.fake_babybuddy import TOKEN, FakeBabyBuddy  # noqa: E402
from tests.test_twilio_whatsapp import Media  # noqa: E402

logging.disable(logging.WARNING)
EVAL_DIR = Path(os.environ.get("PA_EVAL_DIR", tempfile.gettempdir())) / "pa-video"
TZ = datetime.timezone(datetime.timedelta(hours=-3))
EVENING_DAY, NIGHT_DAY = "2026-12-15", "2026-12-16"  # Ceci's night on the rota, as in the simulator's scenes
CRY = f"{NIGHT_DAY}T02:50:00-03:00"
SLEEP_ES = BY_ID["sleep"]["text"]["es"]
SLEEP_EN = BY_ID["sleep"]["text"]["en"]
# (name, the words, what the log holds beyond the day's feeds, the feed the cry's message has to name). A feed is (time, details).
BOTTLE = {"amount_ml": 90, "method": "bottle"}
LOGS = [
    ("the scene's log", (SLEEP_ES, SLEEP_EN), [], "20:40"),
    ("late bottle", ("Estoy muerta, esta noche dejame dormir", "I'm wiped, let me sleep tonight"), [(f"{EVENING_DAY}T23:10:00", BOTTLE)], "23:10"),
    ("after midnight", ("Gonza, hoy dejame dormir a mí por favor", "Gonza, let me sleep tonight please"), [(f"{NIGHT_DAY}T00:25:00", BOTTLE)], "00:25"),
    ("with a diaper after", ("No doy más, ¿me dejan dormir esta noche?", "I can't anymore, can I sleep through tonight?"), [(f"{NIGHT_DAY}T01:45:00", BOTTLE)], "01:45"),
    ("fed half an hour ago", (SLEEP_ES, SLEEP_EN), [(f"{NIGHT_DAY}T02:20:00", {"amount_ml": 60, "method": "bottle"})], "02:20"),
    ("breast, no amount", ("Esta noche necesito dormir, que se encargue Gonza", "I need to sleep tonight, Gonza takes it"), [(f"{EVENING_DAY}T22:05:00", {"method": "breast", "side": "left"})], "22:05"),
    ("three in the night", ("Dejame dormir hoy", "Let me sleep tonight"), [(f"{EVENING_DAY}T22:30:00", BOTTLE), (f"{NIGHT_DAY}T00:30:00", BOTTLE), (f"{NIGHT_DAY}T01:50:00", {"amount_ml": 70, "method": "bottle"})], "01:50"),
    ("a long gap", (SLEEP_ES, SLEEP_EN), "only-early", "16:00"),
    ("nothing in the log", (SLEEP_ES, SLEEP_EN), "empty", None),
    ("feed told in the evening", (SLEEP_ES, SLEEP_EN), "told", "23:30"),
]
ATE = re.compile(r"com[ií]|tom[oó]|mamadera|toma\b|teta|pecho|\bate\b|\beat\b|\bfed\b|\bfeed|bottle|nurs|breast", re.I)
TIME = re.compile(r"\b([01]?\d|2[0-3])[:.h]([0-5]\d)\b")


def settings(lang):
    return Settings(home="video-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=str(EVAL_DIR / uuid.uuid4().hex[:8]), lang=lang)


async def send(core, kind, payload, at):
    _, done = await core.dispatch(kind, payload, at=at)
    return await done


def sent(core, since=0, to=None):
    return [{k: m.get(k) for k in ("to", "text", "quiet") if m.get(k) is not None} for m in core.channel.sent[since:] if to is None or m["to"] == to]


def times_of(text):
    return {f"{int(h):02d}:{m}" for h, m in TIME.findall(text)}


def judge_feed(messages, feed):
    """Does what reached the parent name the last feed, at its right time, and no other time as a feed's? The warmer's end is the one other time it may name."""
    text = " ".join(m["text"] for m in messages)
    named = times_of(text)
    if feed is None:
        return {"states_feed": not named and bool(re.search(r"no (?:hay|tengo|figura|aparece|veo)|sin |nothing|no feed|isn.t|don.t", text, re.I)), "times": sorted(named)}
    return {"states_feed": feed in named and bool(ATE.search(text)), "times": sorted(named), "other_times": sorted(named - {feed, "02:50"})}


async def scene(variant, lang):
    name, words, extra, feed = variant
    words = words[0 if lang == "es" else 1]
    async with Core(settings(lang)) as core:
        try:
            day = LOG
            if extra == "only-early":
                day = [(f"{EVENING_DAY}T12:00:00-03:00", "feeding", BOTTLE), (f"{EVENING_DAY}T16:00:00-03:00", "feeding", BOTTLE)]
            elif extra == "empty":
                day = []
            core.moment = datetime.datetime.fromisoformat(f"{EVENING_DAY}T21:00:00-03:00")
            for at, kind, details in day:
                core.log.add(kind, details, at)
            if isinstance(extra, list):
                for at, details in extra:
                    core.moment = datetime.datetime.fromisoformat(at + "-03:00") + datetime.timedelta(minutes=1)
                    core.log.add("feeding", details, at + "-03:00")
                if name == "with a diaper after":
                    core.log.add("diaper", {"wet": True}, f"{NIGHT_DAY}T01:55:00-03:00")
            await send(core, "schedule", {"name": "evening"}, f"{EVENING_DAY}T21:30:00-03:00")
            before = len(core.channel.sent)
            asked = await send(core, "message", {"from": "ceci", "channel": "WhatsApp", "text": words}, f"{EVENING_DAY}T21:45:00-03:00")
            evening = sent(core, before)
            if extra == "told":
                await send(core, "message", {"from": "gonza", "channel": "WhatsApp", "text": "Le di 90 ml a las 23:30" if lang == "es" else "I gave him 90 ml at 23:30"}, f"{EVENING_DAY}T23:35:00-03:00")
            facts = await tools.facts(core.store, core.settings.home)
            before = len(core.channel.sent)
            out = await send(core, "sound", {"kind": "baby crying", "room": CRY_ROOM[lang]}, CRY)
            night = sent(core, before)
            to_gonza, to_ceci = [m for m in night if m["to"] == "gonza"], [m for m in night if m["to"] == "ceci"]
            result = {"lang": lang, "log": name, "last_feed": feed, "words": words, "evening_status": asked["status"], "evening": evening,
                      "duty_set": facts.get(f"on_duty_{EVENING_DAY}"), "night": night, "ceci_not_woken": not to_ceci,
                      "gonza_heard_out_loud": any(not m.get("quiet") for m in to_gonza), "warmer": core.mock.state("switch.study_tapo_p110_bottle_warmer"), "outcome": out.get("outcome"),
                      **judge_feed(to_gonza, feed)}
            result["told_gonza_evening"] = any(m["to"] == "gonza" for m in evening)
            result["answered_ceci_evening"] = any(m["to"] == "ceci" for m in evening)
            result["evening_ok"] = result["duty_set"] == "gonza" and result["told_gonza_evening"] and result["answered_ceci_evening"] and asked["status"] == "done"
            result["passed"] = bool(result["states_feed"] and result["ceci_not_woken"] and result["gonza_heard_out_loud"] and result["evening_ok"])
            return result
        finally:
            await core.forget()


def fake_twilio(data):
    twilio = ThreadingHTTPServer(("127.0.0.1", 0), Media)
    port = twilio.server_address[1]
    twilio.state = {"seen": [], "audio": data, "type": "audio/ogg", "not_ready": 0, "location": f"http://localhost:{port}/cdn/note"}
    threading.Thread(target=twilio.serve_forever, daemon=True).start()
    return twilio


class MockWhatsApp(tools.MockChannel):
    """The mock channel, and the Twilio side of the webhook with nothing able to leave."""
    def __init__(self, folder, api):
        super().__init__()
        self.whatsapp = TwilioWhatsApp("AC1", "tok", {"gonza": "59891111111", "ceci": "59892222222"}, Path(folder) / "w.json", post=lambda fields: {"sid": "SM"}, media_api=api, media_cdn=("localhost",))


class FfmpegHere:
    def to_wav(self, data):
        return audio.to_wav(data)


def real_ear():
    return voice_client.Voice(FfmpegHere(), Ear())


def noise():
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:a", "libopus", "-f", "ogg", "pipe:1"], capture_output=True, check=True).stdout


async def voice_note(name, data, check):
    """The whole way in: Twilio's signed form, the media through the redirect, ffmpeg, Muse's ear, then the event through the gate and Muse, on the mock home."""
    twilio = fake_twilio(data)
    api = f"http://127.0.0.1:{twilio.server_address[1]}"
    with tempfile.TemporaryDirectory() as folder:
        async with Core(settings("es"), channel=MockWhatsApp(folder, api)) as core:
            try:
                params = {"From": "whatsapp:+59891111111", "MessageSid": "MM" + uuid.uuid4().hex, "Body": "", "NumMedia": "1", "MediaContentType0": "audio/ogg", "MediaUrl0": f"{api}/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1"}
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.echo_app(core)), base_url="http://door") as client:
                    answer = await client.post("/twilio", content=urlencode(params), headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": signature("tok", "https://whatsapp.home.example/twilio", params)})
                for _ in range(180):
                    events = await core.events()
                    if events and all(e["status"] != "queued" for e in events) and core.queue.empty() and any(e["type"] in ("message", "voice_note_not_heard") and e["status"] != "queued" for e in events):
                        break
                    await asyncio.sleep(1)
                feeds = core.log.entries("feeding")
                detail = {"name": name, "webhook": answer.status_code, "events": [{"type": e["type"], "status": e["status"], "payload": e["payload"], "outcome": e["outcome"]} for e in await core.events()],
                          "feeds": feeds, "sent": sent(core), "auth_stopped_at_api": [bool(a) for _, a in twilio.state["seen"]] == [True, False]}
                detail["passed"] = bool(answer.status_code == 200 and detail["auth_stopped_at_api"] and check(detail))
                return detail
            finally:
                await core.forget()
                twilio.shutdown()


def voice_cases():
    notes = ROOT / "results/voice/notes"

    def feed_of(ml, hour=None):
        def check(detail):
            return (any(e["details"].get("amount_ml") == ml and (hour is None or f"T{hour}:" in e["ts"]) for e in detail["feeds"]) and len(detail["feeds"]) == 1 and any(m["to"] == "gonza" for m in detail["sent"])
                    and detail["events"][-1]["payload"].get("channel") == "a voice note")
        return check

    def plain_reply(detail):
        return not detail["feeds"] and [m["to"] for m in detail["sent"]] == ["gonza"] and any(e["type"] == "voice_note_not_heard" for e in detail["events"])
    return [("es01 bottle at three", (notes / "es01.ogg").read_bytes(), feed_of(90, "03")), ("es07 bottle of 120", (notes / "es07.ogg").read_bytes(), feed_of(120)),
            ("en07 bottle English", (notes / "en07.ogg").read_bytes(), feed_of(150)), ("a tone with no words", noise(), plain_reply), ("bytes that aren't audio", b"not audio" * 50, plain_reply)]


def today_at(hour, minute=0):
    return datetime.datetime.now(TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)


async def correct(lang, words, verify):
    """On a Baby Buddy that isn't the family's: the test server, the same REST client the home uses, the times today's since it refuses the future."""
    bb = FakeBabyBuddy()
    log = BabyBuddyLog(bb.url, TOKEN, "test-baby", ["agent"], [])
    now = datetime.datetime.now(TZ)
    async with Core(settings(lang), log=(None, log)) as core:
        try:
            for hours in (5, 2):
                log.add("feeding", dict(BOTTLE), (now - datetime.timedelta(hours=hours)).replace(second=0, microsecond=0).isoformat())
            before = log.entries("feeding")
            first = (now - datetime.timedelta(hours=2)).strftime("%H:%M")
            await send(core, "message", {"from": "gonza", "channel": "WhatsApp", "text": words.format(at=first)}, now.isoformat())
            after = log.entries("feeding")
            return {"before": before, "after": after, "sent": sent(core), "passed": bool(verify(before, after) and [m for m in sent(core) if m["to"] == "gonza"])}
        finally:
            await core.forget()
            bb.close()


async def false_alarm(moment, other_quiet):
    async with Core(settings("es")) as core:
        try:
            alarm = await send(core, "message", {"from": "gonza", "channel": "WhatsApp", "text": "Theo no respira bien, está raro"}, moment.isoformat())
            before = len(core.channel.sent)
            await send(core, "message", {"from": "gonza", "channel": "WhatsApp", "text": "Falsa alarma, ya está bien, era un moco"}, (moment + datetime.timedelta(minutes=10)).isoformat())
            after = sent(core, before)
            ceci = [m for m in after if m["to"] == "ceci"]
            facts = await tools.facts(core.store, core.settings.home)
            wakes = [w["why"][:80] for w in await core.wakes()]
            return {"alarm": alarm["status"], "sent_after": after, "facts": facts, "wakes": wakes,
                    "passed": bool(alarm["status"] == "gated" and len(ceci) == 1 and "Falsa alarma" in ceci[0]["text"] and bool(ceci[0].get("quiet")) == other_quiet and any(m["to"] == "gonza" for m in after) and not any(k.startswith("alarm_") and k != "alarm_answered" for k in facts))}
        finally:
            await core.forget()


async def open_alarm_morning():
    moment = datetime.datetime.fromisoformat(f"{NIGHT_DAY}T03:10:00-03:00")
    async with Core(settings("es")) as core:
        try:
            core.moment = moment
            core.log.add("feeding", dict(BOTTLE), moment.replace(hour=1).isoformat())
            alarm = await send(core, "message", {"from": "gonza", "channel": "WhatsApp", "text": "Tiene los labios azules"}, moment.isoformat())
            before = len(core.channel.sent)
            await send(core, "schedule", {"name": "morning"}, moment.replace(hour=7, minute=30).isoformat())
            morning = sent(core, before)
            ask = re.compile(r"cómo está|como esta", re.I)
            both = all(any(m["to"] == who and ask.search(m["text"]) for m in morning) for who in ("gonza", "ceci"))
            sign = all(any(m["to"] == who and "labios azules" in m["text"].lower() and "03:10" in " ".join(x["text"] for x in morning if x["to"] == who) for m in morning) for who in ("gonza", "ceci"))
            facts = await tools.facts(core.store, core.settings.home)
            return {"alarm": alarm["status"], "morning": morning, "kept_open": [k for k in facts if k.startswith("open_alarm_")], "passed": bool(alarm["status"] == "gated" and both and sign and any(k.startswith("open_alarm_") for k in facts))}
        finally:
            await core.forget()


def home_cases():
    day = today_at(15)

    def amount(before, after):
        return len(after) == len(before) and any(e["details"].get("amount_ml") == 110 for e in after)

    def removed(before, after):
        return len(after) == len(before) - 1
    return [("correct an amount", lambda: correct("es", "Perdón, la de las {at} fueron 110 ml, no 90", amount)),
            ("remove an entry", lambda: correct("es", "La de las {at} no pasó, borrala del registro", removed)),
            ("false alarm by day", lambda: false_alarm(day, False)),
            ("false alarm at night", lambda: false_alarm(datetime.datetime.fromisoformat(f"{NIGHT_DAY}T03:10:00-03:00"), True)),
            ("open alarm in the morning", open_alarm_morning)]


async def guarded(limit, name, job):
    async with limit:
        try:
            result = await job()
        except Exception as failure:
            result = {"passed": False, "exception": f"{type(failure).__name__}: {str(failure)[:300]}"}
        print(name, "PASS" if result["passed"] else "FAIL", json.dumps(result, ensure_ascii=False, default=str)[:1500 if not result["passed"] else 400], flush=True)
        return name, result


async def main(group, runs, path, lang):
    limit = asyncio.Semaphore(int(os.environ.get("PA_EVAL_PARALLEL", "4")))
    if group == "scene":
        jobs = [(f"{lang} {v[0]}", lambda v=v: scene(v, lang)) for v in LOGS]
    elif group == "voice":
        jobs = [(name, lambda name=name, data=data, check=check: voice_note(name, data, check)) for name, data, check in voice_cases()]
    else:
        jobs = home_cases()
    with mock.patch.object(sources, "voice_ears", real_ear):
        done = await asyncio.gather(*[guarded(limit, name, job) for name, job in jobs for _ in range(runs)])
    results = {}
    for name, result in done:
        results.setdefault(name, []).append(result)
    summary = {name: f"{sum(r['passed'] for r in rows)}/{len(rows)}" for name, rows in results.items()}
    print(summary, f"total {sum(r['passed'] for rows in results.values() for r in rows)} of {sum(len(rows) for rows in results.values())}", flush=True)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))


asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "es"))
