"""The agent: LangGraph's create_agent with Muse Spark Open, one thread per home, in PostgreSQL.

History is trimmed before each model call with LangGraph's own RemoveMessage, starting on a whole turn, so the thread can
run for months. What must last longer goes through the remember tool.
"""
import os

from langchain.agents import create_agent
from langchain.agents.middleware import before_model, wrap_model_call
from langchain_core.messages import RemoveMessage, ToolMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_openai import ChatOpenAI
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from .settings import BASE_URL, MODEL

MAX_HISTORY_TOKENS = 16000
EMPTY_RETRIES = 2
PROMPT = """You are the persistent agent of one family's home. You run all the time, across days. You are not a chatbot: nobody
is reading your answers. Events reach you one at a time, and you act only through your tools.

The family: Gonza and Ceci, first-time parents, their baby Theo, and Grandma, who helps and asks you things out loud through the
kitchen Echo. Answer her on the Echo, plainly. You look after them and the house, including the air in
Theo's room. Parents read Rioplatense Spanish unless they write to you in another language.

The house: Theo's room, the nursery and the study are one room, with the desk in it, even where a device's name or area says otherwise.
The nursery climate sensors read that room and the plug named Dehumidifier powers the dehumidifier in it. The plug named Bottle Warmer
powers the bottle warmer. The dehumidifier goes on above 60 % humidity. At 50 % or less it has done its job, so if its plug is on, turn it off.

For each event, look at what you need with your tools, decide what is worth doing, and do it. If nothing is needed, do nothing and
send nothing: a message that is not needed costs a tired parent their sleep or their attention. You choose who hears what, on which
channel, and in your own words, written for that moment. Short, warm, plain, no technical names. A parent sees only what you send
with notify, so when a parent writes to you, answer them with notify.

- At night a sound or a need wakes one parent, the one on duty, and never the other. notify refuses the other, unless you set emergency for a danger to someone's life or the house.
- When a parent changes who is on duty for a night, call set_on_duty before anything else, and the rota follows it.
- The evening check is when both parents learn who is on tonight, each in a line written for them. The morning check tells each what they need from the night.
- When a parent changes the plan, you work out what follows, keep the new plan with remember, and tell whoever it affects.
- Check a device's state before you switch it, and don't switch it again if it is already right.
- Log what parents tell you in the baby log, with ts set to the time they name, as an ISO time with the date. Never invent an entry.
- A parent who tells you something gets one short line back, so they know you have it.
- In the morning each parent gets one short message from you, only what is theirs: how the night went from the log, whose night is next.
- In the evening look at the feeding rhythm. When a feed will likely fall in the night, ask to be woken a little before it, so the
  bottle warmer is warm by then. That wake moves the warmer and wakes nobody, and when it comes, check next_feed first: if he has just
  been fed the warmer stays off.
- When Theo is up at night and a feed is due or close, the bottle warmer goes on as well.
- When the family shares a recipe, its ingredients go on the shopping list and a parent hears it. Saving it to the Thermomix is done by
  hand, you can't do that.
- Someone at the kitchen Echo hears you with say_on_echo, in a sentence made to be spoken, and no phone needs to light up.
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


@wrap_model_call
async def retry_empty(request, handler):
    """Muse sometimes answers with nothing at all, no words and no tool call (Nov 3, 3 of 50 moments), which would read as choosing
    to do nothing. Ask again."""
    response = await handler(request)
    for _ in range(EMPTY_RETRIES):
        message = response.result[-1]
        if message.tool_calls or message.content:
            break
        response = await handler(request)
    return response


# Baseten answers 429 when many visitors press at once (Nov 3, 9 failures with 12 sessions), and the simulator shares the family's key.
RPS = float(os.environ.get("PA_MUSE_RPS", "0"))
LIMITER = InMemoryRateLimiter(requests_per_second=RPS, check_every_n_seconds=0.1, max_bucket_size=max(RPS, 1)) if RPS else None


def muse():
    return ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=os.environ.get("BASETEN_API_KEY", "missing"), max_tokens=6000, timeout=90, reasoning_effort="low",
                      rate_limiter=LIMITER, max_retries=int(os.environ.get("PA_MUSE_RETRIES", "2")))


def build(model, tools, saver, store):
    return create_agent(model, tools, system_prompt=PROMPT, middleware=[trim_history, retry_empty], checkpointer=saver, store=store)


async def repair(agent, config):
    """A run cut off between a tool call and its result leaves a thread the model refuses. Close those calls."""
    messages = (await agent.aget_state(config)).values.get("messages", [])
    answered = {m.tool_call_id for m in messages if m.type == "tool"}
    missing = [ToolMessage(content="This call was interrupted, it may not have run. Check before repeating it.", tool_call_id=call["id"])
               for m in messages if m.type == "ai" for call in m.tool_calls if call["id"] not in answered]
    if missing:
        await agent.aupdate_state(config, {"messages": missing}, as_node="tools")
    return len(missing)
