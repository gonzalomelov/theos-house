"""Tonight's house on the public demo (issue #132): Muse Spark Open plans the visitor's simulated house from the
visitor's own simulated log, through house_brain.py, and the card says the plan in plain words.

The plan goes through HouseBrain.ask exactly as on the family server: the same prompt, plan_schema, validate() with the
clock and safety checks, the same text guards and the same fallback. Nothing is armed. The demo's HouseBrain has no day
engine, no night feed and no white noise device, so apply() moves nothing, and the demo image has no device client at
all. When Muse errors, is slow, or its plan is refused, the card shows what the fixed rules do instead and says so.

"Let me sleep tonight" re-plans through the same trigger the family server uses (Muse is asked with trigger "adapt" and
HouseBrain.asked_to_sleep set), then lists what changed. Nothing is written into the visitor's log: the button is no
parent's words (round b4 found a ready-made "I'm exhausted" note in the log after a tap).

One plan per visitor for each of the two buttons: a second tap returns the same plan with no new Muse call.
"""
import datetime

from .. import house_brain as hb
from ..agent.brain import BrainError
from ..bus import Bus
from ..rhythm import patterns
from ..sleep_forecast import as_of, sessions, sleep_windows
from .babylog import TZ, finished, started

# The night feed's rhythm lead and the white noise cap at the crib. night_feed.py and white_noise.py are not in the
# demo image, a test keeps these the same as theirs.
FIXED_LEAD_MIN = 10
CRIB_CAP_DB = 50.0
NIGHT_FROM = 19  # a visit before this hour (from 05:00) sees tonight's plan from 19:00, planned ahead
# What Muse reads as what_happened when a parent asks to sleep: never written into the log.
ASKED_TO_SLEEP = "{who} asked to sleep tonight, at {at}"
# The simulated parents in Spanish: Papá and Mamá, never "Persona A/B" (blind round b6).
NAMES_ES = {"Parent A": "Papá", "Parent B": "Mamá"}

