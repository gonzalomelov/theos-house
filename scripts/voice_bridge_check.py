"""End to end check of the Echo and Assist voice path on the agent side (issue #112), with fake utterances.

It plays Home Assistant's part from the files in deploy/home-assistant/, so what is tested is the config Gonza
will copy: the Assist custom sentences pick out the query, the rest_command payload template is rendered and POSTed
to a real voice bridge over HTTP with the bearer token, and the intent_script speech template turns the answer into
what Assist says. For the Echo, the automation's condition template decides on the voice_command of a fake
event.gonza_s_echo_dot_voice_event, and its notify message template gives what the Echo would say. Home Assistant
itself is not touched.

Needs jinja2 and PyYAML (the system python3 on the Mac has both, the project venv does not), so:

    python3 scripts/voice_bridge_check.py              # the fake rule-based brain, no network
    python3 scripts/voice_bridge_check.py --muse       # one round with Muse Spark Open on Baseten (a few calls)
"""
import argparse
import itertools
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent.agent import build  # noqa: E402
from parenting_agent.agent import config as config_mod  # noqa: E402
from parenting_agent.voice_bridge import VoiceBridge  # noqa: E402

HA = ROOT / "deploy" / "home-assistant"
ENV = ROOT.parent.parent / "meta-hackathon-2026" / ".env"


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!secret", lambda loader, node: f"<secret {loader.construct_scalar(node)}>")


def load(path):
    return yaml.load(path.read_text(), Loader=Loader)


def expand(template):
    """Every concrete form of a Home Assistant sentence template: [optional] and (a | b) groups, {query} kept."""
    parts = re.split(r"(\[[^\]]*\]|\([^)]*\))", template)
    options = []
    for part in parts:
        if part.startswith("["):
            options.append([""] + [o.strip() for o in part[1:-1].split("|")])
        elif part.startswith("("):
            options.append([o.strip() for o in part[1:-1].split("|")])
        else:
            options.append([part])
    for combo in itertools.product(*options):
        yield re.sub(r"\s+", " ", " ".join(c for c in combo if c is not None)).strip()


def matcher(sentences_file):
    data = load(sentences_file)
    forms = [f for block in data["intents"]["ParentingAgentAsk"]["data"] for s in block["sentences"] for f in expand(s)]
    patterns = [re.compile("^" + re.escape(f).replace(re.escape("{query}"), "(?P<query>.+)") + "$", re.IGNORECASE)
                for f in forms]

    def match(text):
        said = re.sub(r"\s+", " ", text.strip().rstrip("?.!")).strip()
        for p in patterns:
            m = p.match(said)
            if m:
                return m.group("query")
        return None
    return match


def jinja():
    env = jinja2.Environment()
    env.tests["match"] = lambda value, pattern: re.match(pattern, str(value)) is not None
    return env


def rest_call(package, url, token, data, env):
    command = package["rest_command"]["parenting_agent_ask"]
    payload = env.from_string(command["payload"]).render(**data)
    request = urllib.request.Request(url, data=payload.encode(), method=command["method"].upper(),
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": command["content_type"]})
    try:
        with urllib.request.urlopen(request, timeout=command["timeout"]) as response:
            return {"status": response.status, "content": json.loads(response.read())}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "content": {}}


def assist(package, match, url, token, text, env):
    query = match(text)
    if query is None:
        return {"said": text, "matched": False, "spoken": "(not for the agent, Assist handles it itself)"}
    script = package["intent_script"]["ParentingAgentAsk"]
    data = {k: env.from_string(str(v)).render(query=query) for k, v in script["action"][0]["data"].items()}
    response = rest_call(package, url, token, data, env)
    spoken = env.from_string(script["speech"]["text"]).render(action_response=response).strip()
    return {"said": text, "matched": True, "query": query, "status": response["status"], "spoken": spoken}


