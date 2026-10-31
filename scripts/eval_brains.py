"""Brains that are not Meta models, for offline evaluation only. Nothing in parenting_agent/ imports this file.

The hackathon rule is that every model the project calls at runtime is a Meta model, so the family agent, the demo and
the families bot run Muse Spark Open with the fixed rules as their fallback (parenting_agent/agent/brain.py). The model
comparisons in results/muse-vs-haiku, results/demo-app and the families runs asked Claude Haiku the same prompts to see
whether Muse was needed. Those scripts call install() when they are asked for --brain claude, and only then.

    from eval_brains import install
    install()   # brain.build_one now also builds {"provider": "claude", ...}, for this offline process only
"""
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent.agent import brain as brain_mod  # noqa: E402
from parenting_agent.agent.brain import BrainError, Reply, json, post_json, priced, without_thinking  # noqa: E402,F401

# USD per million tokens, input and output, from the Anthropic pricing page, read 2026-10-28.
CLAUDE_PRICES = (0.10, 0.50)
CLAUDE = {"provider": "claude", "model": "claude-haiku-5-5", "max_tokens": 400,
          "price_in_per_mtok": CLAUDE_PRICES[0], "price_out_per_mtok": CLAUDE_PRICES[1]}


class ClaudeBrain:
    name = "claude"
    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, model, max_tokens=800, thinking=None, timeout=30, prices=None):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise BrainError("claude: ANTHROPIC_API_KEY is not set")
        self.model, self.max_tokens, self.timeout, self.prices = model, max_tokens, timeout, prices
        # Thinking off by default: with it on, small models answered with thinking only (meta-hackathon-2026 PR #10).
        self.thinking = thinking or {"type": "disabled"}
        self.headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        self.destination = urllib.parse.urlparse(self.url).hostname

    @staticmethod
    def messages(transcript):
        out = []
        for item in transcript:
            if item["role"] == "user":
                out.append({"role": "user", "content": item["text"]})
            elif item["role"] == "assistant":
                blocks = [{"type": "text", "text": item["text"]}] if item.get("text") else []
                blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]} for c in item.get("tool_calls", [])]
                out.append({"role": "assistant", "content": blocks})
            else:
                block = {"type": "tool_result", "tool_use_id": item["id"], "content": json.dumps(item["result"], default=str)}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def step(self, system, transcript, tools):
        body = {"model": self.model, "max_tokens": self.max_tokens, "thinking": self.thinking, "system": system,
                "messages": self.messages(transcript),
                "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]}
        reply = post_json(self.url, self.headers, body, self.timeout)
        text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
        calls = [{"id": b["id"], "name": b["name"], "arguments": b.get("input") or {}}
                 for b in reply.get("content", []) if b.get("type") == "tool_use"]
        usage = reply.get("usage") or {}
        return priced(Reply(without_thinking(text), calls,
                            {"input_tokens": usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
                             + usage.get("cache_read_input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)}), self.prices)


def install():
    """Let brain.build_one build Claude in this offline process, and add "claude" to the demo's brain list."""
    from parenting_agent.demo import settings
    meta_only = brain_mod.build_one

    def build_one(config):
        if config.get("provider") == "claude":
            prices = (config["price_in_per_mtok"], config["price_out_per_mtok"]) if "price_in_per_mtok" in config else None
            return ClaudeBrain(config.get("model", "claude-haiku-5-5"), config.get("max_tokens", 800),
                               config.get("thinking"), timeout=config.get("timeout_s", 30), prices=prices)
        return meta_only(config)

    brain_mod.build_one = build_one
    settings.BRAINS.setdefault("claude", CLAUDE)
    settings.PRICES.setdefault("claude", CLAUDE_PRICES)
    settings.BRAIN_KEYS = tuple(dict.fromkeys(settings.BRAIN_KEYS + ("ANTHROPIC_API_KEY",)))
    from parenting_agent.families import settings as families
    families.BRAIN_KEYS = tuple(dict.fromkeys(families.BRAIN_KEYS + ("ANTHROPIC_API_KEY",)))
    families.KEEP = tuple(dict.fromkeys(families.KEEP + ("ANTHROPIC_API_KEY",)))
