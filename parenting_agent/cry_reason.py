"""Why is he crying: a ranked likely reason from the baby log, with the evidence (issue #32).

The reason comes from what the log already says, not from the sound: time since the last feed against his usual
gap (the daily rhythm's next-feed estimate), whether a diaper change followed the last feed, and how long he has
been awake against his usual awake time before a sleep. Cry length and voicing are a weak extra signal only, they
move a score by at most 0.05.

It never names pain, illness or any medical cause, and no audio is sent anywhere: ChatterBaby and other cloud
cry services were ruled out in issue #32. Every text passes no_medical() and the rhythm's no_advice().
"""
import datetime
import re
import statistics

from .rhythm import patterns
from .rhythm.log import ordered, parse, when

REASONS = ("hungry", "tired", "diaper", "comfort")
MEDICAL_RE = re.compile(r"\b(pain\w*|hurt\w*|ill|illness|sick\w*|colic\w*|reflux|fever\w*|gas|gassy|teeth|teething|"
                        r"infection|ear|medical|medicine|doctor|pediatrician|allerg\w*|disease|symptom\w*|injur\w*)\b",
                        re.IGNORECASE)
SOUND_WEIGHT = 0.05
COMFORT_SCORE = 0.3
# A change usually follows a feed, so a missing one points to the diaper only once the feed started this many minutes ago
# and the last change is at least DIAPER_MIN_SINCE_CHANGE old. Right after a bottle the log says nothing about it.
DIAPER_AFTER_FEED_MIN = 10
DIAPER_MIN_SINCE_CHANGE = 45
# Awake longer than this under 3 months is not said as a fact: the log is more likely missing a sleep (round b4).
MAX_AWAKE_YOUNG_MIN = 180
# Below this score no reason is likely: the agent says so and lists what to check instead of guessing.
LIKELY = 0.4
CHECKS = "a wet or dirty diaper, too warm or too cold, a burp after the feed, or he may just want to be held"


def no_medical(text):
    return MEDICAL_RE.search(text) is None


def _clamp(x):
    return max(0.0, min(1.0, x))


def _hm(minutes):
    h, m = divmod(round(minutes), 60)
    if not h:
        return f"{m} min"
    return f"{h} h" if not m else f"{h} h {m} min"


def _minutes(a, b):
    return (b - a).total_seconds() / 60


def diaper_after_feed(ctx):
    """True when the log shows a feed with no change after it, and both are old enough to mean something."""
    return ("last_feed" in ctx and "last_change" in ctx and ctx["last_change"] < ctx["last_feed"]
            and ctx.get("feed_ended", True) and ctx["since_feed_min"] >= DIAPER_AFTER_FEED_MIN
            and ctx["since_change_min"] >= DIAPER_MIN_SINCE_CHANGE)


def facts(ctx):
    """What the log says right now, as plain facts: last feed, last change, awake time."""
    out = []
    if "since_feed_min" in ctx:
        out.append(f"last feed {_hm(ctx['since_feed_min'])} ago")
    if "since_change_min" in ctx:
        out.append(f"last diaper change {_hm(ctx['since_change_min'])} ago")
    if "awake_min" in ctx and not ctx["asleep"]:
        out.append(f"awake {_hm(ctx['awake_min'])}")
    return ", ".join(out)


def is_likely(ranked):
    """ranked is [(score, reason, ...)], best first. A reason is likely only above LIKELY and when it is not comfort."""
    return bool(ranked) and ranked[0][1] != "comfort" and ranked[0][0] >= LIKELY


