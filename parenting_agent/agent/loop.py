"""The decide-act loop: one long-running agent that turns events into decisions and acts through tools.

Channels publish "message" events and skills publish "observation" events on the bus. The agent takes
them off its own queue, one at a time, asks the brain what to do with the memory in view, runs the
allowed tools, and publishes a "reply" for the channel that should speak. A tool that is not allowed
becomes an "ask_parent" event, and a later yes from the parent runs it.
"""
import datetime
import json
import queue
import threading

from . import brain as brain_mod
from . import rules

SYSTEM = """You are a persistent agent built for new parents. You know their baby from the log and the facts below,
you speak first when it helps, and you act in the home only through your tools.
Rules:
- Log what the parent tells you about the baby with log_baby_event, one call per event, then confirm in a few words.
  Log only what the newest message says. Earlier messages in the conversation were already handled, never log them again.
  A new message is a new event even when it repeats an earlier one, a second bottle of the same amount included: log it, never ask.
- Answer questions from the baby log: use baby_summary for how much, how many and when was the last, read_baby_log for details.
  Never guess times or amounts. If the log has nothing, say so.
- Never give medical advice, a diagnosis, a dose or a treatment. You log, remind and alert. For anything about health,
  symptoms, fever, medicine or feeding problems, say kindly that you cannot advise on health and suggest calling their pediatrician.
- Some tools always wait for the parent's yes, such as replying to a visitor or calling the partner. When one would help,
  call it anyway with what you would do: the parent is asked before it runs.
- Keep replies short, the parent's hands are often on the baby.
Today is {today}. Facts you were told: {facts}
"""

YES = {"yes", "si", "sí", "ok", "dale", "go ahead", "do it"}
ENTRY_WORDS = {"feeding": "a feed", "diaper": "a diaper", "sleep": "sleep", "bath": "a bath", "note": "a note"}
SAVED_BEFORE_FAIL = "I could not finish my answer, but I logged {entries}. No need to send it again."
NOT_LOGGED = {"en": "I could not log that. Could you send it again?", "es": "No pude anotarlo, ¿me lo repetís?"}
LOG_CHECK = ("[check from the agent, not the parent] The parent's newest message, \"{request}\", is not in the log: "
             "your answer came without a log_baby_event call that ran. Earlier messages were already handled, never log "
             "them again. If this one message reports something about the baby, call log_baby_event once for it now. "
             "Never say something is logged unless log_baby_event ran for it in this turn.")
READ_TOOLS = {"read_baby_log", "baby_summary", "current_time"}
ONE_AFTER_CHECK = "not logged: after the check only the newest message is logged, once. Earlier messages were already handled."


def _number(value):
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def entry_key(arguments):
    """What makes two log calls the same entry: the kind, the amount or the diaper's contents, and the time the
    parent named. A brain that repeats a call for one message, with or without extra fields, logs one entry."""
    details = arguments.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    when = arguments.get("ts") or details.get("time") or details.get("start") or details.get("end")
    fields = {"feeding": ("amount_ml", "duration_min", "method"), "diaper": ("wet", "solid"),
              "sleep": ("action",), "bath": ()}.get(arguments.get("kind"), ("text", "note"))
    values = []
    for name in fields:
        value = details.get(name)
        if name == "method":
            value = "breast" if "breast" in str(value or "").lower() else "bottle"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            value = float(value)
        elif isinstance(value, str):
            value = value.strip().lower()
        values.append(value)
    return (arguments.get("kind"), when, *values)


