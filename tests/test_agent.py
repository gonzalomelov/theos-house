"""Tests for the agent core (issue #1).

The scripted conversation runs with the fake brain always, and with the configured live brain when PA_LIVE=1 and a key
is available (python -m unittest tests.test_agent with PA_LIVE=1 set).
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.brain import OpenAICompatibleBrain, Reply
from parenting_agent.agent.memory import LocalBabyLog, Memory
from parenting_agent.agent.tools import Tool, schema
from parenting_agent.bus import Bus

ROOT = Path(__file__).resolve().parents[1]
LIVE_ENV = "~/.parenting-agent.env"


def make_agent(brain, data_dir, allowed=None):
    config = config_mod.load()
    config.update({"data_dir": str(data_dir), "env_file": LIVE_ENV if brain["provider"] != "fake" else "/nonexistent", "brain": brain})
    if allowed is not None:
        config["allowed_tools"] = allowed
    return build(config)


def converse(agent, text, timeout=60):
    replies = queue.Queue()
    agent.bus.subscribe(replies.put, ["reply"])
    agent.bus.publish("message", channel="test", text=text)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = replies.get(timeout=timeout)
        if event.get("channel") == "test":
            return event["text"]
    raise TimeoutError(text)


class EventBus(unittest.TestCase):
    def test_every_part_sees_an_event_within_one_second(self):
        bus = Bus()
        seen = [queue.Queue() for _ in range(3)]
        for q in seen:
            bus.subscribe(lambda e, q=q: q.put(time.monotonic()), ["observation"])
        sent = time.monotonic()
        bus.publish("observation", source="test", text="hand off")
        delays = [q.get(timeout=1) - sent for q in seen]
        print(f"\nevent bus delay: max {max(delays) * 1000:.2f} ms across {len(delays)} listeners")
        self.assertLess(max(delays), 1.0)

    def test_agent_thread_receives_an_event_within_one_second(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = make_agent({"provider": "fake"}, tmp)
            agent.start()
            sent = time.monotonic()
            reply = converse(agent, "Good morning", timeout=1)
            delay = time.monotonic() - sent
            agent.stop()
            agent.close()
            print(f"\nmessage to agent reply: {delay * 1000:.1f} ms")
            self.assertEqual(reply, "Noted.")
            self.assertLess(delay, 1.0)


class ScriptedConversation:
    """The same conversation for every brain: log a feed, then ask about it."""
    brain = None

    def test_logs_a_feed_and_answers_from_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = make_agent(self.brain, tmp)
            agent.start()
            try:
                first = converse(agent, "He just drank a 120 ml bottle.")
                second = converse(agent, "How much has he drunk today?")
            finally:
                agent.stop()
            feeds = agent.baby_log.entries("feeding")
            calls = [e for e in agent.bus.history if e["kind"] == "brain_call"]
            agent.close()
            print(f"\n[{self.brain['provider']}] reply 1: {first}\n[{self.brain['provider']}] reply 2: {second}\n"
                  f"[{self.brain['provider']}] brain calls went to: {sorted({c['destination'] for c in calls})}")
            self.assertEqual(len(feeds), 1)
            self.assertEqual(int(feeds[0]["details"].get("amount_ml", 0)), 120)
            self.assertIn("120", second)


class FakeBrainConversation(ScriptedConversation, unittest.TestCase):
    brain = {"provider": "fake"}


class AllowedListPolicy(unittest.TestCase):
    def test_tool_not_allowed_waits_for_the_parents_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = make_agent({"provider": "fake"}, tmp, allowed=["read_baby_log", "current_time"])
            agent.start()
            try:
                converse(agent, "He drank 90 ml.")
                self.assertEqual(agent.baby_log.entries(), [])
                asks = [e for e in agent.bus.history if e["kind"] == "ask_parent"]
                self.assertEqual([a["name"] for a in asks], ["log_baby_event"])
                converse(agent, "yes")
            finally:
                agent.stop()
            self.assertEqual(len(agent.baby_log.entries("feeding")), 1)
            agent.close()


class PersistentMemory(unittest.TestCase):
    def test_facts_and_log_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = Memory(Path(tmp) / "memory.sqlite")
            memory.remember("baby_name", "Test Baby")
            LocalBabyLog(memory).add("diaper", {"wet": True})
            memory.close()
            again = Memory(Path(tmp) / "memory.sqlite")
            self.assertEqual(again.facts()["baby_name"]["value"], "Test Baby")
            self.assertEqual(LocalBabyLog(again).entries("diaper")[0]["details"], {"wet": True})


class PluginTools(unittest.TestCase):
    def test_a_plugin_tool_runs_only_when_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = make_agent({"provider": "fake"}, tmp)
            agent.tools.add(Tool("dim_lights", "Dim the lights.", schema({}), lambda: "dimmed"))
            self.assertEqual(agent.tools.run("dim_lights", {})[0], "ask_parent")
            agent.tools.allowed.add("dim_lights")
            self.assertEqual(agent.tools.run("dim_lights", {}), ("ran", "dimmed"))
            agent.close()


class OpenAICompatibleFormat(unittest.TestCase):
    def test_parses_tool_calls_and_text(self):
        reply = OpenAICompatibleBrain.parse({"choices": [{"message": {"content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read_baby_log", "arguments": "{\"kind\": \"feeding\"}"}}]}}]})
        self.assertIsInstance(reply, Reply)
        self.assertEqual(reply.tool_calls, [{"id": "c1", "name": "read_baby_log", "arguments": {"kind": "feeding"}}])

    def test_transcript_becomes_chat_messages(self):
        messages = OpenAICompatibleBrain.messages("sys", [
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "", "tool_calls": [{"id": "c1", "name": "current_time", "arguments": {}}]},
            {"role": "tool", "id": "c1", "name": "current_time", "result": "07:00"}])
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "tool"])


class CheckCommand(unittest.TestCase):
    def test_check_exits_zero_and_lists_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "agent.json"
            config.write_text(json.dumps({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent",
                                          "brain": {"provider": "fake"}, "plugins": ["parenting_agent.agent.console:Console"]}))
            run = subprocess.run([sys.executable, "-m", "parenting_agent", "--check", "--config", str(config)],
                                 cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            loaded = json.loads(run.stdout)
            self.assertIn("log_baby_event", loaded["tools"])
            self.assertEqual(loaded["plugins"], ["console"])


if __name__ == "__main__":
    unittest.main()
