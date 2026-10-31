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

--sets old,judge (the default) runs the 70 messages above, then the round 3 real-new-parent judge's 37 messages, each
set in its own new family. --steps-file runs a JSON file of steps instead, in the same shape as STEPS:
[day, "HH:MM", "A" or "B", message, op, tag], where op is null, ["add", {"kind": "feeding", "method": "bottle",
"ml": 120, "type": "formula", "min": 0, "at": "HH:MM"}] (fields left out take the defaults of F, D, S, N and BATH below),
["edit", day, "HH:MM", kind, {fields}] or ["del", day, "HH:MM", kind], and tag is null, "q", "next" or "asleep HH:MM".
"""
import argparse
import collections
import datetime
import json
import re
import sys
import tempfile
import time
import zoneinfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent.agent import loop as loop_mod  # noqa: E402
from parenting_agent.agent import memory as memory_mod  # noqa: E402
from parenting_agent.agent import rules  # noqa: E402
from parenting_agent.families import service as service_mod  # noqa: E402
from parenting_agent.families import settings as settings_mod  # noqa: E402
from parenting_agent.families.service import Families  # noqa: E402
from parenting_agent.families.store import ALL, visitor_id  # noqa: E402

TZ = zoneinfo.ZoneInfo("America/Montevideo")
# The scorer's own checks, kept before a variant patches rules, so every variant is scored the same way.
message_lang, claims_change, claims_logged = rules.message_lang, rules.claims_change, rules.claims_logged
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
    # PR #97 logs the fever as a note for the pediatrician, with the no-advice line.
    (30, "15:00", B, "tiene fiebre le doy paracetamol?", ("add", N()), None),
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


# The round 3 real-new-parent judge's 37 messages (judges/rounds/r3, his martin3.py), with the log a careful parent keeps.
JUDGE_STEPS = [
    (29, "01:40", A, "recien tomo 80 de la mamadera", ("add", F(ml=80)), None),
    (29, "01:42", A, "uy no fueron 60, los otros 20 los dejo", ("edit", 29, "01:40", "feeding", {"ml": 60.0}), None),
    (29, "02:30", A, "pañal mojadisimo", ("add", D(wet=True)), None),
    (29, "04:50", B, "pecho izquierdo 15", ("add", F("left breast", minutes=15)), None),
    (29, "04:51", B, "pecho izquierdo 15", None, None),
    (29, "04:53", B, "ah no esa ya la habia puesto", None, None),
    (29, "07:15", A, "a que hora comio la ultima", None, "q"),
    (29, "07:16", A, "y cuanto lleva desde la medianoche", None, "q"),
    (29, "09:10", B, "se durmio en el cochecito", None, "asleep 09:10"),
    (29, "10:20", B, "ya se levanto", ("add", S("09:10")), None),
    (29, "10:25", A, "cuanto fue la siesta", None, "q"),
    (29, "13:00", A, "le dimos 100 de materna extraida a eso de las 12 y media",
     ("add", F(ml=100, kind_type="breast milk", at="12:30")), None),
    (29, "13:05", A, "no espera, fue a las 12", ("edit", 29, "12:30", "feeding", {"at": "12:00"}), None),
    (29, "16:00", B, "le puedo dar agua? hace calor", None, None),
    (29, "20:05", A, "/resumen", None, None),
    (30, "00:50", A, "mamadera 4 onzas", ("add", F(ml=120)), None),
    (30, "00:52", A, "en realidad tomo 3, dejo una", ("edit", 30, "00:50", "feeding", {"ml": 90.0}), None),
    (30, "02:40", B, "caca amarilla", ("add", D(solid=True)), None),
    (30, "02:41", B, "saca el ultimo pañal q no era", ("del", 30, "02:40", "diaper"), None),
    (30, "05:00", A, "le dio teta de los dos lados 25 min", ("add", F("both breasts", minutes=25)), None),
    (30, "07:30", A, "le toca ya?", None, "next"),
    (30, "11:00", B, "hizo una siestita de 40 min", ("add", S("10:20")), None),
    (30, "14:00", A, "tomo la mitad de la mamadera de 120", ("add", F(ml=60)), None),
    (30, "18:00", A, "cuantos pañales sucios hoy", None, "q"),
    (30, "20:10", B, "/resumen", None, None),
    (30, "22:00", A, "tiene la nariz tapada y le cuesta tomar", ("add", N()), None),
    (31, "01:20", A, "90", ("add", F(ml=90)), None),
    (31, "01:21", A, "de mamadera digo", None, None),
    (31, "03:30", B, "lloro un monton y despues tomo pecho der 10 min", ("add", F("right breast", minutes=10)), None),
    (31, "06:00", A, "mamadera 110", ("add", F(ml=110)), None),
    (31, "06:01", A, "mamadera 110", None, None),
    (31, "06:02", A, "fueron dos, la otra se la dio mi suegra", ("add", F(ml=110, at="06:01")), None),
    (31, "09:00", A, "q comio ayer en total", None, "q"),
    (31, "12:00", A, "la de la 1 y 20 fue 80", ("edit", 31, "01:20", "feeding", {"ml": 80.0}), None),
    (31, "15:00", A, "durmio 2 horas recien se desperto", ("add", S("13:00")), None),
    (31, "15:05", A, "/proxima", None, "next"),
    (31, "20:10", A, "/resumen", None, None),
]
SETS = {"old": STEPS, "judge": JUDGE_STEPS}
MAKERS = {"feeding": lambda e: F(e.get("method", "bottle"), e.get("ml"), e.get("type"), e.get("min", 0), e.get("at")),
          "diaper": lambda e: D(e.get("wet", False), e.get("solid", False), e.get("at")),
          "sleep": lambda e: S(e["start"], e.get("at")), "note": lambda e: N(e.get("at")), "bath": lambda e: BATH(e.get("at"))}


DOUBLE_LINE = ("A new message is a new event even when it repeats an earlier one, a second bottle of the same amount "
               "included: log it, never ask.")
DOUBLE_ASK = ("The same report again a few minutes after it was logged is usually one message sent twice: log nothing and "
              "ask whether it was sent twice or there were two. Log the second only when the parent says there were two.")


def safety_only():
    """Variant b of the ablation (issue #77): the guards that judge the brain's log calls are switched off and only the
    safety ones stay, the emergency and newborn red flag lines, the health refusal, codes kept out of replies and the
    bounds on amounts, lengths and times. The brain decides the log operations, and its prompt asks about double sends
    because the agent no longer does."""
    off = {"said_only": lambda request, kind, details, ts=None: (details, ts), "addendum": lambda text: None,
           "diaper_patch": lambda text: None, "amount_followup": lambda text: None, "half_ml": lambda text: None,
           "ounces_ml": lambda text: None, "ounce_followup_ml": lambda request, previous: None,
           "named_time": lambda request, now: None, "feed_minutes": lambda text, now: None,
           "kinds_said": lambda text: set(), "denied_kinds": lambda text: set(), "says_sleep": lambda text: True,
           "chat_only": lambda text: False, "says_woke_only": lambda text: False, "medicine_only": lambda text: False,
           "from_earlier": lambda note, request, earlier: False, "one_diaper": lambda calls, request: calls,
           "is_edit_request": lambda text: False, "claims_change": lambda text: False,
           "is_log_request": lambda text: False, "claims_done": lambda text: False,
           "latest_time": lambda ts, now, request="": ts, "names_when": lambda text: True,
           "QUESTION_START": re.compile(r"(?!x)x")}
    for name, value in off.items():
        setattr(rules, name, value)
    loop_mod.Agent.addendum = lambda self, request: False
    loop_mod.Agent.same_feed_just_logged = lambda self, arguments: None
    loop_mod.Agent.delete_held = lambda self, request, arguments: None
    loop_mod.Agent.sleep_call = lambda self, arguments, request: arguments
    loop_mod.Agent.honest = lambda self, text, before, request, editing, ran: text
    loop_mod.Agent.unbacked_value = lambda self, text, before, request, editing, ran: text
    service_mod.SYSTEM = service_mod.SYSTEM.replace(DOUBLE_LINE, DOUBLE_ASK)
    assert DOUBLE_ASK in service_mod.SYSTEM


# The architectures the ablation compares: main's guards, guards cut to safety only, Muse's log operations checked
# by a second Muse call, and Muse's log operations alone.
VARIANTS = {"main": "guards", "safety": safety_only, "ops-verify": "ops-verify", "ops": "ops"}
LOG_MODE = {"mode": "ops"}


def load_steps(path):
    """Steps from a JSON file, in the STEPS shape. "A" and "B" are the two parents."""
    out = []
    for day, hhmm, who, text, op, tag in json.loads(Path(path).read_text()):
        if op and op[0] == "add":
            op = ("add", MAKERS[op[1]["kind"]](op[1]))
        elif op and op[0] == "edit":
            fields = dict(op[4])
            if "ml" in fields and fields["ml"] is not None:
                fields["ml"] = float(fields["ml"])
            op = ("edit", int(op[1]), op[2], op[3], fields)
        elif op:
            op = ("del", int(op[1]), op[2], op[3])
        out.append((int(day), hhmm, A if str(who).upper() == "A" else B, text, op, tag))
    return out


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


def step_brains(events):
    """The model of every brain call in a step, in order. A call Muse could not answer is named by its fallback."""
    answered = []
    for event in events:
        if event["kind"] == "brain_call":
            answered.append(event.get("model"))
        elif answered:
            answered[-1] = event.get("to_model")
    return answered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys-env", required=True)
    parser.add_argument("--out", required=True, help="path without extension, for .md and .json")
    parser.add_argument("--brain", default="baseten", choices=["baseten", "claude", "fake"])
    parser.add_argument("--sets", default="old,judge", help="comma list of message sets: " + ", ".join(SETS))
    parser.add_argument("--steps-file", help="a JSON file of steps to run instead of --sets")
    parser.add_argument("--variant", default="main", choices=list(VARIANTS), help="the log architecture to run")
    parser.add_argument("--claude-max-tokens", type=int, help="the Claude brain's max_tokens, to match Muse's 2048")
    args = parser.parse_args()
    if args.brain == "claude":
        import eval_brains  # offline model comparison only, never part of the runtime
        eval_brains.install()
    if args.claude_max_tokens:
        settings_mod.BRAINS["claude"] = {**settings_mod.BRAINS["claude"], "max_tokens": args.claude_max_tokens}
    setup = VARIANTS[args.variant]
    if callable(setup):
        setup()
        LOG_MODE["mode"] = "guards"
    else:
        LOG_MODE["mode"] = setup
    settings_mod.read_keys(args.keys_env)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    runs = [(Path(args.steps_file).stem, load_steps(args.steps_file))] if args.steps_file else \
        [(name, SETS[name]) for name in args.sets.split(",")]
    lines, results = [], []
    for name, steps in runs:
        part_lines, summary = run_set(args, name, steps)
        lines += part_lines
        results.append(summary)
    total = {"variant": args.variant, "sets": [r["set"] for r in results], "messages": sum(r["messages"] for r in results),
             "wrong_log_states": sum(r["wrong_log_states"] for r in results),
             "reply_misses": sum(r["reply_misses"] for r in results), "fallbacks": sum(r["fallbacks"] for r in results),
             "usd": round(sum(r["usd"] for r in results), 4),
             "seconds_per_message": round(sum(r["seconds"] for r in results) / max(1, sum(r["messages"] for r in results)), 2),
             "by_set": results}
    out.with_suffix(".md").write_text("\n".join(lines) + "\n")
    out.with_suffix(".json").write_text(json.dumps(total, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({k: total[k] for k in ("variant", "sets", "messages", "wrong_log_states", "reply_misses", "fallbacks",
                                            "usd", "seconds_per_message")}
                     | {"per_set": {r["set"]: (r["wrong_log_states"], r["reply_misses"]) for r in results}}))


def run_set(args, name, STEPS):
    """One message set in a new family. Returns its transcript lines and its summary."""
    data = tempfile.mkdtemp(prefix="never-wrong-")
    s = settings_mod.load({"PA_FAMILIES_BRAIN": args.brain, "PA_FAMILIES_DATA_DIR": data,
                           "PA_FAMILIES_FAMILY_USD": "5", "PA_FAMILIES_DAILY_USD": "5", "PA_FAMILIES_MAX_MESSAGES": "200",
                           "PA_FAMILIES_LOG_MODE": LOG_MODE["mode"]})
    clock = {"now": at(28, "23:30")}
    # As the judge did: the memory module's own wall clock follows the simulated one too.
    memory_mod.now = lambda: clock["now"].isoformat(timespec="seconds")
    app = Families(s, clock=lambda: clock["now"])
    lines = [f"# Never wrong, 3 simulated nights, set {name}, variant {args.variant}\n\nBrain: {s['brain'].get('provider')} {s['brain'].get('model')}\n"]
    code = app.store.create_invite(internal=True)
    for text in (f"/start {code}", "Lola", "2/9/2026", "si"):
        replies = app.handle(A, A, text, "private", "es-UY")
    partner = re.search(r"\b([A-Z2-9]{8})\b", replies[-1][1].split("\n", 1)[-1]).group(1)
    app.handle(B, B, f"/start {partner}", "private", "es-UY")
    fam = app.family(app.store.parent(visitor_id(A))["family_id"])
    fallbacks = []
    fam.agent.bus.subscribe(fallbacks.append, ["brain_fallback"])
    # Which brain answered each call of a step: a miss can be put on Muse or on the fallback.
    brains = []
    fam.agent.bus.subscribe(lambda e: brains.append(e), ["brain_call", "brain_fallback"])
    calls = []
    run = fam.agent.tools.run
    fam.agent.tools.run = lambda name, arguments: (calls.append(f"{name}({json.dumps(arguments, ensure_ascii=False)})"),
                                                   run(name, arguments))[1]
    expected, misses, reply_misses, pushes, steps = [], [], [], [], []
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
        brains.clear()
        before = actual_log(fam)
        started = time.monotonic()
        reply = " ".join(t for _, t in app.handle(who, who, text, "private", "es-UY", message_id=f"{n}"))
        seconds = round(time.monotonic() - started, 2)
        after = actual_log(fam)
        answered = step_brains(brains)
        steps.append({"step": n, "brains": answered, "seconds": seconds})
        expected = apply(expected, op, day, hhmm)
        lines.append(f"\n**{n}. `{day} {hhmm}` {'A' if who == A else 'B'}: {text}**\n\n> {reply}\n"
                     + (f"\ntools: `{'`, `'.join(calls)}`\n" if calls else "")
                     + (f"\nbrain: {', '.join(answered)}\n" if answered else ""))
        if after != expected:
            change = diff(expected, after)
            misses.append({"step": n, "message": text, "reply": reply, **change, "tools": list(calls), "brains": answered})
            lines.append(f"\nWRONG LOG STATE: missing {change['missing']}, extra {change['extra']}\n")
            expected = after
        changed = before != after
        if tag in ("q", "next") and NOT_LOGGED.search(reply):
            reply_misses.append({"step": n, "what": "a question got 'No pude anotarlo'", "reply": reply})
        if tag == "next" and not HAS_TIME.search(reply):
            reply_misses.append({"step": n, "what": "a next-feed answer with no time and no 'hace'", "reply": reply})
        # A reply follows the language of the parent's message, and the family's Spanish when the message says neither.
        wanted, got = message_lang(text) or "es", message_lang(reply)
        if got and got != wanted:
            what = "an English reply to a Spanish message" if got == "en" else "a Spanish reply to an English message"
            reply_misses.append({"step": n, "what": what, "reply": reply})
        if claims_change(reply) and not (changed and op and op[0] in ("edit", "del")):
            reply_misses.append({"step": n, "what": "a claimed change that did not happen", "reply": reply})
        if tag and tag.startswith("asleep"):
            # A sleep start is kept until the wake-up makes it one sleep entry: check the start the service holds.
            started = str(fam.fact("_sleep_started"))[11:16]
            if started != tag.split()[1]:
                misses.append({"step": n, "message": text, "reply": reply, "missing": [f"sleep start {tag.split()[1]}"],
                               "extra": [f"sleep start {started or 'none'}"], "tools": list(calls), "brains": answered})
                lines.append(f"\nWRONG LOG STATE: sleep start {started or 'none'}, expected {tag.split()[1]}\n")
        elif tag is None and op is None and claims_logged(reply) and not changed and not text.startswith("/"):
            reply_misses.append({"step": n, "what": "a claimed log with nothing logged", "reply": reply})
    final = actual_log(fam)
    spend = app.store._one("select coalesce(sum(usd),0) from spend where scope=?", (ALL,))[0]
    summary = {"set": name, "brain": s["brain"].get("model"), "messages": len(STEPS), "wrong_log_states": len(misses),
               "reply_misses": len(reply_misses), "fallbacks": len(fallbacks), "usd": round(spend, 4),
               "seconds": round(sum(x["seconds"] for x in steps), 1),
               "fallback_steps": [x["step"] for x in steps if any(b != s["brain"].get("model") for b in x["brains"])],
               "misses": misses, "reply_problems": reply_misses, "steps": steps, "final_log": final}
    lines.append("\n## Final log\n")
    lines += [f"- {json.dumps(e, ensure_ascii=False)}" for e in final]
    lines.append(f"\nWrong log states: {len(misses)} of {len(STEPS)} messages. Reply problems: {len(reply_misses)}. "
                 f"Fallbacks: {len(fallbacks)}. Spend: {spend:.4f} USD.")
    app.close()
    return lines, summary


if __name__ == "__main__":
    main()
