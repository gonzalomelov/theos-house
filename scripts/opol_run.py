"""The OPOL helper on recorded clips, through the real glasses /hear path (issue #144).

    .venv-hearing/bin/python scripts/opol_run.py --make-clips     # MMS-TTS stand-ins, runs/opol/clips (git ignored)
    mkdir /tmp/pa-gpu.lock && python scripts/opol_run.py; rmdir /tmp/pa-gpu.lock    # results/opol/run.json

The clips are labelled stand-ins: Meta's MMS-TTS voices (facebook/mms-tts-eng and -spa) say what a parent would say to
the baby, in English and in Spanish, and two lines that are not for him (one to the other parent, one to the agent). The
baby is the one thing mocked: Theo is not born, so the run's agent is told he is ("baby": {"born": true}).

Everything else is real: each clip is posted as a WAV to the glasses endpoint's /hear on this Mac with the wearer's own
pairing token, the way the glasses app posts an utterance. Muse Spark Open's ear writes it down on Baseten (the existing
glasses path, the /hear race), the speech gate decides, and what is not for the agent goes to the OPOL helper, which
scores it with Meta's MMS language ID (facebook/mms-lid-126) in its worker on this Mac and keeps only the language and
the seconds. Then the on-demand answer, through the agent's loop, and both parents' morning messages the next Monday,
through the family push to a fake Telegram: nothing is sent to anyone.
"""
import argparse
import datetime
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLIPS = ROOT / "runs" / "opol" / "clips"
OUT = ROOT / "results" / "opol"
ENV = Path.home() / "Engineering" / "gonza" / "meta-hackathon-2026" / ".env"
PORT = 8769
TZ = datetime.timezone(datetime.timedelta(hours=-3))
SUNDAY, MONDAY = datetime.datetime(2026, 11, 8, 10, 0, tzinfo=TZ), datetime.datetime(2026, 11, 9, 7, 30, tzinfo=TZ)

# (id, wearer, the language spoken, to whom, the words). Written before the run.
LINES = [
    ("g-en-1", "gonza", "en", "baby", "Good morning Theo, look at the little yellow duck in the water."),
    ("g-en-2", "gonza", "en", "baby", "Who is my favorite boy? Let's put on your soft blue socks now."),
    ("g-en-3", "gonza", "en", "baby", "Can you see the tree outside the window? The leaves are moving in the wind."),
    ("g-es-1", "gonza", "es", "baby", "Mirá Theo, el perro está durmiendo en la alfombra del living."),
    ("c-es-1", "ceci", "es", "baby", "Hola mi amor, ¿tenés hambre? Vamos a comer un poquito."),
    ("c-es-2", "ceci", "es", "baby", "Qué lindo que estás hoy, Theo, mirá la luz que entra por la ventana."),
    ("c-es-3", "ceci", "es", "baby", "Ahora te cambio el pañal y después dormimos la siesta juntos."),
    ("c-en-1", "ceci", "en", "baby", "Look Theo, a big red ball. Can you catch it?"),
    ("c-es-4", "ceci", "es", "gonza", "Gonza, ¿me alcanzás un pañal limpio, por favor?"),
    ("g-ask", "gonza", "es", "agent", "Agente, ¿cuánto inglés escuchó Theo hoy?"),
]


