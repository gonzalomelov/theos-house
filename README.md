# parenting-agent

A persistent agent built for new parents, built during the Meta Global AI Developer Hackathon (from Oct 26 2026).

## Run the agent

```bash
python -m parenting_agent --check                            # load everything, print brain, plug-ins and tools, exit
python -m parenting_agent                                    # Claude stand-in, type to it in the terminal
python -m parenting_agent --config config/agent.fake.json    # offline, rule-based brain
python -m parenting_agent --config config/agent.muse-baseten.json  # Muse Spark Open on Baseten (needs BASETEN_API_KEY)
```

The agent core (issue #1) is standard library only. It keeps its memory in `data/memory.sqlite` and its event log in `data/events.jsonl`, both on the machine that runs it. The only thing that leaves the house is the brain call, and every call logs its destination host as a `brain_call` event.

- `parenting_agent/bus.py`: the event bus every part publishes to.
- `parenting_agent/agent/`: memory and baby log, tools with the allowed list, the swappable brain, the decide-act loop, plug-ins (channels and skills).
- `parenting_agent/vision_run.py` and the vision modules: the camera skill runner, moving onto the agent core in issue #6.

## Baby log in Baby Buddy (issue #2)

Notes like "bottle, 120 ml", "wet and dirty diaper", "she napped from 14:00 to 15:00" or "just gave her a bath" become Baby Buddy entries. Questions like "when was the last dirty diaper?" or "how much did she drink today?" are answered from Baby Buddy through the `baby_summary` and `read_baby_log` tools. Health questions get a kind refusal and a suggestion to call the pediatrician. Notes arrive as text for now, the channels issue adds speech to text.

- `parenting_agent/agent/babybuddy.py`: Baby Buddy as the baby log. Baths are notes that start with "Bath". "Asleep" starts a timer and "awake" turns it into a sleep record. Entries are never timed in the future. A feed whose estimated start overlaps the previous feed starts right after it.
- `config/agent.json` and `config/agent.muse-baseten.json` use Baby Buddy (`baby_log.provider: babybuddy`, URL and token from the env file, reached through the tunnel in `docs/deploy-babybuddy.md`). `config/agent.fake.json` keeps the offline log in the agent's memory file.
- `scripts/voice_log_run.py`: the real run for a usage goal check 2. It sends notes through the agent and the brain, reads each record back from Baby Buddy by id and writes `results/kr222/voice-log.json`.

## Tests

```bash
python -m unittest discover -s tests             # fake brain, no network
PA_LIVE=1 python -m unittest tests.test_agent    # also runs the same conversation with Claude
PA_LIVE=1 PYTHONPATH=tests python -m unittest tests.test_voice_log   # notes, questions and the safety check with Claude
```
