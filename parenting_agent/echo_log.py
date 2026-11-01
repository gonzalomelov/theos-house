"""Write mode for the Alexa skill "baby agent": a parent logs the baby by voice at the Echo, after one spoken yes.

The Echo cannot tell who is speaking, so nothing it hears is written on the first turn. The words go through the same
agent loop, log tools and guards as Telegram (the duplicate question, the correction rules, the final guard, the red
flag lines), in an agent of its own that has the baby log tools and nothing else: no house tool, no message to anyone,
no remember. Its writes land in a staged copy of the log. The Echo then says what it would write ("¿Anoto 90 ml de
mamadera a las 7:50? Decí sí") and only the skill's next "sí" writes exactly that to the real log, tagged "echo".

A correction from the Echo can change or remove only the last entry the Echo itself wrote, never one a parent logged
on Telegram.

    writer = EchoWriter(agent, config)
    writer.turn("le di 90 ml de mamadera", "es")  -> {"reply": "¿Anoto ...? Decí sí.", "confirm": {"id": ...}}
    writer.confirm(id, "es")                       -> {"reply": "Listo, anoté ...", "written": [...]}
"""
import copy
import datetime
import secrets
import threading
import time

from .agent import brain as brain_mod
from .agent import rules
from .agent.babybuddy import BabyBuddyLog, at_or_before_now, iso, DEFAULT_FEED_MINUTES
from .agent.loop import Agent
from .agent.memory import BabyLog, LOG_KINDS, parse_time
from .agent.tools import core_tools
from .bus import Bus
from .spoken_time import when, at_words

ECHO_TAG = "echo"
CHANNEL = "voice"
PERSON = "echo"
CHAT_ID = "echo:echo"
PROPOSAL_S = 120
OWN_HOURS = 12
TOOLS = ("log_baby_event", "edit_baby_event", "delete_baby_event", "read_baby_log", "baby_summary", "current_time")
NOT_OWN = "from the Echo only the last entry the Echo logged can be changed, the parents change the others on Telegram"

LINES = {
    "es": {"yes": " Decí sí.", "done": "Listo, {what}.", "nothing": "No tengo nada para anotar. Decímelo de nuevo.",
           "cancelled": "Listo, no anoté nada.", "not_written": "No anoté nada.", "failed": "No pude anotarlo, el "
           "registro no respondió. Probá de nuevo.", "partly": "Solo {what}. Lo demás no se pudo anotar.",
           "add": ("Anoto", "anoté"), "update": ("Cambio", "cambié"), "delete": ("Borro", "borré"), "and": " y ",
           "ok": "Dale."},
    "en": {"yes": " Say yes.", "done": "Done, {what}.", "nothing": "Nothing is waiting to be logged. Tell me again.",
           "cancelled": "OK, nothing logged.", "not_written": "Nothing was logged.", "failed": "I could not log it, the "
           "log did not answer. Try again.", "partly": "Only {what}. The rest could not be logged.",
           "add": ("Log", "logged"), "update": ("Change", "changed"), "delete": ("Delete", "deleted"), "and": " and ",
           "ok": "OK."},
}


def lines(lang):
    return LINES.get(lang, LINES["en"])


class EchoBabyBuddyLog(BabyBuddyLog):
    """Baby Buddy for the Echo's writes: every record carries the tag "echo" too, and the Echo's own entry can be
    changed or removed. The family's Telegram log is not this class and keeps its own behavior."""

    @classmethod
    def beside(cls, log):
        echo = cls(log.url, log.token, log.child_key, list(log.tags) + [ECHO_TAG], list(log.exclude_tags), log.timeout)
        echo.child_id = log.child_id
        return echo

    def open_sleep(self):
        timers = [t for t in self.request("GET", f"/api/timers/?child={self.child()}&limit=50")["results"]
                  if t.get("name") == "sleep"]
        return iso(parse_time(max(timers, key=lambda t: t["start"])["start"])) if timers else None

    def patch(self, entry, details, ts):
        """Change one entry. Returns {"before", "after"}, as the agent's edit tool does."""
        endpoint = "notes" if entry["kind"] in ("bath", "note") else {"feeding": "feedings", "diaper": "changes",
                                                                       "sleep": "sleep"}[entry["kind"]]
        body = patch_body(entry, details or {}, ts)
        record = self.request("PATCH", f"/api/{endpoint}/{entry['id']}/", body)
        return {"before": entry, "after": self.normalize(endpoint, record)}

    def remove(self, entry):
        endpoint = "notes" if entry["kind"] in ("bath", "note") else {"feeding": "feedings", "diaper": "changes",
                                                                       "sleep": "sleep"}[entry["kind"]]
        self.request("DELETE", f"/api/{endpoint}/{entry['id']}/")
        return {"deleted": entry}


