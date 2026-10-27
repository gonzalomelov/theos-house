# parenting-agent

**A persistent agent built for new parents. It knows your baby, stays with you all day through your phone, glasses and home speakers, reminds you before you have to remember, and acts in your home while your hands stay on the baby. Everything stays in your house.**

Built during the Meta Global AI Developer Hackathon, from Oct 26 2026. See [what was built during the hackathon](#built-during-the-meta-global-ai-developer-hackathon-oct-26-to-nov-4-2026) and [docs/architecture.md](docs/architecture.md).

It logs, reminds and alerts. It never gives medical advice and never diagnoses. It never replaces staying within arm's reach of the baby.

## How it works

One long-running agent sits in the middle. Everything it sees, hears and does goes through an event bus.

- **Memory.** The baby's log lives in Baby Buddy, an open-source baby tracker running on the family's own server. The agent's own notes and conversation live in a local SQLite file.
- **Brain.** A model with tools decides what to do: log a feed, answer a question from the log, arm a skill, act on the house. Anything outside the allowed list waits for a parent's yes.
- **Skills.** The changing-table skill watches through a head-worn camera. A local hand detector raises the alarm in under a second when both hands leave the baby, and Meta's SAM 3.1 confirms whether a hand really touches the baby or only hovers above it.
- **Daily rhythm.** From the log it learns the baby's patterns and speaks first: the next feed, unusual days, a night summary and a fair split of the night between two parents.
- **House.** Home Assistant is its hands: lights, notifications, speakers, the robot vacuum, the TV. Today it runs dry, it publishes what it would do and touches nothing.

## Meta models

| Job | Model | Where it runs |
|---|---|---|
| Touch versus hover at the changing table | **SAM 3.1**, Meta's open weights | On the Mac's GPU, about 1.5 s per frame. Frames never leave the house |
| The agent's brain | **Muse Spark Open**, Meta's open weights | Baseten, with no data kept and no training on it (`config/agent.muse-baseten.json`, waiting for the partner credits) |
| Stand-in brain until then | Claude | Anthropic API, temporary only (`config/agent.json`) |

## Private by design

| Data | Where it goes |
|---|---|
| Camera frames | Stay in memory on the Mac. SAM 3.1 and the hand detector run locally. Nothing is saved, only numbers and states in `runs/` |
| House audio | Planned (#14): labelled locally, never saved |
| The baby's log | Baby Buddy on the family's server, reachable only on that server (see `docs/deploy-babybuddy.md`) |
| The agent's memory | `data/memory.sqlite` and `data/events.jsonl` on the machine that runs it |
| **What leaves the house** | Only the brain call: the conversation text and tool results go to the configured brain (Baseten for Muse Spark Open, Anthropic for the stand-in). Every call logs its destination host as a `brain_call` event |

## Run it

```bash
python -m parenting_agent --check                                  # load everything, print brain, plug-ins and tools, exit
python -m parenting_agent                                          # Claude stand-in, type to it in the terminal
python -m parenting_agent --config config/agent.fake.json          # offline, rule-based brain
python -m parenting_agent --config config/agent.muse-baseten.json  # Muse Spark Open on Baseten (needs BASETEN_API_KEY)
```

Keys are read from a git-ignored `.env` (path in `config/agent.json`). Baby Buddy is reached through an SSH tunnel:

```bash
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro   # see docs/deploy-babybuddy.md
```

Changing-table skill on generated clips streamed in real time:

```bash
scripts/sam3-setup.sh   # once, SAM 3.1 on the Mac GPU, see docs/sam3-local.md
python scripts/kr222_table.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/kt/clips --passes 5
```

Simulated baby week and daily rhythm: see `docs/simulated-week.md` and `docs/daily-rhythm.md`.

Tests:

```bash
python -m unittest discover -s tests             # fake brain, no network
PA_LIVE=1 python -m unittest tests.test_agent    # also runs the same conversation with Claude
```

## Built during the Meta Global AI Developer Hackathon (Oct 26 to Nov 4 2026)

Everything in this repo was written during the event. The repo was created on Oct 26 2026 at 15:03 Montevideo time, after the official start.

| What | Issue | PR | Commit |
|---|---|---|---|
| Baby Buddy on the family server, localhost only, least-privilege agent user | #19, #12 | #20 | 019a83d |
| Home Assistant inventory and action policy | #9 | #21 | f45a7dc |
| Agent core: event bus, memory, decide-act loop, tools with an allowed list, swappable brain | #1 | #22 | fb2e5a2 |
| Simulated first-weeks baby week for Baby Buddy | #13 | #23 | 86f0bcd |
| Daily rhythm, unusual-day notes, fair night shifts | #7 | #24 | 3f6078b |
| Changing-table skill on the core, SAM 3.1 confirm on the Mac GPU | #6 | #25 | c0d7b5d |
| README and architecture | #18 | this PR | |

The first commits of Oct 26 (4f1898a to 90ca5a3) are an early skeleton that the issues above reviewed and partly rewrote.

**Planned, not built yet:** voice log and answers through Baby Buddy (#2), Telegram channel (#3), Muse Spark Open live on Baseten (#4), channel picking (#8), live Home Assistant actions (#9, dry run today), bath skill (#10), house sounds (#14), always on on the family server (#15), sitter handover (#16), simulated full day (#17), demo and submission (#11).

**Public open-source tools used, not written by us:** Meta SAM 3.1 weights and code, MediaPipe hand landmarker, OpenCV, NumPy, Baby Buddy (BSD-2-Clause), Home Assistant.
