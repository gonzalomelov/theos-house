"""The public demo: the real agent core, one isolated demo baby per visitor, spend and abuse caps.

Each visitor gets their own Agent with its own bus, an in-memory memory file and a DemoBabyLog copied from the
simulated week, so visitors never see each other. The simulated baby is Theo, a boy a few weeks old, the same baby as
the story. A second agent per visitor runs prep mode, the before-he-arrives tools on simulated lists with a due date
counted from today. The brain is the real one (Muse Spark Open on
Baseten, Claude only as a logged fallback). House tools only simulate: they record what the agent would do and touch nothing. There is no
Baby Buddy client, no Home Assistant client and no channel plug-in in here.
"""
import collections
import datetime
import re
import hashlib
import hmac
import ipaddress
import json
import secrets
import threading
import time

from .. import cry_reason
from ..agent import brain as brain_mod
from ..agent import rules
from ..agent.loop import SYSTEM, Agent
from ..agent.memory import LocalBabyLog, Memory
from ..agent.tools import Tool, core_tools, schema
from ..bus import Bus
from ..prep import DEFAULTS as PREP_DEFAULTS
from ..prep import Prep
from ..prep import lists as prep_lists
from ..rhythm import patterns
from .babylog import TZ, DemoBabyLog
from .records import Records

ALLOWED = ["log_baby_event", "edit_baby_event", "delete_baby_event", "read_baby_log", "baby_summary", "next_feed", "night_rota",
           "current_time", "dim_lights", "hold_notifications", "pause_vacuum", "announce"]
PREP_ALLOWED = ["current_time", "prep_next", "prep_list", "prep_check", "prep_add", "add_appointment", "appointments",
                "cancel_appointment", "set_due_date", "nursery_plan"]
# Days from today to the simulated due date in prep mode, so the countdown and the list dates always look current.
PREP_DUE_IN_DAYS = 47
# A message about getting ready goes to prep mode even when it is typed on the after-birth tab.
PREP_WORDS = re.compile(r"\b(hospital bag|before (he|she|the baby) (arrives|is born|comes)|due date|nursery|crib|"
                        r"car seat|white noise|prep (list|mode)|pack(ing)? the bag|days left|bolso|sanatorio|maternidad|"
                        r"cuna|cuarto del beb[eé]|silla del auto|ruido blanco|fecha (probable )?de parto|"
                        r"antes de que nazca|cu[aá]ntos d[ií]as faltan)\b", re.I)
# The prep lists come from the real family plan. In the demo the parents are Parent A and Parent B, and no house device
# id or address is ever shown.
DEMO_NAMES = (("Gonza", "Parent A"), ("Ceci", "Parent B"))
DEMO_NAMES_ES = (("Gonza", "Persona A"), ("Ceci", "Persona B"))
DEVICE_ID = re.compile(r"\s*\(?\b(light|switch|sensor|todo|media_player)\.[A-Za-z0-9_]+\)?")
# Replies the demo builds itself, in the visitor's language. Spanish is es-UY: voseo, "mamadera", "pañal".
TEXTS = {
    "en": {"REFUSAL": rules.REFUSAL, "CRY_GUESS": "This is only a guess from the log, never a diagnosis.",
           "CRY_NOT_ENOUGH": "There is not enough in Theo's log yet to guess why. This is never a diagnosis."},
    "es": {"REFUSAL": ("No puedo dar consejos médicos. Para eso, mejor llamá a tu pediatra. Si es urgente, llamá al 911. "
                       "Si querés, anoto lo que ves así lo tenés a mano para la llamada."),
           "CRY_GUESS": "Es solo una pista del registro, nunca un diagnóstico.",
           "CRY_NOT_ENOUGH": "Todavía no hay suficiente en el registro de Theo para adivinar por qué llora. No es un diagnóstico.",
           "CRY_PROBABLY": "Por el registro, capaz que es {reason}: {evidence}.",
           "CRY_NO_REASON": "En el registro no hay una razón probable{evidence}. Para revisar: {checks}.",
           "CRY_CHECKS": "el pañal mojado o sucio, si tiene calor o frío, un provechito después de la toma, o capaz que solo quiere brazos",
           "CRY_FACT_FEED": "última toma hace {ago}", "CRY_FACT_CHANGE": "último cambio de pañal hace {ago}",
           "CRY_FACT_AWAKE": "despierto hace {ago}",
           "CRY_NEXT": "Si no, {reason}: {evidence}.",
           "CRY_HUNGRY": "la última toma fue hace {ago} y suele comer cada {gap}",
           "CRY_TIRED": "se despertó hace {ago} y suele volver a dormirse después de unos {usual}",
           "CRY_DIAPER": "el último cambio de pañal fue hace {ago}",
           "CRY_DIAPER_SINCE_FEED": "no hay cambio de pañal anotado desde la toma de las {at}",
           "CRY_HUNGRY_WORD": "hambre", "CRY_TIRED_WORD": "sueño", "CRY_DIAPER_WORD": "el pañal"},
}
# Words that mark a short message as Spanish or English when the shared check cannot tell, like "nono eran 70".
ES_HINT = re.compile(r"\b(nono|eran?|fue|fueron|mamadera|toma|tom[oó]|pa[ñn]al|llora\w*|durmi\w*|cu[aá]ndo|"
                     r"cu[aá]nto|qu[eé]|por qu[eé]|ac[aá]|ah[ií]|perd[oó]n|borr[aá]\w*|anot[aá]\w*|dale|gracias|hola)\b", re.I)