def patch_body(entry, new, ts):
    """The Baby Buddy fields a correction changes, from the entry as it stands."""
    d = entry.get("details") or {}
    kind = entry["kind"]
    if kind == "feeding":
        end = at_or_before_now(ts) if ts else parse_time(entry["ts"])
        start = parse_time(d.get("start") or entry["ts"])
        if new.get("duration_min") is not None:
            start = end - datetime.timedelta(minutes=float(new["duration_min"]))
        else:
            start += end - parse_time(entry["ts"])
        body = {"start": iso(start), "end": iso(end)}
        if new.get("amount_ml") is not None:
            body["amount"] = float(new["amount_ml"])
        for name in ("method", "type"):
            if new.get(name):
                body[name] = new[name]
        return body
    if kind == "diaper":
        wet, solid = bool(new.get("wet", d.get("wet"))), bool(new.get("solid", d.get("solid")))
        return {"time": iso(at_or_before_now(ts)) if ts else entry["ts"], "wet": wet or not solid, "solid": solid}
    if kind == "sleep":
        start = at_or_before_now(new["start"]) if new.get("start") else parse_time(d.get("start") or entry["ts"])
        end = at_or_before_now(new.get("end") or ts) if (new.get("end") or ts) else parse_time(entry["ts"])
        if end <= start:
            raise ValueError("a sleep must end after it starts")
        return {"start": iso(start), "end": iso(end)}
    text = str(new.get("text") or new.get("note") or d.get("text") or "").strip()[:300]
    if kind == "bath" and not text.lower().startswith("bath"):
        text = f"Bath. {text}".strip()
    return {"note": text, "time": iso(at_or_before_now(ts)) if ts else entry["ts"]}


def patched(entry, new, ts):
    """The entry as it would read after patch_body, without writing it."""
    body = patch_body(entry, new or {}, ts)
    after = copy.deepcopy(entry)
    d = after.setdefault("details", {})
    if entry["kind"] == "feeding":
        after["ts"] = body["end"]
        d["start"] = body["start"]
        d["duration_min"] = round((parse_time(body["end"]) - parse_time(body["start"])).total_seconds() / 60)
        if "amount" in body:
            d["amount_ml"] = body["amount"]
        for name in ("method", "type"):
            if name in body:
                d[name] = body[name]
    elif entry["kind"] == "diaper":
        after["ts"], d["wet"], d["solid"] = body["time"], body["wet"], body["solid"]
    elif entry["kind"] == "sleep":
        after["ts"], d["start"] = body["end"], body["start"]
        d["duration_min"] = round((parse_time(body["end"]) - parse_time(body["start"])).total_seconds() / 60)
    else:
        after["ts"], d["text"] = body["time"], body["note"]
    return after


def target_for(log):
    """Where the Echo's confirmed writes go: Baby Buddy with the "echo" tag, or the agent's own log in offline runs."""
    return EchoBabyBuddyLog.beside(log) if isinstance(log, BabyBuddyLog) else log


