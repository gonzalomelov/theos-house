"""The brain: one model call that reads the conversation and either answers or asks to use tools.

Which model runs is one setting (brain.provider in the agent config), so swapping needs no code change:
- fake: a small rule-based brain for tests and offline runs. No network.
- claude: the stand-in until Muse is reachable. Anthropic Messages API, key ANTHROPIC_API_KEY.
- openai_compatible: any OpenAI-compatible chat endpoint. This is how Muse Spark Open runs on Baseten
  (issue #4), and Meta's Model API speaks it too. Key from the env variable named in brain.key_env.

The agent keeps its own neutral transcript and each provider converts it. Every network call reports
its destination host so the agent can log where data went.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import rules


class BrainError(Exception):
    pass


class Reply:
    """usage is {"input_tokens", "output_tokens"} when the provider reports it, else None (the fake brain)."""

    def __init__(self, text="", tool_calls=None, usage=None):
        self.text, self.tool_calls, self.usage = text, tool_calls or [], usage


def post_json(url, headers, body, timeout):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise BrainError(f"HTTP {error.code}: {error.read()[:300].decode(errors='replace')}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise BrainError(str(error)) from error


def trigger(text, tools):
    """The tool whose description says the parent says exactly this phrase, for example "bath time"."""
    said = text.lower().strip(" .!")
    for tool in tools:
        if said in (p.lower() for p in re.findall(r'says? "([^"]+)"', tool["description"])):
            return tool["name"]
    return None


class FakeBrain:
    """Logs feeds, diapers, sleep and baths it hears, answers from the baby log, refuses health questions. No network."""
    name, model, destination = "fake", "rules", "none (local)"

    def step(self, system, transcript, tools):
        last = transcript[-1]
        if last["role"] == "tool" and last.get("id") == "fake-trigger":
            return Reply(str(last["result"]).split(". ")[0].rstrip(".") + ".")
        if last["role"] == "tool":
            if isinstance(last["result"], str) and "failed" in last["result"]:
                return Reply("I could not do that: " + last["result"])
            if last["name"] == "baby_summary":
                question = next((t["text"] for t in reversed(transcript) if t["role"] == "user"), "")
                return Reply(rules.answer(question, last["result"]) or "I could not find that in the log.")
            if last["name"] == "read_baby_log":
                feeds = [e for e in last["result"] if e["kind"] == "feeding"]
                if not feeds:
                    return Reply("Nothing logged yet today.")
                parts = [f"{e['details'].get('amount_ml', '?')} ml at {e['ts'][11:16]}" for e in feeds]
                return Reply("Logged feeds: " + ", ".join(parts) + ".")
            return Reply("Done, logged.")
        if last["text"].startswith("[observation from"):
            return Reply("Noted.")  # a skill reports what it already logged, nothing to log again
        text = last["text"].split("] ", 1)[-1]
        if rules.is_medical(text):
            return Reply(rules.REFUSAL)
        named = trigger(text, tools)
        if named:
            return Reply(tool_calls=[{"id": "fake-trigger", "name": named, "arguments": {}}])
        if rules.is_question(text):
            return Reply(tool_calls=[{"id": "fake-summary", "name": "baby_summary", "arguments": {}}])
        parsed = rules.parse_note(text)
        if parsed:
            kind, details = parsed
            return Reply(tool_calls=[{"id": "fake-log", "name": "log_baby_event", "arguments": {"kind": kind, "details": details}}])
        return Reply("Noted.")


class ClaudeBrain:
    name = "claude"
    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, model, max_tokens=800, thinking=None, timeout=30):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise BrainError("claude: ANTHROPIC_API_KEY is not set")
        self.model, self.max_tokens, self.timeout = model, max_tokens, timeout
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
        return Reply(text.strip(), calls, {"input_tokens": usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
                                           + usage.get("cache_read_input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)})


class OpenAICompatibleBrain:
    name = "openai_compatible"

    def __init__(self, model, base_url, key_env, max_tokens=800, timeout=30):
        key = os.environ.get(key_env)
        if not key:
            raise BrainError(f"openai_compatible: {key_env} is not set")
        self.model, self.max_tokens, self.timeout = model, max_tokens, timeout
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self.destination = urllib.parse.urlparse(self.url).hostname

    @staticmethod
    def messages(system, transcript):
        out = [{"role": "system", "content": system}]
        for item in transcript:
            if item["role"] == "user":
                out.append({"role": "user", "content": item["text"]})
            elif item["role"] == "assistant":
                message = {"role": "assistant", "content": item.get("text") or None}
                if item.get("tool_calls"):
                    message["tool_calls"] = [{"id": c["id"], "type": "function",
                                              "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                                             for c in item["tool_calls"]]
                out.append(message)
            else:
                out.append({"role": "tool", "tool_call_id": item["id"], "content": json.dumps(item["result"], default=str)})
        return out

    @staticmethod
    def parse(reply):
        message = (reply.get("choices") or [{}])[0].get("message") or {}
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append({"id": call.get("id"), "name": function.get("name"), "arguments": arguments})
        usage = reply.get("usage") or {}
        return Reply((message.get("content") or "").strip(), calls,
                     {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)})

    def step(self, system, transcript, tools):
        body = {"model": self.model, "max_tokens": self.max_tokens, "messages": self.messages(system, transcript),
                "tools": [{"type": "function", "function": t} for t in tools]}
        return self.parse(post_json(self.url, self.headers, body, self.timeout))


def build(config):
    provider = config.get("provider", "fake")
    if provider == "fake":
        return FakeBrain()
    if provider == "claude":
        return ClaudeBrain(config.get("model", "claude-haiku-5-5"), config.get("max_tokens", 800), config.get("thinking"))
    if provider == "openai_compatible":
        return OpenAICompatibleBrain(config["model"], config["base_url"], config["key_env"], config.get("max_tokens", 800))
    raise BrainError(f"unknown brain provider {provider}")


def timed(brain, system, transcript, tools):
    started = time.monotonic()
    reply = brain.step(system, transcript, tools)
    return reply, round(time.monotonic() - started, 3)
