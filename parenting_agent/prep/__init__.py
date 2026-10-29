"""Before he arrives: the agent the family uses every day before Theo is born.

The Prep plug-in gives the agent prep lists (nursery, hospital bag, car seat, white noise machine), appointments, a
countdown to the due date and one short morning nudge to Gonza. Everything is logistics: what to buy, build, place,
pack and when. It never gives medical advice, and an appointment keeps only what, when, where and what to bring.

Lists and appointments live in the agent's own memory file (data/memory.sqlite, tables prep_items and
prep_appointments). Every change is also a "prep" event on the bus with the person who made it, so it lands in
data/events.jsonl next to the "turn" events the KR scorer reads.

The lists start from lists.py. The parents tick, untick and add items by message. Putting a list on the Home
Assistant to-do list always waits for the parent's yes and is a dry run while house.live is false.

The morning nudge goes only to the first chat id in TELEGRAM_CHAT_ID (Gonza), once a day, between nudge.at and
nudge.until local time. The day it was sent is kept in data/prep-nudge.json, so a restart never sends it twice.

Config block "prep": {"due_date": "2026-12-15", "due_date_estimate": true,
                      "nudge": {"enabled": true, "at": "08:00", "until": "11:00", "channel": "telegram",
                                "chat_ids_env": "TELEGRAM_CHAT_ID"}}
"""
import datetime
import json
import os
import threading
import urllib.error
from pathlib import Path

from ..agent import rules
from ..agent.plugins import Plugin
from ..agent.tools import Tool, schema
from ..house import HomeAssistant, never_reason
from . import lists as lists_mod
from . import nursery

SCHEMA = """
create table if not exists prep_items (id integer primary key, list text, item_id text, text text, by text,
  before_due_days integer, position integer, done integer default 0, done_by text, done_ts text, added_by text, ts text,
  unique (list, item_id));
create table if not exists prep_appointments (id integer primary key, title text, starts_at text, place text, bring text,
  added_by text, ts text, cancelled integer default 0);
"""
DEFAULTS = {"due_date": "2026-12-15", "due_date_estimate": True, "ha_todo": "todo.family_to_do_list",
            "nudge": {"enabled": True, "at": "08:00", "until": "11:00", "channel": "telegram",
                      "chat_ids_env": "TELEGRAM_CHAT_ID", "check_every_s": 30}}
ASK_FIRST = ("prep_to_home_assistant",)
PROMPT_FACT = ("Theo is not born yet, the family is getting ready. Prep, purchases, the nursery, the hospital bag, the car "
               "seat, the white noise machine and appointments never go in the baby log: use the prep tools "
               "(prep_next, prep_list, prep_check, prep_add, add_appointment, appointments, nursery_plan). Appointments "
               "are logistics only: never comment on anything medical.")
LOGISTICS_ONLY = "I keep only the logistics of an appointment: what, when, where and what to bring. Nothing medical."
NO_SECRETS = ("a code, a PIN, a password or a long number is never kept in a prep list or an appointment, it would go out "
              "in the morning nudge. Nothing was kept")
NUDGE_FAILED = ("The morning prep message failed today ({error}). Ask me what is next and I will answer from the lists.")


def parse_day(value):
    return datetime.date.fromisoformat(str(value)[:10])