TEXT = {
    "en": {
        "duty": "On duty tonight", "warm": "Bottle warmer pre-heats", "noise": "White noise", "door": "Quiet doorbell",
        "floor": "Floor clean", "why": "Muse's why", "changed": "What changed",
        "rota": "{p}, from the night rota (fair split of wake-ups)",
        "moved": "{p}, Muse handed over the night because a parent asked to sleep",
        "kept": "{p}, Muse kept the night rota",
        "warm_at": "{t}, silent, water only. The light and any push wait for a real cry",
        "warm_none": "Not armed. A cry on the microphone still gets the bottle warmer ready",
        "warm_fixed": "{t}, {lead} min before the guessed night feed around {feed}, silent, water only",
        "warm_fixed_none": "Nothing guessed at night in the next 12 h. A cry on the microphone still gets it ready",
        "noise_base": "On for every sleep, capped at {cap:g} dB at the crib",
        "noise_boost": "up to the cap {a} to {b}",
        "door_base": "A silent phone push during every sleep (nap mode)",
        "door_win": "also {a} to {b}",
        "floor_win": "May run {a} to {b}, never in a predicted sleep, a parent says yes first",
        "floor_none": "No window, nothing runs",
        "floor_fixed": "Fixed rule: only before tummy time, out of any predicted sleep, after a parent's yes",
        "routine_fixed": "Muse's times did not pass the checks, the fixed rule runs",
        "routine_fixed_as": "Muse's times did not pass the checks, the fixed rule runs: {rule}",
        "floor_rule": "only before tummy time, out of any predicted sleep, after a parent's yes",
        "badge": "Simulated house, nothing moves",
        "src_muse": "Muse Spark Open's plan, checked by plain code",
        "src_fixed": "Fixed rules, Muse was not used: {reason}",
        "fixed_reason": {"error": "Muse did not answer in time", "refused": "Muse's plan did not pass the checks",
                          "resting": "the demo reached its daily AI limit", "off": "no AI in this run"},
        "no_change": "Nothing changed in the plan", "fixed_word": "fixed rule",
        "fixed_sleep": "The fixed rules do not re-plan when a parent asks to sleep, so {p} stays on duty",
        "plan_until": "Plan from {now} to {until}",
        "plan_ahead": "Tonight from {now} to {until}, planned at {at} from the simulated day ahead",
    },
    "es": {
        "duty": "De turno esta noche", "warm": "El calienta mamaderas precalienta", "noise": "Ruido blanco",
        "door": "Timbre en silencio", "floor": "Limpieza del piso", "why": "Por qué, según Muse",
        "changed": "Qué cambió",
        "rota": "{p}, por el turno de la noche (reparto justo de despertares)",
        "moved": "{p}, Muse cambió la noche porque alguien pidió dormir",
        "kept": "{p}, Muse mantuvo el turno de la noche",
        "warm_at": "{t}, en silencio, solo agua. La luz y el aviso esperan un llanto real",
        "warm_none": "Sin precalentar. Un llanto en el micrófono igual prepara el calienta mamaderas",
        "warm_fixed": "{t}, {lead} min antes de la toma de noche estimada cerca de las {feed}, en silencio, solo agua",
        "warm_fixed_none": "No hay toma de noche estimada en las próximas 12 h. Un llanto en el micrófono igual lo prepara",
        "noise_base": "Prendido en cada sueño, con tope de {cap:g} dB en la cuna",
        "noise_boost": "al tope de {a} a {b}",
        "door_base": "Un aviso silencioso al celular en cada sueño (modo siesta)",
        "door_win": "y también de {a} a {b}",
        "floor_win": "Puede limpiar de {a} a {b}, nunca en un sueño previsto, y antes alguien dice que sí",
        "floor_none": "Sin ventana, no limpia",
        "floor_fixed": "Regla fija: solo antes del rato boca abajo, fuera de cualquier sueño previsto, con el sí de alguien",
        "routine_fixed": "Los horarios de Muse no pasaron los controles, corre la regla fija",
        "routine_fixed_as": "Los horarios de Muse no pasaron los controles, corre la regla fija: {rule}",
        "floor_rule": "solo antes del rato boca abajo, fuera de cualquier sueño previsto, con el sí de alguien",
        "badge": "Casa simulada, nada se mueve",
        "src_muse": "El plan de Muse Spark Open, revisado por código simple",
        "src_fixed": "Reglas fijas, no se usó Muse: {reason}",
        "fixed_reason": {"error": "Muse no respondió a tiempo", "refused": "el plan de Muse no pasó los controles",
                          "resting": "la demo llegó a su límite diario de IA", "off": "sin IA en esta prueba"},
        "no_change": "No cambió nada en el plan", "fixed_word": "regla fija",
        "fixed_sleep": "Las reglas fijas no cambian el plan cuando alguien pide dormir, así que {p} sigue de turno",
        "plan_until": "Plan de {now} a {until}",
        "plan_ahead": "Esta noche de {now} a {until}, planeado a las {at} con el resto del día simulado",
    },
}


class NoMuse:
    """The house brain's Muse when the demo runs with no AI (the fake brain in tests): every plan falls back."""

    def ask(self, system, text, schema, name="plan"):
        raise BrainError("no Muse in this demo run")


def hm(t):
    return patterns.hhmm(t.astimezone(TZ))


def tonight_start(now):
    """When tonight's plan starts: now in the evening and at night, else 19:00 today."""
    local = now.astimezone(TZ)
    if local.hour >= NIGHT_FROM or local.hour < 5:
        return now
    return local.replace(hour=NIGHT_FROM, minute=0, second=0, microsecond=0)


