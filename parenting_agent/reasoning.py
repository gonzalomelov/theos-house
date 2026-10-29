"""Reasoning: the slow brain that reads the routine and picks house actions. One setting swaps the model.

Providers, chosen by skill config reasoning.provider:
- none: no reasoning calls.
- muse: Muse Spark Open, Meta's open weights, on Baseten's OpenAI-compatible endpoint. Needs BASETEN_API_KEY.
  It always reasons. Its thoughts come back apart (reasoning_content) and are never read.
- claude: the fallback stand-in. Needs ANTHROPIC_API_KEY.

decide() never acts. It returns a proposal ({"action": name or None, "ask_parent": bool, "why": text}) and
the house layer checks it against the allowed list.
"""
import json
import os
import time
import urllib.error
import urllib.request

from .agent.brain import without_thinking


class Unavailable(Exception):
    pass


PROMPT = (
    "You help a parent caring for a baby. Pick at most one house action from the allowed list for this moment, "
    "or none. Anything not on the list must be marked ask_parent and never chosen. Reply with JSON only: "
    '{"action": name or null, "ask_parent": true or false, "why": short text}.'
)


def parse(text, allowed):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return {"action": None, "ask_parent": False, "why": "no JSON in reply"}
    try:
        reply = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {"action": None, "ask_parent": False, "why": "bad JSON in reply"}
    action = reply.get("action")
    if action is not None and action not in allowed:
        return {"action": None, "ask_parent": True, "why": f"{action} is not allowed"}
    return {"action": action, "ask_parent": bool(reply.get("ask_parent")), "why": str(reply.get("why", ""))[:200]}


class NoReasoning:
    name = "none"

    def decide(self, situation, allowed):
        return {"action": None, "ask_parent": False, "why": "reasoning off"}


class HttpReasoning:
    def __init__(self, name, url, headers, body, read):
        self.name, self.url, self.headers, self.body, self.read = name, url, headers, body, read

    def decide(self, situation, allowed):
        user = json.dumps({"situation": situation, "allowed": sorted(allowed)})
        request = urllib.request.Request(self.url, data=json.dumps(self.body(user)).encode(), headers=self.headers, method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                text = self.read(json.loads(response.read()))
        except (urllib.error.URLError, TimeoutError) as error:
            return {"action": None, "ask_parent": False, "why": f"reasoning failed: {error}"[:200]}
        proposal = parse(text, allowed)
        proposal["seconds"] = round(time.monotonic() - started, 3)
        return proposal


def build(config):
    provider = config.get("provider", "none")
    if provider == "none":
        return NoReasoning()
    if provider == "claude":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise Unavailable("claude: ANTHROPIC_API_KEY is not set")
        model = config.get("model", "claude-haiku-5-5")
        return HttpReasoning(
            "claude", "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            lambda user: {"model": model, "max_tokens": 300, "system": PROMPT, "messages": [{"role": "user", "content": user}]},
            lambda reply: "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text"))
    if provider == "muse":
        key = os.environ.get("BASETEN_API_KEY")
        if not key:
            raise Unavailable("muse: BASETEN_API_KEY is not set")
        model = config.get("model", "meta-models/muse-spark-open-1026")
        return HttpReasoning(
            "muse", config.get("url", "https://inference.baseten.co/v1/chat/completions"),
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            lambda user: {"model": model, "max_tokens": 1500, "reasoning_effort": config.get("reasoning_effort", "low"),
                          "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}]},
            lambda reply: without_thinking(((reply.get("choices") or [{}])[0].get("message") or {}).get("content")))
    raise Unavailable(f"unknown reasoning provider {provider}")
