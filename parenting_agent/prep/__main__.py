"""Check the prep mode from a shell, on the Mac or inside the Vostro container.

    python -m parenting_agent.prep show  --config config/agent.vostro.json            # what the nudge would say, sends nothing
    python -m parenting_agent.prep ask   --config config/agent.vostro.json "Test: what is next?"
    python -m parenting_agent.prep nudge --config config/agent.vostro.json --send     # one nudge to Gonza now

ask runs one turn through the real agent and brain on the "cli" channel and prints the answer. Start the message
with "Test:" so the KR scorer never counts it. Nothing is sent on Telegram.
nudge --send sends the morning nudge once to the first chat id in TELEGRAM_CHAT_ID and records the day, so the
running agent does not send it again that day.
"""
import argparse
import json
import queue
import sys

from ..agent import build
from ..agent import config as config_mod


def prep_of(agent):
    for plugin in agent.plugins:
        if plugin.name == "prep":
            return plugin
    raise SystemExit("the prep plug-in is not in this config")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="parenting_agent.prep")
    parser.add_argument("command", choices=["show", "ask", "nudge"])
    parser.add_argument("text", nargs="?")
    parser.add_argument("--config", default="config/agent.json")
    parser.add_argument("--send", action="store_true", help="nudge: really send it")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_intermixed_args(argv)

    config = config_mod.load(args.config)
    if args.command == "ask":
        # Only the prep plug-in: no channel polls and nothing is sent anywhere.
        config["plugins"] = [p for p in config["plugins"] if p.startswith("parenting_agent.prep")]
    agent = build(config)
    prep = prep_of(agent)
    try:
        if args.command == "show":
            print(prep.nudge_text())
            print(json.dumps({"last_nudge": prep.last_nudge(), "nudge_chat_set": prep.gonza_chat() is not None}))
            return 0
        if args.command == "nudge":
            if not args.send:
                print(prep.nudge_text())
                print("not sent, add --send")
                return 0
            text = prep.send_nudge(reason="manual")
            if text is None:
                print("no chat id for the nudge, nothing sent", file=sys.stderr)
                return 1
            sent = [e for e in agent.bus.history if e["kind"] in ("channel_sent", "channel_error")]
            print(json.dumps({"sent": [e["kind"] for e in sent]}))
            return 0 if sent and sent[-1]["kind"] == "channel_sent" else 1
        if not args.text:
            raise SystemExit("ask needs a message")
        replies = queue.Queue()
        agent.bus.subscribe(replies.put, ["reply"])
        agent.start()
        agent.bus.publish("message", channel="cli", text=args.text)
        try:
            reply = replies.get(timeout=args.timeout)
        except queue.Empty:
            print("no answer in time", file=sys.stderr)
            return 1
        tools = [e["name"] for e in agent.bus.history if e["kind"] == "tool"]
        print(json.dumps({"reply": reply["text"], "tools": tools}, ensure_ascii=False, indent=2))
        agent.stop()
        return 0
    finally:
        agent.close()


if __name__ == "__main__":
    raise SystemExit(main())
