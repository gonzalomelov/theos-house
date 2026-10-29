# parenting-agent

## For judges

Built with Muse Spark Open. Every number below is from a run during the event, and each folder's files say how it was measured. Every claim is checked in [results/honesty/claims.md](results/honesty/claims.md).

| Result | Headline | Run |
|---|---|---|
| [results/kr222/](results/kr222/) | Changing table on generated clips streamed live: both hands off spoken 15 of 15, max 1.68 s, SAM 3.1 confirming | Oct 27 |
| [results/hover/lift/](results/hover/lift/README.md) | Touch versus a 2 to 5 cm hover: the lift check caught 24 and 23 of 26 rendered hovers in two runs, 1 false voice on 16 touches, 15 of 16 on a fresh render (2 false voices). Before: 2 of 26 ([results/hover/](results/hover/README.md), Oct 28). Meta depth models scored at chance | Oct 29 |
| [results/carseat/](results/carseat/test.md) | Car seat coach on rendered clips: 11 of 12 wrong installs flagged, 1 of 12 false alarms, 4 of 4 unseen clips abstained | Oct 28 |
| [results/redteam/](results/redteam/README.md) | Red team round 1: 29 regression tests, all fail on the attacked code and pass after the fixes | Oct 28 |
| [results/glasses/](results/glasses/README.md) | Full glasses loop in the iOS simulator with Meta's mock Ray-Ban Meta. Real glasses not paired yet | Oct 28 |
| [results/muse/](results/muse/) | Per-call logs of Muse Spark Open as the brain | Oct 28 |

