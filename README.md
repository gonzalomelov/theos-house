# parenting-agent

**A persistent agent built for new parents. It knows your baby, stays with you all day through your phone, glasses and home speakers, reminds you before you have to remember, and acts in your home while your hands stay on the baby. Everything stays in your house.**

Built during the Meta Global AI Developer Hackathon, from Oct 26 2026. See [what was built during the hackathon](#built-during-the-meta-global-ai-developer-hackathon-oct-26-to-nov-4-2026) and [docs/architecture.md](docs/architecture.md).

It logs, reminds and alerts. It never gives medical advice and never diagnoses. It never replaces staying within arm's reach of the baby.

## How it works

One long-running agent sits in the middle. Everything it sees, hears and does goes through an event bus.

- **Memory.** The baby's log lives in Baby Buddy, an open-source baby tracker running on the family's own server. The agent's own notes and conversation live in a local SQLite file.
- **Brain.** A model with tools decides what to do: log a feed, answer a question from the log, arm a skill, act on the house. Anything outside the allowed list waits for a parent's yes.
- **Skills.** The changing-table and bath skills watch through a head-worn camera. A local hand detector raises the alarm in under a second when both hands leave the baby, and Meta's SAM 3.1 confirms whether a hand really touches the baby or only hovers above it.
- **Daily rhythm.** From the log it learns the baby's patterns and speaks first: the next feed, unusual days, a night summary and a fair split of the night between two parents.
- **House.** Home Assistant is its hands: lights, notifications, speakers, the robot vacuum, the TV, as tools behind the action policy (`parenting_agent/house_tools.py`). It runs dry until `house.live` is true in the agent config, and only Gonza turns that on.

## Meta models

| Job | Model | Where it runs |
|---|---|---|
| Touch versus hover at the changing table and in the bath | **SAM 3.1**, Meta's open weights | On the Mac's GPU, about 1.5 s per frame. Frames never leave the house |
| The agent's brain | **Muse Spark Open**, Meta's open weights | Baseten, data terms still to be checked (`config/agent.muse-baseten.json`, waiting for the partner credits) |
| Stand-in brain until then | Claude | Anthropic API, temporary only (`config/agent.json`) |

## Private by design

| Data | Where it goes |
|---|---|
| Camera frames | Stay in memory on the Mac. SAM 3.1 and the hand detector run locally. Nothing is saved, only numbers and states in `runs/` |
| House audio | Labelled on the Mac by PANNs, never saved, only labels and numbers in `results/` (see `docs/house-sounds.md`) |
| The baby's log | Baby Buddy on the family's server, reachable only on that server (see `docs/deploy-babybuddy.md`) |
| The agent's memory | `data/memory.sqlite` and `data/events.jsonl` on the machine that runs it, on the Vostro in `~/apps/parenting-agent-data` |
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

## Always on, on the family server (issue #15)

The agent runs 24/7 on the Vostro in its own walled-off container: it reaches Baby Buddy and Home Assistant through a relay and the brain and Telegram through an allowlisting proxy, and nothing else. It restarts on its own, keeps its data in a volume, and house actions stay dry run. Deploy, update, logs, stop and rollback with `sh deploy/agent.sh`, see `docs/deploy-agent.md`.

## Baby log in Baby Buddy (issue #2)

Notes like "bottle, 120 ml", "wet and dirty diaper", "she napped from 14:00 to 15:00" or "just gave her a bath" become Baby Buddy entries. Questions like "when was the last dirty diaper?" or "how much did she drink today?" are answered from Baby Buddy through the `baby_summary` and `read_baby_log` tools. Health questions get a kind refusal and a suggestion to call the pediatrician. Notes arrive as text for now, the channels issue adds speech to text.

- `parenting_agent/agent/babybuddy.py`: Baby Buddy as the baby log. Baths are notes that start with "Bath". "Asleep" starts a timer and "awake" turns it into a sleep record. Entries are never timed in the future. A feed whose estimated start overlaps the previous feed starts right after it.
- `config/agent.json` and `config/agent.muse-baseten.json` use Baby Buddy (`baby_log.provider: babybuddy`, URL and token from the env file, reached through the tunnel in `docs/deploy-babybuddy.md`). `config/agent.fake.json` keeps the offline log in the agent's memory file.
- `scripts/voice_log_run.py`: the real run for a usage goal check 2. It sends notes through the agent and the brain, reads each record back from Baby Buddy by id and writes `results/kr222/voice-log.json`.

Changing-table skill on generated clips streamed in real time:

```bash
scripts/sam3-setup.sh   # once, SAM 3.1 on the Mac GPU, see docs/sam3-local.md
python scripts/kr222_table.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/kt/clips --passes 5
```

Bath skill (issue #10), armed by "bath time" and logged by "bath done", the second camera skill and config only (`skills/bath.json`). See `docs/bath.md`.

```bash
python scripts/bath_run.py --baths 10   # bath clips streamed live, Claude brain, Baby Buddy, SAM 3.1
```

Simulated baby week and daily rhythm: see `docs/simulated-week.md` and `docs/daily-rhythm.md`.

Sitter handover: one message briefs a grandparent or a sitter from the log, the parent approves it first, and a time-boxed guest role logs feeds and diapers. See `docs/sitter-handover.md`.

Simulated full day, 06:10 to 02:30 (issue #17), the demo rehearsal in one command:

```bash
python -m parenting_agent.fullday              # Claude brain, Baby Buddy, SAM 3.1, the clips streamed live
python -m parenting_agent.fullday --no-video   # skip the two clip steps
python -m parenting_agent.fullday --wipe-only  # remove the entries earlier runs wrote (tag full-day-sim)
```

It replays the plan page day through the real agent: a bottle by voice, the changing table on the clips with a dirty diaper said aloud, a doorbell during the change, a long-nap note, the bath on its clip, a question answered from the log, and the night feed with the next feed and the next parent on duty. It writes `results/fullday/day.md`, `day.json` and the KR files in `results/fullday/kr222/`. What is not built yet shows as dry run in the report: Home Assistant actions (#9), delivery on Telegram, the ear and the speakers (#3, #8) and the house sound detector (#14). See `docs/full-day.md`.

## Daily house plan: vacuum, shopping list, dinner and white noise (issues #29 and #32)

The vacuum pauses and goes home when a nap starts and never starts when the run would reach a predicted nap. It starts alone only when nobody is home or the baby is out, otherwise it asks. "Clean under the high chair" is a room clean, there is one daily run at the quietest awake time, diapers go on `todo.shopping_list` before they run out, a bad night gives a draft of fast Thermomix dinners from Cookidoo (read only, through home-agents), a reminder says when to start dinner, and white noise follows the rhythm under the 50 dB cap. The Thermomix is never controlled. See `docs/house-plan.md`.

```bash
python scripts/house_plan_check.py   # live and safe: reads the vacuum, dry runs pause and home, one test list item added and removed
```

## Telegram and channel picking (issues #3 and #8)

The agent hears and speaks on Telegram through @home_agent_example_bot, with long polling over plain HTTPS, so nothing is exposed. Only the family's chat ids (`TELEGRAM_CHAT_ID` in the env file, comma separated) are accepted. Other senders are ignored and logged as `channel_ignored` with their chat id only. Messages reach the same agent and the same memory as every other channel.

- `parenting_agent/channels/messaging.py`: one messaging adapter interface and the channel plug-in that runs it. WhatsApp later is a new adapter only.
- `parenting_agent/channels/telegram.py`: the Telegram adapter. Text for now, voice notes later.
- `parenting_agent/channels/router.py`: picks one channel for each `notify` event and each agent reply on the channel `auto`. Help needed goes to the partner (a stub, Ceci has no phone channel yet). Away or unknown presence goes to Telegram. At home with a skill armed, or with the baby asleep, it goes to the ear (the Mac speaker for now). At home with hands free it goes to the kitchen Echo at low volume, and the volume is put back after. Presence comes from `person.gonza`, then `device_tracker.gonzas_iphone`.
- `scripts/channels_check.py`: the real checks, a Telegram round trip, one Echo announce and a reminder routed with presence simulated as away. Results in `results/channels/check.json`.

Home Assistant is reached through `ssh -f -N -L 127.0.0.1:18123:127.0.0.1:8123 vostro`, token `HA_MCP_TOKEN`.

## Car seat coach (issue #30)

The agent coaches an infant carrier install with the car's seat belt, one step at a time by voice. SAM 3.1 on the Mac checks what the head camera can see: the lap belt in both side guides, the shoulder belt in the rear guide, no twist, the level line, the handle upright. The movement test at the belt path and the harness pinch test are asked and logged. It never says "safe", it lists what passed and what remains and suggests one check by a certified technician. The steps and limits come from the maker's manual (Joie i-Snug 2), the car rules from the Tesla Model 3 manual. An outgrow watch compares Baby Buddy weight and height with the seat's limits. Tested on 3D-rendered clips with planted mistakes, see `docs/car-seat-coach.md` and `results/carseat/`.

## Public demo app

A phone-first web chat where anyone can talk to the real agent core about Demo Baby, a simulated baby on the simulated week, with a simulated house. Each visitor gets their own copy, health questions get the kind refusal, and the process carries only the brain key. Local only until Gonza says "OK public". See `docs/demo-app.md`.

```bash
python -m parenting_agent.demo --brain-env ~/.parenting-agent.env   # http://127.0.0.1:8765
python -m parenting_agent.demo.export_sessions                                                     # session rows for the scorer
```

## Invited families on Telegram (issue #40)

Invited parents log their own baby through a second Telegram bot, each family in its own SQLite file, walled off from the family agent, Baby Buddy, Home Assistant and the LAN like the demo. Gonza makes an invite code, the parent sends `/start <code>`, answers 3 questions and is logging. Logs by text, answers from the family's log, next feed reminders, an evening summary, `/deletemydata`, caps per family and for the day. Deployed on the Vostro on Oct 28 2026, invite only. See `docs/families.md`, which also holds the privacy note for parents.

```bash
python -m parenting_agent.families invite --count 3        # codes for new families
python -m parenting_agent.families run --keys-env FILE     # the bot, needs TELEGRAM_FAMILIES_BOT_TOKEN
python -m parenting_agent.families.export_sessions         # session rows for the scorer, kind family
```

## The Tesla, simulated until Nov 5 (issue #31)

The family's Model 3 arrives on Nov 5, so today the agent drives a simulated Model 3 with the same entity ids and services as Home Assistant's official `tesla_fleet` integration. Cabin ready before a trip with the baby ("we leave in 15" or a calendar entry, target from the outside temperature, the parent's yes first), car naps (a drive with the baby becomes a proposed sleep entry, logged only on the parent's yes) and a Child Left Alone Detection check. Everything about the car says "simulated Tesla". On Nov 5 `car.backend` switches to `home_assistant`, commands stay dry until Gonza's OK. See `docs/tesla.md`.

```bash
python -m parenting_agent.tesla   # one trip with the baby on the simulated car, synthetic drive data
```

## Tests

```bash
python -m unittest discover -s tests             # fake brain, no network
PA_LIVE=1 python -m unittest tests.test_agent    # also runs the same conversation with Claude
PA_LIVE=1 PYTHONPATH=tests python -m unittest tests.test_voice_log   # notes, questions and the safety check with Claude
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
| README and architecture | #18 | #26 | 66780c2 |
| Voice log and answers from Baby Buddy | #2 | #27 | 6571481 |
| Simulated full day 06:10 to 02:30, one-command demo rehearsal | #17 | #28 | be7ba04 |
| Public demo app with a simulated baby, local only | #33 | #34 | see PR |
| Always on: the agent in a walled-off container on the Vostro | #15 | #35 | see PR |
| Telegram channel and channel picking | #3, #8 | #36 | see PR |
| House sounds, why is he crying, white noise | #14, #32 | see PR | see PR |
| Sitter handover, time-boxed guest role, summary after | #16 | see PR | see PR |
| Invited families on Telegram, one private log per family, walled off | #40 | see PR | see PR |
| Bath skill, camera skills from config | #10 | #42 | see PR |
| Simulated Tesla: cabin ready, car naps, Child Left Alone Detection check | #31 | #43 | see PR |
| Daily house plan: vacuum around naps, shopping list, fast dinners, white noise | #29, #32 | #44 | see PR |
| Car seat coach: manual to steps, SAM 3.1 visible checks, hand checks, outgrow watch, rendered test clips | #30 | #47 | see PR |

The first commits of Oct 26 (4f1898a to 90ca5a3) are an early skeleton that the issues above reviewed and partly rewrote.

**Planned, not built yet:** Muse Spark Open live on Baseten (#4), live Home Assistant actions (#9, dry run today), demo and submission (#11).

**Public open-source tools used, not written by us:** Meta SAM 3.1 weights and code, PANNs CNN14 (code MIT, weights CC BY 4.0), MediaPipe hand landmarker, OpenCV, NumPy, Baby Buddy (BSD-2-Clause), Home Assistant.
