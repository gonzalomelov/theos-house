"""Live check of the house plan (issue #29) on the real house, minimal and safe.

    ssh -f -N -L 127.0.0.1:18123:127.0.0.1:8123 vostro
    python scripts/house_plan_check.py

What it does:
- Reads the vacuum, its run flag, the shopping list and presence. No vacuum service is called: pause and return to
  base go through the house writer as a dry run, which records the exact request it would send.
- Decides what the policy would do right now about a vacuum start, from real presence. Nothing starts.
- Adds exactly one item, "Test: diapers (agent check)", to todo.shopping_list through the house writer, reads the
  list back, removes the item and reads the list back again.
- Writes results/house-plan/live-check.json. No token is printed or saved.
"""
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent import house_plan as hp  # noqa: E402
from parenting_agent.agent import config as config_mod  # noqa: E402
from parenting_agent.bus import Bus  # noqa: E402
from parenting_agent.house import HomeAssistant  # noqa: E402

OUT = ROOT / "results/house-plan/live-check.json"
TEST_ITEM = "Test: diapers (agent check)"
KEEP = ("status_desc", "vacuum.status_desc", "battery_level", "fan_speed", "supported_features", "friendly_name")


def items(client):
    response = client.response("todo.get_items", hp.SHOPPING)
    return [i["summary"] for i in response["service_response"][hp.SHOPPING]["items"]]


def main():
    config = config_mod.load(ROOT / "config/agent.json")
    config_mod.load_env(config["env_file"])
    settings = hp.DEFAULTS
    client = HomeAssistant(settings["ha_url"], os.environ[settings["ha_token_env"]])
    bus = Bus()
    now = datetime.datetime.now().astimezone()
    out = {"at": now.isoformat(timespec="seconds"), "issue": 29}

    attrs = client.attributes(hp.VACUUM)
    features = attrs.get("supported_features") or 0
    out["vacuum"] = {"entity": hp.VACUUM, "state": client.state(hp.VACUUM),
                     "attributes": {k: attrs[k] for k in KEEP if k in attrs},
                     "run_active": client.state("input_boolean.xiaomi_vacuum_run_active"),
                     "supports_pause": bool(features & 4), "supports_return_to_base": bool(features & 16),
                     "supports_start": bool(features & 8192), "supports_clean_area": bool(features & hp.CLEAN_AREA_FEATURE)}

    dry = hp.HouseWriter(bus, client, live=False)
    out["dock_dry_run"] = [dry.call("vacuum.pause", hp.VACUUM, None, "live check, dry run")["request"],
                           dry.call("vacuum.return_to_base", hp.VACUUM, None, "live check, dry run")["request"]]
    out["room_clean_dry_run"] = dry.call("vacuum.clean_area", hp.VACUUM,
                                         {"cleaning_area_id": [hp.room_for("clean under the high chair")]},
                                         "voice: clean under the high chair")["request"]
    out["vacuum_after"] = {"state": client.state(hp.VACUUM),
                           "run_active": client.state("input_boolean.xiaomi_vacuum_run_active")}

    presence = {p: client.state(p) for p in settings["persons"]}
    presence["device_tracker.gonzas_iphone"] = client.state("device_tracker.gonzas_iphone")
    alone = hp.nobody_home({p: presence[p] for p in settings["persons"]})
    out["start_policy_now"] = {"presence": presence, "nobody_home": alone,
                               "decision": "start alone" if alone else "ask the parent first"}

    live = hp.HouseWriter(bus, client, live=True)
    before = items(client)
    if TEST_ITEM in before:
        raise SystemExit(f"{TEST_ITEM!r} is already on the list, remove it by hand first")
    added = live.call("todo.add_item", hp.SHOPPING, {"item": TEST_ITEM}, "live check")
    with_item = items(client)
    removed = live.call("todo.remove_item", hp.SHOPPING, {"item": TEST_ITEM}, "live check")
    after = items(client)
    out["shopping_list"] = {"entity": hp.SHOPPING, "items_before": len(before), "added": added["kind"],
                            "found_after_add": TEST_ITEM in with_item, "removed": removed["kind"],
                            "found_after_remove": TEST_ITEM in after, "items_after": len(after)}

    out["writes_sent"] = [e["action"] for e in bus.history if e["kind"] == "house_done"]
    out["dry_runs"] = [e["action"] for e in bus.history if e["kind"] == "house_dry"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