class StagedLog(BabyLog):
    """The real log to read, with this turn's writes kept aside. commit() writes them for real, in order."""
    name = "echo-staged"

    def __init__(self, target):
        self.target = target
        self.own = []  # (kind, id) the Echo wrote, for a log without tags
        self.reset()

    def reset(self):
        self.ops, self.changed, self.removed, self.closed, self.n = [], {}, set(), False, 0

    def now(self):
        return self.target.now()

    # -- reading: the real log as this turn would leave it

    def staged(self):
        return [op["entry"] for op in self.ops if op["op"] == "add"]

    def entries(self, kind=None, since=None, limit=50):
        real = self.target.entries(kind, since, max(int(limit or 50), 1) + len(self.removed))
        items = []
        for entry in real:
            ref = (entry.get("kind"), entry.get("id"))
            if ref in self.removed:
                continue
            items.append(copy.deepcopy(self.changed.get(ref, entry)))
        since_time = parse_time(since) if since else None
        for entry in self.staged():
            if (kind is None or entry["kind"] == kind) and (since_time is None or parse_time(entry["ts"]) >= since_time):
                items.append(copy.deepcopy(entry))
        items.sort(key=lambda e: parse_time(e["ts"]))
        return items[-max(int(limit or 50), 1):]

    def open_sleep(self):
        started = [e for e in self.staged() if e["kind"] == "sleep" and e["details"].get("action") == "start"]
        if started:
            return started[-1]["ts"]
        if self.closed:
            return None
        opener = getattr(self.target, "open_sleep", None)
        return opener() if opener else None

    def own_last(self):
        """The newest real entry the Echo wrote in the last hours, or None."""
        since = (self.now() - datetime.timedelta(hours=OWN_HOURS)).isoformat(timespec="seconds")
        mine = [e for e in self.target.entries(None, since, 200)
                if ECHO_TAG in (e.get("tags") or []) or (e.get("kind"), e.get("id")) in self.own]
        return mine[-1] if mine else None

    def find(self, entry_id=None, kind=None, at=None, last=None):
        """Only the Echo's own entries can be named: this turn's, then the last one it wrote."""
        own = self.staged()
        last_real = self.own_last()
        if last_real is not None and (last_real["kind"], last_real["id"]) not in self.removed:
            own = [self.changed.get((last_real["kind"], last_real["id"]), last_real)] + own
        if entry_id is not None:
            own = [e for e in own if str(e.get("id")) == str(entry_id)]
        if kind:
            own = [e for e in own if e["kind"] == kind]
        if at:
            wanted = str(at).strip().zfill(5)[-5:]
            own = [e for e in own if wanted in (str(e["ts"])[11:16], str(e["details"].get("start") or "")[11:16])]
        if not own:
            raise ValueError(NOT_OWN)
        return copy.deepcopy(own[-1])

    # -- writing: kept aside until the yes

    def add(self, kind, details, ts=None):
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown log kind {kind}, expected one of {', '.join(LOG_KINDS)}")
        details = dict(details or {})
        self.check_bounds(kind, details, ts)
        entry = self.preview(kind, details, ts)
        self.ops.append({"op": "add", "kind": kind, "details": details, "ts": ts, "entry": entry})
        return copy.deepcopy(entry)

    def preview(self, kind, details, ts):
        """The entry as the real log would store it, with a staged id."""
        now = self.now()
        moment = parse_time(ts or details.get("end") or details.get("time")) if (ts or details.get("end") or details.get("time")) else now
        moment = min(moment, now)
        self.n += 1
        entry = {"id": f"echo-{self.n}", "kind": kind, "ts": moment.isoformat(timespec="seconds"), "staged": True}
        if kind == "feeding":
            method = details.get("method") or "bottle"
            length = float(details.get("duration_min") or DEFAULT_FEED_MINUTES)
            entry["details"] = {"amount_ml": details.get("amount_ml"), "method": method,
                                "type": details.get("type") or ("breast milk" if "breast" in method else "formula"),
                                "start": (moment - datetime.timedelta(minutes=length)).isoformat(timespec="seconds"),
                                "duration_min": details.get("duration_min")}
        elif kind == "diaper":
            wet, solid = bool(details.get("wet")), bool(details.get("solid"))
            entry["details"] = {"wet": wet or not solid, "solid": solid}
        elif kind == "sleep":
            action = details.get("action")
            if details.get("start") and details.get("end"):
                start = min(parse_time(details["start"]), now)
                entry["details"] = {"start": start.isoformat(timespec="seconds"),
                                    "duration_min": round((moment - start).total_seconds() / 60)}
            elif action == "end" or (details.get("end") and not details.get("start")):
                opened = self.open_sleep()
                if not opened:
                    raise ValueError("no sleep was started, tell me when she fell asleep")
                self.closed = True
                for op in list(self.ops):
                    if op["op"] == "add" and op["kind"] == "sleep" and op["entry"]["details"].get("action") == "start":
                        op["entry"]["details"]["action"] = "started"  # closed in this same turn
                entry["details"] = {"start": opened, "duration_min": round((moment - parse_time(opened)).total_seconds() / 60),
                                    "action": "end"}
            else:
                entry["details"] = {"action": "start"}
        else:
            text = str(details.get("text") or details.get("note") or "")
            if kind == "bath" and not text.lower().startswith("bath"):
                text = f"Bath. {text}".strip()
            entry["details"] = {"text": text or "Note"}
        return entry

    def update(self, entry_id, details=None, ts=None):
        entry = self.find(entry_id)
        details = dict(details or {})
        self.check_bounds(entry["kind"], {k: v for k, v in details.items() if k in ("amount_ml", "duration_min")}, ts)
        if entry.get("staged"):
            op = next(op for op in self.ops if op["op"] == "add" and op["entry"]["id"] == entry["id"])
            op["details"] = {**op["details"], **{k: v for k, v in details.items() if v is not None}}
            op["ts"] = ts or op["ts"]
            fresh = self.preview(op["kind"], op["details"], op["ts"])
            fresh["id"] = entry["id"]
            op["entry"] = fresh
            return {"before": entry, "after": copy.deepcopy(fresh)}
        after = patched(entry, details, ts)
        ref = (entry["kind"], entry["id"])
        self.ops.append({"op": "update", "ref": ref, "details": details, "ts": ts, "before": entry, "after": after})
        self.changed[ref] = after
        return {"before": entry, "after": copy.deepcopy(after)}

    def delete(self, entry_id):
        entry = self.find(entry_id)
        if entry.get("staged"):
            self.ops = [op for op in self.ops if not (op["op"] == "add" and op["entry"]["id"] == entry["id"])]
            return {"deleted": entry}
        ref = (entry["kind"], entry["id"])
        self.ops = [op for op in self.ops if op.get("ref") != ref]
        self.changed.pop(ref, None)
        self.ops.append({"op": "delete", "ref": ref, "before": entry})
        self.removed.add(ref)
        return {"deleted": entry}

    def commit(self):
        """Writes the staged operations to the real log, in order. Returns (done, error): done holds (op, result)."""
        done, error = [], None
        for op in self.ops:
            try:
                if op["op"] == "add":
                    stored = self.target.add(op["kind"], op["details"], op["ts"])
                    if isinstance(stored, dict) and stored.get("id") is not None:
                        self.own.append((stored.get("kind"), stored.get("id")))
                    done.append((op, stored))
                elif op["op"] == "update":
                    done.append((op, self.target.patch(op["before"], op["details"], op["ts"])))
                else:
                    done.append((op, self.target.remove(op["before"])))
            except (TypeError, ValueError, KeyError, RuntimeError, AttributeError) as failure:
                error = failure
                break
        self.reset()
        return done, error