EN_HINT = re.compile(r"\b(the|she|he|his|her|is|was|did|when|how|what|why|it|that|bottle|diaper|fix|delete|just|feed|"
                     r"asleep|crying|hello|hi|thanks)\b", re.I)
DAYS_ES = {"Mon": "lun", "Tue": "mar", "Wed": "mié", "Thu": "jue", "Fri": "vie", "Sat": "sáb", "Sun": "dom"}
MONTHS_ES = {"Jan": "ene", "Feb": "feb", "Mar": "mar", "Apr": "abr", "May": "may", "Jun": "jun", "Jul": "jul",
             "Aug": "ago", "Sep": "set", "Oct": "oct", "Nov": "nov", "Dec": "dic"}


def plain_reply(text):
    """The page shows text as it is: no markdown bold and no em dash, even when the brain writes them."""
    text = re.sub(r"\s*[\u2014\u2013]\s*", ", ", text.replace("**", "").replace("__", ""))
    return re.sub(r"(?m)^\s*\* ", "- ", text)


def hm(minutes):
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def message_lang(text, fallback="en"):
    """The language of one message: Spanish or English by its words, the page's language when it says neither."""
    if rules.looks_spanish(text) or ES_HINT.search(text or ""):
        return "es"
    if EN_HINT.search(text or ""):
        return "en"
    return fallback if fallback in TEXTS else "en"


def answered_by(events, from_log=False):
    """Who wrote the answer, so the page can say it: the AI model when a brain call ran in this turn, else the log
    (why he may be crying, read from his log by a rule) or a fixed rule (the emergency line, a refusal, a logged entry)."""
    calls = [e for e in events if e["kind"] == "brain_call"]
    if calls:
        model = str(calls[-1].get("model") or "")
        return {"kind": "brain", "model": model, "muse": "muse" in model.lower()}
    return {"kind": "log" if from_log else "rule"}


def night_es(text):
    """The rhythm engine's night summary in Spanish. Its sentences are a fixed template, so this is a plain mapping."""
    def day(match):
        return f"{DAYS_ES[match.group(1)]} {match.group(2)}"
    out = re.sub(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{2})\b", day, text)
    out = re.sub(r"A feed was expected around (\d{2}:\d{2}), (\d+) min ago\.", r"Se esperaba una toma cerca de las \1, hace \2 min.", out)
    for en, es in (("Tonight so far, since", "Esta noche hasta ahora, desde"), ("Last night,", "Anoche,"),
                   ("Night summary for", "Resumen de la noche del"), (" to ", " al "), (" feeds at ", " tomas a las "),
                   (" feeds,", " tomas,"), ("longest sleep", "sueño más largo"), ("Wake-ups:", "Despertares:"),
                   ("Next on duty:", "Le toca:"), ("Next feed expected around", "Próxima toma cerca de las")):
        out = out.replace(en, es)
    return out


def countdown_es(text):
    match = re.match(r"(about )?(\d+) days to the due date, (\w{3}) (\d+)( \(an estimate\))?", text)
    if not match:
        return text
    about, days, month, day, estimate = match.groups()
    return (f"{'unos ' if about else ''}{days} días para la fecha de parto, {day} de {MONTHS_ES.get(month, month)}"
            f"{' (estimada)' if estimate else ''}")
# The only sentences the simulated speakers can say. Free text never reaches a speaker, so no code or name is read aloud.
ANNOUNCEMENTS = rules.ANNOUNCEMENTS
ROOMS = ["nursery", "kitchen", "living room", "bedroom", "every room"]
PARENTS = ["Parent A", "Parent B"]
SIMULATED = "Simulated in the demo, nothing ran in a real house"
DEMO_NOTE = """
This is a public demo. The baby is a simulated baby boy called Theo, a few weeks old, and the log is a simulated week.
Always say he and him for Theo. The parents are Parent A and Parent B, simulated too.
For who is up next at night, call night_rota and answer with its text: the night rota is the fair split of wake-ups.
The house is simulated too: house tools only show what you would do. When an action in the house would help, for example
dimming the nursery light for a night feed or holding notifications while he sleeps, call the tool and say in a few words
that it is simulated. dim_lights, hold_notifications, pause_vacuum and announce run alone, simulated. announce says only
one of its fixed sentences, never free text. Calling the partner always waits for the parent's yes. Never ask for, keep or
repeat personal details: no real names, codes, addresses or phone numbers. If a visitor gives one, say you do not keep it.
"""
PREP_NOTE = """
This is the public demo in prep mode: the weeks before a simulated baby boy called Theo is born. The lists, the
appointments and the due date are simulated, the due date is an estimate. Always say he and him for Theo. Answer from the
prep tools, never from general knowledge, and say the lists are simulated when it helps. Never ask for, keep or repeat
personal details: no real names, codes, addresses or phone numbers. If a visitor gives one, say you do not keep it.
"""