class TonightHouse:
    """One visitor's simulated house plan. plan(action) returns (card, muse_calls): action "tonight" or "sleep"."""

    def __init__(self, muse, baby_log, rota, parents, allow_muse=lambda: True, on_spend=lambda usd: None):
        self.bus = Bus(None)
        offset = TZ.utcoffset(None).total_seconds() / 3600
        self.brain = hb.HouseBrain(self.bus, muse or NoMuse(), {"utc_offset_h": offset, "parents": list(parents)})
        self.baby_log, self.rota, self.parents = baby_log, rota, list(parents)
        self.allow_muse, self.on_spend = allow_muse, on_spend
        self.on_call = lambda: None  # counts one Muse plan call against the visitor's limits, set per request
        self.plans = {}
        self.at, self.ahead = None, []

    def cached(self):
        self.drop_stale()
        return dict(self.plans)

    def feeds_key(self):
        """The feeds the plan was made from. A feed logged since (round b5: two test logs moved the next feed from 154
        to 54 min while the warmer kept its times) makes the plan stale."""
        rows = sessions(self.baby_log.rhythm_rows())
        return tuple(sorted(patterns.when(r).isoformat() for r in rows if r["kind"] == "feeding"))[-8:]

    def drop_stale(self):
        """Plans made from other feeds than the log holds now are dropped, and the next ask plans again, so the warmer's
        times and the next feed on the panel come from the same log."""
        key = self.feeds_key()
        if any(card.get("feeds_key") != key for card in self.plans.values()):
            self.bus.publish("guard", status="house_plan_stale", plans=sorted(self.plans))
            self.plans = {}

    def plan(self, action, lang="en", said=None):
        """said is what the parent typed to ask for sleep in the chat, given to Muse as what happened, never logged."""
        self.drop_stale()
        if action == "tonight" and "sleep" in self.plans:
            return self.plans["sleep"], 0  # after "let me sleep" the night is the re-planned one
        if action in self.plans:
            return self.plans[action], 0
        calls = 0
        if action == "sleep" and "tonight" not in self.plans:
            calls += self.plan("tonight", lang)[1]
        real_now = self.baby_log.now()
        if action == "tonight":
            self.at = tonight_start(real_now)
            # A day visit plans the coming night, never the day under a "tonight" title (round 5 saw 07:23 to 19:23 with
            # the warmer not armed): the rest of the simulated day up to the evening is read as the simulated baby will
            # live it, then Muse plans from there.
            self.ahead = [dict(r, ref=f"{r['kind']}#ahead{i}", id=0) for i, r in enumerate(self.baby_log.upcoming)
                          if started(r) < self.at] if self.at > real_now else []
            trigger, what = "bedtime", None
        else:
            who = self.plans["tonight"]["on_duty"]
            trigger = "adapt"
            what = ASKED_TO_SLEEP.format(who=who, at=hm(real_now)) + (f': "{hb.clean_text(said, 160)}"' if said else "")
            # The request is about tonight, so it counts from the start of the planned night.
            self.brain.asked_to_sleep = max(self.brain.asked_to_sleep or real_now, self.at)
        now = max(self.at, real_now)
        rows = self.baby_log.rhythm_rows()
        have = {(r["kind"], r.get("start") or r.get("time")) for r in rows}
        rows += [r for r in self.ahead if finished(r) > real_now and started(r) < now
                 and (r["kind"], r.get("start") or r.get("time")) not in have]
        seen = as_of(rows, now)
        reason = None
        if not self.allow_muse():
            reason = "resting"
            self.brain.plan = None
        else:
            reason = self.ask(seen, now, trigger, what)
            calls += 1
            if reason is None and not told(self.brain.plan, trigger, lang) and self.allow_muse():
                # Muse's why came back empty, or nothing of it was about the plan once the checks cut it (round b4): asked
                # once more. A second empty why hides the field, and a second call that fails keeps the first plan.
                first = self.brain.plan
                self.bus.publish("guard", status="house_why_retry", trigger=trigger)
                if self.ask(seen, now, trigger, what) is not None:
                    self.brain.plan = first
                calls += 1
        card = self.card(seen, now, trigger, what, reason)
        card["feeds_key"] = self.feeds_key()
        card["lang"] = "es" if lang == "es" else "en"
        card["planned_at"] = hm(real_now) if now > real_now else ""
        if action == "sleep":
            card["before"] = self.plans["tonight"]
        self.plans[action] = card
        return card, calls

    def ask(self, seen, now, trigger, what):
        """One Muse plan call, counted and charged. None when Muse's plan stands, else why the fixed rules run."""
        self.on_call()
        spent = self.brain.stats["usd"]
        event = self.brain.ask(seen, now, None, trigger, what)
        self.on_spend(round(self.brain.stats["usd"] - spent, 6))
        if event["kind"] != "house_brain_fallback":
            return None
        refused = str(event.get("reason", "")).startswith("plan refused")
        return "off" if isinstance(self.brain.muse, NoMuse) else ("refused" if refused else "error")

    def card(self, seen, now, trigger, what, reason):
        """The plan as data: local HH:MM times, who is on duty and why, each routine's windows or "fixed"."""
        plan = self.brain.plan if reason is None else None
        rota = self.rota()
        request = self.brain.asked_to_sleep is not None and now - self.brain.asked_to_sleep < datetime.timedelta(hours=12)
        out = {"source": "muse" if plan else "fixed", "fixed_reason": reason, "trigger": trigger, "what": what or "",
               "now": hm(now), "until": hm(now + datetime.timedelta(hours=self.brain.s["horizon_h"])),
               "asked_to_sleep": request}
        windows = lambda items: "fixed" if items is None else [{"start": hm(w["start"]), "end": hm(w["end"]) if w["end"] else ""}
                                                             for w in items]
        if plan:
            # on_duty_on_request: Muse's parent counts only after a parent asked to sleep, else the rota stays (house_brain).
            out["on_duty"], out["on_duty_by"] = (plan["on_duty"], "muse") if request else (rota, "rota")
            out["muse_on_duty"] = plan["on_duty"]
            for name in hb.ROUTINES:
                out[name] = windows(plan[name])
            for field in hb.WHY_FIELDS:
                out[field] = plan.get(field) or ""
            meta = next((e.get("muse") for e in reversed(self.bus.history) if e["kind"] == "house_plan"), None) or {}
            out["muse"] = {"seconds": meta.get("seconds"), "model": meta.get("model")}
        else:
            out["on_duty"], out["on_duty_by"] = rota, "rota"
            for name in hb.ROUTINES:
                out[name] = "fixed"
            for field in hb.WHY_FIELDS:
                out[field] = ""
        if out["bottle_prewarm"] == "fixed":
            fixed = hb.fixed_prewarm(seen, now, TZ, self.brain.s["horizon_h"], FIXED_LEAD_MIN)
            if fixed:
                out["fixed_prewarm"] = {"at": hm(fixed["at"]), "feed": hm(fixed["feed"])}
        out["sleeps"] = [{"start": hm(w["start"]), "end": hm(w["end"]), "kind": w["kind"]}
                         for w in sleep_windows(seen, now, TZ, horizon_h=self.brain.s["horizon_h"])]
        return out


