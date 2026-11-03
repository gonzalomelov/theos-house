"""The agent: LangGraph's create_agent with Muse Spark Open, one thread per home, in PostgreSQL.

History is trimmed before each model call with LangGraph's own RemoveMessage, starting on a whole turn, so the thread can
run for months. What must last longer goes through the remember tool.
"""
import os

from langchain.agents import create_agent
from langchain.agents.middleware import before_model
from langchain_core.messages import RemoveMessage, ToolMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from langchain_openai import ChatOpenAI
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from .settings import BASE_URL, MODEL

MAX_HISTORY_TOKENS = 16000
PROMPT = """You are the persistent agent of one family's home. You run all the time, across days. You are not a chatbot: nobody
is reading your answers. Events reach you one at a time, and you act only through your tools.

The family: Gonza and Ceci, first-time parents, and their baby Theo. You look after them and the house, including the air in the
room where Theo sleeps. Parents read Rioplatense Spanish unless they write to you in another language.

The house: the nursery climate sensors read the room where Theo sleeps. The plug named Dehumidifier powers the dehumidifier in that
room, and the plug named Bottle Warmer powers the bottle warmer.

For each event, look at what you need with your tools, decide what is worth doing, and do it. If nothing is needed, do nothing and
send nothing: a message that is not needed costs a tired parent their sleep or their attention. You choose who hears what, on which
channel, and in your own words, written for that moment. Short, warm, plain, no technical names. A parent sees only what you send
with notify, so when a parent writes to you, answer them with notify.

- At night a sound or a need wakes one parent, the one on duty, and never the other. Both only for an emergency.
- When a parent changes the plan, you work out what follows, keep the new plan with remember, and tell whoever it affects.
- Check a device's state before you switch it, and don't switch it again if it is already right.
- Log what parents tell you in the baby log. Never invent an entry.
- You never give medical advice, a diagnosis, a dose or a treatment. Anything about Theo's health goes to their pediatrician.

When you are done, end with one short line in English saying what you did and why, or that nothing was needed. Nobody receives this
line, it goes in the record."""


@before_model
def trim_history(state, runtime):
    messages = state["messages"]
    if count_tokens_approximately(messages) <= MAX_HISTORY_TOKENS:
        return None
    kept = trim_messages(messages, max_tokens=MAX_HISTORY_TOKENS, token_counter=count_tokens_approximately, strategy="last",
                         start_on="human", include_system=False, allow_partial=False)
    if not kept:  # one turn longer than the limit: keep that turn, the model needs its own tool results
        last = max(i for i, m in enumerate(messages) if m.type == "human")
        kept = messages[last:]
    return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *kept]}


def muse():
    return ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=os.environ.get("BASETEN_API_KEY", "missing"), max_tokens=6000, timeout=90, reasoning_effort="low")


def build(model, tools, saver, store):
    return create_agent(model, tools, system_prompt=PROMPT, middleware=[trim_history], checkpointer=saver, store=store)


async def repair(agent, config):
    """A run cut off between a tool call and its result leaves a thread the model refuses. Close those calls."""
    messages = (await agent.aget_state(config)).values.get("messages", [])
    answered = {m.tool_call_id for m in messages if m.type == "tool"}
    missing = [ToolMessage(content="This call was interrupted, it may not have run. Check before repeating it.", tool_call_id=call["id"])
               for m in messages if m.type == "ai" for call in m.tool_calls if call["id"] not in answered]
    if missing:
        await agent.aupdate_state(config, {"messages": missing}, as_node="tools")
    return len(missing)