FULL = "The demo is full right now. Please try again in a few minutes."
CLIENT_LIMIT = "That is the end of the demo for today from this connection. Thank you for trying the agent."
NEVER_SENT = "not sent: a code, a password, a phone number or an address is never passed on, ask the parent to share it themselves"
RESTING = ("The demo is resting for today, it reached its daily limit. Please come back tomorrow. "
           "Nothing you typed was lost, it simply was not sent.")
BUSY = "The demo is busy with other visitors right now. Please try again in a few seconds."
VISITOR_LIMIT = "That is the end of this demo session, you reached the message limit. Thank you for trying the agent."
TOO_LONG = "Please keep it under {n} characters."
THINK_FAIL = "I could not think that through just now. Please try again."


class SpendCapReached(brain_mod.BrainError):
    pass


class MeteredBrain:
    """The real brain behind the daily spend cap: refuses before a call once today's spend is at the cap,
    and charges each call's tokens (or a fallback estimate when the provider reports none)."""

    def __init__(self, brain, records, settings, fallback_tokens=(4000, 400)):
        self.brain, self.records, self.s, self.fallback = brain, records, settings, fallback_tokens
        self.name, self.model, self.destination = brain.name, brain.model, brain.destination

    def cost(self, usage):
        tokens_in, tokens_out = ((usage or {}).get("input_tokens"), (usage or {}).get("output_tokens"))
        if not tokens_in and not tokens_out:
            tokens_in, tokens_out = self.fallback
        return (tokens_in * self.s["price_in_per_mtok"] + tokens_out * self.s["price_out_per_mtok"]) / 1_000_000

    def resting(self):
        return self.records.spent_today() >= self.s["daily_usd_cap"]

    def step(self, system, transcript, tools):
        if self.resting():
            raise SpendCapReached("daily spend cap reached")
        reply = self.brain.step(system, transcript, tools)
        self.name, self.model, self.destination = self.brain.name, self.brain.model, self.brain.destination
        if self.brain.name == "fake":
            spend = 0.0
        else:
            spend = reply.usd if reply.usd is not None else self.cost(reply.usage)
        self.records.add_spend(spend)
        return reply


class DemoAgent(Agent):
    health_gate = True
    note = DEMO_NOTE
    page_lang = "en"

    def system_prompt(self):
        return super().system_prompt() + self.note + ("Answer in the language of the parent's newest message. In Spanish "
                                                      "write like Uruguay: voseo, mamadera, pañal.\n")

    def lang(self, request):
        return message_lang(request, self.page_lang)

    def refusal(self, request):
        return TEXTS[self.lang(request)]["REFUSAL"]


class PrepAgent(DemoAgent):
    note = PREP_NOTE