def told(plan, trigger, lang):
    """True when a Muse plan has a why the card can show in the visitor's language."""
    if not plan:
        return False
    return bool((trigger == "adapt" and why_line(why_in(plan, "why_changed", lang), lang))
                or why_line(why_in(plan, "summary", lang), lang))


def why_in(card, field, lang):
    """Muse's why in the visitor's language: the Spanish one on the Spanish page, so a plan made while the page was in
    English still has its why after a switch (round b5), and the English one as it was when there is no Spanish."""
    if lang == "es" and card.get(field + "_es"):
        return card[field + "_es"]
    return card.get(field) or ""


def name(parent, lang):
    return NAMES_ES.get(parent, parent) if lang == "es" else parent


def spans(items, t, key, sep=", "):
    return sep.join(t[key].format(a=w["start"], b=w["end"]) for w in items)


def rows(card, lang="en"):
    """[(label, text)] in the visitor's language, the order the card shows them."""
    t = TEXT["es" if lang == "es" else "en"]
    p = name(card["on_duty"], lang)
    if card["on_duty_by"] == "muse":
        duty = t["moved"].format(p=p) if card.get("before") and card["before"]["on_duty"] != card["on_duty"] else t["kept"].format(p=p)
    else:
        duty = t["rota"].format(p=p)
    out = [(t["duty"], duty)]
    warm = card["bottle_prewarm"]
    if warm == "fixed":
        fixed = card.get("fixed_prewarm")
        text = t["warm_fixed"].format(t=fixed["at"], lead=FIXED_LEAD_MIN, feed=fixed["feed"]) if fixed else t["warm_fixed_none"]
        out.append((t["warm"], text if card["source"] == "fixed" else t["routine_fixed_as"].format(rule=text[:1].lower() + text[1:])))
    else:
        out.append((t["warm"], t["warm_at"].format(t=", ".join(w["start"] for w in warm)) if warm else t["warm_none"]))
    noise = t["noise_base"].format(cap=CRIB_CAP_DB)
    boost = card["white_noise_boost"]
    if boost == "fixed" and card["source"] == "muse":
        noise += ". " + t["routine_fixed"]
    elif boost and boost != "fixed":
        noise += ", " + spans(boost, t, "noise_boost")
    out.append((t["noise"], noise))
    door = t["door_base"]
    quiet = card["door_quiet"]
    if quiet == "fixed" and card["source"] == "muse":
        door += ". " + t["routine_fixed"]
    elif quiet and quiet != "fixed":
        door += ", " + spans(quiet, t, "door_win")
    out.append((t["door"], door))
    floor = card["floor_clean"]
    if floor == "fixed":
        out.append((t["floor"], t["floor_fixed"] if card["source"] == "fixed"
                    else t["routine_fixed_as"].format(rule=t["floor_rule"])))
    else:
        out.append((t["floor"], spans(floor, t, "floor_win", "; ") if floor else t["floor_none"]))
    return out


