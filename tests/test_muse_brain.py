"""Muse Spark Open is the brain of every running agent (issue #4), the only model. When a Muse call errors the fixed
rules answer, never another vendor's model, and that fallback is always visible: the reply says the brain is busy, a
brain_fallback event, a stderr line and a count. Local only, no key needed."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from parenting_agent import reasoning
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.agent import brain as brain_mod
from parenting_agent.agent.brain import BrainError, FallbackBrain, OpenAICompatibleBrain, Reply, RulesBrain, without_thinking
from parenting_agent.agent.loop import TEXTS
from parenting_agent.demo import settings as demo_settings
from parenting_agent.families import settings as families_settings
from tests.test_baseten_contract import FakeBaseten, completion

ROOT = Path(__file__).resolve().parent.parent
MUSE_MODEL = "meta-models/muse-spark-open-1026"
KEYS = {"BASETEN_API_KEY": "test-key-not-real"}


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
    def test_the_family_agent_configs_name_muse_with_the_fixed_rules_as_fallback(self):
        for name in ("agent.json", "agent.vostro.json"):
            brain = json.loads((ROOT / "config" / name).read_text())["brain"]
            self.assertEqual((brain["provider"], brain["model"]), ("openai_compatible", MUSE_MODEL), name)
            self.assertEqual(brain["base_url"], "https://inference.baseten.co/v1", name)
            self.assertEqual(brain["fallback"], {"provider": "rules"}, name)

    def test_the_demo_and_the_families_bot_default_to_muse(self):
        self.assertEqual(demo_settings.load({})["brain"]["model"], MUSE_MODEL)
        self.assertEqual(families_settings.load({})["brain"]["model"], MUSE_MODEL)
        self.assertEqual(demo_settings.load({})["brain"]["fallback"], {"provider": "rules"})
        self.assertNotIn("claude", demo_settings.BRAINS)

    def test_every_egress_allowlist_lets_baseten_through_and_no_other_model_host(self):
        for path in ("deploy/egress/filter", "deploy/demo/egress/filter", "deploy/families/egress/filter"):
            hosts = (ROOT / path).read_text().split()
            self.assertIn(r"^inference\.baseten\.co$", hosts, path)
            self.assertNotIn(r"^api\.anthropic\.com$", hosts, path)

    def test_the_deploys_need_the_baseten_key_and_no_anthropic_key(self):
        for path in ("deploy/demo/compose.yml", "deploy/families/compose.yml", "deploy/agent.sh", "deploy/public.sh",
                     "deploy/env.example", "deploy/families/env.example"):
            text = (ROOT / path).read_text()
            self.assertNotIn("ANTHROPIC", text, path)
        for path in ("deploy/demo/compose.yml", "deploy/families/compose.yml"):
            text = (ROOT / path).read_text()
            self.assertIn("BASETEN_API_KEY: ${BASETEN_API_KEY:?", text, path)
            self.assertIn(":-baseten}", text, path)

    def test_no_runtime_code_calls_another_vendors_model(self):
        for path in (ROOT / "parenting_agent").rglob("*.py"):
            source = path.read_text()
            for word in ("api.anthropic.com", "ANTHROPIC_API_KEY", "claude-haiku", "api.openai.com"):
                self.assertNotIn(word, source, f"{path.relative_to(ROOT)} names {word}")

    @mock.patch.dict(os.environ, KEYS)
    def test_the_vostro_config_builds_a_muse_brain_with_a_rules_fallback(self):
        config = json.loads((ROOT / "config" / "agent.vostro.json").read_text())
        brain = brain_mod.build(config["brain"])
        self.assertIsInstance(brain, FallbackBrain)
        self.assertEqual((brain.name, brain.model, brain.destination), ("openai_compatible", MUSE_MODEL, "inference.baseten.co"))
        self.assertIsInstance(brain.backup, RulesBrain)

    def test_another_vendors_model_is_refused(self):
        with self.assertRaises(BrainError):
            brain_mod.build({"provider": "claude", "model": "claude-haiku-5-5"})
        with mock.patch.dict(os.environ, KEYS):
            with self.assertRaises(BrainError):
                brain_mod.build({"provider": "openai_compatible", "model": MUSE_MODEL, "base_url": "https://inference.baseten.co/v1",
                                 "key_env": "BASETEN_API_KEY", "fallback": {"provider": "claude"}})
        with self.assertRaises(reasoning.Unavailable):
            reasoning.build({"provider": "claude"})


class Fallback(unittest.TestCase):
    def test_muse_answers_and_no_fallback_is_logged(self):
        lines = []
        brain = FallbackBrain(Scripted("muse", MUSE_MODEL, [Reply("ok")]), RulesBrain(), log=lines.append)
        reply = brain.step("s", [], [])
        self.assertEqual((reply.text, reply.fallback, brain.fallbacks, lines), ("ok", None, 0, []))

    def test_a_muse_error_falls_back_to_the_rules_and_says_so(self):
        lines = []
        brain = FallbackBrain(Scripted("muse", MUSE_MODEL, [BrainError("HTTP 503: busy")]), RulesBrain(), log=lines.append)
        reply = brain.step("s", [{"role": "user", "text": "hello"}], [])
        self.assertEqual(reply.fallback["from_model"], MUSE_MODEL)
        self.assertEqual(reply.fallback["to_model"], "fixed rules")
        self.assertIn("HTTP 503", reply.fallback["error"])
        self.assertEqual((brain.fallbacks, brain.name, brain.destination), (1, "rules", "none (local)"))
        self.assertTrue(lines[0].startswith("brain_fallback "))

    def agent(self, tmp, fake, **extra):
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "baby_log": {"provider": "local"}, "plugins": [], **extra})
        agent = build(config)
        agent.brain = FallbackBrain(OpenAICompatibleBrain(MUSE_MODEL, fake.base_url, "BASETEN_API_KEY"), RulesBrain(),
                                    log=lambda line: None)
        replies = []
        agent.bus.subscribe(lambda e: replies.append(e["text"]), ["reply"])
        return agent, replies

    @mock.patch.dict(os.environ, KEYS)
    def test_the_agent_logs_each_fallback_and_tells_the_parent_the_brain_is_busy(self):
        fake = FakeBaseten([], status=503)
        with tempfile.TemporaryDirectory() as tmp:
            agent, replies = self.agent(tmp, fake)
            agent.handle({"kind": "message", "channel": "console", "text": "hello"})
            fallbacks = [e for e in agent.bus.history if e["kind"] == "brain_fallback"]
            calls = [e for e in agent.bus.history if e["kind"] == "brain_call"]
            self.assertEqual(len(fallbacks), 1)
            self.assertEqual((calls[0]["model"], calls[0]["fallback"], calls[0]["destination"]),
                             ("fixed rules", True, "none (local)"))
            self.assertTrue(replies[0].startswith(TEXTS["en"]["BRAIN_BUSY"]), replies)
            agent.close()
        fake.close()

    @mock.patch.dict(os.environ, KEYS)
    def test_a_spanish_note_is_logged_by_the_rules_and_said_in_spanish(self):
        fake = FakeBaseten([], status=503)
        with tempfile.TemporaryDirectory() as tmp:
            agent, replies = self.agent(tmp, fake)
            agent.handle({"kind": "message", "channel": "console", "text": "le di 120 ml de mamadera"})
            feeds = agent.baby_log.entries("feeding", None, 10)
            self.assertEqual([float(f["details"]["amount_ml"]) for f in feeds], [120.0])
            self.assertTrue(replies[0].startswith(TEXTS["es"]["BRAIN_BUSY"]), replies)
            self.assertIn("120 ml", replies[0])
            self.assertNotIn("Done", replies[0])
            agent.close()
        fake.close()

    @mock.patch.dict(os.environ, KEYS)
    def test_the_next_turn_after_muse_is_back_says_nothing_about_being_busy(self):
        fake = FakeBaseten([], status=503)
        with tempfile.TemporaryDirectory() as tmp:
            agent, replies = self.agent(tmp, fake)
            agent.handle({"kind": "message", "channel": "console", "text": "hello"})
            agent.brain.primary = Scripted("muse", MUSE_MODEL, [Reply("Hi there.")])
            agent.handle({"kind": "message", "channel": "console", "text": "hello again"})
            self.assertEqual(replies[-1], "Hi there.")
            agent.close()
        fake.close()


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


class AQuestionIsNeverLogged(unittest.TestCase):
    """On the Vostro on Oct 28, Muse answered "¿cuánto tomó hoy?" by logging a second bottle with no amount."""

    def run_turn(self, text, calls):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load()
            config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"},
                           "baby_log": {"provider": "local"}, "plugins": []})
            agent = build(config)
            agent.brain = Scripted("muse", MUSE_MODEL, calls)
            agent.handle({"kind": "message", "channel": "console", "text": text})
            entries = agent.baby_log.entries("feeding", None, 10)
            agent.close()
        return entries

    def test_a_question_holds_a_log_call(self):
        log = Reply(tool_calls=[{"id": "1", "name": "log_baby_event", "arguments": {"kind": "feeding", "details": {}}}])
        self.assertEqual(self.run_turn("¿cuánto tomó hoy?", [log, Reply("Hoy no hay tomas anotadas.")]), [])

    def test_a_note_with_a_question_mark_and_an_amount_still_logs(self):
        log = Reply(tool_calls=[{"id": "1", "name": "log_baby_event",
                                 "arguments": {"kind": "feeding", "details": {"amount_ml": 120, "method": "bottle"}}}])
        self.assertEqual(len(self.run_turn("le di 120 ml de mamadera, ¿está bien?", [log, Reply("Anotada.")])), 1)


class OnlyRealChangesAreSaid(unittest.TestCase):
    def test_a_no_op_edit_beside_a_real_one_is_not_said(self):
        from parenting_agent.agent.loop import changes_text
        bottle = {"kind": "feeding", "ts": "2026-10-28T22:56:00-03:00", "details": {"amount_ml": 120, "method": "bottle"}}
        diaper = {"kind": "diaper", "ts": "2026-10-28T22:56:00-03:00", "details": {"wet": True, "solid": True}}
        said = changes_text([{"before": diaper, "after": diaper},
                             {"before": bottle, "after": {**bottle, "details": {**bottle["details"], "amount_ml": 100}}}], "es")
        self.assertEqual(len(said), 1)
        self.assertIn("100 ml", said[0])


class AnObservationIsNeverLogged(unittest.TestCase):
    def test_a_doorbell_observation_does_not_log_an_earlier_bottle_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load()
            config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"},
                           "baby_log": {"provider": "local"}, "plugins": []})
            agent = build(config)
            agent.brain = Scripted("muse", MUSE_MODEL, [
                Reply(tool_calls=[{"id": "1", "name": "log_baby_event",
                                   "arguments": {"kind": "feeding", "details": {"amount_ml": 120}}}]),
                Reply("Someone is at the door.")])
            agent.handle({"kind": "observation", "source": "ears", "channel": "console", "text": "The doorbell rang."})
            self.assertEqual(agent.baby_log.entries("feeding", None, 10), [])
            agent.close()


class NothingSaysLeaveDuringABath(unittest.TestCase):
    def test_a_go_with_the_baby_sentence_is_cut_while_a_skill_is_on(self):
        from parenting_agent.camera_skill import STAY, implies_left_alone, keep_with_baby
        text = ("Keep your hand on her. If you need to go grab shampoo, take her out of the water with you, then go. "
                "Want me to call your partner?")
        kept = keep_with_baby(text)
        self.assertFalse(implies_left_alone(kept))
        self.assertIn("call your partner", kept)
        self.assertIn(STAY, kept)
        self.assertEqual(keep_with_baby("Bath logged."), "Bath logged.")


if __name__ == "__main__":
    unittest.main()
