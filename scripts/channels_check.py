"""Real checks for the Telegram channel (#3) and channel picking (#8). Sends at most 2 Telegram messages
and makes one Home Assistant announce, all prefixed "Test:".

    python scripts/channels_check.py --telegram   # answer the newest family message through the real agent
    python scripts/channels_check.py --speaker    # one low-volume announce on the kitchen Echo
    python scripts/channels_check.py --away       # a reminder routed with presence simulated as away

Needs the tunnels to Home Assistant (127.0.0.1:18123) and Baby Buddy (127.0.0.1:18790). Writes
results/channels/check.json. No token or chat id is written.
"""
import argparse
import json
import queue
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent.agent import build  # noqa: E402
from parenting_agent.agent import config as config_mod  # noqa: E402
from parenting_agent.channels.router import Router, Situation  # noqa: E402
from parenting_agent.channels.telegram import Telegram  # noqa: E402

OUT = ROOT / "results" / "channels" / "check.json"


def make(config_path, data_dir):
    config = config_mod.load(config_path)
    config.update({"data_dir": data_dir, "plugins": []})
    config["telegram"] = {**config.get("telegram", {}), "prefix": "Test: ", "poll_timeout_s": 5}
    agent = build(config)
    telegram, router = Telegram(agent, config), Router(agent, config)
    agent.plugins = [telegram, router]
    return agent, telegram, router


def newest_family_message(agent, telegram):
    """Skip to the newest update, so only the most recent family message is answered."""
    batch = telegram.messenger.poll(telegram.read_offset(), 0)
    if not batch:
        return None
    telegram.save_offset(batch[-1].update_id)
    return telegram.poll_once(0)


def check_telegram(agent, telegram):
    sent = queue.Queue()
    agent.bus.subscribe(sent.put, ["channel_sent", "channel_error"])
    agent.start()
    accepted = newest_family_message(agent, telegram)
    if not accepted:
        return {"passed": False, "note": "no family message waiting in getUpdates"}
    event = sent.get(timeout=120)
    replies = [e for e in agent.bus.history if e["kind"] == "reply" and e.get("channel") == "telegram"]
    return {"passed": event["kind"] == "channel_sent", "heard": accepted[-1].text, "reply": replies[-1]["text"] if replies else None,
            "message_id": event.get("message_id"), "brain": agent.brain.name, "ignored": agent.bus.count("channel_ignored")}


def check_speaker(router):
    if router.client is None:
        return {"passed": False, "note": "no Home Assistant token"}
    presence = router.presence()
    started = time.monotonic()
    channel, result = router.deliver("Test: the parenting agent can speak in the kitchen.", Situation("home"))
    if router.outputs["home_speaker"].restorer:
        router.outputs["home_speaker"].restorer.join()
    volume_after = None
    for _ in range(10):  # Home Assistant reports the restored volume a moment after the call
        volume_after = router.client.attributes("media_player.gonza_s_echo_dot").get("volume_level")
        if volume_after == result.get("volume_before"):
            break
        time.sleep(0.5)
    return {"passed": channel == "home_speaker" and bool(result.get("confirmed")), "live_presence": presence,
            "channel": channel, "seconds": round(time.monotonic() - started, 3), "volume_restored_to": volume_after,
            **{k: v for k, v in result.items() if k != "response"}, "ha_response_ok": result.get("response") is not None}


def check_away(agent, router):
    sent = queue.Queue()
    agent.bus.subscribe(sent.put, ["channel_sent", "channel_error"])
    router._presence = lambda: "away"
    agent.bus.publish("notify", text="reminder, the next feed is due in about 30 minutes.")
    event = sent.get(timeout=20)
    routed = next(e for e in reversed(agent.bus.history) if e["kind"] == "routed")
    return {"passed": routed["channel"] == "telegram" and event["kind"] == "channel_sent", "simulated_presence": "away",
            "channel": routed["channel"], "reason": routed["reason"], "message_id": event.get("message_id")}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config" / "agent.json"))
    parser.add_argument("--data-dir", default=str(ROOT / "data-channels-check"))
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--speaker", action="store_true")
    parser.add_argument("--away", action="store_true")
    args = parser.parse_args(argv)
    agent, telegram, router = make(args.config, args.data_dir)
    results = json.loads(OUT.read_text()) if OUT.exists() else {}
    try:
        if args.telegram:
            results["telegram_round_trip"] = check_telegram(agent, telegram)
        if args.speaker:
            results["home_speaker_announce"] = check_speaker(router)
        if args.away:
            results["reminder_away_to_telegram"] = check_away(agent, router)
    finally:
        agent.stop()
        agent.close()
    for value in results.values():
        value.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if all(v.get("passed") for v in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
