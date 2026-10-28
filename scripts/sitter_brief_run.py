"""The real run for the sitter handover (issue #16): the parent's sentence goes through the agent and the real brain,
the brief is built from the simulated week, and the draft goes to the parent's Telegram chat as one message
prefixed "Test:". Nothing goes to anyone else.

    python scripts/sitter_brief_run.py           # dry run: print the draft, send nothing
    python scripts/sitter_brief_run.py --send    # also send exactly one Telegram message to the parent's chat

It calls the Bot API sendMessage once and never polls, so it does not compete with the always-on agent's poller.
The clock is set to Sun Oct 26 18:40 on the simulated week. Writes results/sitter/run.json, with no token or chat id.
"""
import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent import sitter  # noqa: E402
from parenting_agent.agent import build  # noqa: E402
from parenting_agent.agent import config as config_mod  # noqa: E402
from parenting_agent.channels.telegram import TelegramMessenger  # noqa: E402

OUT = ROOT / "results" / "sitter" / "run.json"
TZ = datetime.timezone(datetime.timedelta(hours=-3))
NOW = datetime.datetime(2026, 10, 26, 18, 40, tzinfo=TZ)
SENTENCE = "My mom is watching him tonight from 19:00 to 23:00"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config" / "agent.json"))
    parser.add_argument("--send", action="store_true", help="send the draft once to the parent's Telegram chat")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        config = config_mod.load(args.config)
        config.update({"data_dir": tmp, "plugins": [], "baby_log": {"provider": "local"},
                       "rhythm": {"source": "fixture", "fixture": str(ROOT / "tests" / "fixtures" / "simweek.json")},
                       "sitter": {"parent_channel": "telegram"}})
        config["allowed_tools"] = [*config["allowed_tools"], "sitter_handover"]
        agent = build(config)
        plugin = sitter.SitterHandover(agent, config, clock=lambda: NOW)
        agent.plugins = [plugin]
        replies, tools = [], []
        agent.bus.subscribe(replies.append, ["reply"])
        agent.bus.subscribe(tools.append, ["tool"])
        agent.handle({"kind": "message", "channel": "telegram", "text": SENTENCE})
        drafts = [r["text"] for r in replies if r["text"].startswith("Draft handover for")]
        result = {"sentence": SENTENCE, "simulated_now": NOW.isoformat(), "brain": agent.brain.name,
                  "model": agent.brain.model, "tools": [(t["name"], t["status"]) for t in tools],
                  "drafts": len(drafts), "sent": False}
        if len(drafts) != 1:
            agent.close()
            print(json.dumps(result, indent=2))
            raise SystemExit("expected exactly one draft, nothing sent")
        text = "Test: " + drafts[0]
        result.update(draft=text, computed_from=plugin.draft["computed_from"], window=[plugin.draft["start"].isoformat(),
                                                                                       plugin.draft["end"].isoformat()])
        print(text)
        if args.send:
            chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
            if len(chats) != 1:
                agent.close()
                raise SystemExit("TELEGRAM_CHAT_ID must hold exactly the parent's one chat id, nothing sent")
            message_id = TelegramMessenger(os.environ.get("TELEGRAM_BOT_TOKEN", "")).send(chats[0], text)
            result.update(sent=True, message_id=message_id)
            print(f"sent, message id {message_id}")
        agent.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
