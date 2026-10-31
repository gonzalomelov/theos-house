"""Live run for issue #161: recorded cries through the whole cry path on this Mac, results in results/cry-reason/live.json.

    python scripts/cry_reason_live.py

What runs for real: ffmpeg decoding licensed cry recordings on a pipe through the Tapo camera's 8 kHz A-law channel,
the Ear one second at a time, PANNs CNN14 in the hearing worker, the local cry model (cry_sound.py, PANNs embedding and
the Donate-a-Cry head), the log reason (cry_reason.py) on the simulated week, the HouseSounds plug-in, the family push
routing to the parent on duty, the Telegram channel plug-in, and the glasses channel with its HTTP endpoint on
127.0.0.1, read by two event-stream clients the way the glasses app reads it.

What stands in, because it does not exist here: the microphone (no house microphone feeds an agent, so the recordings
play into the Ear), the baby (the simulated week's log and a night moment in it), Telegram (a capturing messenger
writes each message to telegram-captured.jsonl in the run's temporary data dir, the bot token and the chats are fake),
the glasses (an event-stream client per parent). The house is dry: house.live false, the white noise is the simulated
device. The brain is not on this path. Every network call that is not 127.0.0.1 is refused for the whole run, so no
audio can leave the Mac.

Night story: a 19 s cry (cry-01) is a short night fuss, so the white noise comes on and nobody is woken. 60 s later a
cry comes back (cry-04, 30 s of it), so the parent on duty is told on Telegram and on their glasses.
"""
import datetime
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from parenting_agent import cry_sound, hearing  # noqa: E402
from parenting_agent.agent import build  # noqa: E402
from parenting_agent.agent import config as config_mod  # noqa: E402
from parenting_agent.channels.push import FamilyPush  # noqa: E402
from parenting_agent.channels.telegram import Telegram  # noqa: E402
from parenting_agent.dog_watch import CapturedMessages  # noqa: E402
from parenting_agent.glasses import Glasses  # noqa: E402
from parenting_agent.house_sounds import HouseSounds  # noqa: E402
from parenting_agent.rhythm.log import FixtureLog  # noqa: E402
from simweek import cries  # noqa: E402

MEDIA = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic"
SOURCES = Path.home() / "Engineering/gonza/meta-hackathon-2026/muse/data/hearing_sources.json"
FIXTURE = REPO / "tests/fixtures/simweek.json"
OUT = REPO / "results/cry-reason/live.json"
TZ = datetime.timezone(datetime.timedelta(hours=-3))
KEEP = ("sound", "cry_sound_guess", "cry_reason", "white_noise", "notify", "pushed", "reply", "glasses_card")
CHATS = {"gonza": "9100001", "ceci": "9100002"}
PEOPLE = {"gonza": {"name": "Gonza", "rota": "Parent A", "chat_ids_env": "TELEGRAM_CHAT_ID", "lang": "es"},
          "ceci": {"name": "Ceci", "rota": "Parent B", "chat_ids_env": "TELEGRAM_CECI_CHAT_ID", "lang": "es"}}


