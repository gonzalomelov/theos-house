"""The adversarial 3-night run of the families bot: is the log ever wrong (issue #77)?

70 tired-parent messages written after the round 2 real-new-parent judge, none taken from his harness or from
scripts/families_3day_run.py: typos, no accents, voseo, double sends, corrections of amounts, sides and times, deletes,
a "se mando doble" with nothing sent twice, questions, a health question and observations. Two parents, a Montevideo
clock simulated from Oct 29 to Oct 31 2026, the real brain (Muse Spark Open on Baseten by default), the families
service through Families.handle and tick as the tests use it, and no Telegram.

After every message the whole log is compared with the log a careful human would keep. A step where they differ is a
wrong log state: the run records the diff and then takes the real log as the new truth, so one miss is counted once.
Replies are checked too: a claimed change with no change, "No pude anotarlo" for a question, a next-feed answer with
neither a time nor how long ago. As the judge did, the memory module's wall clock is patched to the simulated clock.

    .venv/bin/python scripts/families_never_wrong_run.py --keys-env ~/.parenting-agent.env \
        --out results/families-never-wrong/run-1
"""
import argparse
import collections
import datetime
import json
import re
import sys
import tempfile
import zoneinfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent.agent import memory as memory_mod  # noqa: E402
from parenting_agent.agent import rules  # noqa: E402
from parenting_agent.families import settings as settings_mod  # noqa: E402
from parenting_agent.families.service import Families  # noqa: E402
from parenting_agent.families.store import ALL, visitor_id  # noqa: E402

TZ = zoneinfo.ZoneInfo("America/Montevideo")
A, B = 8101, 8102
NOT_LOGGED = re.compile(r"No pude anotarlo", re.I)
HAS_TIME = re.compile(r"\b\d{1,2}:\d{2}\b|\bhace\b")


def F(method="bottle", ml=None, kind_type=None, minutes=0, at=None):
    """An expected feed. kind_type is the milk type: unknown for a bottle with none said, breast milk for a breast feed."""
    breast = "breast" in method
    return {"kind": "feeding", "method": method, "ml": float(ml) if ml is not None else None,
            "type": kind_type or ("breast milk" if breast else "unknown"), "min": minutes, "at": at}


def D(wet=False, solid=False, at=None):
    return {"kind": "diaper", "wet": wet or not solid, "solid": solid, "at": at}


def S(start, at=None):
    return {"kind": "sleep", "start": start, "at": at}


def N(at=None):
    return {"kind": "note", "at": at}


def BATH(at=None):
    return {"kind": "bath", "at": at}