Run the tests with Python 3.11. No keys and no network needed, the live brain tests skip unless `PA_LIVE=1`:

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
```

What runs where:

| Machine | What runs there |
|---|---|
| Mac (M3 Max) | SAM 3.1 on the GPU, the MediaPipe hand reflex, PANNs house sounds, the glasses endpoint and the iOS simulator. Frames and audio stay here |
| Vostro (the family's home server) | The always-on family agent, the public demo at baby.bygmv.com and the families bot, each in a walled-off container, next to Baby Buddy and Home Assistant |
| Baseten | Muse Spark Open, the brain. It gets conversation text and tool results only |

Licenses: our code is MIT ([LICENSE](LICENSE)). Models and SDKs keep their own terms, see [THIRD_PARTY.md](THIRD_PARTY.md).

**A persistent agent built for new parents. It knows your baby, stays with you all day through your phone, glasses and home speakers, reminds you before you have to remember, and acts in your home while your hands stay on the baby. Video and audio stay in your house. Only the conversation text goes to the brain.**

What runs today: the phone (Telegram and a web page) and the kitchen Echo. The glasses app ran the full loop only in the iOS simulator with Meta's mock Ray-Ban Meta, real glasses are not paired yet (`results/glasses/README.md`). House actions run dry, except reading the house, one Echo announcement and one test shopping list item (`results/channels/check.json`, `results/house-plan/live-check.json`). Every claim in this repo is checked in [results/honesty/claims.md](results/honesty/claims.md).

Built during the Meta Global AI Developer Hackathon, which started Oct 26 2026 at 12 PM ET. Prior work from Oct 21 to 25 is named in [Prior work](#prior-work-oct-21-to-25-2026-before-the-event). See [what was built during the hackathon](#built-during-the-meta-global-ai-developer-hackathon-oct-26-to-nov-4-2026) and [docs/architecture.md](docs/architecture.md).

It logs, reminds and alerts. It is built to never give medical advice and never diagnose: a rule gate refuses health questions and answers red flags (not breathing, blue lips, choking, a fall) with "call emergency services now" without a brain call (`parenting_agent/agent/rules.py`), and the brain's prompt forbids advice. The gate is a word list, so the prompt is the last line for anything it misses (`results/redteam/README.md`). It never replaces staying within arm's reach of the baby.

## How it works

One long-running agent sits in the middle. Everything it sees, hears and does goes through an event bus.

- **Memory.** The baby's log lives in Baby Buddy, an open-source baby tracker running on the family's own server. The agent's own notes and conversation live in a local SQLite file.
- **Brain.** A model with tools decides what to do: log a feed, answer a question from the log, arm a skill, act on the house. Anything outside the allowed list waits for a parent's yes.
- **Skills.** The changing-table and bath skills watch through a head-worn camera. A local hand detector raises the alarm in under a second when both hands leave the baby, and Meta's SAM 3.1 confirms or cancels the alarm. A hand held 2 to 5 cm above the baby looks like a touch to both, so a lift check measures how much the hand grew toward the head camera. On rendered hovers (Oct 29) it caught 24 and 23 of 26 in two runs with 1 false voice on 16 touches, and 15 of 16 with 2 false voices on a fresh render, against 2 of 26 before (`results/hover/lift/README.md`). Meta's depth models did not see the lift and are not used. It is untested on a real hand.
- **Daily rhythm.** From the log it learns the baby's patterns and speaks first: the next feed, unusual days, a night summary and a fair split of the night between two parents.
- **House.** Home Assistant is its hands: lights, notifications, speakers, the robot vacuum, the TV, as tools behind the action policy (`parenting_agent/house_tools.py`). It runs dry until `house.live` is true in the agent config, and only Gonza turns that on.

## Meta models

| Job | Model | Where it runs |
|---|---|---|
| Confirms or cancels the hand alarm at the changing table and in the bath. A 2 to 5 cm hover is caught by the lift check instead, see `results/hover/lift/README.md` (Oct 29) | **SAM 3.1**, Meta's open weights | On the Mac's GPU, 1.5 to 3 s per frame. Frames never leave the house |
| The agent's brain, in the family agent, the families bot and the public demo | **Muse Spark Open** (`meta-models/muse-spark-open-1026`), Meta's open weights | Baseten's OpenAI-compatible API, synchronous calls only (`config/agent.json`, `config/agent.vostro.json`). Every call logs its model and host as a `brain_call` event. Per-call logs from Oct 28 runs in `results/muse/` |
| Second pair of eyes in the car seat coach: one zoomed still per step, handle and level line, a pass needs SAM 3.1 and Muse both. On 28 test renders (Oct 29) 12 of 12 wrong installs not passed, 0 false alarms, see `results/carseat/muse/README.md` | **Muse Spark Open**, image input | Baseten, opt-in (`car_seat.muse`). The still is sent once and never saved |
| Cry reason from the sound, a guess next to the log | **Muse Spark Open**, audio input | Built and off: on Oct 29 the Baseten endpoint did not hear audio (0 audio tokens, canary failed in 4 formats), so no cry audio is sent. See `results/sounds/muse/README.md` |
| Fallback brain, only when a Muse call errors | Claude Haiku 5.5 | Anthropic API. Each fallback is a `brain_fallback` event and a stderr line, so it is counted, never silent |

## Private by design

| Data | Where it goes |
|---|---|
| Camera frames | Stay in memory on the Mac. SAM 3.1 and the hand detector run locally. Nothing is saved, only numbers and states in `runs/`. Opt-in exception: with `car_seat.muse` on, one zoomed still per car seat step goes to Muse Spark Open on Baseten |
| House audio | Labelled on the Mac by PANNs, never saved, only labels and numbers in `results/` (see `docs/house-sounds.md`). Opt-in exception, off by default: the first 5 s of a detected cry may go to Muse Spark Open on Baseten for a guess at the reason, and only after a synthetic audio canary passes. On Oct 28 and 29 the canary failed, so no house audio has been sent |
| The baby's log | Baby Buddy on the family's server, reachable only on that server (see `docs/deploy-babybuddy.md`) |
| The agent's memory | `data/memory.sqlite` and `data/events.jsonl` on the machine that runs it, on the Vostro in `~/apps/parenting-agent-data` |
| **What leaves the house** | The brain call: the conversation text and tool results (baby log lines included) go to the configured brain, Baseten for Muse Spark Open, Anthropic only when a Muse call errors and Claude answers as the fallback. Every call logs its destination host as a `brain_call` event. Baseten's docs say it does not store inputs or outputs of synchronous calls by default (https://docs.baseten.co/observability/security). Anthropic deletes API inputs and outputs within 30 days by default (https://privacy.claude.com/en/articles/7996866). Telegram messages also go through Telegram's servers. No frame and no audio leaves, except two opt-in Muse senses that are part of the brain call to Baseten: one zoomed still frame per car seat camera step (`car_seat.muse`), and the first 5 s of a detected cry (`house_sounds.muse_audio`), each sent once in memory and dropped. See `docs/car-seat-coach.md` and `docs/house-sounds.md` |

## Run it

```bash
python -m parenting_agent --check                                  # load everything, print brain, plug-ins and tools, exit
python -m parenting_agent                                          # Muse Spark Open, Claude only as a logged fallback
python -m parenting_agent --config config/agent.fake.json          # offline, rule-based brain
python -m parenting_agent --config config/agent.muse-baseten.json  # Muse Spark Open alone, no fallback (needs BASETEN_API_KEY)
```

Keys are read from a git-ignored `.env` (path in `config/agent.json`). Baby Buddy is reached through an SSH tunnel:

```bash
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro   # see docs/deploy-babybuddy.md
```

## Always on, on the family server (issue #15)

The agent runs 24/7 on the Vostro in its own walled-off container: it reaches Baby Buddy and Home Assistant through a relay and the brain and Telegram through an allowlisting proxy, and nothing else. It restarts on its own, keeps its data in a volume, and house actions stay dry run. Deploy, update, logs, stop and rollback with `sh deploy/agent.sh`, see `docs/deploy-agent.md`.

## Baby log in Baby Buddy (issue #2)

Notes like "bottle, 120 ml", "wet and dirty diaper", "she napped from 14:00 to 15:00" or "just gave her a bath" become Baby Buddy entries. Questions like "when was the last dirty diaper?" or "how much did she drink today?" are answered from Baby Buddy through the `baby_summary` and `read_baby_log` tools. Health questions get a kind refusal and a suggestion to call the pediatrician. Notes arrive as text or as Telegram voice notes: Muse Spark Open hears the voice note itself and the answer comes back as text and as a voice note in Meta's MMS-TTS voice, see `docs/voice.md`.

- `parenting_agent/agent/babybuddy.py`: Baby Buddy as the baby log. Baths are notes that start with "Bath". "Asleep" starts a timer and "awake" turns it into a sleep record. Entries are never timed in the future. A feed whose estimated start overlaps the previous feed starts right after it.
- `config/agent.json` and `config/agent.muse-baseten.json` use Baby Buddy (`baby_log.provider: babybuddy`, URL and token from the env file, reached through the tunnel in `docs/deploy-babybuddy.md`). `config/agent.fake.json` keeps the offline log in the agent's memory file.
- `scripts/voice_log_run.py`: the real run for a usage goal check 2 (the KR calls it the voice log, the notes are typed text). It sends notes through the agent and the brain, reads each record back from Baby Buddy by id and writes `results/kr222/voice-log.json`.

Changing-table skill on generated clips streamed in real time:

```bash
scripts/sam3-setup.sh   # once, SAM 3.1 on the Mac GPU, see docs/sam3-local.md
python scripts/kr222_table.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/kt/clips --passes 5
```

Bath skill (issue #10), armed by "bath time" and logged by "bath done", the second camera skill and config only (`skills/bath.json`). See `docs/bath.md`.

```bash
python scripts/bath_run.py --baths 10   # bath clips streamed live, Muse brain, Baby Buddy, SAM 3.1
```

Simulated baby week and daily rhythm: see `docs/simulated-week.md` and `docs/daily-rhythm.md`.

Sitter handover: one message briefs a grandparent or a sitter from the log, the parent approves it first, and a time-boxed guest role logs feeds and diapers. See `docs/sitter-handover.md`.

Simulated full day, 06:10 to 02:30 (issue #17), the demo rehearsal in one command:

```bash
python -m parenting_agent.fullday              # Muse brain, Baby Buddy, SAM 3.1, the clips streamed live
python -m parenting_agent.fullday --no-video   # skip the two clip steps
python -m parenting_agent.fullday --wipe-only  # remove the entries earlier runs wrote (tag full-day-sim)
```

It replays the plan page day through the real agent: a typed "bottle, 120 ml" on the ear channel, the changing table on the clips with a typed dirty diaper note, a doorbell during the change, a long-nap note, the bath on its clip, a question answered from the log, and the night feed with the next feed and the next parent on duty. It writes `results/fullday/day.md`, `day.json` and the KR files in `results/fullday/kr222/`. The recorded run is from Oct 27 with the Claude brain, before Muse became the brain. What was not built on Oct 27 shows as dry run in that report: Home Assistant actions (#9), delivery on Telegram, the ear and the speakers (#3, #8) and the house sound detector (#14). See `docs/full-day.md`.

## Daily house plan: vacuum, shopping list, dinner and white noise (issues #29 and #32)

The vacuum pauses and goes home when a nap starts and never starts when the run would reach a predicted nap. It starts alone only when nobody is home or the baby is out, otherwise it asks. "Clean under the high chair" is a room clean, there is one daily run at the quietest awake time, diapers go on `todo.shopping_list` before they run out, a bad night gives a draft of fast Thermomix dinners from Cookidoo (read only, through home-agents), a reminder says when to start dinner, and white noise follows the rhythm under a 50 dB cap in code. The cap uses a placeholder calibration (70 dB at full level) until the machine exists and is measured, so no dB number here is measured. The Thermomix is never controlled. See `docs/house-plan.md`.

```bash
python scripts/house_plan_check.py   # live and safe: reads the vacuum, dry runs pause and home, one test list item added and removed
```

## Telegram and channel picking (issues #3 and #8)

The agent hears and speaks on Telegram through @home_agent_example_bot, with long polling over plain HTTPS, so nothing is exposed. Only the family's chat ids (`TELEGRAM_CHAT_ID` in the env file, comma separated) are accepted. Other senders are ignored and logged as `channel_ignored` with their chat id only. Messages reach the same agent and the same memory as every other channel.

- `parenting_agent/channels/messaging.py`: one messaging adapter interface and the channel plug-in that runs it. WhatsApp later is a new adapter only.
- `parenting_agent/channels/telegram.py`: the Telegram adapter. Text and voice notes (getFile download, sendVoice reply).
- `parenting_agent/voice/`: the ears and the voice. `ear.py` sends the voice note to Muse Spark Open as audio input, `tts.py` speaks with MMS-TTS, `server.py` is the walled voice service on the Vostro. See `docs/voice.md`.
- `parenting_agent/channels/router.py`: picks one channel for each `notify` event and each agent reply on the channel `auto`. Help needed goes to the partner (a stub, Ceci has no phone channel yet). Away or unknown presence goes to Telegram. At home with a skill armed, or with the baby asleep, it goes to the ear (the Mac speaker for now). At home with hands free it goes to the kitchen Echo at low volume, and the volume is put back after. Presence comes from `person.gonza`, then `device_tracker.gonzas_iphone`.
- `scripts/channels_check.py`: the real checks, a Telegram round trip, one Echo announce and a reminder routed with presence simulated as away. Results in `results/channels/check.json`.

Home Assistant is reached through `ssh -f -N -L 127.0.0.1:18123:127.0.0.1:8123 vostro`, token `HA_MCP_TOKEN`.

## Before he arrives (issue #56)

Theo is not born yet, so the family agent helps get ready: prep lists for the nursery (from the home twin's measured plan), the hospital bag, the car seat and the white noise machine, appointments, a countdown to the due date, and one short morning nudge to Gonza on Telegram. Logistics only, never medical. Every message is a `turn` event with the person who sent it, so the daily-use KR is scored from the agent's own log. See `docs/before-he-arrives.md`.

## Car seat coach (issue #30)

The agent coaches an infant carrier install with the car's seat belt, one step at a time by voice. SAM 3.1 on the Mac checks what the head camera can see: the lap belt in both side guides, the shoulder belt in the rear guide, no twist, the level line, the handle upright. The movement test at the belt path and the harness pinch test are asked and logged. Its spoken lines never use the word "safe" (a filter on the coach's own lines, `parenting_agent/carseat/coach.py`), it lists what passed and what remains and suggests one check by a certified technician. The steps and limits come from the maker's manual (Joie i-Snug 2). The car rules come from Tesla's published child seat pages, not yet checked against the printed manual. An outgrow watch compares Baby Buddy weight and height with the seat's limits. Tested on 3D-rendered clips with planted mistakes, see `docs/car-seat-coach.md` and `results/carseat/`.

## Ray-Ban Meta glasses (issue #57)

`apps/glasses` is an iPhone app on Meta's Wearables Device Access Toolkit. It streams the glasses camera, sends 10 frames a second to the agent on the family's Mac over the home network (`parenting_agent/glasses.py`, pairing token, never a public address), sends the parent's phrases (a button or typed text, there is no speech recognition in the app yet), and shows and speaks what the agent answers. On Oct 28 the full loop ran in the iOS 27 simulator with DAT's mock Ray-Ban Meta playing the synthetic changing-table clip: "changing time", both hands off, "hand" spoken, "done", change logged. Real glasses are not paired yet. See `apps/glasses/README.md` and `results/glasses/README.md`.

```bash
python -m parenting_agent --config config/agent.glasses.json   # Muse Spark Open brain, glasses channel, changing table and bath on the glasses
```

## Public demo app

A phone-first web chat where anyone can talk to the real agent core about Demo Baby, a simulated baby on the simulated week, with a simulated house. Each visitor gets their own copy, health questions get the kind refusal, and the process carries only the brain keys. Live at https://baby.bygmv.com since Oct 28 2026. See `docs/demo-app.md`.

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
PA_LIVE=1 python -m unittest tests.test_agent    # also runs the same conversation with the configured live brain
PA_LIVE=1 PYTHONPATH=tests python -m unittest tests.test_voice_log   # notes, questions and the safety check with the live brain
```