def echo(package, url, token, command, env, person=""):
    automation = package["automation"][0]
    attrs = {"voice_command": command, "person_first_name": person}
    state_attr = lambda entity, name: attrs.get(name)  # noqa: E731
    condition = env.from_string(automation["conditions"][0]["value_template"]).render(state_attr=state_attr).strip()
    if condition != "True":
        return {"said": command, "forwarded": False, "spoken": "(Alexa answers it herself, the agent never sees it)"}
    data = {k: env.from_string(str(v)).render(state_attr=state_attr) for k, v in automation["actions"][0]["data"].items()}
    response = rest_call(package, url, token, data, env)
    message = env.from_string(automation["actions"][1]["data"]["message"]).render(agent=response).strip()
    return {"said": command, "forwarded": True, "status": response["status"], "spoken_on_echo": message,
            "speaker": automation["actions"][1]["target"]["entity_id"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--muse", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "results" / "echo-voice"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    package = load(HA / "packages" / "parenting_agent_voice.yaml")
    match_en = matcher(HA / "custom_sentences" / "en" / "parenting_agent.yaml")
    match_es = matcher(HA / "custom_sentences" / "es" / "parenting_agent.yaml")
    env = jinja()
    with tempfile.TemporaryDirectory() as tmp:
        config = config_mod.load()
        brain = {"provider": "fake"}
        if args.muse:
            brain = json.loads((ROOT / "config" / "agent.muse-baseten.json").read_text())["brain"]
        config.update({"data_dir": tmp, "env_file": str(ENV) if args.muse else "/nonexistent", "brain": brain,
                       "baby_log": {"provider": "local"}, "plugins": [],
                       "voice_bridge": {"port": 0, "host": "127.0.0.1", "timeout_s": 60, "token_file": str(Path(tmp) / "token")}})
        agent = build(config)
        bridge = VoiceBridge(agent, config)
        agent.plugins = [bridge]
        agent.start()
        bridge.start()
        url = f"http://127.0.0.1:{bridge.port}/ask"
        runs = []
        try:
            started = time.monotonic()
            if args.muse:
                plan = [("assist", "baby agent fed 90 ml"), ("echo", "baby agent when was the last feed"),
                        ("assist", "agente del bebé cambié un pañal mojado")]
            else:
                plan = [("assist", "baby agent fed 90 ml"), ("assist", "Ask the baby agent how much did he drink today?"),
                        ("assist", "turn on the study light"), ("assist", "agente del bebé tomó 120 ml"),
                        ("echo", "baby agent wet diaper"), ("echo", "tell the baby agent he fell asleep"),
                        ("echo", "what time is it"), ("echo", "baby agent yes")]
            for kind, text in plan:
                t0 = time.monotonic()
                if kind == "assist":
                    match = match_es if "agente" in text.lower() else match_en
                    row = assist(package, match, url, bridge.token, text, env)
                else:
                    row = echo(package, url, bridge.token, text, env, person="Gonza")
                row.update(path=kind, seconds=round(time.monotonic() - t0, 2))
                runs.append(row)
                print(json.dumps(row, ensure_ascii=False))
            wrong = rest_call(package, url, "not-the-token", {"text": "baby agent fed 90 ml", "source": "assist", "person": ""}, env)
            runs.append({"path": "wrong token", "status": wrong["status"]})
            print(json.dumps(runs[-1]))
            log = agent.baby_log.entries(None, None, 100)
            brain_calls = [e for e in agent.bus.history if e["kind"] == "brain_call"]
            report = {"brain": brain.get("model", "fake rule-based"), "runs": runs, "log_after": log,
                      "brain_calls": len(brain_calls), "brain_hosts": sorted({e.get("destination") or e.get("host") or "" for e in brain_calls}),
                      "seconds_total": round(time.monotonic() - started, 1)}
        finally:
            bridge.stop()
            agent.stop()
            agent.close()
    name = "muse-run.json" if args.muse else "fake-run.json"
    (out / name).write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n")
    print("log after:", json.dumps(report["log_after"], ensure_ascii=False))
    print("brain calls", report["brain_calls"], report["brain_hosts"])


if __name__ == "__main__":
    main()