class Visitor:
    """One visitor's demo: their own agent, bus, memory and baby log, plus what the simulated house did."""

    def __init__(self, brain, settings, clock):
        self.clock = clock
        self.lock = threading.Lock()
        self.last_seen = time.monotonic()
        self.bus = Bus(None)
        self.memory = Memory(":memory:")
        self.baby_log = DemoBabyLog(clock=clock)
        tools = core_tools(self.memory, self.baby_log, ALLOWED, remember_keys=())  # the demo keeps no facts from visitors
        self.add_house_tools(tools)
        tools.add(Tool("next_feed", "When the next feed is expected, from the rhythm of this baby's own log. Use it for "
                       "'when is the next feed?' and answer with its text.", schema({}), self.next_feed_text))
        tools.add(Tool("night_rota", "Who is up next at night, from the night wake-ups in the log: the fair split, the same "
                       "as the panel. Use it for 'who is up next?' or 'whose turn is it tonight?' and answer with its text.",
                       schema({}), self.night_rota))
        self.agent = DemoAgent(self.bus, self.memory, self.baby_log, tools, brain,
                               max_steps=settings["max_steps"], history=settings["history"])
        self.agent.reply_guards.append(plain_reply)
        self.memory.remember("baby_name", "Theo (simulated)")
        self.memory.remember("baby", "a simulated baby boy, a few weeks old: he and him")
        self.memory.remember("parents", "Parent A and Parent B")
        self.replies = collections.deque()
        self.bus.subscribe(self.replies.append, ["reply"])
        self.brain, self.settings = brain, settings
        self._prep = None
        self.answered_by = None

    def add_house_tools(self, tools):
        def simulated(action):
            def run(**arguments):
                self.bus.publish("house_dry", action=action, arguments=arguments)
                return SIMULATED
            return run
        tools.add(Tool("dim_lights", "Dim the lights in a room, for night feeds. Simulated in the demo.",
                       schema({"room": {"type": "string"}, "level": {"type": "integer"}}), simulated("dim_lights")))
        tools.add(Tool("hold_notifications", "Hold phone and speaker notifications while the baby sleeps or the parent's hands are busy. "
                       "Simulated in the demo.", schema({}), simulated("hold_notifications")))
        tools.add(Tool("pause_vacuum", "Pause the robot vacuum so it does not wake the baby. Simulated in the demo.",
                       schema({}), simulated("pause_vacuum")))
        announce = simulated("announce")

        def say_fixed(message, where="nursery"):
            if message not in ANNOUNCEMENTS or where not in ROOMS:
                raise ValueError(f"announce says only one of: {', '.join(ANNOUNCEMENTS)}, in one of: {', '.join(ROOMS)}")
            return announce(message=message, text=ANNOUNCEMENTS[message], where=where)
        tools.add(Tool("announce", "Say one fixed sentence on a house speaker, never free text. Simulated in the demo. "
                       + " ".join(f"{k}: {v}" for k, v in ANNOUNCEMENTS.items()),
                       schema({"message": {"type": "string", "enum": list(ANNOUNCEMENTS)},
                               "where": {"type": "string", "enum": ROOMS}}, ["message"]), say_fixed))
        partner = simulated("call_partner")

        def call_partner(text):
            if rules.personal_detail(text):
                raise ValueError(NEVER_SENT)
            return partner(text=str(text)[:200])
        tools.add(Tool("call_partner", "Ask the other parent to come and help, in a short sentence with no codes or personal "
                       "details. It always waits for the parent's yes.", schema({"text": {"type": "string"}}, ["text"]), call_partner))

    def actions_since(self, index):
        events = list(self.bus.history)[index:]
        out = []
        for e in events:
            if e["kind"] == "house_dry":
                out.append({"action": e["action"], "arguments": e.get("arguments") or {}, "status": "simulated"})
            elif e["kind"] == "ask_parent":
                out.append({"action": e.get("name"), "arguments": e.get("arguments") or {}, "status": "waits for your yes"})
        return out

    def prep(self):
        """Prep mode, made on first use: its own agent, bus and memory, the before-he-arrives lists simulated and the due
        date PREP_DUE_IN_DAYS from today. Copying a list to Home Assistant is not in the demo at all."""
        if self._prep is None:
            self._prep = PrepMode(self.brain, self.settings, self.clock)
        return self._prep

    def talk(self, text, mode="baby", lang="en"):
        """(reply, actions, mode). A message about getting ready goes to prep mode from either tab. lang is the page's
        language, used only when the message's own words do not tell."""
        self.agent.page_lang = lang
        if mode == "prep" or (PREP_WORDS.search(text) and not rules.is_health(text) and not rules.is_log_request(text)):
            self.prep().agent.page_lang = lang
            prep_start = len(self.prep().bus.history)
            reply, actions = self.prep().talk(text)
            self.answered_by = answered_by(list(self.prep().bus.history)[prep_start:])
            return reply, actions, "prep"
        start = len(self.bus.history)
        self.replies.clear()
        from_log = rules.is_cry_question(text) and not rules.is_health(text) and not rules.is_log_request(text)
        if from_log:
            # Only a bare "why is he crying?" gets the likely reason from the log with no brain call, as in the families
            # bot. A cry with anything else in it (bluish, lethargic, hot, swallowed a coin) is not bare, so the agent's
            # gates answer it: the emergency line, the newborn call-now line or the refusal.
            self.memory.add_message("demo", "user", text, ts=self.baby_log.now())
            self.agent.say("demo", self.cry_text(self.agent.lang(text)))
        else:
            # Health advice is refused inside the agent before any brain call, and a dose given or a milestone is logged.
            self.agent.handle({"kind": "message", "channel": "demo", "text": text})
        reply = " ".join(e["text"] for e in self.replies) or "OK."
        self.answered_by = answered_by(list(self.bus.history)[start:], from_log)
        return reply, self.actions_since(start), "baby"

    def cry_text(self, lang="en"):
        """Why Theo may be crying, from his log only: a guess, never a diagnosis and never the emergency line. The
        Spanish text is built from the same scores as the families bot's."""
        t = TEXTS["es" if lang == "es" else "en"]
        now = self.baby_log.now()
        rows = self.baby_log.rhythm_rows()
        ctx = cry_reason.context(rows, now, TZ)
        if "last_feed" not in ctx and "last_change" not in ctx:
            return t["CRY_NOT_ENOUGH"]
        if lang != "es":
            try:
                return cry_reason.explain(rows, now, TZ)["text"] + " " + t["CRY_GUESS"]
            except ValueError:
                return t["CRY_NOT_ENOUGH"]
        ranked = sorted(((round(score, 3), reason) for reason, (score, _) in cry_reason.scores(ctx).items()),
                        key=lambda r: (-r[0], cry_reason.REASONS.index(r[1])))
        facts = [t["CRY_FACT_FEED"].format(ago=hm(ctx["since_feed_min"])) if "since_feed_min" in ctx else "",
                 t["CRY_FACT_CHANGE"].format(ago=hm(ctx["since_change_min"])) if "since_change_min" in ctx else "",
                 t["CRY_FACT_AWAKE"].format(ago=hm(ctx["awake_min"])) if "awake_min" in ctx and not ctx["asleep"] else ""]
        known = ", ".join(f for f in facts if f)
        evidence = {"comfort": (": " + known) if known else ""}
        if "since_feed_min" in ctx and "feed_gap_min" in ctx:
            evidence["hungry"] = t["CRY_HUNGRY"].format(ago=hm(ctx["since_feed_min"]), gap=hm(ctx["feed_gap_min"]))
        if "awake_min" in ctx and "usual_awake_min" in ctx:
            evidence["tired"] = t["CRY_TIRED"].format(ago=hm(ctx["awake_min"]), usual=hm(ctx["usual_awake_min"]))
        if "since_change_min" in ctx:
            evidence["diaper"] = (t["CRY_DIAPER_SINCE_FEED"].format(at=patterns.hhmm(ctx["last_feed"].astimezone(TZ)))
                                  if cry_reason.diaper_after_feed(ctx) else t["CRY_DIAPER"].format(ago=hm(ctx["since_change_min"])))
        top = ranked[0][1] if ranked[0][1] in evidence and cry_reason.is_likely(ranked) else "comfort"
        text = (t["CRY_NO_REASON"].format(evidence=evidence["comfort"], checks=t["CRY_CHECKS"]) if top == "comfort"
                else t["CRY_PROBABLY"].format(reason=t[f"CRY_{top.upper()}_WORD"], evidence=evidence[top]))
        if (top != "comfort" and len(ranked) > 1 and ranked[1][1] not in ("comfort", top) and ranked[1][1] in evidence
                and ranked[1][0] >= cry_reason.LIKELY):
            text += " " + t["CRY_NEXT"].format(reason=t[f"CRY_{ranked[1][1].upper()}_WORD"], evidence=evidence[ranked[1][1]])
        if ctx.get("next_feed_at") and top != "hungry":
            text += " " + night_es(patterns.next_feed_sentence(ctx["next_feed"], now, TZ))
        return text + " " + t["CRY_GUESS"]

    def rota(self):
        now = self.clock().astimezone(TZ)
        handled = [w["parent"] for w in patterns.night_wakeups(self.baby_log.rhythm_rows(), TZ) if w["at"] < now]
        counts = {p: handled.count(p) for p in PARENTS}
        return {"on_duty": patterns.next_on_duty(handled, PARENTS), "counts": counts, "last": handled[-1] if handled else None}

    def night_rota(self):
        r = self.rota()
        counts = ", ".join(f"{p} {n}" for p, n in r["counts"].items())
        last = f" {r['last']} took the last one." if r["last"] else ""
        return (f"Next night wake-up: {r['on_duty']}. Wake-ups in this week's log: {counts}.{last} The rota is the fair "
                "split: fewer wake-ups goes next, a tie goes to whoever did not take the last one. Simulated parents.")

    def proactive(self, lang="en"):
        """What the agent says first today, computed from this visitor's log: next feed, night summary, notes."""
        now = self.clock().astimezone(TZ)
        rows = self.baby_log.rhythm_rows()
        out = {}
        nxt = patterns.next_feed(rows, now)
        if nxt:
            minutes = round((nxt["at"] - now).total_seconds() / 60)
            when = patterns.hhmm(nxt["at"].astimezone(TZ))
            out["next_feed"] = {"at": when, "in_min": minutes, "gap_min": nxt["gap_min"],
                                "text": (f"Next feed around {when}, in about {minutes} min. Feeds have been about {nxt['gap_min']} min apart."
                                         if minutes >= 0 else patterns.next_feed_sentence(nxt, now, TZ)),
                                "house": ("dim_lights" if patterns.is_night(nxt["at"].astimezone(TZ)) else None)}
        summary = patterns.night_summary(rows, now, TZ, PARENTS, current=True)
        out["night_summary"] = {"text": night_es(summary["text"]) if lang == "es" else summary["text"], "on_duty": summary["on_duty"]}
        notes = patterns.unusual_notes(rows, TZ)
        out["unusual"] = [n["text"] for n in notes[-2:]]
        return out

    def next_feed_text(self):
        nxt = self.proactive().get("next_feed")
        return nxt["text"] if nxt else "Not enough feeds in the log yet to tell when the next one is."

    def close(self):
        self.memory.close()
        if self._prep is not None:
            self._prep.memory.close()

    def recent(self, limit=6):
        return [{"kind": e["kind"], "at": e["ts"][11:16], "day": e["ts"][:10], "details": e["details"]}
                for e in self.baby_log.entries(None, None, limit)][::-1]