def changes(card, lang="en"):
    """What the re-plan changed, routine by routine, against the plan before it."""
    before = card.get("before")
    if not before:
        return []
    t = TEXT["es" if lang == "es" else "en"]
    if card["source"] == "fixed":
        return [t["fixed_sleep"].format(p=name(card["on_duty"], lang))]
    labels = dict(zip(("duty", "bottle_prewarm", "white_noise_boost", "door_quiet", "floor_clean"),
                      (t["duty"], t["warm"], t["noise"], t["door"], t["floor"])))
    fmt = lambda items: t["fixed_word"] if items == "fixed" else (", ".join(
        f"{w['start']}-{w['end']}" if w["end"] else w["start"] for w in items) or "-")
    out = []
    if before["on_duty"] != card["on_duty"]:
        out.append(f"{labels['duty']}: {name(before['on_duty'], lang)} → {name(card['on_duty'], lang)}")
    for key in hb.ROUTINES:
        if before[key] != card[key]:
            out.append(f"{labels[key]}: {fmt(before[key])} → {fmt(card[key])}")
    return out or [t["no_change"]]


def why_line(text, lang):
    """Muse's own words about the plan, through the final guard (final_guard.py) in the visitor's language: on the
    Spanish page an English sentence goes and Parent B reads Mamá, so the card never mixes the two (blind round 1).
    An empty line when nothing is left: the card then shows no "why" line at all."""
    if not text:
        return ""
    from ..agent import final_guard
    names = NAMES_ES if lang == "es" else {label: label for label in NAMES_ES}
    result = final_guard.guard(text, "es" if lang == "es" else "en", names, models_ok=True)
    if result.fallback:
        return ""
    if lang != "es":
        return result.text
    # A short English sentence ("Mamá takes the night.") is below the guard's two English words: the Spanish card
    # drops every sentence with an English word that does not read Spanish.
    from ..agent import rules
    return " ".join(p for p in final_guard.SENTENCE.split(result.text)
                    if rules.looks_spanish(p) or not rules.ENGLISH.search(p)).strip()


def view(card, lang="en"):
    """The card as the page shows it: every text already in the visitor's language, plus the plain data."""
    t = TEXT["es" if lang == "es" else "en"]
    source = t["src_muse"] if card["source"] == "muse" else t["src_fixed"].format(
        reason=t["fixed_reason"].get(card["fixed_reason"], t["fixed_reason"]["error"]))
    return {"source": card["source"], "label": source, "badge": t["badge"],
            "span": (t["plan_ahead"].format(now=card["now"], until=card["until"], at=card["planned_at"])
                     if card.get("planned_at") else t["plan_until"].format(now=card["now"], until=card["until"])),
            "rows": [{"label": a, "text": b} for a, b in rows(card, lang)],
            "why": why_line(why_in(card, "summary", lang), lang), "why_label": t["why"],
            "why_changed": why_line(why_in(card, "why_changed", lang), lang),
            "changes": changes(card, lang), "changes_label": t["changed"], "on_duty": name(card["on_duty"], lang),
            "seconds": (card.get("muse") or {}).get("seconds")}


# Chat words the agent's log honesty guards read as a claimed change or action (rules.CLAIMS_CHANGE, CLAIMS_DONE). The
# chat text says the same thing in other words, the card keeps the plain ones.
CHAT_WORDS = (("Fixed rules", "The standing rules"), ("the fixed rule", "the standing rule"), ("Fixed rule", "Standing rule"),
              ("fixed rule", "standing rule"), ("What changed", "Difference"))


def text(card, lang="en"):
    """The card as one plain text, for the chat."""
    v = view(card, lang)
    lines = [f"{v['badge']}. {v['label']}. {v['span']}."] + [f"{r['label']}: {r['text']}." for r in v["rows"]]
    if v["why"]:
        lines.append(f"{v['why_label']}: {v['why']}")
    if v["changes"]:
        lines.append(f"{v['changes_label']}: " + "; ".join(v["changes"]) + ".")
    if v["why_changed"]:
        lines.append(v["why_changed"])
    out = "\n".join(lines)
    for plain, chat in CHAT_WORDS if lang != "es" else ():
        out = out.replace(plain, chat)
    return out