def context(entries, now, tz, young=True):
    """What the log says at the moment of the cry. Only entries that already happened count. young is a baby under 3
    months (or of unknown age): awake longer than MAX_AWAKE_YOUNG_MIN is not stated, the log is more likely missing a
    sleep than he is up that long."""
    past = ordered(entries, now)
    feeds = [e for e in past if e["kind"] == "feeding"]
    changes = [e for e in past if e["kind"] == "change"]
    sleeps = [e for e in past if e["kind"] == "sleep" and e.get("end")]
    done = [s for s in sleeps if parse(s["end"]) <= now]
    # A sleep a parent started and never ended ("se durmió" with no "se despertó"): he slept after the last sleep that
    # ended, so the time since that one is no awake time. Round b4 read "awake 4 h 1 min" for a 6 week old this way.
    opened = [e for e in past if e["kind"] == "sleep" and not e.get("end") and e.get("start")
              and parse(e["start"]) <= now and (not done or parse(e["start"]) >= parse(done[-1]["end"]))]
    ctx = {"now": now, "tz": tz, "asleep": any(parse(s["start"]) <= now < parse(s["end"]) for s in sleeps), "refs": []}
    if feeds:
        last = feeds[-1]
        ctx.update(last_feed=when(last), since_feed_min=_minutes(when(last), now), feed_ended=not last.get("end")
                   or parse(last["end"]) <= now)
        ctx["refs"].append(last["ref"])
    nxt = patterns.next_feed(past, now)
    if nxt:
        ctx.update(feed_gap_min=nxt["gap_min"], next_feed_at=nxt["at"], next_feed=nxt)
        ctx["refs"] += nxt["computed_from"]
    if changes:
        ctx.update(last_change=when(changes[-1]), since_change_min=_minutes(when(changes[-1]), now))
        ctx["refs"].append(changes[-1]["ref"])
    if done:
        last_sleep = done[-1]
        woke = parse(last_sleep["end"])
        ctx.update(woke_at=woke, awake_min=0.0 if ctx["asleep"] else _minutes(woke, now))
        ctx["refs"].append(last_sleep["ref"])
        if opened or (young and not ctx["asleep"] and ctx["awake_min"] > MAX_AWAKE_YOUNG_MIN):
            ctx["awake_unknown"] = ctx.pop("awake_min")
        night = patterns.is_night(woke.astimezone(tz))
        windows = [_minutes(parse(a["end"]), parse(b["start"])) for a, b in zip(done, done[1:])
                   if patterns.is_night(parse(a["end"]).astimezone(tz)) == night
                   and now - parse(a["end"]) <= datetime.timedelta(days=2)]
        if len(windows) >= 3:
            ctx["usual_awake_min"] = statistics.median(windows)
            ctx["next_sleep_at"] = woke + datetime.timedelta(minutes=ctx["usual_awake_min"])
    return ctx


def scores(ctx, features=None):
    """A score from 0 to 1 per reason, with the evidence sentence behind each."""
    out = {}
    if "since_feed_min" in ctx and "feed_gap_min" in ctx:
        ratio = ctx["since_feed_min"] / max(ctx["feed_gap_min"], 1)
        out["hungry"] = (_clamp((ratio - 0.55) / 0.4),
                         f"last feed {_hm(ctx['since_feed_min'])} ago, he eats about every {_hm(ctx['feed_gap_min'])}")
    if "awake_min" in ctx and "usual_awake_min" in ctx and not ctx["asleep"]:
        ratio = ctx["awake_min"] / max(ctx["usual_awake_min"], 1)
        out["tired"] = (_clamp((ratio - 0.55) / 0.4),
                        f"awake {_hm(ctx['awake_min'])}, he usually sleeps again after about {_hm(ctx['usual_awake_min'])}")
    if "since_change_min" in ctx:
        if diaper_after_feed(ctx):
            out["diaper"] = (0.85, f"no diaper change since the {patterns.hhmm(ctx['last_feed'].astimezone(ctx['tz']))} "
                                   f"feed, a change usually follows each feed")
        else:
            out["diaper"] = (0.5 * _clamp(ctx["since_change_min"] / 240),
                             f"last diaper change {_hm(ctx['since_change_min'])} ago")
    out["comfort"] = (COMFORT_SCORE, facts(ctx) or "nothing logged yet")
    if features:
        length, voiced = features.get("length_s") or 0, features.get("voiced_share") or 0
        if length >= 60 and voiced >= 0.6 and "hungry" in out:
            out["hungry"] = (out["hungry"][0] + SOUND_WEIGHT, out["hungry"][1] + f", and a long steady cry ({length} s)")
        elif 0 < length < 20 and "tired" in out:
            out["tired"] = (out["tired"][0] + SOUND_WEIGHT, out["tired"][1] + f", and a short fussy cry ({length} s)")
    return out


