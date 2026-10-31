"""The glasses day scenes (scripts/glasses_hud_day.py) with no simulator and no SAM 3.1, scored for noise.

    python scripts/glasses_day_noise.py --out results/e2e-day/glasses-after.json

The same family agent, scenes, Muse, Baby Buddy test child, Home Assistant reads, captured Telegram and dry house as the
recorded glasses day. What differs, so it runs anywhere with no GPU: both parents' glasses are event-stream listeners
(the way Ceci's were in the recorded day), and the car seat coach looks at a fixed picture of a correct install through
the unit tests' fake vision (tests/test_carseat.py), so its camera steps pass without a heavy model.

Noise is scored the way the end-to-end day scores a message (parenting_agent/e2e/score.py): every text that reached a
parent, on Telegram, on a glasses card, as a glasses reply or spoken by the coach, is noise when it has an English
sentence (both parents read Spanish) or internal text.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import glasses_hud_day as hud_day  # noqa: E402


class NoSimulatorDay(hud_day.Day):
    def cards_of(self, person, since_unix):
        listener = self.gonza if person == "gonza" else self.ceci
        return [{**e["card"], "agent_unix": e.get("agent_unix"), "shown_unix": e["received_unix"]}
                for e in listener.seen if e["kind"] == "card" and e["received_unix"] >= since_unix]

    def execute(self):
        import os
        import secrets
        import datetime
        import freezegun
        freezegun.configure(extend_ignore_list=hud_day.REAL_MODULES + ["tests.test_carseat"])
        import parenting_agent.glasses  # noqa: F401 real time in the endpoint
        import parenting_agent.carseat.coach  # noqa: F401
        from parenting_agent.agent import build
        from parenting_agent.channels import telegram as telegram_mod
        from parenting_agent.e2e import clock as clock_mod
        from parenting_agent.e2e import harness
        from parenting_agent.voice import client as voice_client
        from tests.test_carseat import FakeVision, FrameFeed, scene

        harness.load_env()
        self.tokens = {p: secrets.token_urlsafe(12) for p in ("gonza", "ceci")}
        for person, token in self.tokens.items():
            os.environ[f"PARENTING_AGENT_GLASSES_TOKEN_{person.upper()}"] = token
        hud_day.DATA.mkdir(exist_ok=True)
        for stale in hud_day.DATA.iterdir():
            if stale.is_file():
                stale.unlink()
        bb = harness.BabyBuddy(os.environ["BABYBUDDY_URL"], os.environ["BABYBUDDY_TOKEN"])
        child = bb.child(harness.CHILD)
        baseline = json.loads(harness.BASELINE.read_text())
        start = hud_day.at(self.day0, "06:00") - datetime.timedelta(minutes=5)
        end = hud_day.at(self.day0, "16:00")
        removed = bb.cleanup(child["id"], hud_day.at(self.day0, "00:00"), end, baseline)
        seeded = self.seed(bb, child)
        config = self.config(child)
        self.transport = harness.Transport(os.environ["BABYBUDDY_URL"])
        self.transport.install()
        self.clock = clock_mod.VirtualClock(start, harness.TZ)
        self.messenger = harness.CaptureMessenger(self.clock)
        telegram_mod.TelegramMessenger = lambda token, api=None: self.messenger
        voice_client.RemoteVoice = harness.LocalEarVoice
        self.container = None
        self.agent = agent = build(config)
        agent.bus.subscribe(self.on_event)
        self.channel = next(p for p in agent.plugins if p.name == "telegram")
        self.channel.run = lambda: None
        glasses = next(p for p in agent.plugins if p.name == "glasses")
        coach = next(p for p in agent.plugins if p.name == "car-seat")
        found, _ = scene()
        coach._vision, coach._source = FakeVision(found), FrameFeed(frames=10 ** 6, step=0.1)
        coach.quiet = True
        self.hub = glasses.hub
        self.hub.camera_person = "gonza"  # Gonza's glasses are the camera, as in the recorded day
        for plugin in agent.plugins:
            if plugin.name in ("telegram", "glasses", "car-seat") or not hasattr(plugin, "stopped"):
                continue
            plugin.stopped = self.clock.event(plugin.name)
        agent.start()
        for plugin in agent.plugins:
            plugin.start()
        self.clock.quiet()
        self.gonza = hud_day.Listener(self.hub.url, self.tokens["gonza"])
        self.ceci = hud_day.Listener(self.hub.url, self.tokens["ceci"])
        time.sleep(1)
        results = []
        try:
            for item in hud_day.scenes(self.day0):
                item = {**item, "hold_s": 1}
                results.append(self.run_scene(item))
        finally:
            for plugin in agent.plugins:
                plugin.stop()
            agent.stop()
            agent.close()
            self.clock.stop()
            self.transport.uninstall()
        events = hud_day.rows(hud_day.DATA / "events.jsonl")
        return {"day": self.args.day, "removed_before_run": removed, "seeded": seeded, "scenes": results,
                "passed": sum(r["passed"] for r in results), "of": len(results),
                "telegram": self.messenger.sent, "chats": harness.CHATS,
                "glasses": {"gonza": self.gonza.seen, "ceci": self.ceci.seen},
                "spoken": [{"person": "gonza", "text": e.get("text"), "step": e.get("step")} for e in events
                           if e["kind"] == "voice" and e.get("skill") == "car-seat"],
                "final_guard": [e for e in events if e["kind"] == "final_guard"],
                "brain_usd": round(self.transport.usd, 4), "brain_calls": dict(self.transport.calls),
                "refused": self.transport.refused}


def texts(run):
    """Every text that reached a parent: (person, where, text)."""
    from parenting_agent.e2e.harness import CHATS
    person_of = {chat: who for who, chat in CHATS.items()}
    out = [(person_of.get(m["chat"], m["chat"]), "telegram", m["text"]) for m in run["telegram"] if m.get("text")]
    for person, seen in run["glasses"].items():
        for event in seen:
            if event["kind"] == "card":
                card = event["card"]
                out.append((person, "card", " · ".join(card[k] for k in ("title", "status", "detail", "meta") if card.get(k))))
            elif event["kind"] == "reply" and event.get("text"):
                out.append((person, "glasses reply", event["text"]))
            elif event["kind"] == "voice" and event.get("text"):
                out.append((person, "spoken", event["text"]))
    out += [(s["person"], "spoken", s["text"]) for s in run["spoken"] if s.get("text")]
    return out


def score(run):
    from parenting_agent.e2e.score import INTERNAL, english
    rows = []
    for person, where, text in texts(run):
        problems = []
        if english(text):
            problems.append("English to a Spanish parent")
        internal = INTERNAL.search(text)
        if internal:
            problems.append(f"internal text ({internal.group(0)})")
        rows.append({"to": person, "where": where, "text": text, "problems": problems})
    by_where = {}
    for row in rows:
        total, noise = by_where.get(row["where"], (0, 0))
        by_where[row["where"]] = (total + 1, noise + bool(row["problems"]))
    return {"noise": sum(bool(r["problems"]) for r in rows), "of": len(rows),
            "by_where": {w: {"noise": n, "of": t} for w, (t, n) in sorted(by_where.items())},
            "noisy": [r for r in rows if r["problems"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--day", default="2026-10-30")
    parser.add_argument("--out", required=True)
    parser.add_argument("--score", action="store_true", help="only score an earlier run again")
    args = parser.parse_args()
    out = Path(args.out)
    if args.score:
        run = json.loads(out.read_text())
    else:
        args.out_dir, args.name, args.video, args.udid = str(out.parent), out.stem, None, None
        run = NoSimulatorDay(args).execute()
    run["noise"] = score(run)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({"passed": run["passed"], "of": run["of"], "brain_usd": run["brain_usd"],
                      "noise": {k: run["noise"][k] for k in ("noise", "of", "by_where")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