def scrub(text, names=DEMO_NAMES):
    for real, simulated in names:
        text = re.sub(rf"\b{real}\b", simulated, text)
    return DEVICE_ID.sub("", text)


def demo_item_id(item_id):
    return item_id.replace("gonza_", "parent_a_").replace("ceci_", "parent_b_")


# The prep lists in es-UY for a Spanish page: (list, demo item id) -> (the English text as the demo seeds it, the Spanish).
PREP_TITLES_ES = {"nursery": "Cuarto del bebé", "hospital_bag": "Bolso para el sanatorio",
                  "car_seat": "Silla del auto, Joie Litetrax con cinturón", "white_noise": "Máquina de ruido blanco, casera"}
PREP_ITEMS_ES = {(name, demo_item_id(row[0])): (scrub(row[1]), scrub(prep_lists.ES[name][row[0]], DEMO_NAMES_ES))
                 for name, spec in prep_lists.LISTS.items() for row in spec["items"] if row[0] in prep_lists.ES.get(name, {})}


def prep_text_es(list_name, item_id, text):
    """A seeded prep item in Spanish. An item the visitor added or reworded keeps its own words."""
    seeded = PREP_ITEMS_ES.get((list_name, item_id))
    return seeded[1] if seeded and seeded[0] == text else text


