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
- `parenting_agent/changing_table.py`: the changing-table skill as a plug-in (issue #6). The agent arms it with `start_changing_table` and closes it with `finish_changing_table`.
- `parenting_agent/reflex.py`, `alarm.py`, `skill.py`, `sources.py`, `speaker.py`: the local reflex (MediaPipe), the chime then voice alarm, the skill lifecycle, the head camera page and the speaker.
- `parenting_agent/sam3_local.py` and `sam3_worker.py`: Meta's SAM 3.1 on this Mac's GPU, which confirms touch versus hover. See `docs/sam3-local.md`.
- `parenting_agent/house.py` and `tracking.py`: Home Assistant actions with an allowed list, and the Baby Buddy log.

## Changing-table skill on generated clips

```bash
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro       # Baby Buddy, see docs/deploy-babybuddy.md
python scripts/kr222_table.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/kt/clips --passes 5
```

It streams the clips in real time through the skill and writes `results/kr222/table.json` (the a usage goal check 1 file). Frames stay in memory, the run log in `runs/` holds only numbers and states.

## Tests

```bash
python -m unittest discover -s tests             # fake brain, no network
PA_LIVE=1 python -m unittest tests.test_agent    # also runs the same conversation with Claude
```

## Daily rhythm (issue #7)

The agent speaks first from the baby log: next-feed warnings, notes on unusual days, a night summary and fair night shifts. See `docs/daily-rhythm.md`.
