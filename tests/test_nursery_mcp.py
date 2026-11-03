"""The read-only MCP server for Muse (deploy/nursery-mcp): the key, the one tool, and no way to write.

Offline: Home Assistant is a fake function. No network, no house.
"""
import datetime
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("nursery_mcp", Path(__file__).resolve().parent.parent / "deploy/nursery-mcp/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

NOW = datetime.datetime(2026, 11, 3, 13, 0, tzinfo=datetime.timezone.utc)


def fake(minutes_ago=1, value="21.5"):
    def fetch(entity):
        return {"state": value, "last_reported": (NOW - datetime.timedelta(minutes=minutes_ago)).isoformat()}
    return fetch


class Reading(unittest.TestCase):
    def test_fresh_values_and_guide(self):
        r = server.reading(fake(), NOW)
        self.assertEqual((r["temperature_c"], r["humidity_pct"]), (21.5, 21.5))
        self.assertEqual((r["guide"]["low_c"], r["guide"]["high_c"]), (16, 20))

    def test_stale_or_bad_is_null(self):
        self.assertIsNone(server.reading(fake(minutes_ago=6), NOW)["temperature_c"])
        self.assertIsNone(server.reading(fake(value="unavailable"), NOW)["temperature_c"])

    def test_failed_read_is_null(self):
        def fail(entity):
            raise OSError("down")
        self.assertIsNone(server.reading(fail, NOW)["humidity_pct"])


class Rpc(unittest.TestCase):
    def test_one_read_only_tool(self):
        tools = server.rpc({"id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["nursery_climate"])
        self.assertTrue(tools[0]["annotations"]["readOnlyHint"])

    def test_call_returns_the_reading(self):
        server_now = server.reading
        server.reading = lambda fetch: server_now(fetch, NOW)
        try:
            result = server.rpc({"id": 2, "method": "tools/call", "params": {"name": "nursery_climate"}}, fake())["result"]
        finally:
            server.reading = server_now
        self.assertEqual(result["structuredContent"]["temperature_c"], 21.5)
        self.assertFalse(result["isError"])

    def test_unknown_tool_and_notification(self):
        self.assertIn("error", server.rpc({"id": 3, "method": "tools/call", "params": {"name": "light_on"}}))
        self.assertIsNone(server.rpc({"method": "notifications/initialized"}))


class Key(unittest.TestCase):
    def test_key_is_required(self):
        self.assertTrue(server.authorized({"Authorization": "Bearer k1"}, "k1"))
        self.assertTrue(server.authorized({"X-API-Key": "k1"}, "k1"))
        self.assertFalse(server.authorized({"Authorization": "Bearer no"}, "k1"))
        self.assertFalse(server.authorized({}, "k1"))
        self.assertFalse(server.authorized({"Authorization": "Bearer "}, ""))


if __name__ == "__main__":
    unittest.main()
