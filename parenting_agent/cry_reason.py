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


def context(entries, now, tz):
    """What the log says at the moment of the cry. Only entries that already happened count."""
    past = ordered(entries, now)
    feeds = [e for e in past if e["kind"] == "feeding"]
    changes = [e for e in past if e["kind"] == "change"]
    sleeps = [e for e in past if e["kind"] == "sleep" and e.get("end")]
    done = [s for s in sleeps if parse(s["end"]) <= now]
    ctx = {"now": now, "tz": tz, "asleep": any(parse(s["start"]) <= now < parse(s["end"]) for s in sleeps), "refs": []}
    if feeds:
        last = feeds[-1]
        ctx.update(last_feed=when(last), since_feed_min=_minutes(when(last), now), feed_ended=not last.get("end")
                   or parse(last["end"]) <= now)
        ctx["refs"].append(last["ref"])
    nxt = patterns.next_feed(past, now)
    if nxt:
        ctx.update(feed_gap_min=nxt["gap_min"], next_feed_at=nxt["at"])
        ctx["refs"] += nxt["computed_from"]
    if changes:
        ctx.update(last_change=when(changes[-1]), since_change_min=_minutes(when(changes[-1]), now))
        ctx["refs"].append(changes[-1]["ref"])
    if done:
        last_sleep = done[-1]
        woke = parse(last_sleep["end"])
        ctx.update(woke_at=woke, awake_min=0.0 if ctx["asleep"] else _minutes(woke, now))
        ctx["refs"].append(last_sleep["ref"])
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
        unchanged = "last_feed" in ctx and ctx["last_change"] < ctx["last_feed"] and ctx.get("feed_ended", True)
        if unchanged:
            out["diaper"] = (0.85, f"no diaper change since the {patterns.hhmm(ctx['last_feed'].astimezone(ctx['tz']))} "
                                   f"feed, a change usually follows each feed")
        else:
            out["diaper"] = (0.5 * _clamp(ctx["since_change_min"] / 240),
                             f"last diaper change {_hm(ctx['since_change_min'])} ago")
    out["comfort"] = (COMFORT_SCORE, "fed, changed and rested recently by the log, he may want to be held")
    if features:
        length, voiced = features.get("length_s") or 0, features.get("voiced_share") or 0
        if length >= 60 and voiced >= 0.6 and "hungry" in out:
            out["hungry"] = (out["hungry"][0] + SOUND_WEIGHT, out["hungry"][1] + f", and a long steady cry ({length} s)")
        elif 0 < length < 20 and "tired" in out:
            out["tired"] = (out["tired"][0] + SOUND_WEIGHT, out["tired"][1] + f", and a short fussy cry ({length} s)")
    return out


def explain(entries, now, tz, features=None, pronoun="he"):
    """The ranked reasons and the sentence the agent says, for a cry heard at now."""
    ctx = context(entries, now, tz)
    ranked = sorted(((round(s, 3), reason, text) for reason, (s, text) in scores(ctx, features).items()),
                    key=lambda r: (-r[0], REASONS.index(r[1])))
    top_score, top, evidence = ranked[0]
    if top == "comfort":
        text = f"Crying, no clear reason in the log: {evidence}."
    else:
        text = f"Probably {'a diaper' if top == 'diaper' else top}: {evidence}."
    if len(ranked) > 1 and ranked[1][1] != "comfort" and ranked[1][0] >= 0.4:
        text += f" Next guess: {ranked[1][1]}, {ranked[1][2]}."
    if ctx.get("next_feed_at") and top != "hungry":
        text += f" Next feed expected around {patterns.hhmm(ctx['next_feed_at'].astimezone(tz))}."
    if pronoun != "he":
        text = re.sub(r"\bhe\b", pronoun, text)
    if not (no_medical(text) and patterns.no_advice(text)):
        raise ValueError("cry reason text failed the no-medical guard")
    return {"top": top, "text": text, "ranked": [{"reason": r, "score": s, "evidence": t} for s, r, t in ranked],
            "computed_from": ctx["refs"], "asleep": ctx["asleep"],
            "next_sleep_at": ctx["next_sleep_at"].isoformat() if ctx.get("next_sleep_at") else None}
