"""Scores an end-to-end day the way a parent would feel it, and writes the timeline.

Every message that left the agent is checked: on time, to the right parent, once, in Spanish (both parents write in
Spanish), with nothing internal in it. Every proactive item the day needs is looked for. Every log entry the parents
asked for is looked up in Baby Buddy.
"""
import collections
import datetime
import json
import re
from pathlib import Path

from ..agent import rules

INTERNAL = re.compile(r"finish[_ ]?reason|reason length|\bParent [AB]\b|\bMuse\b|\bJSON\b|Traceback|\bNone\b|\bnull\b|"
                      r"\b[a-z]+_[a-z_]+\b|fixed routines|computed from|\bplan armed\b", re.I)
PREP = re.compile(r"before he arrives|antes de que llegue", re.I)
NEXT_FEED = re.compile(r"next feed|pr[óo]xima toma", re.I)
SUPPLY = re.compile(r"diapers|pañales|panales", re.I)
NIGHT = (22, 6)


def parse(ts):
    return datetime.datetime.fromisoformat(ts)


def is_night(t):
    return t.hour >= NIGHT[0] or t.hour < NIGHT[1]


def english(text):
    """English to a Spanish parent: a sentence with English words and nothing that reads Spanish. Checked sentence by
    sentence, so an English line inside a Spanish morning message counts."""
    body = re.sub(r"«[^»]*»", "", text)  # the heard words of a voice note are the parent's own
    parts = [p for p in re.split(r"(?<=[.!?:])\s+|\n", body) if len(p.split()) >= 3]
    return any(not rules.looks_spanish(p) and len(rules.ENGLISH.findall(p)) >= 2 for p in parts)


def load(run_dir):
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text())
    events = [json.loads(line) for line in (run_dir / "data/events.jsonl").read_text().splitlines() if line.strip()]
    return run, events


def outgoing(run, events):
    """Each text message that left, with who got it and whether the agent started it."""
    person_of = {chat: who for who, chat in run["chats"].items()}
    replies = [e for e in events if e["kind"] == "reply"]
    rows = []
    for sent in run["sent"]:
        if sent.get("voice"):
            continue
        text = sent["text"]
        match = next((e for e in replies if str(e.get("chat_id")) == sent["chat"] and e.get("text") and e["text"] in text
                      and abs((parse(e["ts"]) - parse(sent["at"])).total_seconds()) <= 120), None)
        rows.append({"at": sent["at"], "to": person_of.get(sent["chat"], sent["chat"]), "text": text,
                     "proactive": bool(match and match.get("proactive")), "source": (match or {}).get("source")})
    return rows


def judge_messages(rows, run, events):
    """Noise per message: English, internal words, prep lines after the birth, duplicates, the wrong parent."""
    sleep_asked = next((parse(s["at"]) for s in run["steps"] if s.get("who") == "ceci" and "necesito dormir"
                        in (s.get("text") or "")), None)
    told = [(parse(s["at"]), s["who"]) for s in run["steps"] if s.get("do") in ("message", "voice")]
    seen = collections.defaultdict(list)
    for row in rows:
        t, problems = parse(row["at"]), []
        if english(row["text"]):
            problems.append("English to a Spanish parent")
        internal = INTERNAL.search(row["text"])
        if internal:
            problems.append(f"internal text ({internal.group(0)})")
        if PREP.search(row["text"]):
            problems.append("prep lines after the birth")
        # A push the agent starts twice is noise. A short confirmation that repeats ("Pañal mojado registrado.") answers
        # a new message each time, so replies are never duplicates.
        key = (row["to"], re.sub(r"\d", "#", row["text"].strip().lower())[:160])
        if row["proactive"] and any(abs((t - other).total_seconds()) < 6 * 3600 for other in seen[key]):
            problems.append("duplicate")
        if row["proactive"]:
            seen[key].append(t)
        if row["proactive"] and is_night(t):
            if row["to"] == "ceci" and sleep_asked and t > sleep_asked:
                problems.append("night push to Ceci after she asked to sleep")
            just_said = any(who == row["to"] and 0 <= (t - when).total_seconds() <= 180 for when, who in told)
            if just_said and row.get("source") == "night_feed":
                problems.append("night push to the parent who just said it")
        row["problems"] = problems
        row["verdict"] = "noise" if problems else "ok"
    return rows