class PrepMode:
    """Prep mode for one visitor: the Prep plug-in's tools on an in-memory copy of the lists, with every list date
    moved so the simulated due date is PREP_DUE_IN_DAYS from today. Nothing here reaches a house or a channel."""

    def __init__(self, brain, settings, clock):
        self.clock = clock
        self.bus = Bus(None)
        self.memory = Memory(":memory:")
        log = LocalBabyLog(self.memory)
        tools = core_tools(self.memory, log, PREP_ALLOWED, remember_keys=())
        self.agent = PrepAgent(self.bus, self.memory, log, tools, brain, max_steps=settings["max_steps"],
                               history=settings["history"])
        due = clock().astimezone(TZ).date() + datetime.timedelta(days=PREP_DUE_IN_DAYS)
        self.plugin = Prep(self.agent, {"prep": {"due_date": due.isoformat(), "due_date_estimate": True,
                                                 "nudge": {"enabled": False}}, "data_dir": "/nonexistent"},
                           clock=lambda: clock().astimezone(TZ))
        # Prep mode has no baby log and no house: only the prep tools and the clock.
        tools.items = {name: tool for name, tool in tools.items.items() if name in PREP_ALLOWED}
        self.simulate_lists(due)
        nursery_plan = tools.items["nursery_plan"].handler
        tools.items["nursery_plan"].handler = lambda layout=None: json.loads(scrub(json.dumps(
            {k: v for k, v in nursery_plan(layout).items() if k != "devices"}, ensure_ascii=False)))
        add_appointment = tools.items["add_appointment"].handler

        def keep_appointment(title, when, place=None, bring=None):
            if any(rules.personal_detail(str(part)) for part in (title, place, bring) if part):
                raise ValueError("not kept: the demo never keeps an address, a phone number or a code")
            return add_appointment(title, when, place, bring)
        tools.items["add_appointment"].handler = keep_appointment
        self.wrap_spanish(tools)
        self.reply_lang = "en"
        self.agent.page_lang = "en"
        self.agent.reply_guards.append(plain_reply)
        self.memory.remember("baby_name", "Theo (simulated, not born yet)")
        self.memory.remember("parents", "Parent A and Parent B")
        self.replies = collections.deque()
        self.bus.subscribe(self.replies.append, ["reply"])

    def simulate_lists(self, due):
        """Fixed list dates move with the simulated due date, so a list never shows a date long gone, and the texts
        name Parent A and Parent B with no house device id."""
        offset = (due - datetime.date.fromisoformat(PREP_DEFAULTS["due_date"])).days
        with self.plugin.lock:
            for row_id, item_id, by, text in self.plugin.db.execute("select id, item_id, by, text from prep_items").fetchall():
                moved = (datetime.date.fromisoformat(by) + datetime.timedelta(days=offset)).isoformat() if by else None
                item_id = demo_item_id(item_id)
                self.plugin.db.execute("update prep_items set by = ?, text = ?, item_id = ? where id = ?",
                                       (moved, scrub(text), item_id, row_id))
            self.plugin.db.commit()

    def wrap_spanish(self, tools):
        """For a Spanish message the brain reads the lists in Spanish, and a few Spanish words tick an item."""
        prep_list, prep_next, prep_check = (tools.items[n].handler for n in ("prep_list", "prep_next", "prep_check"))

        def check(item, list=None, done=True):
            try:
                return prep_check(item, list, done)
            except ValueError:
                words = str(item).lower().strip()
                hits = [key for key, (_, es) in PREP_ITEMS_ES.items()
                        if list in (None, key[0]) and words and words in es.lower()]
                if len(hits) != 1:
                    raise
                return prep_check(hits[0][1], hits[0][0], done)
        tools.items["prep_list"].handler = lambda list=None: self.translate(prep_list(list), self.reply_lang)
        tools.items["prep_next"].handler = lambda: self.translate(prep_next(), self.reply_lang)
        tools.items["prep_check"].handler = check

    @staticmethod
    def translate(out, lang):
        """prep_list or prep_next output with the seeded texts and the list titles in Spanish when lang is es."""
        if lang != "es":
            return out
        out = json.loads(json.dumps(out))
        if isinstance(out.get("items"), list):
            name = next((k for k, v in prep_lists.LISTS.items() if v["title"] == out.get("title")), None)
            for item in out["items"]:
                item["text"] = prep_text_es(item.get("list", name), item["id"], item["text"])
            if name:
                out["title"] = PREP_TITLES_ES[name]
        else:
            for name, summary in out.items():
                summary["title"] = PREP_TITLES_ES.get(name, summary["title"])
        return out

    def talk(self, text):
        self.reply_lang = self.agent.lang(text)
        start = len(self.bus.history)
        self.replies.clear()
        self.agent.handle({"kind": "message", "channel": "demo", "text": text})
        events = list(self.bus.history)[start:]
        actions = [{"action": e["action"], "arguments": {"list": e.get("list"), "item": e.get("item_id")},
                    "status": "simulated"} for e in events if e["kind"] == "prep"]
        return " ".join(e["text"] for e in self.replies) or "OK.", actions

    def state(self, lang="en"):
        nxt = self.translate(self.plugin.next(items=3), lang)
        lists = self.translate(self.plugin.list(), lang)
        return {"countdown": countdown_es(nxt["countdown"]) if lang == "es" else nxt["countdown"], "items": nxt["items"],
                "open_total": nxt["open_total"],
                "lists": {name: {"title": v["title"], "open": v["open"], "done": v["done"]} for name, v in lists.items()}}


