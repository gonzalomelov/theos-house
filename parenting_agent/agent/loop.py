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

SYSTEM = """You are a persistent agent built for new parents. You know their baby from the log and the facts below,
you speak first when it helps, and you act in the home only through your tools.
Rules:
- Log what the parent tells you about the baby with log_baby_event, one call per event, then confirm in a few words.
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
        else:
            observed = f"[observation from {event.get('source', 'a skill')}] {event.get('text', '')}"
            transcript = self.transcript(observed)
            # Kept in memory too, so a later turn knows why the agent spoke and does not think it invented the event.
            self.memory.add_message(channel, "user", observed)
        self.decide(channel, transcript)

    def decide(self, channel, transcript):
        system, specs = self.system_prompt(), self.tools.specs()
        for _ in range(self.max_steps):
            reply, seconds = brain_mod.timed(self.brain, system, transcript, specs)
            self.bus.publish("brain_call", provider=self.brain.name, model=self.brain.model,
                             destination=self.brain.destination, seconds=seconds, tool_calls=len(reply.tool_calls))
            if not reply.tool_calls:
                self.say(channel, reply.text or "OK.")
                return
            transcript.append({"role": "assistant", "text": reply.text, "tool_calls": reply.tool_calls})
            for call in reply.tool_calls:
                status, result = self.tools.run(call["name"], call["arguments"])
                self.bus.publish("tool", name=call["name"], status=status)
                if status == "ask_parent":
                    self.pending.append(call)
                    self.bus.publish("ask_parent", channel=channel, name=call["name"], arguments=call["arguments"])
                transcript.append({"role": "tool", "id": call["id"], "name": call["name"], "result": result})
        self.say(channel, "I stopped after too many steps. Tell me again in other words.")