class HeldMemory:
    """The family's conversation memory, with this turn's lines held back until the yes, so a later turn never reads
    "Anoté" for something that was not written."""

    def __init__(self, memory):
        self.memory, self.held = memory, []
        self.lock = getattr(memory, "lock", threading.Lock())

    def add_message(self, channel, role, text, ts=None):
        self.held.append((channel, role, text, ts))

    def recent_messages(self, limit=20):
        held = [{"ts": ts.isoformat(timespec="seconds") if isinstance(ts, datetime.datetime) else str(ts or ""),
                 "channel": c, "role": r, "text": t} for c, r, t, ts in self.held]
        return (self.memory.recent_messages(limit) + held)[-limit:]

    def facts(self):
        return self.memory.facts()

    def remember(self, key, value):
        raise ValueError("the Echo does not remember facts")

    def flush(self, answer=None):
        """Keeps the held lines. answer replaces what the agent said, for a write that was confirmed or dropped."""
        held, self.held = self.held, []
        for channel, role, text, ts in held:
            if role == "assistant" and answer is not None:
                continue
            self.memory.add_message(channel, role, text, ts=ts)
        if answer is not None and held:
            self.memory.add_message(CHANNEL, "assistant", answer, ts=held[-1][3])

    def close(self):
        pass


def _ml(value):
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return None


