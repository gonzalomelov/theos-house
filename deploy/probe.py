"""Reads Baby Buddy and Home Assistant from inside the running agent container, the way the agent does.
Piped in by agent.sh, never part of the image:

    docker exec -i parenting-agent python - < deploy/probe.py

Prints counts and status codes only, never a token or a baby log entry.
"""
import json
import os
import urllib.error
import urllib.request

from parenting_agent.agent import config as config_mod
from parenting_agent.agent.babybuddy import BabyBuddyError, BabyBuddyLog


def home_assistant():
    token = os.environ.get("HA_MCP_TOKEN")
    if not token:
        return "no HA_MCP_TOKEN"
    request = urllib.request.Request(os.environ["HA_URL"] + "/api/", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return f"HTTP {response.status} {json.loads(response.read()).get('message', '')}"
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}"
    except (urllib.error.URLError, TimeoutError) as error:
        return f"unreachable: {error}"


def main():
    config = config_mod.load("config/agent.vostro.json")
    result = {"house": "live" if os.environ.get("HA_TOKEN") else "dry run (no HA_TOKEN)"}
    try:
        log = BabyBuddyLog.from_config(config["baby_log"])
        result["baby_buddy_child_id"] = log.child()
        result["baby_buddy_entries_read"] = len(log.entries(limit=20))
    except BabyBuddyError as error:
        result["baby_buddy_error"] = str(error)[:200]
    result["home_assistant_api"] = home_assistant()
    print(json.dumps(result, indent=2))
    return 0 if "baby_buddy_child_id" in result and result["home_assistant_api"].startswith("HTTP 200") else 1


if __name__ == "__main__":
    raise SystemExit(main())