def make_clips():
    """Each line spoken by MMS-TTS in its language, 16 kHz mono 16-bit, with 0.3 s of silence on each side."""
    import numpy as np
    import torch
    from transformers import AutoTokenizer, VitsModel
    CLIPS.mkdir(parents=True, exist_ok=True)
    voices = {}
    for clip_id, _, lang, _, text in LINES:
        name = {"en": "facebook/mms-tts-eng", "es": "facebook/mms-tts-spa"}[lang]
        if name not in voices:
            voices[name] = (VitsModel.from_pretrained(name).eval(), AutoTokenizer.from_pretrained(name))
        model, tokenizer = voices[name]
        torch.manual_seed(144)
        with torch.no_grad():
            audio = model(**tokenizer(text, return_tensors="pt")).waveform[0].numpy()
        rate = model.config.sampling_rate
        pad = np.zeros(int(0.3 * rate), np.float32)
        pcm = (np.clip(np.concatenate([pad, audio, pad]), -1, 1) * 32767).astype("<i2")
        with wave.open(str(CLIPS / f"{clip_id}.wav"), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(pcm.tobytes())
        print(f"{clip_id}: {len(pcm) / rate:.1f} s", flush=True)


def load_key():
    """Only the Baseten key, for Muse's ear, from the hackathon's git ignored .env. Never printed."""
    for raw in ENV.read_text().splitlines():
        key, _, value = raw.strip().partition("=")
        if key.strip() == "BASETEN_API_KEY":
            os.environ["BASETEN_API_KEY"] = value.strip().strip('"').strip("'")
    for blank in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_FAMILIES_BOT_TOKEN", "HA_MCP_TOKEN", "HA_TOKEN"):
        os.environ[blank] = ""
    if not os.environ.get("BASETEN_API_KEY"):
        raise SystemExit("BASETEN_API_KEY is not in the .env")


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


class Messenger:
    """Telegram stand-in: keeps what would be sent, sends nothing."""

    def __init__(self):
        self.sent = []

    def poll(self, offset, timeout):
        return []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        return len(self.sent)


def seconds_of(path):
    with wave.open(str(path)) as reader:
        return reader.getnframes() / reader.getframerate()


def run():
    load_key()
    from parenting_agent.agent import build
    from parenting_agent.agent import config as config_mod
    from parenting_agent.channels.push import FamilyPush
    from parenting_agent.channels.telegram import Telegram
    from parenting_agent.glasses import Glasses
    from parenting_agent.glasses_speech import Gate
    from parenting_agent.opol import Opol
    missing = [c for c, *_ in LINES if not (CLIPS / f"{c}.wav").is_file()]
    if missing:
        raise SystemExit(f"no clips for {missing}: run with --make-clips under .venv-hearing first")
    tokens = {person: secrets.token_urlsafe(12) for person in ("gonza", "ceci")}
    os.environ.update({f"PARENTING_AGENT_GLASSES_TOKEN_{p.upper()}": t for p, t in tokens.items()})
    os.environ.update({"TELEGRAM_CHAT_ID": "9001", "TELEGRAM_CECI_CHAT_ID": "9002"})  # made up, the messenger is fake
    vostro = json.loads((ROOT / "config/agent.vostro.json").read_text())
    tmp = tempfile.TemporaryDirectory()
    config = config_mod.load(None)
    config.update({"data_dir": tmp.name, "env_file": f"{tmp.name}/none.env", "brain": {"provider": "fake"},
                   "plugins": [], "house": {"live": False}, "people": vostro["people"],
                   "telegram": {"allowed_chat_ids_env": "TELEGRAM_CHAT_ID"},
                   "family_push": {"channel": "telegram", "morning": True},
                   "glasses": {"port": PORT, "host": "127.0.0.1", "wearers": ["gonza", "ceci"]},
                   "baby": {"born": True, "name": "Theo"},  # the mock: Theo is not born yet
                   "opol": {**vostro["opol"], "min_minutes": 0.1, "lid": {"enabled": True, "device": "mps"}}})
    agent = build(config)
    clock = Clock(SUNDAY)
    messenger = Messenger()
    glasses = Glasses(agent, config)
    telegram = Telegram(agent, config, messenger=messenger)
    push = FamilyPush(agent, config, clock=clock)
    opol = Opol(agent, config, clock=clock)
    agent.plugins = [glasses, telegram, push, opol]
    seen = []
    agent.bus.subscribe(seen.append, None)
    agent.start()
    glasses.start()
    opol.start()
    rows = []
    started_all = time.monotonic()
    try:
        for clip_id, wearer, lang, to, text in LINES:
            glasses.gate = Gate()  # each line heard fresh, no wake word window left from the last
            since = len(seen)
            path = CLIPS / f"{clip_id}.wav"
            request = urllib.request.Request(f"http://127.0.0.1:{PORT}/hear", data=path.read_bytes(), method="POST",
                                             headers={"Authorization": f"Bearer {tokens[wearer]}",
                                                      "Content-Type": "audio/wav",
                                                      "X-Speech-End-Unix": f"{time.time():.3f}"})
            with urllib.request.urlopen(request, timeout=10) as reply:
                assert reply.status == 202
            deadline = time.monotonic() + 120
            done = None
            while time.monotonic() < deadline and done is None:
                events = seen[since:]
                speech = next((e for e in events if e["kind"] == "speech"), None)
                if speech is not None and not speech["took"]:
                    done = next((e for e in events if e["kind"] == "opol"), None)
                elif speech is not None:
                    done = next((e for e in events if e["kind"] == "reply"), None)
                time.sleep(0.1)
            opol.queue.join()
            time.sleep(0.3)
            events = seen[since:]
            speech = next((e for e in events if e["kind"] == "speech"), {})
            counted = [e for e in events if e["kind"] == "opol" and e["action"] != "lid_ready"]
            row = {"id": clip_id, "wearer": wearer, "lang": lang, "to": to, "text": text,
                   "clip_s": round(seconds_of(path), 2), "heard": speech.get("text"), "gate": speech.get("why"),
                   "opol": [{k: e.get(k) for k in ("action", "lang", "seconds", "by", "share", "reason")
                             if e.get(k) is not None} for e in counted],
                   "replies": [e["text"] for e in events if e["kind"] == "reply"]}
            want = {"baby": ("counted", lang), "gonza": ("skipped", None), "agent": (None, None)}[to]
            got = (counted[0]["action"], counted[0].get("lang")) if counted else (None, None)
            row["right"] = got == want
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("id", "lang", "to", "heard", "gate", "opol", "right")},
                             ensure_ascii=False), flush=True)
        lid_ready = next((e for e in seen if e["kind"] == "opol" and e["action"] == "lid_ready"), {})
        asked = {}
        for chat, question in (("9002", "¿cuánto español escuchó Theo hoy?"),):
            agent.bus.publish("message", channel="telegram", text=question, chat_id=chat,
                              person=telegram.person_of(chat), voice=False)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not messenger.sent:
                time.sleep(0.05)
            asked[question] = messenger.sent[-1][1] if messenger.sent else None
        clock.moment = MONDAY
        agent.bus.publish("notify", text="Buen día.", channel="telegram", source="day-engine", routine="morning_brief",
                          facts={"night": {}, "low": [], "appointments": [], "meals": []})
        push.morning_flush()
        morning = {agent.people.name(p): t for p, t in
                   next(e for e in reversed(seen) if e["kind"] == "morning_message")["texts"].items()}
        with agent.memory.lock:
            stored = agent.memory.db.execute("select day, person, lang, round(seconds, 2), utterances from opol_seconds "
                                             "order by person, lang").fetchall()
            tables = {t: agent.memory.db.execute(f"select * from {t}").fetchall() for (t,) in agent.memory.db.execute(
                "select name from sqlite_master where type = 'table' and name like 'opol%'")}
        words_kept = [r["id"] for r in rows if r["to"] == "baby" and any(
            w in json.dumps(tables, ensure_ascii=False) for w in r["text"].split() if len(w) > 4)]
        wavs_written = sorted(str(p.relative_to(tmp.name)) for p in Path(tmp.name).rglob("*.wav"))
    finally:
        opol.stop()
        glasses.stop()
        agent.stop()
    result = {"run": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
              "clips": "MMS-TTS stand-ins (facebook/mms-tts-eng, facebook/mms-tts-spa), labelled in LINES",
              "ear": "meta-models/muse-spark-open-1026 on inference.baseten.co, the glasses /hear race (existing path)",
              "language_id": "facebook/mms-lid-126 rev 53da6e3, in opol_worker.py on this Mac, " + str(lid_ready.get("info")),
              "mocked": "Theo (not born): the run's agent has baby.born true. Telegram: a fake messenger, nothing sent",
              "right": sum(r["right"] for r in rows), "lines": len(rows), "rows": rows,
              "stored_opol_seconds": stored, "words_found_in_opol_tables": words_kept,
              "wav_files_in_the_agent_data_dir": wavs_written, "asked": asked,
              "morning_monday": morning, "telegram_sent": len(messenger.sent),
              "seconds": round(time.monotonic() - started_all, 1)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: result[k] for k in ("right", "lines", "stored_opol_seconds", "words_found_in_opol_tables",
                                              "asked", "morning_monday")}, indent=1, ensure_ascii=False))
    tmp.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--make-clips", action="store_true")
    args = parser.parse_args()
    make_clips() if args.make_clips else run()