# The same sentence in Spanish (es-UY), from the same scores, for a parent who reads Spanish (the people block "lang").
ES = {"probably": "Por el registro, capaz que es {reason}: {evidence}.",
      "no_reason": "En el registro no hay una razón probable{known}. Para revisar: {checks}.",
      "next": "Si no, {reason}: {evidence}.",
      "hungry": "la última toma fue hace {ago} y suele comer cada {gap}",
      "tired": "está despierto hace {ago} y suele volver a dormirse después de unos {usual}",
      "diaper": "el último cambio de pañal fue hace {ago}",
      "diaper_since_feed": "no hay cambio de pañal anotado desde la toma de las {at}",
      "feed_fact": "la última toma fue hace {ago}", "change_fact": "el último cambio de pañal fue hace {ago}",
      "awake_fact": "está despierto hace {ago}",
      "checks": "el pañal mojado o sucio, si tiene calor o frío, un provechito después de la toma, o capaz que solo quiere brazos",
      "words": {"hungry": "hambre", "tired": "sueño", "diaper": "el pañal"},
      "next_feed": "Próxima toma cerca de las {at}.", "late_feed": "Se esperaba una toma cerca de las {at}, hace {late} min."}


def spanish(ctx, ranked, likely, now, tz):
    """The cry sentence in Spanish, from the same context and ranking as explain()."""
    evidence = {}
    if "since_feed_min" in ctx and "feed_gap_min" in ctx:
        evidence["hungry"] = ES["hungry"].format(ago=_hm(ctx["since_feed_min"]), gap=_hm(ctx["feed_gap_min"]))
    if "awake_min" in ctx and "usual_awake_min" in ctx and not ctx["asleep"]:
        evidence["tired"] = ES["tired"].format(ago=_hm(ctx["awake_min"]), usual=_hm(ctx["usual_awake_min"]))
    if "since_change_min" in ctx:
        evidence["diaper"] = (ES["diaper_since_feed"].format(at=patterns.hhmm(ctx["last_feed"].astimezone(tz)))
                              if diaper_after_feed(ctx) else ES["diaper"].format(ago=_hm(ctx["since_change_min"])))
    top = ranked[0][1]
    if not likely or top not in evidence:
        known = [ES[f"{k}_fact"].format(ago=_hm(ctx[m])) for k, m in (("feed", "since_feed_min"),
                 ("change", "since_change_min"), ("awake", "awake_min")) if m in ctx and not (k == "awake" and ctx["asleep"])]
        text = ES["no_reason"].format(known=(": " + ", ".join(known)) if known else "", checks=ES["checks"])
    else:
        text = ES["probably"].format(reason=ES["words"][top], evidence=evidence[top])
        if len(ranked) > 1 and ranked[1][1] in evidence and ranked[1][0] >= LIKELY:
            text += " " + ES["next"].format(reason=ES["words"][ranked[1][1]], evidence=evidence[ranked[1][1]])
    if ctx.get("next_feed_at") and top != "hungry":
        at = patterns.hhmm(ctx["next_feed"]["at"].astimezone(tz))
        late = round((now - ctx["next_feed"]["at"]).total_seconds() / 60)
        text += " " + (ES["next_feed"].format(at=at) if late <= 0 else ES["late_feed"].format(at=at, late=late))
    return text


def explain(entries, now, tz, features=None, pronoun="he", young=True):
    """The ranked reasons and the sentence the agent says, for a cry heard at now."""
    ctx = context(entries, now, tz, young)
    ranked = sorted(((round(s, 3), reason, text) for reason, (s, text) in scores(ctx, features).items()),
                    key=lambda r: (-r[0], REASONS.index(r[1])))
    top_score, top, evidence = ranked[0]
    likely = is_likely(ranked)
    if not likely:
        known = facts(ctx)
        text = (f"Nothing in the log points to a likely reason{': ' + known if known else ''}. "
                f"Things to check: {CHECKS}.")
    else:
        text = f"Probably {'a diaper' if top == 'diaper' else top}: {evidence}."
    if likely and len(ranked) > 1 and ranked[1][1] != "comfort" and ranked[1][0] >= LIKELY:
        text += f" Next guess: {ranked[1][1]}, {ranked[1][2]}."
    if ctx.get("next_feed_at") and top != "hungry":
        text += " " + patterns.next_feed_sentence(ctx["next_feed"], now, tz)
    if pronoun != "he":
        text = re.sub(r"\bhe\b", pronoun, text)
    if not (no_medical(text) and patterns.no_advice(text)):
        raise ValueError("cry reason text failed the no-medical guard")
    return {"top": top, "likely": likely, "text": text, "text_es": spanish(ctx, ranked, likely, now, tz), "ranked": [{"reason": r, "score": s, "evidence": t} for s, r, t in ranked],
            "computed_from": ctx["refs"], "asleep": ctx["asleep"],
            "next_sleep_at": ctx["next_sleep_at"].isoformat() if ctx.get("next_sleep_at") else None}
