"""Plays the judge story against a running simulator with real Muse, and checks what it chose. Writes results/simulator-first/.

Run: python3 scripts/simulator_live_eval.py [--runs 3] [--url http://127.0.0.1:8781]
Passing here shows the story works. The prompt has been read against these same moments, so it isn't a held-out number.
"""
import argparse
import http.cookiejar
import json
import pathlib
import time
import urllib.request

DEHUM = "Tapo P110 - Dehumidifier"


class Visitor:
    def __init__(self, url):
        self.url = url
        self.open = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), urllib.request.ProxyHandler({})).open

    def post(self, path, body):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.load(self.open(request, timeout=120))

    def state(self):
        return json.load(self.open(self.url + "/api/state", timeout=30))

    def scene(self, scene_id):
        return self.send("/api/scene", {"id": scene_id})

    def send(self, path, body):
        """Sends one thing and returns every step the stream showed for it, once it is done."""
        after = self.state()["seq"]
        self.post(path, body)
        steps, kind, open_runs = [], None, set()
        with self.open(f"{self.url}/api/stream?after={after}", timeout=240) as stream:
            for raw in stream:  # a wake Muse asked for may run first, so it is done when every event that started is
                line = raw.decode().strip()
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    step = json.loads(line[5:])
                    steps.append(step)
                    if kind == "event":
                        open_runs.add(step["event_id"])
                    elif kind == "done":
                        open_runs.discard(step["event_id"])
                        if not open_runs:
                            return steps
        return steps


def to(state, who, since):
    return [m["text"] for m in state["sent"] if m["to"] == who][since:]


def story(url):
    v = Visitor(url)
    v.post("/api/session", {})
    v.post("/api/reset", {})
    out, counts = [], {"gonza": 0, "ceci": 0, "echo": 0}

    def play(scene_id, check):
        started = time.time()
        steps = v.scene(scene_id)
        state = v.state()
        new = {who: to(state, who, counts[who]) for who in counts}
        ok = bool(check(state, new, steps))
        out.append({"scene": scene_id, "passed": ok, "seconds": round(time.time() - started, 1), "sent": new,
                    "tools": [s["tool"] for s in steps if s["kind"] == "tool_call"], "decision": next((s["note"] or s["text"] for s in steps if s["kind"] == "decision"), ""),
                    "failed": any(s["kind"] == "error" for s in steps)})
        for who in counts:
            counts[who] += len(new[who])
    plug = lambda state: state["home"]["devices"][DEHUM]["state"]
    play("evening", lambda s, n, _: n["gonza"] or n["ceci"])
    play("sleep", lambda s, n, _: n["gonza"] and s["facts"])
    play("cry", lambda s, n, _: n["gonza"] and not n["ceci"])
    play("feed", lambda s, n, _: any(e["kind"] == "feeding" and e["details"].get("amount_ml") == 90 and e["ts"].startswith("2026-12-16T03:00") for e in s["log"]))
    play("morning", lambda s, n, _: n["gonza"] and n["ceci"] and n["gonza"] != n["ceci"])
    play("grandma", lambda s, n, _: n["echo"] and "3" in " ".join(n["echo"]) + "tres")
    play("nap", lambda s, n, _: n["ceci"] and len(s["facts"]) >= 1)
    play("humid", lambda s, n, _: plug(s) == "off" and n["ceci"])
    play("recipe", lambda s, n, _: n["gonza"] and any(w in " ".join(n["gonza"]).lower() for w in ("pumpkin", "zapallo")))
    play("carseat", lambda s, n, steps: any(x["kind"] == "tool_call" and x["tool"] == "start_car_seat_coach" for x in steps))
    state = v.state()
    return {"scenes": out, "facts": state["facts"], "log": state["log"], "passed": sum(s["passed"] for s in out), "of": len(out)}


def same_event(url):
    """Nothing is scripted: one event, different homes, different choices. Each case starts from a fresh home."""
    event = {"type": "state_changed", "payload": {"entity_id": "sensor.nursery_climate_humidity", "state": "71.2"}}
    v = Visitor(url)
    v.post("/api/session", {})

    def case(prepare, sent):
        v.post("/api/reset", {})
        for entity, state in prepare:
            v.post("/api/home", {"entity_id": entity, "state": state})
        steps = v.send("/api/events", sent)
        state = v.state()
        return {"plug": state["home"]["devices"][DEHUM]["state"], "moves": [m["tool"] for m in state["home"]["moves"]],
                "tools": [s["tool"] for s in steps if s["kind"] == "tool_call"]}
    off = case([], event)
    on = case([("switch.study_tapo_p110_dehumidifier", "on")], event)
    low = case([], {"type": "state_changed", "payload": {"entity_id": "sensor.nursery_climate_humidity", "state": "45"}})
    return {"plug_off": off, "plug_already_on": on, "low_humidity": low,
            "passed": off["moves"] == ["HassTurnOn"] and on["moves"] == [] and on["plug"] == "on" and low["moves"] == []}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--url", default="http://127.0.0.1:8781")
    args = parser.parse_args()
    where = pathlib.Path("results/simulator-first")
    where.mkdir(parents=True, exist_ok=True)
    checks = [same_event(args.url) for _ in range(args.runs)]
    (where / "same-event.json").write_text(json.dumps(checks, ensure_ascii=False, indent=1))
    print(f"same event, different home: {sum(c['passed'] for c in checks)}/{len(checks)}", [c for c in checks if not c["passed"]], flush=True)
    runs = []
    for i in range(args.runs):
        run = story(args.url)
        runs.append(run)
        print(f"run {i + 1}: {run['passed']}/{run['of']}", [(s["scene"], s["seconds"]) for s in run["scenes"] if not s["passed"]], flush=True)
        (where / "story-runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1))