def expectations(run, events, rows, day0):
    """The items a parent must get, each found or missed."""
    D = lambda d, hhmm: datetime.datetime.combine(day0 + datetime.timedelta(days=d),
                                                  datetime.time(*map(int, hhmm.split(":"))), parse(run["start"]).tzinfo)
    proactive = [r for r in rows if r["proactive"]]
    out = []

    def check(name, ok, detail):
        out.append({"item": name, "found": bool(ok), "detail": detail})

    for d in (0, 1):
        for who in ("gonza", "ceci"):
            got = [r for r in proactive if r["to"] == who and D(d, "07:25") <= parse(r["at"]) <= D(d, "08:10")]
            morning = [r for r in got if re.search(r"good morning|buen d[íi]a", r["text"], re.I)]
            check(f"morning message day {d} to {who}", len(morning) == 1 and len(got) == 1,
                  f"{len(morning)} morning message(s), {len(got)} message(s) 07:25 to 08:10")
    feeds = [parse(s["at"]) for s in run["steps"] if (s.get("expect") or [None])[0] == "feeding"]
    day_feeds = [f for f in feeds if not is_night(f) and f - parse(run["start"]) > datetime.timedelta(hours=1)]
    for f in day_feeds:
        warned = [r for r in proactive if NEXT_FEED.search(r["text"]) and f - datetime.timedelta(minutes=90) <= parse(r["at"]) <= f]
        check(f"next-feed reminder before the {f:%H:%M} feed", warned, f"{len(warned)} reminder(s) in the 90 min before")
    naps = [e for e in events if e["kind"] == "routine" and e.get("name") == "nap_mode" and e.get("step") == "on"]
    starts = [parse(s["at"]) for s in run["steps"] if (s.get("expect") or [None])[0] == "sleep_start"]
    for s in starts:
        hit = [e for e in naps if 0 <= (parse(e["ts"]) - s).total_seconds() <= 300]
        check(f"nap mode on after the {s:%H:%M} sleep", hit, f"{len(hit)} nap_mode on event(s) within 5 min")
    asked = D(0, "20:00")
    handover = [r for r in proactive if r["to"] == "gonza" and asked <= parse(r["at"]) <= D(0, "21:30")
                and re.search(r"gonza|te toca|de turno|on duty", r["text"], re.I)]
    check("night handover to Gonza after Ceci asked to sleep", handover, f"{len(handover)} message(s) to Gonza 20:00 to 21:30")
    tonight = [r for r in proactive if D(0, "20:25") <= parse(r["at"]) <= D(0, "21:30")
               and re.search(r"tonight|esta noche", r["text"], re.I)]
    check("tonight's plan at bedtime, at most one per parent", tonight and len(tonight) <= 2,
          f"{len(tonight)} plan message(s)")
    cry = D(1, "02:50")
    woke = [r for r in proactive if r["to"] == "gonza" and 0 <= (parse(r["at"]) - cry).total_seconds() <= 300]
    check("night cry: push to Gonza (on duty) within 5 min", woke, f"{len(woke)} push(es)")
    ceci_night = [r for r in proactive if r["to"] == "ceci" and asked <= parse(r["at"]) and is_night(parse(r["at"]))]
    check("no night push to Ceci after she asked to sleep", not ceci_night, f"{len(ceci_night)} night push(es) to Ceci")
    low = [r for r in proactive if SUPPLY.search(r["text"]) and re.search(r"low|running|quedan|termin|lista|list", r["text"], re.I)]
    per = collections.Counter(r["to"] for r in low)
    check("diapers running low told once to each parent", per.get("gonza") == 1 and per.get("ceci") == 1, dict(per) or "none")
    adds = [e for e in events if (e["kind"] in ("house_dry", "house_live") and "todo.add_item" in
                                  str(e.get("action") or e.get("service")))]
    check("diapers on the shopping list once (dry in the run)", 1 <= len(adds) <= 2,
          f"{len(adds)} shopping list write(s): " + ", ".join(str(e.get("routine")) for e in adds))
    draft = [r for r in rows if r["to"] == "ceci" and D(0, "12:00") <= parse(r["at"]) <= D(0, "12:10")
             and re.search(r"resumen|handover|abuela|mam[áa]", r["text"], re.I)]
    sitter_events = [e for e in events if e["kind"] in ("sitter_draft", "sitter_summary")]
    check("sitter brief drafted for Ceci's mother", any(e["kind"] == "sitter_draft" for e in sitter_events),
          f"{len(draft)} reply, events: {[e['kind'] for e in sitter_events]}")
    check("sitter summary after the window", any(e["kind"] == "sitter_summary" for e in sitter_events),
          [e["kind"] for e in sitter_events])
    relayed = [r for r in rows if r["to"] == "ceci" and not r["proactive"] and D(0, "11:22") <= parse(r["at"]) <= D(0, "11:25")]
    check("grandma's question through Ceci answered with the last feed time",
          any(re.search(r"\b\d{1,2}:\d{2}\b", r["text"]) and not re.search(r"repet|anotar", r["text"]) for r in relayed),
          "; ".join(r["text"][:120] for r in relayed) or "no answer")
    ignored = [e for e in events if e["kind"] == "channel_ignored"]
    to_grandma = [r for r in rows if r["to"] == "grandma"]
    check("grandma's own message: no family user, ignored and nothing sent to her chat", ignored and not to_grandma,
          f"{len(ignored)} ignored, {len(to_grandma)} sent (no grandma in the people block)")
    heard = [e for e in events if e["kind"] == "voice_heard"]
    check("voice note heard", heard, f"{len(heard)} voice_heard")
    doors = [e for e in events if e["kind"] == "routine" and e.get("name") == "door"]
    check("no door routine", not doors, f"{len(doors)} door routine event(s)")
    for d in (0, 1):
        for who in ("gonza", "ceci"):
            msg = next((r for r in proactive if r["to"] == who and D(d, "07:25") <= parse(r["at"]) <= D(d, "08:10")
                        and re.search(r"good morning|buen d[íi]a", r["text"], re.I)), None)
            if msg:
                clean = not english(msg["text"]) and not INTERNAL.search(msg["text"]) and not PREP.search(msg["text"])
                check(f"morning message day {d} to {who}: Spanish, only what is theirs", clean,
                      "; ".join(p for p in msg.get("problems", [])) or "clean")
    return out