# (day, time, who, message, what the log does, what the reply is). The log op is None (no change), ("add", entry),
# ("edit", day, at, kind, fields) or ("del", day, at, kind). The reply tag is q (a question), next (the next feed),
# asleep HH:MM (a sleep start the service keeps until the wake-up) or None.
STEPS = [
    # Night 1, Oct 29
    (29, "00:40", A, "le di 120 de formula", ("add", F(ml=120, kind_type="formula")), None),
    (29, "00:42", A, "nono eran 100, sobro un poco", ("edit", 29, "00:40", "feeding", {"ml": 100.0}), None),
    (29, "01:30", A, "pañal pis nomas", ("add", D(wet=True)), None),
    (29, "03:10", B, "teta izq 15 min", ("add", F("left breast", minutes=15)), None),
    (29, "03:11", B, "teta izq 15 min", None, None),
    (29, "03:12", B, "se mando dos veces sorry", None, None),
    (29, "03:40", B, "cambie pañal, caca y pis", ("add", D(wet=True, solid=True)), None),
    (29, "04:05", A, "se durmio recien", None, "asleep 04:05"),
    (29, "06:20", A, "se desperto", ("add", S("04:05")), None),
    (29, "06:25", A, "mamadera 90", ("add", F(ml=90)), None),
    (29, "06:26", A, "mamadera 90", None, None),
    (29, "06:27", A, "fueron dos, tomo otra", ("add", F(ml=90, at="06:26")), None),
    (29, "07:00", B, "cuanto tomo desde anoche?", None, "q"),
    (29, "08:15", B, "pecho der 10 min", ("add", F("right breast", minutes=10)), None),
    (29, "08:16", B, "no perdon, fue el izquierdo", ("edit", 29, "08:15", "feeding", {"method": "left breast"}), None),
    (29, "09:30", A, "a q hora le toca?", None, "next"),
    (29, "10:00", A, "le di 110 a las 9:40", ("add", F(ml=110, at="09:40")), None),
    (29, "10:02", A, "no, fue a las 9 y media", ("edit", 29, "09:40", "feeding", {"at": "09:30"}), None),
    (29, "11:00", B, "pañal sucio", ("add", D(solid=True)), None),
    (29, "11:01", B, "borra el ultimo pañal porfa", ("del", 29, "11:00", "diaper"), None),
    (29, "12:30", A, "hizo un poquito de caca amarilla", ("add", D(solid=True)), None),
    (29, "13:00", A, "vomitó un poco despues de la teta", ("add", N()), None),
    (29, "14:00", B, "cuantos pañales lleva hoy?", None, "q"),
    # Night 2, Oct 30
    (30, "00:20", A, "biberon de 130", ("add", F(ml=130)), None),
    (30, "00:21", A, "ahh no era 120", ("edit", 30, "00:20", "feeding", {"ml": 120.0}), None),
    (30, "02:00", B, "teta derecha 18 minutos", ("add", F("right breast", minutes=18)), None),
    (30, "02:02", B, "teta derecha 18 minutos", None, None),
    (30, "02:03", B, "una sola", None, None),
    (30, "02:30", A, "le cambie el pañal mojado", ("add", D(wet=True)), None),
    (30, "03:45", A, "se quedo dormida a las 3 y 20", None, "asleep 03:20"),
    (30, "05:10", A, "se desperto a las 5", ("add", S("03:20", at="05:00")), None),
    (30, "05:15", B, "mamadera 100 ml de leche materna", ("add", F(ml=100, kind_type="breast milk")), None),
    (30, "05:17", B, "perdon fueron 80", ("edit", 30, "05:15", "feeding", {"ml": 80.0}), None),
    (30, "06:00", A, "cuando fue la ultima toma?", None, "q"),
    (30, "07:30", B, "teta izq y der, 25 min", ("add", F("both breasts", minutes=25)), None),
    (30, "08:00", A, "tomo 3 onzas", ("add", F(ml=90)), None),
    (30, "08:01", A, "me equivoque, eran 2 onzas", ("edit", 30, "08:00", "feeding", {"ml": 60.0}), None),
    (30, "09:00", B, "hace cuanto q no hace caca?", None, "q"),
    (30, "10:30", A, "pañal con pis y caca", ("add", D(wet=True, solid=True)), None),
    (30, "10:31", A, "ese pañal era solo pis", ("edit", 30, "10:30", "diaper", {"solid": False}), None),
    (30, "12:00", B, "lo bañamos", ("add", BATH()), None),
    (30, "12:05", B, "/proxima", None, "next"),
    (30, "13:15", A, "le di 100", ("add", F(ml=100)), None),
    (30, "13:16", A, "le di 100", None, None),
    (30, "13:18", A, "q?", None, None),
    (30, "13:19", A, "fue una sola, la mande 2 veces", None, None),
    (30, "15:00", B, "tiene fiebre le doy paracetamol?", None, None),
    (30, "16:40", A, "pecho izq 12 min a las 16:20", ("add", F("left breast", minutes=12, at="16:20")), None),
    (30, "16:45", A, "borra esa ultima toma, no fue", ("del", 30, "16:20", "feeding"), None),
    # Night 3, Oct 31
    (31, "00:50", A, "90 ml formula", ("add", F(ml=90, kind_type="formula")), None),
    (31, "00:52", A, "nono 70", ("edit", 31, "00:50", "feeding", {"ml": 70.0}), None),
    (31, "01:40", B, "panal mojado", ("add", D(wet=True)), None),
    (31, "03:00", B, "teta der 15 min", ("add", F("right breast", minutes=15)), None),
    (31, "03:01", B, "se mando doble", None, None),
    (31, "04:30", A, "mamadera 120", ("add", F(ml=120)), None),
    (31, "04:31", A, "nonono 110", ("edit", 31, "04:30", "feeding", {"ml": 110.0}), None),
    (31, "05:00", A, "se durmio", None, "asleep 05:00"),
    (31, "07:10", A, "ya se desperto", ("add", S("05:00")), None),
    (31, "07:15", B, "cuanto durmio anoche?", None, "q"),
    (31, "08:00", B, "teta de los dos lados 20 min", ("add", F("both breasts", minutes=20)), None),
    (31, "08:02", B, "no eran 25 min", ("edit", 31, "08:00", "feeding", {"min": 25}), None),
    (31, "09:30", A, "mamadera de 150", ("add", F(ml=150)), None),
    (31, "09:35", A, "dejo 30, o sea tomo 120", ("edit", 31, "09:30", "feeding", {"ml": 120.0}), None),
    (31, "10:00", B, "cuantas tomas van hoy?", None, "q"),
    (31, "11:20", A, "vomito un poquito dsp de la toma", ("add", N()), None),
    (31, "12:00", B, "a q hr come d nuevo?", None, "next"),
    (31, "13:00", A, "pañal sucio verde", ("add", D(solid=True)), None),
    (31, "13:30", B, "/resumen", None, None),
    (31, "14:00", A, "le dimos 60 de formula a las 13:45", ("add", F(ml=60, kind_type="formula", at="13:45")), None),
    (31, "14:02", A, "perdon, a las 13:40", ("edit", 31, "13:45", "feeding", {"at": "13:40"}), None),
]


