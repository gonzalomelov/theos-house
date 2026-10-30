"""Score the held-out set once against a checkout, with the real Muse Spark Open brain in log ops mode.

Usage: python score.py <repo checkout> <out prefix> [baseten|claude]
The optional brain is baseten (Muse) by default. claude runs the same set on Claude Haiku with max_tokens 2048, as Muse.
Writes <out prefix>.md (transcript and verdicts) and <out prefix>.json (scores). Telegram is never touched: replies
come back from Families.handle. The keys are read from the hackathon .env into this process only.
"""
import datetime
import json
import os
import re
import sys
import tempfile
import zoneinfo
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
BRAIN = sys.argv[3] if len(sys.argv) > 3 else "baseten"
sys.path.insert(0, str(REPO))

from parenting_agent.families import settings as settings_mod  # noqa: E402
from parenting_agent.families.service import Families  # noqa: E402
from parenting_agent.families.store import ALL, visitor_id  # noqa: E402
import parenting_agent.agent.memory as MEM  # noqa: E402

TZ = zoneinfo.ZoneInfo("America/Montevideo")
WHO = {"A": 8101, "B": 8102}
ENGLISH = re.compile(r"\b(the|I|I've|I'm|logged|no worries|left it|kept|bottle|feed|diaper|sleep|nothing|changed)\b")
TAIL = "consejo médico"


def at(text):
    return datetime.datetime.fromisoformat(text).replace(tzinfo=TZ)


def snapshot(fam):
    entries = {e["id"]: e for e in fam.log.entries(None, None, 10_000)}
    return entries, fam.log.open_sleep() or ""


def hm(ts):
    return datetime.datetime.fromisoformat(ts).astimezone(TZ).strftime("%H:%M")


def matches(entry, want):
    d = entry["details"]
    if entry["kind"] != want["kind"]:
        return False
    if "ml" in want and float(d.get("amount_ml") or 0) != float(want["ml"]):
        return False
    if "method" in want and want["method"] not in str(d.get("method") or ""):
        return False
    if "duration" in want and int(d.get("duration_min") or 0) != int(want["duration"]):
        return False
    for flag in ("wet", "solid"):
        if flag in want and bool(d.get(flag)) != want[flag]:
            return False
    if "at" in want:
        moment = d.get("start") if entry["kind"] == "feeding" and d.get("start") else entry["ts"]
        if hm(moment) != want["at"] and hm(entry["ts"]) != want["at"]:
            return False
    return True


def verdict(expect, before, after, reply):
    (old, old_open), (new, new_open) = before, after
    added = [e for i, e in new.items() if i not in old]
    edited = [e for i, e in new.items() if i in old and old[i] != e]
    deleted = [e for i, e in old.items() if i not in new]
    problems = []
    if expect.get("allow_sleep"):
        added = [e for e in added if e["kind"] != "sleep"]
        new_open = old_open = ""
    if expect.get("none"):
        if added or edited or deleted or new_open != old_open:
            problems.append("log changed")
    if "add" in expect:
        left = list(added)
        for want in expect["add"]:
            hit = next((e for e in left if matches(e, want)), None)
            if hit is None:
                problems.append(f"missing {want}")
            else:
                left.remove(hit)
        if left:
            problems.append(f"extra {[(e['kind'], e['details']) for e in left]}")
        if edited or deleted:
            problems.append("an older entry changed")
    if "edit" in expect:
        if added or deleted or not any(matches(e, expect["edit"]) for e in edited):
            problems.append(f"edit to {expect['edit']} not made")
    if "sleep_start" in expect:
        if not new_open or hm(new_open) != expect["sleep_start"]:
            problems.append(f"open sleep {new_open or 'none'}")
        if added or edited or deleted:
            problems.append("other change")
    if "sleep_end" in expect:
        sleeps = [e for e in added if e["kind"] == "sleep"]
        if len(sleeps) != 1 or hm(sleeps[0]["ts"]) != expect["sleep_end"] or new_open:
            problems.append("sleep not closed at " + expect["sleep_end"])
    for word in expect.get("reply_has", []):
        if word not in reply:
            problems.append(f"reply lacks {word}")
    for word in expect.get("reply_not", []):
        if word in reply:
            problems.append(f"reply says {word}")
    if expect.get("no_tail") and TAIL in reply:
        problems.append("unasked medical tail")
    language_ok = not ENGLISH.search(reply)
    if not language_ok:
        problems.append("reply in English")
    return problems, language_ok