class DemoApp:
    def __init__(self, settings, brain=None, clock=None):
        self.s = settings
        self.clock = clock or (lambda: datetime.datetime.now(TZ))
        self.records = Records(settings["data_dir"])
        raw = brain or brain_mod.build(settings["brain"])
        self.brain = MeteredBrain(raw, self.records, settings)
        self.visitors = collections.OrderedDict()
        self.lock = threading.Lock()
        self.thinking = threading.BoundedSemaphore(settings["max_parallel_brain"])
        self.clients = Clients(settings)
        self.preview = (0.0, None)

    def visitor(self, vid, fresh=False):
        """The visitor's own demo, made on their first message or reset. None when the demo is full: a visitor who
        is still talking is never dropped to make room for a new one."""
        with self.lock:
            self._evict()
            if fresh or vid not in self.visitors:
                if vid not in self.visitors and len(self.visitors) >= self.s["max_visitors_in_memory"]:
                    return None
                if vid in self.visitors:
                    self.visitors.pop(vid).close()
                self.visitors[vid] = Visitor(self.brain, self.s, self.clock)
            self.visitors.move_to_end(vid)
            v = self.visitors[vid]
            v.last_seen = time.monotonic()
            return v

    def known(self, vid):
        with self.lock:
            return self.visitors.get(vid)

    def _evict(self):
        """Drop visitors idle for visitor_idle_s. When the demo is full, drop the longest idle one only if it has
        been quiet for protect_s: an active conversation is never evicted."""
        now = time.monotonic()
        for vid in [k for k, v in self.visitors.items() if v.last_seen < now - self.s["visitor_idle_s"]]:
            self.visitors.pop(vid).close()
        while len(self.visitors) >= self.s["max_visitors_in_memory"]:
            vid, oldest = next(iter(self.visitors.items()))
            if oldest.last_seen > now - self.s["protect_s"]:
                break
            self.visitors.pop(vid).close()

    def fresh_state(self):
        """What a visitor with no demo yet sees, built at most once a minute and never kept as a visitor, so page
        loads and cookie-less requests cannot fill the demo or push anyone out."""
        made, v = self.preview
        if v is None or time.monotonic() - made > 60:
            if v is not None:
                v.close()
            v = Visitor(self.brain, self.s, self.clock)
            self.preview = (time.monotonic(), v)
        return v

    def remaining(self, vid, internal):
        if internal:
            return None
        return max(0, self.s["max_messages_per_visitor"] - self.records.messages_from(vid))

    def state(self, vid, internal, lang="en"):
        v = self.known(vid) or self.fresh_state()
        return {"proactive": v.proactive(lang), "recent": v.recent(), "prep": v.prep().state(lang),
                "remaining": self.remaining(vid, internal), "resting": self.brain.resting(), "max_input": self.s["max_input_chars"]}

    def message(self, vid, internal, text, client=None, mode="baby", lang="en"):
        """Returns (http status, body). Records one session row for each message the demo takes in. client is the
        connection the request came from (Cloudflare's CF-Connecting-IP behind the tunnel), which a visitor cannot
        reset the way they drop a cookie. It is kept only as a keyed hash in memory, never stored or logged."""
        text = (text or "").strip()
        if not text:
            return 400, {"error": "empty"}
        if len(text) > self.s["max_input_chars"]:
            return 413, {"error": "too_long", "reply": TOO_LONG.format(n=self.s["max_input_chars"])}
        if not internal and self.records.messages_from(vid) >= self.s["max_messages_per_visitor"]:
            return 429, {"error": "visitor_limit", "reply": VISITOR_LIMIT, "remaining": 0}
        new = self.known(vid) is None
        if not internal and not self.clients.allow(client, new_visitor=new):
            return 429, {"error": "client_limit", "reply": CLIENT_LIMIT, "remaining": 0}
        if new and self.visitor(vid) is None:
            return 503, {"error": "full", "reply": FULL, "remaining": self.remaining(vid, internal)}
        self.records.add_message(vid, internal)
        if self.brain.resting() or (not internal and self.records.messages_today() > self.s["max_messages_per_day"]):
            return 503, {"error": "resting", "reply": RESTING, "remaining": self.remaining(vid, internal)}
        if not self.thinking.acquire(timeout=20):
            return 503, {"error": "busy", "reply": BUSY, "remaining": self.remaining(vid, internal)}
        try:
            v = self.visitor(vid)
            if v is None:
                return 503, {"error": "full", "reply": FULL, "remaining": self.remaining(vid, internal)}
            with v.lock:
                try:
                    lang = "es" if lang == "es" else "en"
                    reply, actions, mode = v.talk(text, "prep" if mode == "prep" else "baby", lang)
                except SpendCapReached:
                    v.memory.add_message("demo", "assistant", RESTING)
                    return 503, {"error": "resting", "reply": RESTING, "remaining": self.remaining(vid, internal)}
                except brain_mod.BrainError as error:
                    v.bus.publish("agent_error", error=str(error)[:300])
                    v.memory.add_message("demo", "assistant", THINK_FAIL)
                    return 502, {"error": "brain", "reply": THINK_FAIL, "remaining": self.remaining(vid, internal)}
            return 200, {"reply": reply, "actions": actions, "mode": mode, "answered_by": v.answered_by, "proactive": v.proactive(lang), "recent": v.recent(),
                         "prep": v.prep().state(lang), "remaining": self.remaining(vid, internal)}
        finally:
            self.thinking.release()

    def reset(self, vid, internal, client=None, lang="en"):
        """A fresh demo baby. It counts as a new visitor for the connection's limit, so resets cannot fill the demo."""
        if not internal and not self.clients.allow(client, new_visitor=True, message=False):
            return 429, {"error": "client_limit", "reply": CLIENT_LIMIT, "remaining": 0}
        if self.visitor(vid, fresh=True) is None:
            return 503, {"error": "full", "reply": FULL}
        return 200, self.state(vid, internal, lang)

    def close(self):
        with self.lock:
            for v in self.visitors.values():
                v.close()
            self.visitors.clear()
            if self.preview[1] is not None:
                self.preview[1].close()
        self.records.close()


