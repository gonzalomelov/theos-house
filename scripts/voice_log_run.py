"""Real run: spoken notes go through the agent and the brain into Baby Buddy, and each
record is read back from Baby Buddy's API by id. Writes results/kr222/voice-log.json in the schema that
measure-kr222.sh checks.

    python scripts/voice_log_run.py                       # config/agent.json: Claude brain, Baby Buddy on the Vostro
    python scripts/voice_log_run.py --config config/agent.muse-baseten.json

Baby Buddy is reached through the SSH tunnel in docs/deploy-babybuddy.md. Each note is its own conversation,
the way notes arrive through the day. Notes arrive as text here, speech to text comes with the channels issue.
"""
import argparse
import datetime
import json
import queue
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent.agent import build  # noqa: E402
from parenting_agent.agent import config as config_mod  # noqa: E402

NOTES = [
    ("bottle, 120 ml", "feeding"),
    ("wet and dirty diaper", "diaper"),
    ("just gave her a bath", "bath"),
    ("wet diaper", "diaper"),
]
QUESTIONS = ["How much did she drink today?", "When was the last dirty diaper?"]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def converse(agent, text, timeout=90):
    replies = queue.Queue()
    agent.bus.subscribe(replies.put, ["reply"])
    agent.bus.publish("message", channel="run", text=text)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = replies.get(timeout=timeout)
        if event.get("channel") == "run":
            return event["text"]
    raise TimeoutError(text)


def fresh_agent(config):
    data = tempfile.mkdtemp(prefix="voice-log-run-")
    agent = build(dict(config, data_dir=data, plugins=[]))
    created = []
    add = agent.baby_log.add

    def recording_add(kind, details, ts=None):
        entry = add(kind, details, ts)
        created.append(entry)
        return entry

    agent.baby_log.add = recording_add
    agent.start()
    return agent, created


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config" / "agent.json"))
    parser.add_argument("--out", default=str(ROOT / "results" / "kr222" / "voice-log.json"))
    args = parser.parse_args(argv)
    config = config_mod.load(args.config)
    if (config.get("baby_log") or {}).get("provider") != "babybuddy":
        raise SystemExit("this run needs the Baby Buddy log (baby_log.provider babybuddy in the config)")

    entries, answers, brain = [], [], None
    for utterance, expected in NOTES:
        agent, created = fresh_agent(config)
        brain = brain or {"provider": agent.brain.name, "model": agent.brain.model, "destination": agent.brain.destination}
        spoken_at = now()
        try:
            reply = converse(agent, utterance)
        finally:
            agent.stop()
        for entry in created:
            if "id" not in entry:
                continue
            record = agent.baby_log.get(entry["kind"], entry["id"])
            entries.append({"utterance": utterance, "expected_type": expected, "spoken_at": spoken_at, "reply": reply,
                            "babybuddy": {"id": record["id"], "type": record["kind"], "time": record["ts"], "details": record["details"]}})
        agent.close()
        print(f"{utterance!r} -> {reply}  [{len(created)} record(s)]", flush=True)

    for question in QUESTIONS:
        agent, _ = fresh_agent(config)
        try:
            reply = converse(agent, question)
        finally:
            agent.stop()
            agent.close()
        answers.append({"question": question, "answer": reply})
        print(f"{question!r} -> {reply}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    document = {"generated_at": now(), "brain": brain, "baby_log": "babybuddy", "entries": entries, "answers": answers}
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out} with {len(entries)} entries read back from Baby Buddy", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
