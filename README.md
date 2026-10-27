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

## Tests

```bash
python -m unittest discover -s tests             # fake brain, no network
PA_LIVE=1 python -m unittest tests.test_agent    # also runs the same conversation with Claude
```

## Daily rhythm (issue #7)

The agent speaks first from the baby log: next-feed warnings, notes on unusual days, a night summary and fair night shifts. See `docs/daily-rhythm.md`.