class Clients:
    """Limits per connection, which a visitor cannot reset by dropping the cookie: messages per day and new demo
    babies per hour. A connection is kept as an HMAC under a key made at start and held only in memory, so no IP is
    ever stored or logged, and a restart forgets them all."""

    def __init__(self, settings, clock=time.time):
        self.s, self.clock = settings, clock
        self.key = secrets.token_bytes(32)
        self.seen = collections.OrderedDict()
        self.lock = threading.Lock()

    def name(self, client):
        """An IPv6 client counts by its /64, which one home or one phone holds, so rotating addresses inside it does
        not reset the limits."""
        value = str(client or "unknown").strip()
        try:
            address = ipaddress.ip_address(value.split("%")[0])
            if address.version == 6 and not address.ipv4_mapped:
                value = str(ipaddress.ip_network(f"{address}/64", strict=False))
            elif address.version == 6:
                value = str(address.ipv4_mapped)
        except ValueError:
            pass
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()[:32]

    def allow(self, client, new_visitor=False, message=True):
        now = self.clock()
        with self.lock:
            name = self.name(client)
            messages, babies = self.seen.pop(name, ([], []))
            messages = [t for t in messages if t > now - 86400]
            babies = [t for t in babies if t > now - 3600]
            ok = ((not message or len(messages) < self.s["max_messages_per_client"])
                  and (not new_visitor or len(babies) < self.s["max_new_visitors_per_client"]))
            if ok:
                if message:
                    messages.append(now)
                if new_visitor:
                    babies.append(now)
            self.seen[name] = (messages, babies)
            while len(self.seen) > 20000:
                self.seen.popitem(last=False)
            return ok


def dumps(body):
    return json.dumps(body, ensure_ascii=False, default=str).encode()
