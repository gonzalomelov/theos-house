"""Muse Spark Open on Baseten (issue #4): the request the brain sends, checked against a fake Baseten server.

The fake answers like Baseten's OpenAI-compatible Chat Completions endpoint (docs.baseten.co, Model APIs and
Function calling, read 2026-10-28): POST {base_url}/chat/completions, Authorization: Bearer <key>, tools as
{"type": "function", "function": {...}}, tool calls back in choices[0].message.tool_calls with JSON string
arguments, and results returned as role "tool" messages with the call's tool_call_id. Local only, no key needed.
"""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.brain import BrainError, OpenAICompatibleBrain
from parenting_agent.house_tools import HouseTools

ROOT = Path(__file__).resolve().parent.parent
MUSE = json.loads((ROOT / "config" / "agent.muse-baseten.json").read_text())
KEY = "test-key-not-real"


class FakeBaseten:
    """Answers each POST with the next scripted reply and keeps what was sent."""

    def __init__(self, replies, status=200):
        self.replies, self.status, self.requests = list(replies), status, []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                answer = fake.replies.pop(0) if fake.status == 200 else {"error": {"message": "Invalid API key"}}
                data = json.dumps(answer).encode()
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def completion(content=None, tool_calls=None, finish_reason="stop"):
    message = {"role": "assistant", "content": content, "reasoning_content": "thinking it over"}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"id": "chatcmpl-1", "object": "chat.completion", "model": MUSE["brain"]["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020}}


def call(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def muse_agent(tmp, base_url, plugins=()):
    config = config_mod.load()
    config.update({**MUSE, "data_dir": tmp, "env_file": "/nonexistent", "baby_log": {"provider": "local"}, "plugins": []})
    config["brain"] = {**MUSE["brain"], "base_url": base_url}
    config["allowed_tools"] = MUSE["allowed_tools"] + ["study_light"]
    agent = build(config)
    for plugin in plugins:
        plugin(agent, config)
    replies = []
    agent.bus.subscribe(lambda e: replies.append(e["text"]), ["reply"])
    return agent, replies


class MuseConfig(unittest.TestCase):
    def test_model_id_and_endpoint_are_baseten_s(self):
        brain = MUSE["brain"]
        self.assertEqual(brain["provider"], "openai_compatible")
        self.assertEqual(brain["model"], "meta-models/muse-spark-open-1026")  # the model id Baseten serves, checked with a real call on 2026-10-28
        self.assertEqual(brain["base_url"], "https://inference.baseten.co/v1")
        self.assertEqual(brain["key_env"], "BASETEN_API_KEY")
        self.assertGreaterEqual(brain["max_tokens"], 2000)  # it always reasons, and reasoning counts against max_tokens

    def test_missing_key_says_what_to_set(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BASETEN_API_KEY", None)
            with self.assertRaises(BrainError) as raised:
                OpenAICompatibleBrain(MUSE["brain"]["model"], MUSE["brain"]["base_url"], "BASETEN_API_KEY")
        message = str(raised.exception)
        self.assertIn("BASETEN_API_KEY is not set", message)
        self.assertIn("meta-models/muse-spark-open-1026 on inference.baseten.co", message)


@mock.patch.dict(os.environ, {"BASETEN_API_KEY": KEY})
class BasetenContract(unittest.TestCase):
    def test_a_tool_round_trip_matches_the_chat_completions_format(self):
        fake = FakeBaseten([
            completion(tool_calls=[call("call_1", "log_baby_event", {"kind": "feeding", "details": {"amount_ml": 90}})]),
            completion("Logged 90 ml."),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            agent, replies = muse_agent(tmp, fake.base_url)
            agent.handle({"kind": "message", "channel": "console", "text": "she drank 90 ml"})
            first, second = fake.requests
            self.assertEqual(first["path"], "/v1/chat/completions")
            self.assertEqual(first["auth"], f"Bearer {KEY}")
            body = first["body"]
            self.assertEqual(body["model"], "meta-models/muse-spark-open-1026")
            self.assertEqual(body["max_tokens"], MUSE["brain"]["max_tokens"])
            self.assertEqual(body["reasoning_effort"], "low")
            self.assertNotIn("n", body)  # Muse Spark Open returns HTTP 400 for n above 1
            self.assertEqual(body["messages"][0]["role"], "system")
            self.assertEqual(body["messages"][-1], {"role": "user", "content": body["messages"][-1]["content"]})
            names = [t["function"]["name"] for t in body["tools"]]
            self.assertEqual(sorted(names), sorted(agent.tools.names()))
            for tool in body["tools"]:
                self.assertEqual(tool["type"], "function")
                self.assertEqual(set(tool["function"]), {"name", "description", "parameters"})
                self.assertEqual(tool["function"]["parameters"]["type"], "object")
            assistant, result = second["body"]["messages"][-2:]
            self.assertEqual(assistant["role"], "assistant")
            self.assertEqual(json.loads(assistant["tool_calls"][0]["function"]["arguments"]),
                             {"kind": "feeding", "details": {"amount_ml": 90}})
            self.assertEqual(result["role"], "tool")
            self.assertEqual(result["tool_call_id"], "call_1")
            self.assertEqual(replies, ["Logged 90 ml."])
            self.assertEqual(agent.baby_log.entries("feeding")[-1]["details"]["amount_ml"], 90)
            brain_calls = [e for e in agent.bus.history if e["kind"] == "brain_call"]
            self.assertEqual([e["destination"] for e in brain_calls], ["127.0.0.1", "127.0.0.1"])
            self.assertNotIn(KEY, (Path(tmp) / "events.jsonl").read_text())
            agent.close()
        fake.close()

    def test_house_tools_reach_muse_and_stay_dry(self):
        fake = FakeBaseten([completion(tool_calls=[call("call_2", "study_light", {"on": True, "warm": True, "brightness_pct": 10})]),
                            completion("The study light would be dimmed, the house is in dry run.")])
        with tempfile.TemporaryDirectory() as tmp:
            agent, replies = muse_agent(tmp, fake.base_url, plugins=[lambda a, c: HouseTools(a, c, client=None)])
            agent.handle({"kind": "message", "channel": "console", "text": "dim the lights for the night feed"})
            sent = [t["function"]["name"] for t in fake.requests[0]["body"]["tools"]]
            self.assertIn("study_light", sent)
            self.assertIn("start_vacuum", sent)  # offered, but it waits for the yes
            tool_message = fake.requests[1]["body"]["messages"][-1]
            self.assertIn("dry run", tool_message["content"])
            self.assertEqual([e["status"] for e in agent.bus.history if e["kind"] == "house_call"], ["dry"])
            agent.close()
        fake.close()

    def test_an_answer_cut_by_max_tokens_is_an_error_not_silence(self):
        fake = FakeBaseten([completion(None, finish_reason="length")])
        with tempfile.TemporaryDirectory() as tmp:
            agent, _ = muse_agent(tmp, fake.base_url)
            with self.assertRaises(BrainError) as raised:
                agent.brain.step("sys", [{"role": "user", "text": "hi"}], [])
            self.assertIn("max_tokens", str(raised.exception))
            agent.close()
        fake.close()

    def test_a_rejected_key_names_the_status(self):
        fake = FakeBaseten([], status=401)
        with tempfile.TemporaryDirectory() as tmp:
            agent, _ = muse_agent(tmp, fake.base_url)
            with self.assertRaises(BrainError) as raised:
                agent.brain.step("sys", [{"role": "user", "text": "hi"}], [])
            self.assertIn("HTTP 401", str(raised.exception))
            agent.close()
        fake.close()


if __name__ == "__main__":
    unittest.main()
