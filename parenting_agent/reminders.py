"""Reminders a parent asks for: "recordame en 20 minutos sacar la ropa" comes back to the parent who asked.

The tool remind_me(text, minutes or at) keeps a reminder for the person, the chat and the channel of the message that
asked for it. When it is due, a "notify" event with that person goes out, and the family push (channels/push.py) sends
it to that parent's own chat, never to the other one. Without the family push the plug-in answers the chat itself.

Limits: 1 minute to 24 hours ahead, at most 20 open reminders, 200 characters. A reminder that holds a code or a long
number, or a medicine with a dose, is refused: the agent never repeats those. Open reminders are kept in
data_dir/reminders.json, so a restart keeps them, and one that came due while the agent was down goes out at start
with the time it was meant for.

Add "parenting_agent.reminders:Reminders" to the plug-ins and "remind_me" to allowed_tools.
"""
import datetime
import json
import threading
from pathlib import Path

from .agent import rules
from .agent.plugins import Plugin
from .agent.tools import Tool, schema
from .channels.push import find_plugin
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS
from .voice.screen import has_dose

MAX_MIN = 24 * 60
MAX_OPEN = 20
MAX_CHARS = 200


class Reminders(Plugin):
    name = "reminders"

    def __init__(self, agent, config, clock=None):
        super().__init__(agent, config)
        rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self.path = Path(config.get("data_dir", "data")) / "reminders.json"
        self.lock = threading.Lock()
        self.open = self.load()
        self.stopped = threading.Event()
        agent.tools.add(Tool(
            "remind_me", "Remind the parent who asked, in their own chat, at a later time: in minutes from now, or at a "
            "local time HH:MM (today, or tomorrow when it already passed). text is what to remind, in their words.",
            schema({"text": {"type": "string"}, "minutes": {"type": "integer"}, "at": {"type": "string"}}, ["text"]),
            self.remind_me))

    def load(self):
        try:
            items = json.loads(self.path.read_text())
            return [r for r in items if isinstance(r, dict) and r.get("due") and r.get("text")]
        except (OSError, ValueError):
            return []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.open, ensure_ascii=False))

    def due_at(self, now, minutes=None, at=None):
        if at:
            try:
                t = datetime.time.fromisoformat(str(at).strip())
            except ValueError:
                raise ValueError(f"at must be HH:MM, got {at!r}") from None
            due = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            return due if due > now else due + datetime.timedelta(days=1)
        if minutes is None:
            raise ValueError("say when: minutes from now or a time HH:MM")
        minutes = int(minutes)
        if not 1 <= minutes <= MAX_MIN:
            raise ValueError(f"a reminder is 1 to {MAX_MIN} minutes ahead, got {minutes}")
        return now + datetime.timedelta(minutes=minutes)

    def remind_me(self, text, minutes=None, at=None):
        text = " ".join(str(text or "").split())[:MAX_CHARS]
        if not text:
            raise ValueError("a reminder needs its text")
        if rules.has_secret(text) or has_dose(text):
            raise ValueError("not kept: a reminder never holds a code, a long number or a medicine dose")
        now = self.clock()
        due = self.due_at(now, minutes, at)
        if due - now > datetime.timedelta(minutes=MAX_MIN):
            raise ValueError("a reminder is at most 24 hours ahead")
        event = getattr(self.agent, "current_event", None) or {}
        with self.lock:
            if len(self.open) >= MAX_OPEN:
                raise ValueError(f"there are already {MAX_OPEN} open reminders")
            self.open.append({"text": text, "due": due.isoformat(timespec="seconds"), "asked": now.isoformat(timespec="seconds"),
                              "person": event.get("person"), "chat_id": event.get("chat_id"),
                              "channel": event.get("channel")})
            self.save()
        self.agent.bus.publish("reminder_set", person=event.get("person"), due=due.isoformat(timespec="seconds"),
                               chars=len(text))
        return f"Reminder set for {due:%H:%M}" + ("" if due.date() == now.date() else " tomorrow") + f": {text}"

    def tick(self, now=None):
        now = now or self.clock()
        with self.lock:
            due = [r for r in self.open if datetime.datetime.fromisoformat(r["due"]) <= now]
            if not due:
                return []
            self.open = [r for r in self.open if r not in due]
            self.save()
        return [self.fire(r, now) for r in due]

    def fire(self, reminder, now):
        meant = datetime.datetime.fromisoformat(reminder["due"]).astimezone(self.tz)
        es = rules.looks_spanish(reminder["text"])
        late = now - meant > datetime.timedelta(minutes=5)
        if es:
            text = f"Recordatorio que pediste{f' para las {meant:%H:%M}' if late else ''}: {reminder['text']}"
        else:
            text = f"Reminder you asked for{f' for {meant:%H:%M}' if late else ''}: {reminder['text']}"
        if find_plugin(self.agent, "family-push") is not None:
            return self.agent.bus.publish("notify", text=text, source="reminders", person=reminder.get("person"),
                                          chat_id=reminder.get("chat_id"), channel=reminder.get("channel"))
        to = {"chat_id": reminder["chat_id"]} if reminder.get("chat_id") else {}
        return self.agent.bus.publish("reply", channel=reminder.get("channel") or "telegram", text=text,
                                      person=reminder.get("person"), proactive=True, source="reminders", **to)

    def start(self):
        threading.Thread(target=self.run, name="reminders", daemon=True).start()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.tick()
            except Exception as error:  # a bad file must not stop the agent
                self.agent.bus.publish("reminder_error", error=str(error)[:300])
            self.stopped.wait(15)

    def stop(self):
        self.stopped.set()