def log_accuracy(run, day0):
    """The entries the parents asked for, looked up in Baby Buddy. Seeded history is left out."""
    tz = parse(run["start"]).tzinfo
    rows = [r for r in run["baby_buddy"] if "e2e-seed" not in (r.get("tags") or [])]
    used, out = set(), []

    def find(kind_ok, t, minutes):
        """The nearest entry of the kind within minutes of t that no other step took."""
        best = None
        for r in rows:
            stamp = r.get("start") or r.get("time")
            if (r["endpoint"], r["id"]) in used or not stamp or not kind_ok(r):
                continue
            gap = abs((parse(stamp.replace("Z", "+00:00")) - t).total_seconds())
            if gap <= minutes * 60 and (best is None or gap < best[0]):
                best = (gap, r)
        if best is None:
            return None
        used.add((best[1]["endpoint"], best[1]["id"]))
        return best[1]

    open_sleep = None
    for step in sorted((s for s in run["steps"] if s.get("expect")), key=lambda s: s["at"]):
        kind, details = step["expect"][0], step["expect"][1]
        t = parse(step["at"])
        if details.get("at"):
            h, m = map(int, details["at"].split(":"))
            t = t.replace(hour=h, minute=m)
        if kind == "feeding":
            r = find(lambda r: r["endpoint"] == "feedings", t - datetime.timedelta(minutes=10), 25)
            ok = r is not None and (details.get("amount") is None or float(r.get("amount") or 0) == details["amount"]) \
                and (details.get("method") is None or r.get("method") == details["method"])
            got = f"{r.get('method')} {r.get('amount')} ml at {parse(r['start']).astimezone(tz):%H:%M}" if r else "nothing"
        elif kind == "change":
            r = find(lambda r: r["endpoint"] == "changes", t, 15)
            ok = r is not None and all(r.get(k) == v for k, v in details.items())
            got = f"wet {r.get('wet')} solid {r.get('solid')}" if r else "nothing"
        elif kind == "bath":
            r = find(lambda r: r["endpoint"] == "notes" and str(r.get("note", "")).lower().startswith("bath"), t, 20)
            ok, got = r is not None, (r or {}).get("note", "nothing")
        elif kind == "sleep_start":
            open_sleep = step
            continue
        elif kind == "sleep_end":
            start = parse(open_sleep["at"]) if open_sleep else None
            r = find(lambda r: r["endpoint"] == "sleep", start, 10) if start else None
            ok = r is not None and abs((parse(r["end"]) - t).total_seconds()) <= 600
            got = (f"sleep {parse(r['start']).astimezone(tz):%H:%M} to {parse(r['end']).astimezone(tz):%H:%M}"
                   if r else "nothing")
            open_sleep = None
        else:
            continue
        out.append({"at": step["at"], "who": step["who"], "said": step.get("text") or "(voice note)", "want": kind,
                    "got": got, "ok": ok})
    extra = [r for r in rows if (r["endpoint"], r["id"]) not in used and r["endpoint"] != "timers"]
    return out, extra