def _hm(ts):
    moment = parse_time(ts)
    return moment.hour, moment.minute


def thing(entry, lang, now, name):
    """An entry as a noun phrase with its time: "la mamadera de las 7:50", "the 7:50 bottle"."""
    kind, d = entry["kind"], entry.get("details") or {}
    nouns = {"es": {"bottle": "la mamadera", "breast": "el pecho", "diaper": "el pañal", "sleep": "el sueño",
                    "bath": "el baño", "note": "la nota"},
             "en": {"bottle": "bottle", "breast": "breast feed", "diaper": "diaper", "sleep": "sleep", "bath": "bath",
                    "note": "note"}}[lang if lang in ("es", "en") else "en"]
    key = ("breast" if "breast" in str(d.get("method") or "") else "bottle") if kind == "feeding" else kind
    moment = parse_time(entry["ts"])
    said = when(moment, now, lang)
    if lang == "es":
        return f"{nouns[key]} de {said.replace('a las ', 'las ', 1).replace('a la ', 'la ', 1)}"
    return f"the {nouns[key]} {said}"


def what_added(op, lang, now, name):
    """What an add writes, as the parent said it: "90 ml de mamadera a las 7:50", "a dirty diaper at 7:50"."""
    kind, d, entry = op["kind"], op["details"], op["entry"]
    es = lang == "es"
    at = when(parse_time(entry["ts"]), now, lang)
    baby = name or ("el bebé" if es else "the baby")
    if kind == "feeding":
        method = str(d.get("method") or "bottle")
        if "breast" in method:
            side = {"left breast": (" izquierdo", "left breast feed"), "right breast": (" derecho", "right breast feed"),
                    "both breasts": (" de los dos lados", "breast feed on both sides")}.get(method, ("", "breast feed"))
            minutes = _ml(d.get("duration_min"))
            if es:
                return f"{minutes + ' minutos de ' if minutes else ''}pecho{side[0]} {at}"
            return f"a {minutes + ' minute ' if minutes else ''}{side[1]} {at}"
        ml = _ml(d.get("amount_ml"))
        milk = {"formula": (" de fórmula", " of formula"), "breast milk": (" de leche materna", " of breast milk")}.get(d.get("type"))
        if es:
            return f"{ml + ' ml de mamadera' if ml else 'una mamadera'}{milk[0] if milk else ''} {at}"
        return f"{'a ' + ml + ' ml bottle' if ml else 'a bottle'}{milk[1] if milk else ''} {at}"
    if kind == "diaper":
        wet, solid = bool(entry["details"].get("wet")), bool(entry["details"].get("solid"))
        word = ("mojado y sucio", "wet and dirty") if wet and solid else (("sucio", "dirty") if solid else ("mojado", "wet"))
        return f"un pañal {word[0]} {at}" if es else f"a {word[1]} diaper {at}"
    if kind == "sleep":
        sd = entry["details"]
        if sd.get("action") in ("start", "started"):
            return f"que {baby} se durmió {at}" if es else f"that {baby} fell asleep {at}"
        if sd.get("action") == "end":
            return f"que {baby} se despertó {at}" if es else f"that {baby} woke up {at}"
        start, end = _hm(sd["start"]), _hm(entry["ts"])
        if es:
            return f"que {baby} durmió de {at_words(*start, 'es')[2:]} a {at_words(*end, 'es')[2:]}"
        return f"a sleep from {at_words(*start, 'en')[3:]} to {at_words(*end, 'en')[3:]}"
    if kind == "bath":
        return f"un baño {at}" if es else f"a bath {at}"
    text = str(entry["details"].get("text") or "")[:120]
    return f"la nota {text}" if es else f"the note {text}"