def at(day, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.datetime(2026, 10, day, h, m, tzinfo=TZ)


def normal(entry):
    """One log entry in the fields the run compares. A breast feed's duration and a bottle's milk type count."""
    d, ts = entry["details"], entry["ts"]
    out = {"kind": entry["kind"], "day": int(ts[8:10]), "at": ts[11:16]}
    if entry["kind"] == "feeding":
        out.update(method=d.get("method") or "bottle", ml=float(d["amount_ml"]) if d.get("amount_ml") is not None else None,
                   type=d.get("type") or "unknown", min=int(d.get("duration_min") or 0))
    elif entry["kind"] == "diaper":
        out.update(wet=bool(d.get("wet")), solid=bool(d.get("solid")))
    elif entry["kind"] == "sleep":
        out.update(start=str(d.get("start") or "")[11:16])
    return out


def key(e):
    return json.dumps(e, sort_keys=True)


def actual_log(fam):
    rows = []
    for kind in ("feeding", "diaper", "sleep", "bath", "note"):
        rows += [normal(e) for e in fam.log.entries(kind, None, 100_000)]
    return sorted(rows, key=lambda e: (e["day"], e["at"], e["kind"], key(e)))


def apply(expected, op, day, hhmm):
    """The log after one message, as a careful human would keep it."""
    expected = [dict(e) for e in expected]
    if op is None:
        return expected
    if op[0] == "add":
        entry = {k: v for k, v in op[1].items()}
        entry["day"], entry["at"] = day, entry.get("at") or hhmm
        expected.append(entry)
    elif op[0] in ("edit", "del"):
        _, d, t, kind = op[:4]
        found = [e for e in expected if e["day"] == d and e["at"] == t and e["kind"] == kind]
        if not found:
            # The entry went missing at an earlier step, a miss already counted there: nothing to change now.
            return expected
        if op[0] == "del":
            expected.remove(found[-1])
        else:
            found[-1].update(op[4])
    return sorted(expected, key=lambda e: (e["day"], e["at"], e["kind"], key(e)))


def diff(expected, actual):
    want, got = collections.Counter(map(key, expected)), collections.Counter(map(key, actual))
    return {"missing": [json.loads(k) for k in (want - got).elements()], "extra": [json.loads(k) for k in (got - want).elements()]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys-env", required=True)
    parser.add_argument("--out", required=True, help="path without extension, for .md and .json")
    parser.add_argument("--brain", default="baseten", choices=["baseten", "claude", "fake"])
    args = parser.parse_args()
    settings_mod.read_keys(args.keys_env)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = tempfile.mkdtemp(prefix="never-wrong-")
    s = settings_mod.load({"PA_FAMILIES_BRAIN": args.brain, "PA_FAMILIES_DATA_DIR": data,
                           "PA_FAMILIES_FAMILY_USD": "5", "PA_FAMILIES_DAILY_USD": "5", "PA_FAMILIES_MAX_MESSAGES": "200"})
    clock = {"now": at(28, "23:30")}
    # As the judge did: the memory module's own wall clock follows the simulated one too.
    memory_mod.now = lambda: clock["now"].isoformat(timespec="seconds")
    app = Families(s, clock=lambda: clock["now"])
    lines = [f"# Never wrong, 3 simulated nights\n\nBrain: {s['brain'].get('provider')} {s['brain'].get('model')}\n"]
    code = app.store.create_invite(internal=True)
    for text in (f"/start {code}", "Lola", "2/9/2026", "si"):
        replies = app.handle(A, A, text, "private", "es-UY")
    partner = re.search(r"\b([A-Z2-9]{8})\b", replies[-1][1].split("\n", 1)[-1]).group(1)
    app.handle(B, B, f"/start {partner}", "private", "es-UY")
    fam = app.family(app.store.parent(visitor_id(A))["family_id"])
    fallbacks = []
    fam.agent.bus.subscribe(fallbacks.append, ["brain_fallback"])
    calls = []
    run = fam.agent.tools.run
    fam.agent.tools.run = lambda name, arguments: (calls.append(f"{name}({json.dumps(arguments, ensure_ascii=False)})"),
                                                   run(name, arguments))[1]
    expected, misses, reply_misses, pushes = [], [], [], []
    last = clock["now"]
    for n, (day, hhmm, who, text, op, tag) in enumerate(STEPS, 1):
        moment = at(day, hhmm)
        tick = last
        while tick + datetime.timedelta(minutes=5) < moment:
            tick += datetime.timedelta(minutes=5)
            clock["now"] = tick
            for chat, said in app.tick(tick):
                pushes.append(said)
                lines.append(f"- `{tick:%d %H:%M}` push to {'A' if str(chat) == str(A) else 'B'}: {said}")
                if NOT_LOGGED.search(said):
                    reply_misses.append({"step": n, "what": "push says it could not log", "reply": said})
        clock["now"], last = moment, moment
        calls.clear()
        before = actual_log(fam)
        reply = " ".join(t for _, t in app.handle(who, who, text, "private", "es-UY", message_id=f"{n}"))
        after = actual_log(fam)
        expected = apply(expected, op, day, hhmm)
        lines.append(f"\n**{n}. `{day} {hhmm}` {'A' if who == A else 'B'}: {text}**\n\n> {reply}\n"
                     + (f"\ntools: `{'`, `'.join(calls)}`\n" if calls else ""))
        if after != expected:
            change = diff(expected, after)
            misses.append({"step": n, "message": text, "reply": reply, **change, "tools": list(calls)})
            lines.append(f"\nWRONG LOG STATE: missing {change['missing']}, extra {change['extra']}\n")
            expected = after
        changed = before != after
        if tag in ("q", "next") and NOT_LOGGED.search(reply):
            reply_misses.append({"step": n, "what": "a question got 'No pude anotarlo'", "reply": reply})
        if tag == "next" and not HAS_TIME.search(reply):
            reply_misses.append({"step": n, "what": "a next-feed answer with no time and no 'hace'", "reply": reply})
        if rules.claims_change(reply) and not (changed and op and op[0] in ("edit", "del")):
            reply_misses.append({"step": n, "what": "a claimed change that did not happen", "reply": reply})
        if tag and tag.startswith("asleep"):
            # A sleep start is kept until the wake-up makes it one sleep entry: check the start the service holds.
            started = str(fam.fact("_sleep_started"))[11:16]
            if started != tag.split()[1]:
                misses.append({"step": n, "message": text, "reply": reply, "missing": [f"sleep start {tag.split()[1]}"],
                               "extra": [f"sleep start {started or 'none'}"], "tools": list(calls)})
                lines.append(f"\nWRONG LOG STATE: sleep start {started or 'none'}, expected {tag.split()[1]}\n")
        elif tag is None and op is None and rules.claims_logged(reply) and not changed and not text.startswith("/"):
            reply_misses.append({"step": n, "what": "a claimed log with nothing logged", "reply": reply})
    final = actual_log(fam)
    spend = app.store._one("select coalesce(sum(usd),0) from spend where scope=?", (ALL,))[0]
    summary = {"brain": s["brain"].get("model"), "messages": len(STEPS), "wrong_log_states": len(misses),
               "reply_misses": len(reply_misses), "fallbacks": len(fallbacks), "usd": round(spend, 4),
               "misses": misses, "reply_problems": reply_misses, "final_log": final}
    lines.append("\n## Final log\n")
    lines += [f"- {json.dumps(e, ensure_ascii=False)}" for e in final]
    lines.append(f"\nWrong log states: {len(misses)} of {len(STEPS)} messages. Reply problems: {len(reply_misses)}. "
                 f"Fallbacks: {len(fallbacks)}. Spend: {spend:.4f} USD.")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n")
    out.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    app.close()
    print(json.dumps({k: summary[k] for k in ("messages", "wrong_log_states", "reply_misses", "fallbacks", "usd")}))


if __name__ == "__main__":
    main()