class Prep(Plugin):
    name = "prep"
    kind = "skill"

    def __init__(self, agent, config, client=None, clock=None):
        super().__init__(agent, config)
        raw = config.get("prep") or {}
        self.cfg = {**DEFAULTS, **raw, "nudge": {**DEFAULTS["nudge"], **(raw.get("nudge") or {})}}
        self.house_live = (config.get("house") or {}).get("live") is True
        self.client = client
        self.clock = clock
        self.marker = Path(config.get("data_dir", "data")) / "prep-nudge.json"
        self.stopped = threading.Event()
        self.thread = None
        self.db, self.lock = agent.memory.db, agent.memory.lock
        with self.lock:
            self.db.executescript(SCHEMA)
        self.seed()
        # The instruction is a standing rule of the agent, never a fact: remember could overwrite a fact (round 2).
        if PROMPT_FACT not in getattr(agent, "prompt_notes", []):
            agent.prompt_notes = [*getattr(agent, "prompt_notes", []), PROMPT_FACT]
        with self.lock:
            self.db.execute("delete from facts where key = 'before_he_arrives'")
            self.db.commit()
        self.failed_day = None
        for name in ASK_FIRST:
            if name in agent.tools.allowed:
                agent.tools.allowed.discard(name)
                agent.bus.publish("prep_warning", error=f"{name} removed from the allowed list, it always waits for a yes")
        lists = {"type": "string", "enum": list(lists_mod.ORDER)}
        for tool in (
            Tool("prep_next", "What is next before Theo arrives: the countdown to the due date, the next appointment and the "
                 "next open prep items. Use it for 'what is next', 'what do we still need', 'how many days left'.",
                 schema({}), self.next),
            Tool("prep_list", "One prep list with every item and whether it is done: nursery, hospital_bag, car_seat, "
                 "white_noise. Without a list, the count of open items in each.", schema({"list": lists}), self.list),
            Tool("prep_check", "Tick a prep item as done, or untick it with done false. item is the item id or a few words "
                 "of its text, for example 'crib' or 'amplifier'.",
                 schema({"list": lists, "item": {"type": "string"}, "done": {"type": "boolean"}}, ["item"]), self.check),
            Tool("prep_add", "Add an item to a prep list, with an optional by date (YYYY-MM-DD).",
                 schema({"list": lists, "text": {"type": "string"}, "by": {"type": "string"}}, ["list", "text"]), self.add),
            Tool("add_appointment", "Keep an appointment before the birth: title, when (ISO local time), place and what to "
                 "bring. Logistics only, never anything medical.",
                 schema({"title": {"type": "string"}, "when": {"type": "string"}, "place": {"type": "string"},
                         "bring": {"type": "string"}}, ["title", "when"]), self.add_appointment),
            Tool("appointments", "The upcoming appointments, soonest first.", schema({}), self.appointments),
            Tool("cancel_appointment", "Remove an appointment by its id from appointments.",
                 schema({"id": {"type": "integer"}}, ["id"]), self.cancel_appointment),
            Tool("set_due_date", "Set Theo's due date when a parent says it (YYYY-MM-DD).",
                 schema({"date": {"type": "string"}}, ["date"]), self.set_due_date),
            Tool("nursery_plan", "The nursery plan from the home twin: room size, the two layouts and their placement checks "
                 "(walkway, door swing, shelf over the crib, white noise distance).",
                 schema({"layout": {"type": "string", "enum": sorted(nursery.LAYOUTS)}}), self.nursery_plan),
            Tool("prep_to_home_assistant", "Copy the open items of a prep list to the family to-do list in Home Assistant. "
                 "Always waits for the parent's yes.", schema({"list": lists}, ["list"]), self.to_home_assistant),
        ):
            agent.tools.add(tool)

    # Time and who is acting

    def now(self):
        return self.clock() if self.clock else self.agent.now()

    def person(self):
        event = getattr(self.agent, "current_event", None) or {}
        return event.get("person")

    def publish(self, action, **fields):
        event = getattr(self.agent, "current_event", None) or {}
        self.agent.bus.publish("prep", action=action, person=event.get("person"), channel=event.get("channel"), **fields)

    # Lists

    def seed(self):
        stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        with self.lock:
            for item in lists_mod.seed_items():
                self.db.execute(
                    "insert or ignore into prep_items (list, item_id, text, by, before_due_days, position, done, done_by, "
                    "done_ts, added_by, ts) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'plan', ?)",
                    (item["list"], item["item_id"], item["text"], item["by"], item["before_due_days"], item["position"],
                     1 if item["in_hand"] else 0, "in hand" if item["in_hand"] else None,
                     stamp if item["in_hand"] else None, stamp))
            self.db.commit()

    def rows(self, list_name=None):
        query = "select list, item_id, text, by, before_due_days, position, done, done_by, done_ts from prep_items"
        args = ()
        if list_name:
            query, args = query + " where list = ?", (list_name,)
        with self.lock:
            found = self.db.execute(query, args).fetchall()
        keys = ("list", "item_id", "text", "by", "before_due_days", "position", "done", "done_by", "done_ts")
        return [dict(zip(keys, row)) for row in found]

    def due_date(self):
        """The due date a parent set, or the config date. A fact that is not a date (a "mid December" kept before
        round 2) never stops the countdown or the nudge: the config date stands and the bad fact is reported."""
        fact = self.agent.memory.facts().get("due_date")
        if fact:
            try:
                return parse_day(fact["value"]), False
            except ValueError:
                self.agent.bus.publish("prep_warning", error="the due_date fact is not a date, the config date is used")
        return parse_day(self.cfg["due_date"]), bool(self.cfg["due_date_estimate"])

    def by_date(self, item):
        if item["by"]:
            return parse_day(item["by"])
        if item["before_due_days"] is not None:
            return self.due_date()[0] - datetime.timedelta(days=int(item["before_due_days"]))
        return None

    def open_items(self):
        order = {name: i for i, name in enumerate(lists_mod.ORDER)}
        far = datetime.date.max
        items = [i for i in self.rows() if not i["done"]]
        items.sort(key=lambda i: (self.by_date(i) or far, order.get(i["list"], 99), i["position"]))
        return items

    def resolve(self, item, list_name=None):
        words = str(item).lower().strip()
        candidates = self.rows(list_name)
        exact = [i for i in candidates if i["item_id"] == words.replace(" ", "_")]
        if exact:
            return exact[0]
        found = [i for i in candidates if words and words in i["text"].lower()]
        if len(found) == 1:
            return found[0]
        if not found:
            raise ValueError(f"no prep item matches {item!r}" + (f" in {list_name}" if list_name else ""))
        raise ValueError(f"{item!r} matches {len(found)} items: " + "; ".join(f"{i['list']}/{i['item_id']}" for i in found[:5]))

    def list(self, list=None):
        if list is None:
            out = {}
            for name in lists_mod.ORDER:
                items = self.rows(name)
                out[name] = {"title": lists_mod.LISTS[name]["title"], "open": sum(1 for i in items if not i["done"]),
                             "done": sum(1 for i in items if i["done"])}
            return out
        if list not in lists_mod.LISTS:
            raise ValueError(f"unknown list {list!r}, expected one of {', '.join(lists_mod.ORDER)}")
        items = sorted(self.rows(list), key=lambda i: i["position"])
        return {"title": lists_mod.LISTS[list]["title"], "source": lists_mod.LISTS[list]["source"],
                "items": [{"id": i["item_id"], "text": i["text"], "done": bool(i["done"]),
                           "by": (self.by_date(i).isoformat() if self.by_date(i) else None)} for i in items]}

    def check(self, item, list=None, done=True):
        found = self.resolve(item, list)
        if bool(found["done"]) == bool(done):
            return f"already {'done' if done else 'open'}: {found['text']}"
        stamp = self.now().isoformat(timespec="seconds")
        with self.lock:
            self.db.execute("update prep_items set done = ?, done_by = ?, done_ts = ? where list = ? and item_id = ?",
                            (1 if done else 0, self.person() if done else None, stamp if done else None,
                             found["list"], found["item_id"]))
            self.db.commit()
        self.publish("check" if done else "uncheck", list=found["list"], item_id=found["item_id"])
        left = sum(1 for i in self.rows(found["list"]) if not i["done"])
        return f"{'done' if done else 'open again'}: {found['text']}. {left} open in {lists_mod.LISTS[found['list']]['title']}."

    def add(self, list, text, by=None):
        if list not in lists_mod.LISTS:
            raise ValueError(f"unknown list {list!r}, expected one of {', '.join(lists_mod.ORDER)}")
        if rules.holds_code(text):
            raise ValueError(NO_SECRETS)
        if by:
            by = parse_day(by).isoformat()
        stamp = self.now().isoformat(timespec="seconds")
        with self.lock:
            position = self.db.execute("select coalesce(max(position), -1) + 1 from prep_items where list = ?", (list,)).fetchone()[0]
            item_id = f"added_{position}"
            self.db.execute("insert into prep_items (list, item_id, text, by, position, added_by, ts) values (?, ?, ?, ?, ?, ?, ?)",
                            (list, item_id, str(text)[:200], by, position, self.person(), stamp))
            self.db.commit()
        self.publish("add", list=list, item_id=item_id)
        return f"added to {lists_mod.LISTS[list]['title']}: {text}" + (f", by {by}" if by else "")

    # Appointments and the countdown

    def add_appointment(self, title, when, place=None, bring=None):
        text = " ".join(str(part) for part in (title, place, bring) if part)
        if rules.is_medical(text) or rules.is_medical_es(text):
            raise ValueError(LOGISTICS_ONLY)
        if rules.holds_code(title) or rules.holds_code(bring) or rules.holds_code(place, numbers=False):
            raise ValueError(NO_SECRETS)
        moment = datetime.datetime.fromisoformat(str(when))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=self.now().tzinfo)
        stamp = self.now().isoformat(timespec="seconds")
        with self.lock:
            cursor = self.db.execute(
                "insert into prep_appointments (title, starts_at, place, bring, added_by, ts) values (?, ?, ?, ?, ?, ?)",
                (str(title)[:120], moment.isoformat(timespec="minutes"), (place or "")[:120] or None,
                 (bring or "")[:200] or None, self.person(), stamp))
            self.db.commit()
        self.publish("appointment", appointment_id=cursor.lastrowid)
        return f"kept: {title}, {moment.strftime('%a %b %d %H:%M')}" + (f", {place}" if place else "")

    def upcoming(self):
        now = self.now()
        with self.lock:
            found = self.db.execute("select id, title, starts_at, place, bring from prep_appointments where cancelled = 0").fetchall()
        items = [{"id": i, "title": t, "when": s, "place": p, "bring": b} for i, t, s, p, b in found
                 if datetime.datetime.fromisoformat(s) >= now - datetime.timedelta(hours=1)]
        return sorted(items, key=lambda a: a["when"])

    def appointments(self):
        return self.upcoming() or "no appointments kept yet"

    def cancel_appointment(self, id):
        with self.lock:
            changed = self.db.execute("update prep_appointments set cancelled = 1 where id = ? and cancelled = 0", (int(id),)).rowcount
            self.db.commit()
        if not changed:
            raise ValueError(f"no appointment with id {id}")
        self.publish("cancel_appointment", appointment_id=int(id))
        return f"removed appointment {id}"

    def set_due_date(self, date):
        day = parse_day(date)
        self.agent.memory.remember("due_date", day.isoformat())
        self.publish("due_date")
        return f"due date set to {day.strftime('%b %d %Y')}"

    def countdown(self):
        day, estimate = self.due_date()
        left = (day - self.now().date()).days
        when = day.strftime("%b %d").replace(" 0", " ")
        if left < 0:
            return f"the due date, {when}, was {-left} days ago"
        return f"{'about ' if estimate else ''}{left} days to the due date, {when}{' (an estimate)' if estimate else ''}"

    def next(self, items=3):
        today = self.now().date()
        open_items = self.open_items()
        soon = [a for a in self.upcoming() if datetime.datetime.fromisoformat(a["when"]).date() <= today + datetime.timedelta(days=7)]
        out = {"countdown": self.countdown(), "next_appointment": soon[0] if soon else None, "items": []}
        for item in open_items[:items]:
            by = self.by_date(item)
            out["items"].append({"list": item["list"], "id": item["item_id"], "text": item["text"],
                                 "by": by.isoformat() if by else None, "late": bool(by and by < today)})
        out["open_total"] = len(open_items)
        return out

    def nursery_plan(self, layout=None):
        return nursery.summary(layout)

    # Home Assistant, only with a yes

    def to_home_assistant(self, list):
        entity = self.cfg["ha_todo"]
        items = [i for i in self.rows(list) if not i["done"]]
        held = [i for i in items if rules.holds_code(i["text"])]
        items = [i for i in items if i not in held]
        reason = never_reason(entity)
        if reason:
            return f"refused: {reason}"
        client = self.client
        if client is None and self.house_live:
            token = os.environ.get((self.config.get("house") or {}).get("ha_token_env", "HA_MCP_TOKEN"))
            url = os.environ.get("HA_URL") or (self.config.get("house") or {}).get("ha_url")
            client = HomeAssistant(url, token) if token and url else None
        if not self.house_live or client is None:
            why = "house.live is off" if not self.house_live else "no Home Assistant token"
            for item in items:
                self.agent.bus.publish("house_call", action="prep_to_home_assistant", service="todo.add_item", entity=entity,
                                       live=False, status="dry", reason=why, data={"item": item["text"][:120]})
            return (f"dry run ({why}): {len(items)} items would go on the to-do list, nothing changed in the house"
                    + self.held_note(held))
        added = 0
        for item in items:
            try:
                client.service("todo.add_item", entity, {"item": item["text"][:120]})
                added += 1
                self.agent.bus.publish("house_call", action="prep_to_home_assistant", service="todo.add_item",
                                       entity=entity, live=True, status="ran")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                self.agent.bus.publish("house_call", action="prep_to_home_assistant", service="todo.add_item",
                                       entity=entity, live=True, status="error", error=str(error)[:200])
                break
        return f"added {added} of {len(items)} items to the to-do list" + self.held_note(held)

    @staticmethod
    def held_note(held):
        return f", {len(held)} item(s) holding a code left out" if held else ""

    # The morning nudge

    def nudge_text(self):
        nxt = self.next()
        lines = [f"Good morning. {nxt['countdown'][0].upper()}{nxt['countdown'][1:]}."]
        appointment = nxt["next_appointment"]
        if appointment:
            moment = datetime.datetime.fromisoformat(appointment["when"])
            lines.append(f"Next appointment: {appointment['title']}, {moment.strftime('%a %b %d %H:%M')}"
                         + (f", {appointment['place']}" if appointment.get("place") else "") + ".")
        if nxt["items"]:
            lines.append("Next up:")
            for item in nxt["items"]:
                if rules.holds_code(item["text"]):
                    # An item kept before round 2 can hold a code: the push never carries it.
                    lines.append("- an item that holds a code, ask me for it")
                    continue
                lines.append(f"- {item['text'].split(': http')[0]}" + (" (late)" if item["late"] else ""))
        lines.append("Tell me when one is done, or ask what is next.")
        return "\n".join(lines)

    def gonza_chat(self):
        raw = os.environ.get(self.cfg["nudge"]["chat_ids_env"], "")
        ids = [c.strip() for c in raw.split(",") if c.strip()]
        return ids[0] if ids else None

    def last_nudge(self):
        try:
            return json.loads(self.marker.read_text()).get("date")
        except (OSError, ValueError):
            return None

    def nudge_due(self, now):
        settings = self.cfg["nudge"]
        if not settings["enabled"]:
            return False
        start, end = (datetime.time.fromisoformat(settings[k]) for k in ("at", "until"))
        return start <= now.time() < end and self.last_nudge() != now.date().isoformat()

    def send_nudge(self, reason="scheduled"):
        """Sends the nudge to Gonza's chat and records the day. Returns the text, or None when there is no chat."""
        now = self.now()
        chat = self.gonza_chat()
        if chat is None:
            self.agent.bus.publish("nudge_skipped", reason=f"no chat id in {self.cfg['nudge']['chat_ids_env']}")
            return None
        text = self.nudge_text()
        channel = self.cfg["nudge"]["channel"]
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(json.dumps({"date": now.date().isoformat(), "ts": now.isoformat(timespec="seconds"), "reason": reason}))
        self.agent.memory.add_message(channel, "assistant", text, ts=now)
        self.agent.bus.publish("nudge", person="gonza", channel=channel, reason=reason, items=len(self.next()["items"]))
        self.agent.bus.publish("reply", channel=channel, chat_id=chat, text=text)
        return text

    def nudge_failed(self, error):
        """A nudge that fails is never silent: a prep_error event, a line in the container log and, once a day, a
        short message to Gonza's chat that says it failed."""
        self.agent.bus.publish("prep_error", error=str(error)[:200])
        print(f"prep: morning nudge failed, {type(error).__name__}", flush=True)
        today = self.now().date().isoformat()
        chat = self.gonza_chat()
        if chat is None or self.failed_day == today:
            return
        self.failed_day = today
        self.agent.bus.publish("reply", channel=self.cfg["nudge"]["channel"], chat_id=chat,
                               text=NUDGE_FAILED.format(error=type(error).__name__))

    def tick(self):
        now = self.now()
        if self.nudge_due(now):
            self.send_nudge()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 a failed nudge is reported, the agent keeps running
                self.nudge_failed(error)
            self.stopped.wait(self.cfg["nudge"]["check_every_s"])

    def start(self):
        self.thread = threading.Thread(target=self.run, name="prep", daemon=True)
        self.thread.start()
        self.agent.bus.publish("prep_started", open_items=len(self.open_items()), nudge_at=self.cfg["nudge"]["at"],
                               nudge_chat=self.gonza_chat() is not None)

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)
