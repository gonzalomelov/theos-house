"""Reads Baby Buddy and Home Assistant from inside the running agent container, the way the agent does.
Piped in by agent.sh, never part of the image:

    docker exec -i parenting-agent python - < deploy/probe.py          # Baby Buddy and Home Assistant
    docker exec -i parenting-agent python - token < deploy/probe.py    # one Home Assistant request, the token only

The token mode exits 3 when Home Assistant answers 401 or 403, so agent.sh stops before any other call.
Home Assistant bans an IP after a few failed logins, and the shared client makes no call after the first one.

Prints counts and status codes only, never a token or a baby log entry.
"""
import json
import os
import sys
import urllib.error

from parenting_agent.agent import config as config_mod
from parenting_agent.agent.babybuddy import BabyBuddyError, BabyBuddyLog
from parenting_agent.house import HomeAssistant, TokenRejected

TOKEN_REJECTED_EXIT = 3


def home_assistant():
    token = os.environ.get("HA_MCP_TOKEN")
    if not token:
        return "no HA_MCP_TOKEN"
    try:
        return f"HTTP 200 {(HomeAssistant(os.environ['HA_URL'], token).ping() or {}).get('message', '')}"
    except TokenRejected as error:
        return f"HTTP {error.code} token rejected"
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}"
    except (urllib.error.URLError, TimeoutError) as error:
        return f"unreachable: {error}"


def token_only():
    status = home_assistant()
    print(f"home_assistant_token: {status}")
    if status.endswith("token rejected"):
        return TOKEN_REJECTED_EXIT
    return 0 if status.startswith("HTTP 200") else 1


def main():
    if sys.argv[1:] == ["token"]:
        return token_only()
    config = config_mod.load("config/agent.vostro.json")
    result = {"house": "live" if os.environ.get("HA_TOKEN") else "dry run (no HA_TOKEN)"}
    try:
        log = BabyBuddyLog.from_config(config["baby_log"])
        result["baby_buddy_child_id"] = log.child()
        result["baby_buddy_entries_read"] = len(log.entries(limit=20))
    except BabyBuddyError as error:
        result["baby_buddy_error"] = str(error)[:200]
    if os.environ.get("PA_NO_HA") == "1":
        result["home_assistant_api"] = "skipped, PA_NO_HA=1: no request sent"
        print(json.dumps(result, indent=2))
        return 0 if "baby_buddy_child_id" in result else 1
    result["home_assistant_api"] = home_assistant()
    print(json.dumps(result, indent=2))
    return 0 if "baby_buddy_child_id" in result and result["home_assistant_api"].startswith("HTTP 200") else 1


if __name__ == "__main__":
    raise SystemExit(main())
