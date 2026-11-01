"""The brain: one model call that reads the conversation and either answers or asks to use tools.

Which model runs is one setting (brain.provider in the agent config), so swapping needs no code change:
- fake: a small rule-based brain for tests and offline runs. No network.
- rules: the same fixed rules, as the fallback when a Muse call errors. No model, no network.
- openai_compatible: any OpenAI-compatible chat endpoint. This is how Muse Spark Open runs on Baseten
  (issue #4), and Meta's Model API speaks it too. Key from the env variable named in brain.key_env.

Only Meta models run at runtime (the hackathon rule). A brain config with a "fallback" block runs the fixed rules
only when Muse errors, never another vendor's model, and the agent then tells the parent plainly that the brain is
busy. Every fallback is printed to stderr and carried on the reply, and the agent logs it as a brain_fallback event,
so it can be counted. Offline scripts that compare Muse with other models build those brains in scripts/eval_brains.py,
outside this package.

The agent keeps its own neutral transcript and each provider converts it. Every network call reports
its destination host so the agent can log where data went.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import rules


class BrainError(Exception):
    pass


class Reply:
    """usage is {"input_tokens", "output_tokens"} when the provider reports it, else None (the fake brain).
    usd is the call's cost when the brain knows its prices. fallback is set when the fallback brain answered."""

    def __init__(self, text="", tool_calls=None, usage=None, usd=None, fallback=None):
        self.text, self.tool_calls, self.usage, self.usd, self.fallback = text, tool_calls or [], usage, usd, fallback


THINKING = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|\Z)", re.S | re.I)


def without_thinking(text):
    """A reasoning model's thoughts never reach a parent, even when an endpoint puts them in the answer text."""
    return THINKING.sub("", text or "").strip()


def priced(reply, prices):
    if prices and reply.usage:
        reply.usd = (reply.usage.get("input_tokens", 0) * prices[0] + reply.usage.get("output_tokens", 0) * prices[1]) / 1_000_000
    return reply


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
        text = last["text"].split("] ", 1)[-1].split("\n[check from the agent", 1)[0]
        if rules.is_medical(text) and rules.health_route(text) != "log":
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


class RulesBrain(FakeBrain):
    """The fallback when Muse errors: the fixed rules, no model and no network."""
    name, model, destination = "rules", "fixed rules", "none (local)"


class OpenAICompatibleBrain:
    name = "openai_compatible"

    def __init__(self, model, base_url, key_env, max_tokens=800, timeout=30, reasoning_effort=None, prices=None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        key = os.environ.get(key_env)
        if not key:
            raise BrainError(f"openai_compatible: {key_env} is not set. Put {key_env}=... in the git-ignored env file "
                             f"named by env_file to run {model} on {urllib.parse.urlparse(self.url).hostname}")
        self.model, self.max_tokens, self.timeout, self.prices = model, max_tokens, timeout, prices
        # Muse Spark Open on Baseten always reasons, xhigh by default, and reasoning counts against max_tokens.
        self.reasoning_effort = reasoning_effort
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
        choice = (reply.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if choice.get("finish_reason") == "length" and not message.get("content") and not message.get("tool_calls"):
            raise BrainError("openai_compatible: max_tokens ran out before an answer, raise brain.max_tokens "
                             "or lower brain.reasoning_effort")
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append({"id": call.get("id"), "name": function.get("name"), "arguments": arguments})
        usage = reply.get("usage") or {}
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        # The reasoning comes back apart, in message.reasoning_content, and is never read here.
        return Reply(without_thinking(message.get("content")), calls,
                     {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0),
                      "reasoning_tokens": reasoning})

    def step(self, system, transcript, tools):
        body = {"model": self.model, "max_tokens": self.max_tokens, "messages": self.messages(system, transcript)}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return priced(self.parse(post_json(self.url, self.headers, body, self.timeout)), self.prices)


class FallbackBrain:
    """The configured brain first. Only when it errors, the fallback answers, and that is never silent: it is printed
    to stderr, counted in self.fallbacks and carried on the reply as reply.fallback for the agent to log.
    name, model and destination always say which brain answered the last call."""

    def __init__(self, primary, fallback, log=None):
        self.primary, self.backup, self.fallbacks = primary, fallback, 0
        self.log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        self.use(primary)

    def use(self, brain):
        self.name, self.model, self.destination = brain.name, brain.model, brain.destination

    def step(self, system, transcript, tools):
        try:
            reply = self.primary.step(system, transcript, tools)
            self.use(self.primary)
            return reply
        except BrainError as error:
            self.fallbacks += 1
            note = {"from_model": self.primary.model, "to_model": self.backup.model, "error": str(error)[:300]}
            self.log("brain_fallback " + json.dumps(note))
            reply = self.backup.step(system, transcript, tools)
            self.use(self.backup)
            reply.fallback = note
            return reply


def thinks(brain):
    """True when a model answers through this brain: not the offline fake brain or the fixed rules. A metered or fallback
    brain counts by the brain it calls first."""
    inner = getattr(brain, "brain", brain)
    inner = getattr(inner, "primary", inner)
    return getattr(inner, "name", "fake") not in ("fake", "rules")


# Providers of models that are not Meta's. They never run inside the agent, the demo or the families bot.
NOT_META = ("claude", "anthropic", "openai")


def build_one(config):
    provider = config.get("provider", "fake")
    prices = (config["price_in_per_mtok"], config["price_out_per_mtok"]) if "price_in_per_mtok" in config else None
    if provider == "fake":
        return FakeBrain()
    if provider == "rules":
        return RulesBrain()
    if provider in NOT_META:
        raise BrainError(f"{provider} is not a Meta model: the runtime brain is Muse Spark Open, with the fixed rules as "
                         "its fallback. Offline model comparisons use scripts/eval_brains.py")
    if provider == "openai_compatible":
        return OpenAICompatibleBrain(config["model"], config["base_url"], config["key_env"], config.get("max_tokens", 800),
                                     timeout=config.get("timeout_s", 30), reasoning_effort=config.get("reasoning_effort"),
                                     prices=prices)
    raise BrainError(f"unknown brain provider {provider}")


def build(config):
    primary = build_one(config)
    if not config.get("fallback"):
        return primary
    if config["fallback"].get("provider") != "rules":
        raise BrainError("brain.fallback must be {\"provider\": \"rules\"}: when Muse errors the fixed rules answer, "
                         "never another model")
    return FallbackBrain(primary, build_one(config["fallback"]))


def timed(brain, system, transcript, tools):
    """One brain call and its seconds. With PA_BRAIN_LOG set, each call also appends one JSON line there (model,
    seconds, tokens, cost, fallback), never any text, so a run's latency and cost per call can be measured."""
    started = time.monotonic()
    reply = brain.step(system, transcript, tools)
    seconds = round(time.monotonic() - started, 3)
    if os.environ.get("PA_BRAIN_LOG"):
        line = {"ts": time.time(), "provider": brain.name, "model": brain.model, "seconds": seconds,
                "tool_calls": len(reply.tool_calls), **(reply.usage or {}), "usd": reply.usd, "fallback": reply.fallback}
        with open(os.path.expanduser(os.environ["PA_BRAIN_LOG"]), "a") as log:
            log.write(json.dumps(line) + "\n")
    return reply, seconds