## Built during the Meta Global AI Developer Hackathon (Oct 26 12 PM ET to Nov 4 9 PM ET 2026)

The repo was created on Oct 26 2026 at 15:03 Montevideo time (14:03 ET), after the 12 PM ET start. Its code was written during the event, but parts were ported from prior work, listed below.

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
| Public demo app with a simulated baby, live at baby.bygmv.com since Oct 28 | #33 | #34 | see PR |
| Always on: the agent in a walled-off container on the Vostro | #15 | #35 | see PR |
| Telegram channel and channel picking | #3, #8 | #36 | see PR |
| House sounds, why is he crying, white noise | #14, #32 | see PR | see PR |
| Sitter handover, time-boxed guest role, summary after | #16 | see PR | see PR |
| Invited families on Telegram, one private log per family, walled off | #40 | see PR | see PR |
| Bath skill, camera skills from config | #10 | #42 | see PR |
| Simulated Tesla: cabin ready, car naps, Child Left Alone Detection check | #31 | #43 | see PR |
| Daily house plan: vacuum around naps, shopping list, fast dinners, white noise | #29, #32 | #44 | see PR |
| Car seat coach: manual to steps, SAM 3.1 visible checks, hand checks, outgrow watch, rendered test clips | #30 | #47 | see PR |
| Touch versus hover ablation, reflex only against SAM 3.1, the voice waits for SAM 3.1 on near readings (Oct 28) | #6, #10 | see PR | see PR |
| Voice notes heard by Muse Spark Open, answers spoken with Meta MMS-TTS, walled voice service (Oct 28) | #58 | see PR | see PR |
| Hover lift check: hand growth toward the head camera, Meta depth models tried and not used (Oct 29) | #6, #10 | see PR | see PR |

