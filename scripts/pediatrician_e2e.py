"""The pediatrician visit summary once, live, on E2E Baby's history: the family agent as on the Vostro, nothing sent.

What is real: the family agent config (config/agent.vostro.json) and its plug-ins, built with build(), the agent's
loop and its guards, Muse Spark Open on Baseten (it words the questions), the family push routing, the glasses card and
the Echo's spoken line through the voice bridge.

What is replaced: the baby log is the agent's local log holding E2E Baby's fixed history (parenting_agent/e2e/
history.json, the entries every e2e run resets that child to, read in Baby Buddy's shape), so nothing writes to Baby
Buddy: only the e2e day writes to its child. E2E Baby was born Oct 1. Telegram is the e2e harness's capturing
messenger (fake chat ids, api.telegram.org refused at the transport), house writes are refused by the same transport
and house.live is false. The clock of the pediatrician plug-in is set to the morning after the history ends, so the two
pushes fire on its schedule.

    .venv/bin/python scripts/pediatrician_e2e.py [out_dir]       default results/pediatrician/
"""
import datetime
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent import hud_cards  # noqa: E402
from parenting_agent.agent import build  # noqa: E402
from parenting_agent.agent.babybuddy import BabyBuddyLog  # noqa: E402
from parenting_agent.channels import telegram as telegram_mod  # noqa: E402
from parenting_agent.e2e import harness  # noqa: E402
from parenting_agent.e2e.clock import REAL  # noqa: E402

TZ = harness.TZ
START = datetime.datetime(2026, 10, 29, 6, 0, tzinfo=TZ)  # E2E Baby's history ends Oct 29 05:05
SCRIPT = [  # (minutes after START, who, text)
    (0, "gonza", "Turno con la pediatra el viernes 10:00"),
    (5, "ceci", "preguntarle a la pediatra si es normal que haga tanta fuerza cuando hace caca"),
    (9, "gonza", "preguntarle a la pediatra cuándo le podemos cortar las uñas"),
    (14, "ceci", "resumen para la pediatra"),
]
AFTER = [(datetime.datetime(2026, 10, 30, 11, 20, tzinfo=TZ), "ceci",
          "La pediatra dijo que las uñas se pueden limar desde ya"),
         (datetime.datetime(2026, 10, 30, 11, 22, tzinfo=TZ), "ceci", "cerrar pregunta 2")]


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment

    def now(self):
        return self.moment


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    harness.load_env()
    history = json.loads(harness.HISTORY.read_text())
    child = {"slug": "local", "first_name": "E2E Baby", "birth_date": "2026-10-01"}
    started = REAL["monotonic"]()
    with tempfile.TemporaryDirectory() as tmp:
        run = harness.Run("pediatrician", ROOT / "config/agent.vostro.json", Path(tmp), START, START, [],
                          overrides={"baby.born": True, "baby.birth_date": child["birth_date"]})
        config = run.config(child)
        config["baby_log"] = {"provider": "local"}
        transport = harness.Transport("http://127.0.0.1:1")
        transport.install()
        clock = Clock(START)
        messenger = harness.CaptureMessenger(clock)
        telegram_mod.TelegramMessenger = lambda token, api=None: messenger
        try:
            agent = build(config)
            rows = []
            for endpoint, records in history.items():
                for i, record in enumerate(records):
                    entry = BabyBuddyLog.normalize(None, endpoint, {"id": i, **record})
                    rows.append((entry["ts"], entry["kind"], json.dumps(entry["details"])))
            with agent.memory.lock:
                agent.memory.db.executemany("insert into baby_log (ts, kind, details) values (?, ?, ?)", sorted(rows))
                agent.memory.db.commit()
            pedi = next(p for p in agent.plugins if p.name == "pediatrician")
            pedi.clock = clock
            channel = next(p for p in agent.plugins if p.name == "telegram")
            bridge = next(p for p in agent.plugins if p.name == "voice-bridge")
            assert config["house"]["live"] is False
            replies, steps = [], []
            agent.bus.subscribe(lambda e: replies.append(e) if e["kind"] == "reply" else None)

            def say(who, text):
                before = len(messenger.sent)
                messenger.incoming(who, text)
                channel.poll_once(timeout=0)
                event = agent.inbox.get(timeout=5)
                agent.current_event = event
                try:
                    agent.handle(event)
                finally:
                    agent.current_event = None
                    agent.turn(event, answered=True)
                steps.append({"at": clock.moment.isoformat(), "who": who, "said": text,
                              "answer": [m["text"] for m in messenger.sent[before:]]})

            for minutes, who, text in SCRIPT:
                clock.moment = START + datetime.timedelta(minutes=minutes)
                say(who, text)
            pushes = []
            for moment in (datetime.datetime(2026, 10, 29, 19, 0, tzinfo=TZ),
                           datetime.datetime(2026, 10, 30, 8, 0, tzinfo=TZ)):
                clock.moment = moment
                before = len(messenger.sent)
                notified = pedi.tick(moment)
                pushes.append({"at": moment.isoformat(), "to": [n["person"] for n in notified],
                               "sent": messenger.sent[before:]})
            pushed = [e for e in replies if e.get("source") == "pediatrician"]
            card = hud_cards.from_push(pushed[-1], "es") if pushed else None
            clock.moment = datetime.datetime(2026, 10, 30, 8, 5, tzinfo=TZ)
            glasses = pedi.glance("es")
            echo = bridge.ask("agente del bebé, resumen para la pediatra", "echo")["reply"]
            for moment, who, text in AFTER:
                clock.moment = moment
                say(who, text)
            calls = [e for e in agent.bus.history if e["kind"] == "brain_call" and e.get("provider") == "pediatrician"]
            muse = [e for e in agent.bus.history if e["kind"] == "pediatrician" and str(e.get("action")).startswith("muse")]
            result = {"history": "parenting_agent/e2e/history.json", "born": child["birth_date"], "start": START.isoformat(),
                      "history_entries": len(rows), "said_note": agent.baby_log.entries("note")[-1],
                      "house_live": config["house"]["live"], "steps": steps, "pushes": pushes, "glasses_card": card,
                      "glasses_on_demand": glasses, "echo": echo, "muse_calls": calls, "muse_events": muse,
                      "refused": transport.refused, "telegram_api_calls": transport.calls.get("api.telegram.org", 0),
                      "questions_left": pedi.questions(), "real_s": round(REAL["monotonic"]() - started)}
        finally:
            transport.uninstall()
    (out / "run.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    summary = next((s for s in pushes[0]["sent"] if s["chat"] == harness.CHATS["ceci"]), {}).get("text", "")
    (out / "summary-eve-ceci.txt").write_text(summary + "\n")
    print(summary)
    print("---")
    print("card:", json.dumps(card, ensure_ascii=False))
    print("echo:", echo)
    print("muse calls:", len(calls), "usd:", round(sum(c.get("usd") or 0 for c in calls), 4),
          "rejected:", [e.get("why") for e in muse if e.get("action") == "muse_rejected"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "results/pediatrician")