class Agent:
    def __init__(self, bus, memory, baby_log, tools, brain, max_steps=6, history=20):
        self.bus, self.memory, self.baby_log, self.tools, self.brain = bus, memory, baby_log, tools, brain
        self.max_steps, self.history = max_steps, history
        self.inbox = queue.Queue()
        self.pending = []
        self.thread = None
        self.stopped = threading.Event()
        bus.subscribe(self.inbox.put, ["message", "observation"])

    def start(self):
        self.thread = threading.Thread(target=self.run, name="agent", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.inbox.put(None)
        if self.thread:
            self.thread.join(timeout=5)

    def close(self):
        self.memory.close()
        self.bus.close()

    def run(self):
        while not self.stopped.is_set():
            event = self.inbox.get()
            if event is None:
                break
            try:
                self.handle(event)
            except brain_mod.BrainError as error:
                self.bus.publish("agent_error", error=str(error)[:300])
                self.say(event.get("channel", "console"), "I could not think that through just now. Please try again.")

    def say(self, channel, text):
        self.memory.add_message(channel, "assistant", text)
        self.bus.publish("reply", channel=channel, text=text)

    def system_prompt(self):
        facts = {key: item["value"] for key, item in self.memory.facts().items()} or "none yet"
        return SYSTEM.format(today=datetime.date.today().isoformat(), facts=json.dumps(facts, ensure_ascii=False))

    def transcript(self, new_text):
        items = [{"role": m["role"], "text": f"[{m['ts'][11:16]}] {m['text']}" if m["role"] == "user" else m["text"]}
                 for m in self.memory.recent_messages(self.history)]
        items.append({"role": "user", "text": new_text})
        return items

    def propose(self, channel, name, arguments, text=None):
        """A plug-in asks the parent before one of its tools runs: the parent's next yes runs it, like a brain call
        that was not on the allowed list. A newer proposal for the same tool replaces the older one."""
        self.pending = [call for call in self.pending if call["name"] != name]
        self.pending.append({"id": f"proposal-{name}", "name": name, "arguments": dict(arguments)})
        self.bus.publish("ask_parent", channel=channel, name=name, arguments=arguments, source="plugin")
        if text:
            self.say(channel, text)

    def approve_pending(self, channel):
        results = []
        for call in self.pending:
            tool = self.tools.items[call["name"]]
            result = tool.handler(**call["arguments"])
            self.bus.publish("tool", name=call["name"], status="ran_after_yes")
            results.append(f"{call['name']}: {result}")
        self.pending = []
        self.say(channel, "Done. " + "; ".join(str(r)[:80] for r in results))

    def handle(self, event):
        channel = event.get("channel", "console")
        if event["kind"] == "message":
            text = event["text"].strip()
            if self.pending and text.lower().strip(" .!") in YES:
                self.memory.add_message(channel, "user", text)
                self.approve_pending(channel)
                return
            stamp = datetime.datetime.now().strftime("%H:%M")
            transcript = self.transcript(f"[{stamp}] {text}")
            self.memory.add_message(channel, "user", text)
            self.decide(channel, transcript, request=text)
            return
        else:
            observed = f"[observation from {event.get('source', 'a skill')}] {event.get('text', '')}"
            transcript = self.transcript(observed)
            # Kept in memory too, so a later turn knows why the agent spoke and does not think it invented the event.
            self.memory.add_message(channel, "user", observed)
        self.decide(channel, transcript)

    def saved_before_fail(self, entries):
        """The reply when the brain fails after the log already changed: it says what was kept, so the parent does not
        send it again, and the memory holds an answer, so the next turn does not log the same message a second time."""
        words = []
        for entry in entries:
            word = ENTRY_WORDS.get(entry.get("kind"), "an entry")
            ml = (entry.get("details") or {}).get("amount_ml")
            words.append(f"{word} of {float(ml):g} ml" if entry.get("kind") == "feeding" and _number(ml) else word)
        return SAVED_BEFORE_FAIL.format(entries=", ".join(words))

    def not_logged(self, request):
        """The honest answer when a parent's note was not saved. Kept in memory like any answer, so the next turn
        sees that nothing was logged."""
        return NOT_LOGGED["es" if rules.looks_spanish(request) else "en"]

    @staticmethod
    def needs_log(request, text, failed, acted):
        """True when the brain's answer to a parent's message must not go out as it is, because no log call ran: a log
        call failed, or nothing acted on the message although it reports something to log or the answer says it
        logged. A plug-in tool that ran, such as finish_bath on "bath done", acted on it, and a call waiting for the
        parent's yes is never held."""
        if request is None or acted == "ask_parent":
            return False
        if failed:
            return True
        if acted:
            return False
        return rules.is_log_request(request) or (rules.claims_logged(text) and not rules.is_question(request))

    def decide(self, channel, transcript, request=None):
        """One incoming message or observation, through the brain and the tools, until the brain answers. Within it a
        log entry is written once, whatever the brain repeats. If the brain fails after something was logged, the agent
        still answers with what it kept.

        request is the parent's message. When it reports something to log and the brain answers without a log call
        that ran, its answer is never sent, so a parent is never told "logged" when nothing was saved. The brain is
        asked once more to call the tool, and if it still does not, the parent hears that it could not be logged."""
        system, specs = self.system_prompt(), self.tools.specs()
        logged, kept = {}, []
        failed, acted, checked = False, None, False
        wanted = rules.log_kind(request) if request is not None else None
        for _ in range(self.max_steps):
            try:
                reply, seconds = brain_mod.timed(self.brain, system, transcript, specs)
            except brain_mod.BrainError as error:
                if not kept:
                    raise
                self.bus.publish("agent_error", error=str(error)[:300])
                self.say(channel, self.saved_before_fail(kept))
                return
            self.bus.publish("brain_call", provider=self.brain.name, model=self.brain.model,
                             destination=self.brain.destination, seconds=seconds, tool_calls=len(reply.tool_calls))
            if not reply.tool_calls:
                if not kept and self.needs_log(request, reply.text, failed, acted):
                    if not checked:
                        checked = True
                        self.bus.publish("guard", status="asked_to_log", failed=failed)
                        transcript.append({"role": "assistant", "text": reply.text or "(no answer)"})
                        transcript.append({"role": "user", "text": LOG_CHECK.format(request=request.replace('"', "'"))})
                        continue
                    self.bus.publish("guard", status="not_logged", failed=failed)
                    self.say(channel, self.not_logged(request))
                    return
                self.say(channel, reply.text or "OK.")
                return
            transcript.append({"role": "assistant", "text": reply.text, "tool_calls": reply.tool_calls})
            for call in reply.tool_calls:
                key = entry_key(call["arguments"] or {}) if call["name"] == "log_baby_event" else None
                if key is not None and checked and (kept or (wanted and call["arguments"].get("kind") != wanted)):
                    # Asked to log the newest message, a brain can try to log earlier ones too. Only one entry of the
                    # kind the message reports runs.
                    self.bus.publish("tool", name=call["name"], status="held")
                    transcript.append({"role": "tool", "id": call["id"], "name": call["name"], "result": ONE_AFTER_CHECK})
                    continue
                if key is not None and key in logged:
                    self.bus.publish("tool", name=call["name"], status="duplicate")
                    transcript.append({"role": "tool", "id": call["id"], "name": call["name"],
                                       "result": {"already_logged": logged[key], "note": "already logged for this message, not logged again"}})
                    continue
                status, result = self.tools.run(call["name"], call["arguments"])
                self.bus.publish("tool", name=call["name"], status=status)
                failed = failed or (key is not None and status == "error")
                if status == "ask_parent":
                    acted = "ask_parent"
                elif status == "ran" and call["name"] not in READ_TOOLS and acted is None:
                    acted = call["name"]
                if key is not None and status == "ran":
                    logged[key] = result
                    kept.append(call["arguments"])
                if status == "ask_parent":
                    self.pending.append(call)
                    self.bus.publish("ask_parent", channel=channel, name=call["name"], arguments=call["arguments"])
                transcript.append({"role": "tool", "id": call["id"], "name": call["name"], "result": result})
        self.say(channel, "I stopped after too many steps. Tell me again in other words.")
