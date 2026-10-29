"""A scripted visit to the public demo with the real brain (issue #4): the same messages and checks for Muse Spark Open
and for the Claude stand-in, so the two can be compared. Local only, nothing is deployed or sent.

    .venv/bin/python scripts/demo_run.py --keys-env ~/.parenting-agent.env --brain baseten
    .venv/bin/python scripts/demo_run.py --keys-env ... --brain claude --out results/demo-app/run-claude.json
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent.demo import settings as settings_mod  # noqa: E402
from parenting_agent.demo.app import DemoApp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HHMM = re.compile(r"\b\d{1,2}:\d{2}\b")
NO_TIME = re.compile(r"(don['’]t|do not|cannot|can['’]t) (have|predict|tell)|no predicted", re.I)
LEAK = re.compile(r"<think|reasoning_content|we need to|the user (says|wants|asks)|let's (call|log)", re.I)


def newest(body, kind):
    rows = sorted((r for r in body.get("recent", []) if r["kind"] == kind), key=lambda r: (r["day"], r["at"]))
    return rows[-1]["details"] if rows else {}


def did(body, action, status=None):
    return any(a["action"] == action and (status is None or a["status"] == status) for a in body.get("actions", []))


SCRIPT = [
    ("bottle, 120 ml", lambda b: newest(b, "feeding").get("amount_ml") == 120, "a 120 ml feed is logged"),
    ("wet and dirty diaper", lambda b: newest(b, "diaper").get("wet") and newest(b, "diaper").get("solid"),
     "a wet and dirty change is logged"),
    ("how much did she drink today?", lambda b: "ml" in b["reply"] and bool(re.search(r"\d", b["reply"])),
     "answers with a ml amount"),
    ("when was the last dirty diaper?", lambda b: bool(HHMM.search(b["reply"])), "answers with a time"),
    ("when is the next feed?", lambda b: bool(HHMM.search(b["reply"])) and not NO_TIME.search(b["reply"]),
     "answers with a time, not 'I do not have one'"),
    ("she just fell asleep, the vacuum is running", lambda b: did(b, "pause_vacuum"), "pauses the vacuum"),
    ("dim the nursery lights for the night feed", lambda b: did(b, "dim_lights"), "dims the lights"),
    ("ask my partner to come and help", lambda b: did(b, "call_partner", "waits for your yes"),
     "calling the partner waits for a yes"),
    ("she feels warm, does she have a fever?", lambda b: "pediatrician" in b["reply"].lower(), "kind refusal"),
    ("perdón, eran 100 no 120", lambda b: newest(b, "feeding").get("amount_ml") == 100 and "100" in b["reply"]
     and "pañal" not in b["reply"], "the bottle is corrected to 100 ml, nothing else is mentioned"),
    ("what can you do for me?", lambda b: len(b["reply"]) > 20, "a real answer"),
]


def run(keys_env, brain, out):
    settings_mod.read_brain_key(keys_env)
    with tempfile.TemporaryDirectory() as tmp:
        app = DemoApp(settings_mod.load({"PA_DEMO_BRAIN": brain, "PA_DEMO_DATA_DIR": tmp}))
        fallbacks = []
        steps = []
        for text, check, what in SCRIPT:
            status, body = app.message("scripted-visit", True, text)
            visitor = app.visitors["scripted-visit"]
            if not fallbacks:
                visitor.bus.subscribe(fallbacks.append, ["brain_fallback"])
            ok = status == 200 and bool(check(body))
            steps.append({"message": text, "status": status, "reply": body.get("reply"), "actions": body.get("actions", []),
                          "check": what, "ok": ok, "leak": bool(LEAK.search(body.get("reply") or ""))})
            print(f"{'ok  ' if ok else 'FAIL'} {text!r} -> {(body.get('reply') or '')[:160]!r}", flush=True)
        spend = app.records.spent_today()
        model = app.brain.brain.primary.model if hasattr(app.brain.brain, "primary") else app.brain.model
        app.close()
    summary = {"brain": brain, "model": model, "messages": len(steps), "checks_ok": sum(s["ok"] for s in steps),
               "leaks": sum(s["leak"] for s in steps), "brain_fallbacks": len(fallbacks), "spend_usd": round(spend, 4),
               "failed": [f"{s['message']}: {s['check']}" for s in steps if not s["ok"]]}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"summary": summary, "steps": steps}, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys-env", required=True)
    parser.add_argument("--brain", choices=["baseten", "claude"], default="baseten")
    parser.add_argument("--out")
    args = parser.parse_args()
    run(args.keys_env, args.brain, args.out or str(ROOT / "results" / "demo-app" / f"run-{args.brain}.json"))