class LocalOnly:
    """Refuses every urllib call that does not go to 127.0.0.1 for the whole run, and counts the refusals."""

    def __init__(self):
        self.real, self.refused = urllib.request.urlopen, []

    def __call__(self, request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if not url.startswith(("http://127.0.0.1", "http://localhost")):
            self.refused.append(url.split("?")[0][:80])
            raise OSError("refused: this run stays on the Mac")
        return self.real(request, *args, **kwargs)


def watch(url, token, person, cards, stop):
    """One parent's glasses app: reads the endpoint's event stream and keeps the cards."""
    request = urllib.request.Request(url + "events", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=30) as stream:
        for raw in stream:
            if stop.is_set():
                return
            line = raw.decode().strip()
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event.get("kind") == "card":
                    cards.append({"person": person, "unix": round(time.time(), 3), **event["card"]})


def clean(event):
    return {k: v for k, v in event.items() if k not in ("t", "chat_id")}


def main():
    sources = {s["id"]: s for s in json.loads(SOURCES.read_text())}
    entries = FixtureLog(FIXTURE).entries()
    case = next(c for c in cries.candidates(entries) if c["at"].hour < 5)
    guard = LocalOnly()
    urllib.request.urlopen = guard
    os.environ.update({"TELEGRAM_BOT_TOKEN": "capture-no-token", "TELEGRAM_CHAT_ID": CHATS["gonza"],
                       "TELEGRAM_CECI_CHAT_ID": CHATS["ceci"]})
    tokens = {p: secrets.token_urlsafe(12) for p in PEOPLE}
    for person, token in tokens.items():
        os.environ[f"PARENTING_AGENT_GLASSES_TOKEN_{person.upper()}"] = token
    clock = {"now": case["at"]}
    with tempfile.TemporaryDirectory() as tmp:
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": [],
                       "people": PEOPLE, "house": {"live": False},
                       "rhythm": {"source": "fixture", "fixture": str(FIXTURE)},
                       "telegram": {"allowed_chat_ids": list(CHATS.values())},
                       "family_push": {"channel": "telegram"},
                       "glasses": {"port": 0, "host": "127.0.0.1", "wearers": list(PEOPLE)},
                       "house_sounds": {"cry_model": {"enabled": True}}})
        agent = build(config)
        captured = Path(tmp) / "telegram-captured.jsonl"
        telegram = Telegram(agent, config, messenger=CapturedMessages(captured))
        started = time.monotonic()
        listener = hearing.PannsListener()
        load_s = round(time.monotonic() - started, 2)
        sounds = HouseSounds(agent, config, listener=listener, clock=lambda: clock["now"])
        push = FamilyPush(agent, config, clock=lambda: clock["now"])
        glasses = Glasses(agent, config)
        agent.plugins = [telegram, sounds, push, glasses]
        cards, stop = [], threading.Event()
        for person, token in tokens.items():
            threading.Thread(target=watch, args=(glasses.hub.url, token, person, cards, stop), daemon=True).start()
        deadline = time.monotonic() + 10
        while len(glasses.hub.wearers_live()) < len(PEOPLE) and time.monotonic() < deadline:
            time.sleep(0.05)
        plays = []
        for clip_id, after_s in (("cry-01", 0), ("cry-04", 60)):
            clock["now"] += datetime.timedelta(seconds=after_s)
            src = sources[clip_id]
            samples = hearing.from_file(MEDIA / src["file"], 0, 30, camera_channel=True)
            first = len(agent.bus.history)
            began = time.monotonic()
            hearing.play(sounds.listen(), samples)
            del samples
            plays.append({"clip": clip_id, "title": src["title"], "license": src["license"], "page": src["page"],
                          "at": clock["now"].isoformat(), "process_s": round(time.monotonic() - began, 2),
                          "events": [clean(e) for e in list(agent.bus.history)[first:] if e["kind"] in KEEP]})
        time.sleep(1)
        stop.set()
        sent = [json.loads(line) for line in captured.read_text().splitlines()] if captured.exists() else []
        sounds.stop()
        glasses.hub.close()
        agent.close()
    urllib.request.urlopen = guard.real
    head = cry_sound.Head.load()
    names = {v: k for k, v in CHATS.items()}
    result = {
        "run": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "where": "this Mac, PANNs on CPU in the hearing worker, nothing sent off the Mac",
        "simulated_moment": case["at"].isoformat(), "simulated_truth": case["truth"],
        "listener_load_s": load_s, "local_model": {"speak": head.meta.get("speak"), "test": head.meta.get("test")},
        "network_refused": guard.refused, "audio_written": False,
        "plays": plays,
        "telegram_captured": [{"to": names.get(m["chat"], m["chat"]), "text": m["text"]} for m in sent],
        "glasses_cards": [{k: c.get(k) for k in ("person", "topic", "title", "status", "detail", "alert")} for c in cards],
    }
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"telegram": result["telegram_captured"], "cards": result["glasses_cards"],
                      "guesses": [{k: e.get(k) for k in ("label", "confidence", "speak")} for p in plays for e in p["events"]
                                  if e["kind"] == "cry_sound_guess"],
                      "refused": guard.refused}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