| Muse Spark Open as the brain of the family agent, the families bot and the demo, Claude only as a logged fallback | #4 | #61 | 115dc2e |
| Red team round 1 closed, a regression test per attack | #60 | #63 | ed6c488 |

The first commits of Oct 26 (4f1898a to 90ca5a3) are an early skeleton that the issues above reviewed and partly rewrote. Commit f41acfa ports the reflex and the chime then voice alarm from the prior work below.

**Planned, not built yet:** the glasses app on real glasses, live Home Assistant actions (#9, dry run today), demo and submission (#11).

## Prior work (Oct 21 to 25 2026, before the event)

Built in the prep repo `gonzalomelov/meta-hackathon-2026` (64 commits from Oct 21 to 25) and reused here. None of its numbers is used as event evidence.

| Prior work | Date | Reused here as |
|---|---|---|
| MediaPipe hand reflex with the contact rule, chime on every alarm then a spoken prompt after a 1.2 s hold | Oct 22 to 23 | `reflex.py`, `alarm.py` (ported in f41acfa) |
| SAM 3.1 run locally from Meta's weights, then on the Mac GPU (MPS) | Oct 23 to 24 | `scripts/sam3-setup.sh`, `sam3_worker.py` |
| Touch versus hover kill test, 21 of 21 hovers read off on one clip | Oct 23 to 24 | Not used. Replaced by the Oct 28 ablation in `results/hover/README.md` |
| iPhone Safari page as the head camera over Tailscale | Oct 23 | `sources.py`, `phone.html` |
| PANNs CNN14 labels under speech (18 of 24 events at 0 dB) and the thresholds, Tapo microphone listening | Oct 23 | `hearing.py` thresholds, `docs/house-sounds.md` |
| Home Assistant MCP check and actions driven by live events | Oct 21 to 23 | the house layer design |
| Generated changing-table clips (Oct 22), the generated bath clip and the hover clip (Oct 23) | Oct 22 to 23 | test clips outside git, the bath set was re-cut from it on Oct 28 |
| Positioning, the Baby Buddy safety vet, the day 1 runbook | Oct 23 to 25 | planning only |

**Public open-source tools used, not written by us:** Meta SAM 3.1 weights and code, Meta MMS-TTS weights (facebook/mms-tts-spa and facebook/mms-tts-eng, CC-BY-NC 4.0, non-commercial), FFmpeg, PyTorch and Hugging Face Transformers, PANNs CNN14 (code MIT, weights CC BY 4.0), MediaPipe hand landmarker, OpenCV, NumPy, Baby Buddy (BSD-2-Clause), Home Assistant.