def what_changed(op, lang, now, name):
    before, after = op["before"], op["after"]
    es = lang == "es"
    a, b = before.get("details") or {}, after.get("details") or {}
    parts = []
    if _ml(a.get("amount_ml")) != _ml(b.get("amount_ml")) and _ml(b.get("amount_ml")):
        parts.append(f"{_ml(b['amount_ml'])} ml")
    if str(before.get("ts"))[11:16] != str(after.get("ts"))[11:16]:
        parts.append(at_words(*_hm(after["ts"]), lang)[(2 if es else 3):])
    if before["kind"] == "feeding" and a.get("method") != b.get("method") and b.get("method"):
        parts.append(("pecho" if "breast" in str(b["method"]) else "mamadera") if es else
                     ("breast feed" if "breast" in str(b["method"]) else "bottle"))
    if before["kind"] == "diaper" and (bool(a.get("wet")), bool(a.get("solid"))) != (bool(b.get("wet")), bool(b.get("solid"))):
        parts.append(("mojado y sucio" if b.get("wet") and b.get("solid") else ("sucio" if b.get("solid") else "mojado"))
                     if es else ("wet and dirty" if b.get("wet") and b.get("solid") else ("dirty" if b.get("solid") else "wet")))
    if before["kind"] in ("note", "bath") and a.get("text") != b.get("text"):
        parts.append(str(b.get("text") or "")[:120])
    joined = lines(lang)["and"].join(parts) or ("lo mismo" if es else "the same")
    return f"{thing(before, lang, now, name)} a {joined}" if es else f"{thing(before, lang, now, name)} to {joined}"


def phrase(op, lang, now, name):
    if op["op"] == "add":
        return what_added(op, lang, now, name)
    if op["op"] == "update":
        return what_changed(op, lang, now, name)
    return thing(op["before"], lang, now, name)


def sentence(ops, lang, now, name, past=False):
    """"Anoto 90 ml de mamadera a las 7:50 y cambio ...", or in the past "anoté ..."."""
    words = lines(lang)
    parts = []
    for i, op in enumerate(ops):
        verb = words[op["op"]][1 if past else 0]
        parts.append(f"{verb if i == 0 and not past else verb.lower()} {phrase(op, lang, now, name)}")
    return words["and"].join(parts)


def question(ops, lang, now, name):
    """The one spoken confirmation before a write: "¿Anoto 90 ml de mamadera a las 7:50? Decí sí."."""
    said = sentence(ops, lang, now, name)
    return (f"¿{said}?" if lang == "es" else f"{said}?") + lines(lang)["yes"]