def main():
    spec = json.loads((HERE / "heldout.json").read_text())
    env = {}
    settings_mod.read_keys(str(Path.home() / ".parenting-agent.env"), env)
    for name in settings_mod.BRAIN_KEYS:
        if name in env:
            os.environ[name] = env[name]
    data = tempfile.mkdtemp(prefix="heldout-")
    if BRAIN == "claude":
        settings_mod.BRAINS["claude"] = {**settings_mod.BRAINS["claude"], "max_tokens": 2048}
    s = settings_mod.load({"PA_FAMILIES_BRAIN": BRAIN, "PA_FAMILIES_DATA_DIR": data, "PA_FAMILIES_LOG_MODE": "ops"})
    clock = {"now": at(spec["start"])}
    MEM.now = lambda: clock["now"].isoformat(timespec="seconds")
    app = Families(s, clock=lambda: clock["now"])
    lines = [f"brain {s['brain']['model']} log_mode {s.get('log_mode')} repo {REPO}"]
    code = app.store.create_invite(internal=True)
    for t in (f"/start {code}", spec["baby"], spec["birth"], "si"):
        r = app.handle(WHO["A"], WHO["A"], t, "private", "es-UY")
    partner = re.search(r"\b([A-Z2-9]{8})\b", r[-1][1].split("\n", 1)[-1]).group(1)
    app.handle(WHO["B"], WHO["B"], f"/start {partner}", "private", "es-UY")
    fam = app.family(app.store.parent(visitor_id(WHO["A"]))["family_id"])
    fallbacks = []
    fam.agent.bus.subscribe(fallbacks.append, ["brain_fallback"])
    rows, last = [], clock["now"]
    for i, m in enumerate(spec["messages"], 1):
        moment, tick = at(m["at"]), last
        while tick + datetime.timedelta(minutes=5) < moment:
            tick += datetime.timedelta(minutes=5)
            clock["now"] = tick
            app.tick(tick)
        clock["now"], last = moment, moment
        before = snapshot(fam)
        r = app.handle(WHO[m["who"]], WHO[m["who"]], m["text"], "private", "es-UY", message_id=f"h{i}")
        reply = " | ".join(x for _, x in r)
        problems, language_ok = verdict(m["expect"], before, snapshot(fam), reply)
        rows.append({"n": i, "text": m["text"], "ok": not problems, "language_ok": language_ok, "problems": problems,
                     "reply": reply})
        lines.append(f"{i:2d} [{moment:%d %H:%M}] {m['who']}: {m['text']}\n   > {reply}\n   {'OK' if not problems else 'WRONG: ' + '; '.join(problems)}")
    spend = app.store._one("select coalesce(sum(usd),0) from spend where scope=?", (ALL,))[0]
    lines.append("\nFINAL LOG")
    for e in fam.log.entries(None, None, 10_000):
        lines.append(f"{e['kind']} {e['ts'][:16]} {json.dumps(e['details'], ensure_ascii=False)}")
    ok = sum(r["ok"] for r in rows)
    summary = {"right": ok, "total": len(rows), "spanish": sum(r["language_ok"] for r in rows), "fallbacks": len(fallbacks),
               "usd": round(spend, 4), "repo": str(REPO)}
    lines.append(f"\nright {ok} of {len(rows)}, Spanish replies {summary['spanish']} of {len(rows)}, fallbacks {len(fallbacks)}, "
                 f"spend {spend:.4f} USD")
    OUT.with_suffix(".md").write_text("\n".join(lines) + "\n")
    OUT.with_suffix(".json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
    app.close()
    print(json.dumps(summary))


main()