def summarize(run, events, day0):
    rows = judge_messages(outgoing(run, events), run, events)
    expected = expectations(run, events, rows, day0)
    logs, extra = log_accuracy(run, day0)
    proactive = [r for r in rows if r["proactive"]]
    numbers = {
        "messages_out": len(rows), "proactive": len(proactive), "replies": len(rows) - len(proactive),
        "noise": sum(1 for r in rows if r["problems"]),
        "noise_by_kind": dict(collections.Counter(p.split(" (")[0] for r in rows for p in r["problems"])),
        "expected_found": sum(1 for e in expected if e["found"]), "expected": len(expected),
        "log_ok": sum(1 for l in logs if l["ok"]), "log_expected": len(logs), "log_extra": len(extra),
        "brain_usd": run["brain_usd"], "brain_calls": run["brain_calls"], "real_seconds": run["real_seconds"],
        "house_writes_refused": len([r for r in run["refused"] if r["what"] == "house write"]),
        "telegram_refused": len([r for r in run["refused"] if r["what"] == "telegram"]),
    }
    return {"label": run["label"], "numbers": numbers, "messages": rows, "expected": expected, "log": logs,
            "log_extra": [{k: r.get(k) for k in ("endpoint", "id", "start", "time", "end", "amount", "note", "wet", "solid")}
                          for r in extra]}


KEY_EVENTS = {"routine": lambda e: e.get("name") in ("nap_mode", "door", "supplies", "floor_clean") and
              e.get("step") in ("on", "off", "low", "announce", "silent_push", "ask"),
              "night_feed": lambda e: e.get("step") in ("prepare", "prewarm", "push", "done"),
              "house_plan": lambda e: True, "house_brain_fallback": lambda e: True, "sitter_draft": lambda e: True,
              "sitter_summary": lambda e: True, "channel_ignored": lambda e: True, "voice_heard": lambda e: True,
              "proactive": lambda e: True}


def event_line(e):
    kind = e["kind"]
    if kind == "routine":
        return f"routine {e.get('name')} {e.get('step')}" + (f" ({e.get('item')})" if e.get("item") else "")
    if kind == "night_feed":
        return f"night feed {e.get('step')}: {e.get('reason') or e.get('to') or ''}"[:140]
    if kind == "house_plan":
        return f"house plan ({e.get('trigger')}) accepted {e.get('accepted')}"
    if kind == "house_brain_fallback":
        return f"house brain fallback ({e.get('trigger')}): {str(e.get('reason'))[:100]}"
    return kind


def timeline(run, events, summary):
    """Rows: time, who, what, verdict. Parents' messages, the agent's answers and pushes, and the house's own steps."""
    rows = []
    for s in run["steps"]:
        if s.get("do") == "sound":
            rows.append((s["at"], "house mic (simulated)", "a cry at night", "input"))
        else:
            rows.append((s["at"], s["who"].capitalize(), f"says: {s.get('text') or '(voice note es01)'}", "input"))
    for m in summary["messages"]:
        rows.append((m["at"], f"agent to {m['to'].capitalize()}", ("push: " if m["proactive"] else "reply: ") + m["text"],
                     "ok" if not m["problems"] else "NOISE: " + ", ".join(m["problems"])))
    for e in events:
        check = KEY_EVENTS.get(e["kind"])
        if check and check(e):
            rows.append((e["ts"], "house", event_line(e), "log"))
    rows.sort(key=lambda r: r[0])
    return rows


def cell(text):
    return str(text).replace("|", "/").replace("\n", " ")


def write(run_dir, day0):
    run, events = load(run_dir)
    summary = summarize(run, events, day0)
    rows = timeline(run, events, summary)
    out = Path(run_dir)
    (out / "score.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    n = summary["numbers"]
    lines = [f"# End-to-end day: {run['label']}", "",
             f"Virtual day {run['start'][:16]} to {run['end'][:16]}, real time {n['real_seconds']} s, brain {n['brain_usd']} USD.",
             "", "| Number | Value |", "|---|---|"]
    lines += [f"| {k} | {cell(v)} |" for k, v in n.items()]
    lines += ["", "## What a parent must get", "", "| Item | Found | Detail |", "|---|---|---|"]
    lines += [f"| {cell(e['item'])} | {'yes' if e['found'] else 'MISSED'} | {cell(e['detail'])} |" for e in summary["expected"]]
    lines += ["", "## The log", "", "| Time | Who | Said | Want | Got | Verdict |", "|---|---|---|---|---|---|"]
    lines += [f"| {l['at'][11:16]} | {l['who']} | {cell(l['said'])} | {l['want']} | {cell(l['got'])} | "
              f"{'ok' if l['ok'] else 'WRONG'} |" for l in summary["log"]]
    if summary["log_extra"]:
        lines += ["", f"Entries nobody asked for: {len(summary['log_extra'])}", ""]
        lines += [f"- {cell(json.dumps(x, ensure_ascii=False))}" for x in summary["log_extra"]]
    lines += ["", "## Timeline", "", "| Time | Who | What | Verdict |", "|---|---|---|---|"]
    lines += [f"| {t[5:16].replace('T', ' ')} | {cell(w)} | {cell(what)[:400]} | {cell(v)} |" for t, w, what, v in rows]
    (out / "timeline.md").write_text("\n".join(lines) + "\n")
    return summary