class EchoWriter:
    """The Echo's own agent: the family agent's loop and guards with the log tools alone, writing after a yes."""

    def __init__(self, agent, config, clock=time.monotonic):
        self.main, self.clock = agent, clock
        self.log = StagedLog(target_for(agent.baby_log))
        self.memory = HeldMemory(agent.memory)
        self.bus = Bus()
        self.replies = []
        self.bus.subscribe(self.forward)
        self.bus.subscribe(self.replies.append, ["reply"])
        tools = core_tools(self.memory, self.log, TOOLS, remember_keys=())
        echo = Agent(self.bus, self.memory, self.log, tools, agent.brain, max_steps=getattr(agent, "max_steps", 6))
        for name in ("people", "log_mode", "health_gate", "prompt_notes", "baby_name", "birth_date", "danger"):
            if hasattr(agent, name):
                setattr(echo, name, getattr(agent, name))
        self.name = (config.get("baby") or {}).get("name")
        self.agent = echo
        self.proposal = None

    def forward(self, event):
        """What the Echo's agent did goes to the family's event log under its own kind, so nothing else reacts to it."""
        if event["kind"] in ("reply", "message"):
            return
        fields = {k: v for k, v in event.items() if k not in ("kind", "t", "ts", "unix")}
        self.main.bus.publish("echo_log_event", event=event["kind"], **fields)

    def now(self):
        return self.agent.now()

    def turn(self, words, lang):
        """The parent's words through the agent, nothing written. Returns the reply, and a confirm id when it would write."""
        self.drop()
        agent = self.agent
        agent.brain = self.main.brain
        event = {"kind": "message", "channel": CHANNEL, "text": words, "person": PERSON, "chat_id": CHAT_ID,
                 "source": "echo"}
        self.replies.clear()
        agent.current_event, said = event, agent.said
        try:
            agent.handle(event)
        except brain_mod.BrainError as error:
            self.bus.publish("agent_error", error=str(error)[:300])
            agent.say(CHANNEL, "I could not think that through just now. Please try again.")
        finally:
            agent.current_event = None
            agent.turn(event, answered=agent.said > said)
        replies = list(self.replies)
        text = " ".join(r["text"] for r in replies).strip()
        if not self.log.ops:
            self.memory.flush()
            return {"reply": text or lines(lang)["ok"]}
        ask = question(self.log.ops, lang, self.now(), self.name)
        safety = self.safety_line(words, replies, lang)
        self.proposal = {"id": secrets.token_urlsafe(9), "at": self.clock(), "lang": lang}
        self.main.bus.publish("echo_log", status="asked", ops=[op["op"] for op in self.log.ops],
                              kinds=[op.get("kind") or op["before"]["kind"] for op in self.log.ops])
        return {"reply": (safety + " " if safety else "") + ask,
                "confirm": {"id": self.proposal["id"], "expires_s": PROPOSAL_S}}

    def safety_line(self, words, replies, lang):
        """A red flag line is said before the question, never left out for it."""
        for reply in replies:
            flag = str(reply.get("flag") or "")
            if flag.startswith("urgent_") and flag[7:] in rules.URGENT_REPLY:
                return rules.URGENT_REPLY[flag[7:]][lang if lang in ("es", "en") else "en"]
            if flag == "emergency":
                return rules.EMERGENCY_REPLY[lang if lang in ("es", "en") else "en"]
        if rules.names_red_flag(words) or any(rules.carries_safety_line(r["text"]) for r in replies):
            return self.agent.safety_line(words)
        return ""

    def live(self, proposal_id):
        proposal = self.proposal
        return (proposal is not None and proposal_id and secrets.compare_digest(str(proposal_id), proposal["id"])
                and self.clock() - proposal["at"] <= PROPOSAL_S)

    def confirm(self, proposal_id, lang):
        """The yes: exactly what was asked is written, tagged "echo". Returns the reply and the entries written."""
        if not self.live(proposal_id):
            self.main.bus.publish("echo_log", status="nothing_to_confirm")
            self.drop()
            return {"reply": lines(lang)["nothing"], "written": []}
        lang = self.proposal["lang"]
        self.proposal = None
        ops = list(self.log.ops)
        now = self.now()
        done, error = self.log.commit()
        written = []
        for op, result in done:
            if op["op"] == "add" and isinstance(result, dict):
                written.append({"op": "add", "kind": result.get("kind"), "id": result.get("id"), "timer": result.get("timer")})
            elif isinstance(result, dict):
                entry = result.get("after") or result.get("deleted") or {}
                written.append({"op": op["op"], "kind": entry.get("kind"), "id": entry.get("id")})
        words = lines(lang)
        if error is None:
            reply = words["done"].format(what=sentence(ops, lang, now, self.name, past=True))
        elif done:
            reply = words["partly"].format(what=sentence([op for op, _ in done], lang, now, self.name, past=True))
        else:
            reply = words["failed"]
        self.memory.flush(reply)
        self.main.bus.publish("echo_log", status="written" if error is None else "write_failed", written=written,
                              error=str(error)[:200] if error else None)
        return {"reply": reply, "written": written}

    def cancel(self, lang):
        had = self.proposal is not None
        self.drop()
        return {"reply": lines(lang)["cancelled" if had else "nothing"]}

    def drop(self):
        """An unconfirmed write is forgotten, and the memory says so."""
        if self.proposal is None and not self.log.ops:
            return
        lang = (self.proposal or {}).get("lang", "en")
        self.proposal = None
        self.log.reset()
        self.memory.flush(lines(lang)["not_written"])
        self.main.bus.publish("echo_log", status="dropped")
