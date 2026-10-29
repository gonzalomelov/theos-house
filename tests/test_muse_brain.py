"""Muse Spark Open is the brain of every running agent (issue #4). Claude answers only when a Muse call errors,
and that fallback is always visible: a brain_fallback event, a stderr line and a count. Local only, no key needed."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from parenting_agent import reasoning
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.brain import BrainError, FallbackBrain, OpenAICompatibleBrain, Reply, without_thinking
from parenting_agent.demo import settings as demo_settings
from parenting_agent.families import settings as families_settings
from tests.test_baseten_contract import FakeBaseten, completion

ROOT = Path(__file__).resolve().parent.parent
MUSE_MODEL = "meta-models/muse-spark-open-1026"
KEYS = {"BASETEN_API_KEY": "test-key-not-real", "ANTHROPIC_API_KEY": "test-key-not-real"}


class Scripted:
    def __init__(self, name, model, replies):
        self.name, self.model, self.destination, self.replies, self.calls = name, model, name + ".test", list(replies), 0

    def step(self, system, transcript, tools):
        self.calls += 1
        answer = self.replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class EveryAgentRunsMuse(unittest.TestCase):
    def test_the_family_agent_configs_name_muse_with_claude_only_as_fallback(self):
        for name in ("agent.json", "agent.vostro.json"):
            brain = json.loads((ROOT / "config" / name).read_text())["brain"]
            self.assertEqual((brain["provider"], brain["model"]), ("openai_compatible", MUSE_MODEL), name)
            self.assertEqual(brain["base_url"], "https://inference.baseten.co/v1", name)
            self.assertEqual(brain["fallback"]["provider"], "claude", name)

    def test_the_demo_and_the_families_bot_default_to_muse(self):
        self.assertEqual(demo_settings.load({})["brain"]["model"], MUSE_MODEL)
        self.assertEqual(families_settings.load({})["brain"]["model"], MUSE_MODEL)
        self.assertEqual(demo_settings.load({})["brain"]["fallback"]["provider"], "claude")

    def test_every_egress_allowlist_lets_baseten_through(self):
        for path in ("deploy/egress/filter", "deploy/demo/egress/filter", "deploy/families/egress/filter"):
            self.assertIn(r"^inference\.baseten\.co$", (ROOT / path).read_text().split(), path)

    def test_the_deploys_need_the_baseten_key(self):
        for path in ("deploy/demo/compose.yml", "deploy/families/compose.yml"):
            text = (ROOT / path).read_text()
            self.assertIn("BASETEN_API_KEY: ${BASETEN_API_KEY:?", text, path)
            self.assertIn(":-baseten}", text, path)

    @mock.patch.dict(os.environ, KEYS)
    def test_the_vostro_config_builds_a_muse_brain_with_a_claude_fallback(self):
        config = json.loads((ROOT / "config" / "agent.vostro.json").read_text())
        brain = __import__("parenting_agent.agent.brain", fromlist=["build"]).build(config["brain"])
        self.assertIsInstance(brain, FallbackBrain)
        self.assertEqual((brain.name, brain.model, brain.destination), ("openai_compatible", MUSE_MODEL, "inference.baseten.co"))


class Fallback(unittest.TestCase):
    def test_muse_answers_and_no_fallback_is_logged(self):
        lines = []
        brain = FallbackBrain(Scripted("muse", MUSE_MODEL, [Reply("ok")]), Scripted("claude", "haiku", []), log=lines.append)
        reply = brain.step("s", [], [])
        self.assertEqual((reply.text, reply.fallback, brain.fallbacks, lines), ("ok", None, 0, []))

    def test_a_muse_error_falls_back_and_says_so(self):
        lines = []
        brain = FallbackBrain(Scripted("muse", MUSE_MODEL, [BrainError("HTTP 503: busy")]),
                              Scripted("claude", "haiku", [Reply("from claude")]), log=lines.append)
        reply = brain.step("s", [], [])
        self.assertEqual(reply.text, "from claude")
        self.assertEqual(reply.fallback["from_model"], MUSE_MODEL)
        self.assertIn("HTTP 503", reply.fallback["error"])
        self.assertEqual((brain.fallbacks, brain.model), (1, "haiku"))
        self.assertTrue(lines[0].startswith("brain_fallback "))

    @mock.patch.dict(os.environ, KEYS)
    def test_the_agent_logs_each_fallback_as_an_event(self):
        fake = FakeBaseten([], status=503)
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load()
            config.update({"data_dir": tmp, "env_file": "/nonexistent", "baby_log": {"provider": "local"}, "plugins": []})
            agent = build(config)
            agent.brain = FallbackBrain(OpenAICompatibleBrain(MUSE_MODEL, fake.base_url, "BASETEN_API_KEY"),
                                        Scripted("claude", "claude-haiku-5-5", [Reply("Hi.")]), log=lambda line: None)
            replies = []
            agent.bus.subscribe(lambda e: replies.append(e["text"]), ["reply"])
            agent.handle({"kind": "message", "channel": "console", "text": "hello"})
            fallbacks = [e for e in agent.bus.history if e["kind"] == "brain_fallback"]
            calls = [e for e in agent.bus.history if e["kind"] == "brain_call"]
            self.assertEqual(len(fallbacks), 1)
            self.assertEqual((calls[0]["model"], calls[0]["fallback"]), ("claude-haiku-5-5", True))
            self.assertEqual(replies, ["Hi."])
            agent.close()
        fake.close()

    @mock.patch.dict(os.environ, {"BASETEN_API_KEY": "test-key-not-real"})
    def test_a_missing_fallback_key_keeps_muse_alone(self):
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        with mock.patch.dict(os.environ, env, clear=True):
            brain = __import__("parenting_agent.agent.brain", fromlist=["build"]).build(
                {"provider": "openai_compatible", "model": MUSE_MODEL, "base_url": "https://inference.baseten.co/v1",
                 "key_env": "BASETEN_API_KEY", "fallback": {"provider": "claude"}})
        self.assertIsInstance(brain, OpenAICompatibleBrain)


@mock.patch.dict(os.environ, KEYS)
class MuseReasoningNeverLeaks(unittest.TestCase):
    def test_thoughts_inside_the_answer_text_are_cut(self):
        self.assertEqual(without_thinking("<think>the baby is 3 days old</think>Logged 90 ml."), "Logged 90 ml.")
        self.assertEqual(without_thinking("Anotado.<think>unfinished"), "Anotado.")

    def test_reasoning_content_is_never_read_and_its_tokens_are_counted(self):
        reply = completion("Anotado, 90 ml.")
        reply["choices"][0]["message"]["reasoning_content"] = "SECRET THOUGHT"
        reply["usage"]["completion_tokens_details"] = {"reasoning_tokens": 77}
        parsed = OpenAICompatibleBrain.parse(reply)
        self.assertEqual(parsed.text, "Anotado, 90 ml.")
        self.assertEqual(parsed.usage["reasoning_tokens"], 77)

    def test_a_priced_brain_puts_the_cost_on_the_reply(self):
        fake = FakeBaseten([completion("ok")])
        brain = OpenAICompatibleBrain(MUSE_MODEL, fake.base_url, "BASETEN_API_KEY", prices=(1.25, 4.25))
        reply = brain.step("s", [{"role": "user", "text": "hi"}], [])
        self.assertAlmostEqual(reply.usd, (900 * 1.25 + 120 * 4.25) / 1_000_000)
        fake.close()

    def test_the_house_reasoning_runs_on_muse_spark_open(self):
        fake = FakeBaseten([completion('{"action": "study_light", "ask_parent": false, "why": "nap"}')])
        slow = reasoning.build({"provider": "muse", "url": fake.base_url + "/chat/completions"})
        proposal = slow.decide({"nap": True}, {"study_light"})
        self.assertEqual(proposal["action"], "study_light")
        self.assertEqual(fake.requests[0]["body"]["model"], MUSE_MODEL)
        fake.close()


if __name__ == "__main__":
    unittest.main()
