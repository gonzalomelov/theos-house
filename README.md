# parenting-agent

**Live demo: https://baby.bygmv.com** (phone first, no sign-in, a simulated baby and a simulated house, nothing real moves)

A persistent agent for new parents, built with Muse Spark Open and SAM 3.1 during the Meta Global AI Developer Hackathon (Oct 26 2026 12 PM ET to Nov 4 2026 9 PM ET).

## Built during the event, and what is prior work

| When | What | Where |
|---|---|---|
| Oct 21 to 25, before the event (prior work) | The MediaPipe hand reflex with the contact rule and the chime then voice alarm, built Oct 22 to 23 in the private prep repo | Not in this repo since Oct 31: it is the separate private library `a private repo` v0.1.0, installed by `requirements-prior.txt`. `reflex.py` and `alarm.py` here hold only the event-time changes, as subclasses. Without the library the skills run SAM 3.1 only. It was ported in on Oct 26 (f41acfa) and moved out on Oct 31 |
| Oct 21 to 25, before the event (prior work) | SAM 3.1 run locally on the Mac GPU, the iPhone Safari camera page, the PANNs sound thresholds (PANNs left the runtime on Oct 31) | ported into `scripts/sam3-setup.sh`, `sam3_worker.py`, `sources.py`, `phone.html`, and `hearing.py` until Oct 31. Full list in [Prior work](#prior-work-oct-21-to-25-2026-before-the-event) |
| Oct 26, after the 12 PM ET start | The repo's first commit, 4f1898a at 14:03 ET, and the agent core skeleton | 4f1898a to 90ca5a3 |
| Oct 27 | SAM 3.1 confirms or cancels the hand alarm | c0d7b5d (PR #25) |
| Oct 28 | Muse Spark Open becomes the brain of all three agents, the public demo, the glasses app on Meta's mock device | 115dc2e (PR #61), PR #34, b571201 (PR #65) |
| Oct 29 | The lift check that catches a hand hovering 2 to 5 cm, SAM 3.1 hand masks anchoring it, Muse plans the house, the families log ops | 4436ccd (PR #75), 9092ad0 (PR #93), 18160b5 (PR #118), 19c0523 (PR #117) |
| Oct 30 | One first-month day and night end to end, the HUD on the Ray-Ban Display through DAT's Display API | 3fd0bc3 (PR #149), 5eb98d3 (PR #155) |

Everything from Oct 26 on is event work. Details in [Built during the hackathon](#built-during-the-meta-global-ai-developer-hackathon-oct-26-12-pm-et-to-nov-4-9-pm-et-2026).

## Run it from a clean clone

Python 3.11. No keys and no network needed for the tests and the offline brain:

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests                                   # fake brain, live brain tests skip unless PA_LIVE=1
.venv/bin/python -m parenting_agent --config config/agent.fake.json --check      # load the agent with the offline, rule-based brain
.venv/bin/python -m parenting_agent.demo --brain-env FILE                         # the demo on http://127.0.0.1:8765, FILE holds BASETEN_API_KEY
```

The camera skills run SAM 3.1 only on such a clone. The MediaPipe reflex and alarm are prior work (Oct 22 to 23) in a separate private library: with access, `.venv/bin/pip install -r requirements-prior.txt` adds it, and `"hands"` in the agent config picks `mediapipe`, `sam3_only` or `auto`.

More in [Run it](#run-it).

## For judges

Built with Muse Spark Open. Every number below is from a run during the event, newest first, and each folder's files say how it was measured. The claims up to PR #153 are audited, each with its file and whether it holds, in [results/honesty/claims.md](results/honesty/claims.md).

| Result | Headline | Run |
|---|---|---|
| [results/hero2/](results/hero2/README.md) | The hero run on Muse and SAM 3.1, glasses app in the iOS simulator with Meta's mock Ray-Ban Meta: Muse armed the watch in 3 of 3 takes, both hands off spoken 6 of 6, a 2.5 cm hover spoken 6 of 6, one hand on kept silent 11 of 11, "done, it was dirty" logged dirty in Baby Buddy and read back 3 of 3. Without SAM 3.1's hand regions, one run: 1 of 2 hovers | Oct 29 |
| [results/muse-vs-haiku/](results/muse-vs-haiku/README.md) | Is Muse needed? An offline comparison, Haiku never runs in the agent. Same prompts and checks, only the model changed, two runs each: log ops a tie (0 of 45 wrong for Muse and for Claude Haiku 5.5, 36 of 36 for both on the round 4 set). House planner: Muse 3 of 4 adaptation cases in both runs, Haiku 2 of 4 in both. Four cases the team wrote, a one-case gap. Haiku costs about 11 to 15 times less per call | Oct 30 |
| [results/e2e-day/](results/e2e-day/README.md) | One first-month day and night through the real family agent on a fast clock, real Muse, real Baby Buddy, Home Assistant writes forced dry, Telegram captured: things a parent must get 11 of 34 before, 30 of 34 after, noise 16 of 55 before, 0 of 58 after, log 25 of 25 | Oct 30 |
| [results/demo-house/](results/demo-house/README.md) | Tonight's house on baby.bygmv.com: Muse plans the simulated house and re-plans on "let me sleep", checked by plain code, nothing moves. Since Oct 30 a day visit plans the coming night from 19:00, and Muse's why never names a routine the checks refused | Oct 30 |
| [results/families-log-ablation/](results/families-log-ablation/README.md) | Families bot, fifth blind set of 45 tired-parent messages, scored once: Muse log ops 1 of 45 wrong log states, the old rule guards 13 of 45. Both runs use Muse. On Oct 30 Claude Haiku 5.5 ran the same log ops design and tied: on a rerun of this set, two runs each, both models made 0 wrong log states ([results/muse-vs-haiku/](results/muse-vs-haiku/README.md)), so log ops is a design result, not a Muse-only one. The four blind sets before scored 8, 8, 5 and 11 wrong on the old design. Log ops is the families default. After the round 4 fixes a fresh set of 36 Spanish messages went 36 of 36, from 29 of 36 ([results/babylog-r4/](results/babylog-r4/README.md)) | Oct 29 |
| [results/hover/held/](results/hover/held/README.md) | A diaper, a wipe or a bottle in the hand, fresh blind set scored once: 19 of 24 hovers spoken within 2.5 s (the target of 20 missed by one, the other 5 spoken late), "hand" said on 1 of 12 touches, but the chime sounded on 9 of 12 touches. Before, on main: 6 of 24 and 10 of 12. SAM 3.1's hand region carries the hand when MediaPipe loses it under the object | Oct 29 |
| [results/dog-near-baby/](results/dog-near-baby/README.md) | Dog near the baby, SAM 3.1 on the Mac, blind set frozen before the design: 3 of 8 real photos caught and 12 of 12 composites (cut with SAM 3.1's own masks, so they favour it), 15 of 20 in all, 0 false alerts on 49. Expect missed dogs. Alert to Telegram, Echo in dry run. Runs only while the Mac is on | Oct 29 |
| [results/muse-house/](results/muse-house/README.md) | Muse plans the house: passed 3 of 4 adaptation cases the fixed rules fail (a parent asks to sleep, a dog barks in a nap, the doorbell before a nap). The long nap case fails for both. On the day checks Muse matched the fixed rules, it changed no outcome, and the shipped setting was not rerun on the day. Muse named the wrong parent once in each of two runs, so the rota stays fixed unless a parent asks to sleep | Oct 29 |
| [results/safety-gate-r4/](results/safety-gate-r4/README.md) | Safety gate on a held-out set written before the round 4 fix: 35 of 44 red flags put on the call 911 now line (13 of 44 before), 0 of 44 everyday lines put on it. The same agent wrote the set and the fix, so it is fresh phrasing, not a third party's blind set. No log guard replaces a safety answer any more | Oct 29 |
| [results/night-feed/](results/night-feed/README.md) | The 3 AM feed on six simulated nights: the parent was pushed 0 times and the white noise lowered 0 times while the baby slept (12 and 9 before the change), 8 of 8 bottles had warm water at the feed start with the cry on the microphone, 2 of 8 on the rhythm guess alone. The cry timing is an assumption. The warmer is a virtual dry switch, its per-night cap lives in the agent's memory, so a restart in the night starts it over | Oct 29 |
| [results/redteam/](results/redteam/README.md) | Red team round 1: 29 regression tests, all fail on the attacked code and pass after the fixes. Round 2: 38 tests, 27 fail before, all pass after (PR #81). Round 4 house findings: 14 of 16 tests fail before and pass after, the other 2 are controls ([results/redteam/round4-house/](results/redteam/round4-house/README.md)) | Oct 28, Oct 29 |
| [results/hover/blind/](results/hover/blind/README.md) | Touch versus a 2 to 5 cm hover with empty hands, blind set frozen before the design: the final design caught 22 of 32 hovers and never said hand on 16 touches, 2 touches chimed. Lift with SAM 3.1 hand masks: 23 of 32, never said hand on a touch, 1 touch chimed. Lift alone, no SAM 3.1: 21 of 32, said hand on 1 touch, 2 touches chimed. Reflex alone: 0 of 32. 8 of the 16 bath hovers show one hand and are missed by design since the bath fix. Meta depth models were too weak to use, AUC 0.41 to 0.66 | Oct 29 |
| [results/bath/onehand/](results/bath/onehand/README.md) | Bath fix: one hand on the baby stays silent 10 of 10, both hands off spoken 10 of 10, SAM 3.1 confirm on. Before the fix the one-hand clip spoke "hand" in 5 of 10 baths (PR #92) | Oct 29 |
| [results/carseat/](results/carseat/test.md) | Car seat coach on rendered clips: 11 of 12 wrong installs flagged, 1 of 12 false alarms, 4 of 4 unseen clips abstained. SAM 3.1 is essential here: Muse alone got the shoulder belt right 12 of 28 times, and nothing else checks a belt ([results/meta-models/](results/meta-models/README.md)) | Oct 28, Oct 29 |
| [results/fullday/](results/fullday/README.md) | The simulated full day with Muse as the brain, the clips and SAM 3.1: 7 of 7 steps at 01:13, 6 of 7 at 01:00 (the doorbell failed) | Oct 29 |
| [results/kr222/](results/kr222/) | Changing table on generated clips streamed live: both hands off spoken 15 of 15, max 1.68 s, SAM 3.1 confirming. No brain call in this check | Oct 27 |
| [results/glasses-day/](results/glasses-day/README.md) | Everything the agent tells a parent as a card on that parent's Ray-Ban Display, live on a compressed day: the family agent on this Mac, Muse, Baby Buddy, SAM 3.1 for the car seat, the display through DAT's Display API on Meta's mock. 11 of 11 scenes, each card only on the right parent's glasses, red flags sticky and never dimmed. Glasses and lens simulated | Oct 30 |
| [results/glasses/](results/glasses/README.md) | Full glasses loop in the iOS simulator with Meta's mock Ray-Ban Meta. Real glasses not paired yet | Oct 28 |
| [results/muse/](results/muse/README.md) | Muse Spark Open as the brain: latency, cost, fallbacks and per-call logs | Oct 28 |

What runs where:

| Machine | What runs there |
|---|---|
| Mac (M3 Max) | SAM 3.1 on the GPU, the MediaPipe Hands reflex (Google's hand model, prior work), house sounds heard by Meta's Perception Encoder Audio, the glasses endpoint and the iOS simulator. Frames and audio stay here, apart from two opt-in Muse senses, both off by default: a car seat still and a cry clip |
| Vostro (the family's home server) | The always-on family agent, the public demo at baby.bygmv.com and the families bot, each in a walled-off container, next to Baby Buddy and Home Assistant |
| Baseten | Muse Spark Open, the brain and the only model called off the Mac. It gets messages, voice notes, tool results with baby log lines and, only when turned on, a car seat still or a cry clip. All on the free hackathon credits, where Meta may use them to train future Meta models |
| Amazon | The kitchen Echo. Alexa's cloud hears what is said to the Echo and speaks the agent's answers and announcements. The "baby agent" skill runs as an AWS Lambda on Gonza's Amazon account, see [What stays home and what leaves](#what-stays-home-and-what-leaves) |

Licenses: our code is MIT ([LICENSE](LICENSE)). Models and SDKs keep their own terms, see [THIRD_PARTY.md](THIRD_PARTY.md).

**My world before my son arrives: a persistent agent for new parents, built while we wait for Theo. Today it keeps the baby log from your phone (Telegram and a web page), tells you first when the next feed is due, when he cries shows what the log says (last feed, last diaper, time awake), never a medical reason, and says "hand" when both your hands leave the baby on a head camera, tested so far on generated clips only. Glasses run only in the iOS simulator so far. In the house three actions are allowed to act for real since Oct 30: the study light, the vacuum pause and dock, and the shopping list. None has moved yet (no live write in the family agent's log up to Nov 1 10:30), and everything else runs dry. Video and house audio stay in your house, apart from two opt-in senses that are off by default: a car seat still and a cry clip. Messages, voice notes and the log lines the agent reads go to the brain, Muse Spark Open on Baseten. Those calls run on the free hackathon credits, where Meta may use what is sent to train future Meta models, so we do not promise they stay private. What is said to the kitchen Echo, and the answer it speaks, goes through Amazon.**

What runs today: the phone (Telegram and a web page) and the kitchen Echo. The glasses app ran the full loop only in the iOS simulator with Meta's mock Ray-Ban Meta, real glasses are not paired yet (`results/glasses/README.md`). Three live tests ran in the house: one Echo announcement (`results/channels/check.json`), one test shopping list item added and removed (`results/house-plan/live-check.json`) and one Telegram dog alert to Gonza (`results/dog-near-baby/README.md`). Since Oct 30 the family agent on the Vostro has three live house actions, Gonza's yes in chat: the study light goes on dim and warm in the night feed on a real awake signal (the baby, in English or Spanish, never the parent or the dog) and off after the feed, the vacuum pauses and goes back to its base when a nap or night sleep starts (never a start or a resume), and diapers, wipes or formula that run low, or an item a parent asks for, go on the Home Assistant shopping list, never twice and never removed (at most 6 light, 4 vacuum and 6 shopping list writes, `docs/home-assistant-inventory.md`). The study light read unavailable at 06:35 on Oct 30 and is back online: at 19:26 Home Assistant read it with a state (off), so the next real awake signal at night can switch it. Live means allowed, not done: on Nov 1 at 10:30 the family agent's event log, from Oct 28 on, held no `house_live` write, so no device has moved for real so far. A device that reads unavailable gets nothing sent, and the reply says so. Everything else is a dry run, and reading the house is read only. Ceci is connected to the family bot: her chat id is configured on the Vostro and the agent's start event shows her chat as connected. Her messages get their own replies. Since Oct 30 the pushes the agent starts on its own go to the right parent over Telegram: one short morning message per parent with only what is theirs (the brief, the night explanation and the prep nudge merged), shared ones (supplies, tonight's plan) to both, each scheduled push at most once a day per parent across restarts, night pushes to the parent on duty from the night rota, a reminder to whoever asked, and a question that waits for a yes to one parent, whose yes alone answers it (`docs/before-he-arrives.md`, `parenting_agent/channels/push.py`). Claims are audited in [results/honesty/claims.md](results/honesty/claims.md).

Built during the Meta Global AI Developer Hackathon, which started Oct 26 2026 at 12 PM ET. Prior work from Oct 21 to 25 is named in [Prior work](#prior-work-oct-21-to-25-2026-before-the-event). See [what was built during the hackathon](#built-during-the-meta-global-ai-developer-hackathon-oct-26-12-pm-et-to-nov-4-9-pm-et-2026) and [docs/architecture.md](docs/architecture.md).

It logs, reminds and alerts. It is built to refuse medical advice and diagnosis. Red flags get: call 911 now. The agent never calls anyone itself. A rule gate refuses health questions and answers red flags (not breathing, gasping, blue lips, choking, a fall, under water in the bath, a swallowed battery or magnet, a bulging or sunken soft spot, a fit or whole body shaking, a dog bite, and in pregnancy green or brown fluid or contractions a few minutes apart, in English and rioplatense Spanish) with "call emergency services now" without a brain call (`parenting_agent/agent/rules.py`), and the brain's prompt forbids advice. A safe sleep question (tummy or back, the crib, bed sharing) gets the AAP's public line with its source (https://www.healthychildren.org/English/ages-stages/baby/sleep/Pages/a-parents-guide-to-safe-sleep.aspx), the same every time, never a refusal with no fact and never advice about one baby. The gate is a word list, so the prompt is the last line for anything it misses (`results/redteam/README.md`). On a held-out set written before the round 4 fix it caught 35 of 44 red flags and put 0 of 44 everyday lines on the 911 line. The six phrasings the round 5 auditor found missing (blue around the mouth, purple and blotchy skin, a dog that snapped or broke the skin, tarascón, dropped out of my arms, tumbled down stairs) and a bottle too hot that made him scream were added on Oct 30, with the auditor's six false 911 lines (chokes on laughter, limp with sleep, the dog bit his toy) kept off and the held-out everyday set still at 0 of 44 (`tests/test_round5.py`), and no log guard replaces a reply that names a red flag or sends the parent to help (`results/safety-gate-r4/README.md`). It never replaces staying within arm's reach of the baby.

## How it works

One long-running agent sits in the middle. Everything it sees, hears and does goes through an event bus.

- **Memory.** The baby's log lives in Baby Buddy, an open-source baby tracker running on the family's own server. The agent's own notes and conversation live in a local SQLite file.
- **Brain.** A model with tools decides what to do: log a feed, answer a question from the log, arm a skill, act on the house. Anything outside the allowed list waits for the yes of the parent who was asked, on the chat where it was asked.
- **Skills.** The changing-table and bath skills watch through a head-worn camera. By default a local hand detector, Google's MediaPipe Hands (prior work, Apache 2.0), raises the alarm in under a second when both hands leave the baby, and Meta's SAM 3.1 confirms or cancels the alarm. A hand held 2 to 5 cm above the baby looks like a touch to both, so a lift check measures how much the hand grew toward the head camera. On the changing table it measures inside SAM 3.1's hand masks. In the bath it needs both hands, so one hand on the baby never reads as a hover (one hand silent in 10 of 10 baths, both hands off spoken 10 of 10, `results/bath/onehand/README.md`). On a blind set frozen before the design (Oct 29) it caught 22 of 32 hovers and never said hand on 16 touches, 2 touches chimed, against 0 of 32 for the reflex alone and 21 of 32 without SAM 3.1, which said hand on 1 touch. 8 of the 16 bath hovers show one hand and are missed by design (`results/hover/blind/README.md`). An earlier, smaller blind render gave 15 of 16 hovers with 2 false alarms on 16 touches (`results/hover/lift/README.md`). Meta's depth models did not see the lift and are not used. It is untested on a real hand. One setting, `"hands": "sam3_only"`, runs the skills on SAM 3.1 alone with no MediaPipe, in case the organizers rule MediaPipe out: on the same blind set, scored once on Oct 31, 22 of 32 hovers (table 16 of 16, bath 6 of 16), 0 of 16 touches said hand, 2 chimed, the same totals as the MediaPipe design, but slower when both hands leave at once (a SAM 3.1 look takes 1.5 to 3 s). A clone without the prior work library runs this way (`results/hover/blind/README.md`).
- **Daily rhythm.** From the log it learns the baby's patterns and speaks first: the next feed, unusual days, a night summary and a fair split of the night between two parents.
- **House.** Home Assistant is its hands: lights, notifications, speakers, the robot vacuum, the TV, as tools behind the action policy (`parenting_agent/house_tools.py`). Everything runs dry except the actions named in `house.live_actions` (`parenting_agent/house_live.py`). Since Oct 30 that is the night feed's study light, nap mode's vacuum pause and dock and the shopping list add, on the family agent only. None of the three has fired for real yet (Nov 1). Replies say which happened: done for real, or only written down.

## Meta models

| Job | Model | Where it runs |
|---|---|---|
| Confirms or cancels the hand alarm at the changing table and in the bath, and its hand masks anchor the lift check that catches a 2 to 5 cm hover on the changing table (blind set Oct 29: 22 of 32 hovers, 0 of 16 false voices, against 21 and 1 without SAM 3.1). Essential in the car seat coach, the dog watch and the held object hover. Every Meta model with and without numbers: `results/meta-models/README.md` | **SAM 3.1**, Meta's open weights | On the Mac's GPU, 1.5 to 3 s per frame. Frames stay in the house, except the opt-in car seat still below |
| The agent's brain, in the family agent, the families bot and the public demo. It proposes the families log operations (fifth blind set 1 of 45 wrong, 13 of 45 with the old rule guards, both on Muse. Claude Haiku 5.5 on the same design tied, 0 of 45 for both on Oct 30, `results/muse-vs-haiku/`) and plans the house (3 of 4 adaptation cases, the fixed rules matched it on the day checks) | **Muse Spark Open** (`meta-models/muse-spark-open-1026`), Meta's open weights | Baseten's OpenAI-compatible API, synchronous calls only (`config/agent.json`, `config/agent.vostro.json`). Every call logs its model and host as a `brain_call` event. Per-call logs from Oct 28 runs in `results/muse/` |
| Second pair of eyes in the car seat coach: one zoomed still per step, handle and level line, a pass needs SAM 3.1 and Muse both. On 28 test renders (Oct 29) 12 of 12 wrong installs not passed, 0 false alarms, see `results/carseat/muse/README.md` | **Muse Spark Open**, image input | Baseten, opt-in and off by default (`car_seat.muse`). The same still goes in 3 parallel calls by default (`samples`, a majority vote), and we never save it |
| A label for a cry sound, shown next to the log, never advice | **Muse Spark Open**, audio input | Built and off: on Oct 29 Muse heard speech but not house sounds (11 of 46 labels against 41 for PANNs, which ran then, beep canary 0 of 3), so no cry audio is sent. See `results/sounds/muse/README.md` and `results/audio-truth/README.md` |
| Hears cries, the doorbell, a dog and a splash in the house: the cry is the night feed's awake signal. Zero shot from text prompts. On a held-out set written before tuning (Oct 31): 339 of 348 cries with 1 false alarm, against 331 of 348 and 0 for PANNs, the non-Meta model it replaced. The cry's likely reason still comes from the baby log, never from the sound (`results/sounds/meta-hearing/README.md`) | **Perception Encoder Audio Frame** (`facebook/pe-a-frame-small`, Apache 2.0), Meta's open weights | On the Mac's CPU (`scripts/hearing-setup.sh`). House audio stays in the house, except the opt-in cry clip (off by default, never sent so far) |
| The spoken answers of voice notes | **MMS-TTS** (`facebook/mms-tts-spa`, `facebook/mms-tts-eng`), Meta's open research weights, CC BY-NC 4.0 | In the voice container on the Vostro, or on the Mac |

Every model the agent runs is a Meta model, with one exception: by default the changing-table and bath skills use Google's MediaPipe Hands (prior work, Apache 2.0) on the Mac to propose the hands, and SAM 3.1 confirms or cancels. The setting `"hands": "sam3_only"` runs those skills on SAM 3.1 alone, with no MediaPipe: same blind set totals, slower when both hands leave at once (see Skills above). A clone without the prior work library runs that way. When a Muse call errors, the agent does not switch to another vendor's model: the fixed rules that run the tests answer instead (log a plain note, read the log, refuse health advice), and the reply starts by saying plainly that the brain is busy. Each fallback is a `brain_fallback` event and a stderr line, so it is counted, never silent. Claude Haiku appears only in offline model comparisons (`scripts/eval_brains.py`, `results/muse-vs-haiku/`), never in the agent, the demo or the families bot.

## What stays home and what leaves

| Data | Where it goes |
|---|---|
| Camera frames | Stay in memory on the Mac. SAM 3.1 and the hand detector run locally. Nothing is saved, only numbers and states in `runs/`. Opt-in exception, off by default: with `car_seat.muse` on, one zoomed still per car seat camera step goes to Muse Spark Open on Baseten |
| House audio | Labelled on the Mac by Meta's Perception Encoder Audio, never saved, only labels and numbers in `results/` (see `docs/house-sounds.md`). Opt-in exception, off by default: the first 5 s of a detected cry may go to Muse Spark Open on Baseten for a guess at the reason, and only after a synthetic audio canary passes. On Oct 28 and 29 the canary failed, so no house audio has been sent. A voice note a parent sends on Telegram is different: it goes as audio to Muse on Baseten to be written down |
| The baby's log | Baby Buddy on the family's server, reachable only on that server (see `docs/deploy-babybuddy.md`) |
| The agent's memory | `data/memory.sqlite` and `data/events.jsonl` on the machine that runs it, on the Vostro in `~/apps/parenting-agent-data` |
| **What leaves the house** | The brain call: the conversation text and tool results (baby log lines included) go to Muse Spark Open on Baseten, the only model called off the Mac. Every call logs its destination host as a `brain_call` event. Telegram voice notes go there too, as audio, on by default in the family agent and the families bot: the note is held in memory, converted in the house and sent once to inference.baseten.co, never saved by us. Telegram messages also go through Telegram's servers. |
| **Training** | Muse runs on the hackathon's free credits. Meta said on the event's Discord (Oct 27) that on the free credits "your content may be used to train future Meta models". So the messages, the tool results with their log lines and the voice notes sent to Muse may be kept and used for training. We do not promise otherwise. What stays home: the Baby Buddy database itself (the log lines a question reads still go to Muse in the tool results), the video frames and the house audio, apart from the two opt-in senses below |
| **Opt-in senses** | Apart from voice notes, no frame and no audio leaves, except two opt-in Muse senses, both off by default, that are part of the brain call to Baseten: one zoomed still per car seat camera step (`car_seat.muse`, the same still in 3 parallel calls by default for a majority vote), and the first 5 s of a detected cry (`house_sounds.muse_audio`, never sent so far because the canary failed). Each is made in memory and dropped after the call. See `docs/car-seat-coach.md` and `docs/house-sounds.md` |
| **The kitchen Echo (Amazon)** | Everything said to the Echo goes to Amazon's Alexa cloud, as with any Alexa command. Two paths reach the agent. The Home Assistant path (live since Oct 31, read only): Alexa's cloud turns the words into text, Home Assistant's Alexa Devices integration reads them from Amazon, and the agent's answer goes back to Amazon to be spoken. The "baby agent" skill (Oct 31, private, development stage on Gonza's Amazon account): Alexa's cloud sends the words to an AWS Lambda in us-east-1, the Lambda posts them through Cloudflare to the agent on the Vostro and speaks the reply. The Lambda's AWS log keeps each question's words and the answer. So the answers' log facts (a time, an amount, a diaper) reach Amazon. Announcements to the Echo also go through Amazon. See `docs/echo-and-assist.md` |
| **Cloudflare** | The public demo (baby.bygmv.com) and the Echo skill's path reach the Vostro through a Cloudflare tunnel, so their requests pass through Cloudflare. The demo's visitor messages also go to Muse on Baseten, about Demo Baby, a simulated baby |

## Run it

```bash
python -m parenting_agent --check                                  # load everything, print brain, plug-ins and tools, exit
python -m parenting_agent                                          # Muse Spark Open, the fixed rules when a Muse call errors
python -m parenting_agent --config config/agent.fake.json          # offline, rule-based brain
python -m parenting_agent --config config/agent.muse-baseten.json  # Muse Spark Open alone, no fallback (needs BASETEN_API_KEY)
```

Keys are read from a git-ignored `.env` (path in `config/agent.json`). Muse Spark Open needs `BASETEN_API_KEY`. **The Baseten key and its hackathon credits expire on Nov 9 2026.** After that the live brain calls fail and every agent answers from the fixed rules, saying the brain is busy, until a new key is set. The tests, `config/agent.fake.json` and the recorded runs in `results/` need no key. Baby Buddy is reached through an SSH tunnel:

```bash
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro   # see docs/deploy-babybuddy.md
```

## Always on, on the family server (issue #15)

The agent runs 24/7 on the Vostro in its own walled-off container: it reaches Baby Buddy and Home Assistant through a relay and the brain and Telegram through an allowlisting proxy, and nothing else. It restarts on its own, keeps its data in a volume, and house actions stay dry run except the three live allowed ones above (study light, vacuum pause and dock, shopping list add), none fired yet. Deploy, update, logs, stop and rollback with `sh deploy/agent.sh`, see `docs/deploy-agent.md`.

## One day and night, end to end (issue #148)

`python -m parenting_agent.e2e` runs the family agent as deployed (its config, every plug-in and loop, Muse, Baby Buddy, Home Assistant reads) through a first-month day and night on a fast clock, with Telegram captured and house writes forced dry, and scores what a parent would feel. On Oct 30, before the fixes: 11 of 34 things a parent must get, 16 of 55 messages noise (mostly English to a Spanish parent). After: 30 of 34, 0 of 58 noise, 25 of 25 log entries right. See `results/e2e-day/README.md`.

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

It replays the plan page day through the real agent: a typed "bottle, 120 ml" on the ear channel, the changing table on the clips with a typed dirty diaper note, a doorbell during the change, a long-nap note, the bath on its clip, a question answered from the log, and the night feed with the next feed and the next parent on duty. It writes `results/fullday/day.md`, `day.json` and the KR files in `results/fullday/kr222/`. The newest recorded runs are from Oct 29 with Muse Spark Open as the brain, the clips and SAM 3.1: 7 of 7 steps at 01:13 (`results/fullday/muse-sam-lift/day.md`) and 6 of 7 at 01:00, where the doorbell step failed (`results/fullday/muse-sam/day.md`). An Oct 27 run with Claude Haiku 5.5 as the brain also passed 7 of 7 (`results/fullday/day.md`). Home Assistant actions are dry runs in every report. See `results/fullday/README.md` and `docs/full-day.md`.

## Daily house plan: vacuum, shopping list, dinner and white noise (issues #29 and #32)

The vacuum pauses and goes home when a nap starts and never starts when the run would reach a predicted nap. It starts alone only when nobody is home or the baby is out, otherwise it asks. "Clean under the high chair" is a room clean, there is one daily run at the quietest awake time, diapers go on `todo.shopping_list` before they run out, a bad night gives a draft of fast Thermomix dinners from Cookidoo (read only, through home-agents), a reminder says when to start dinner, and white noise follows the rhythm under a 50 dB cap in code. The cap uses a placeholder calibration (70 dB at full level) until the machine exists and is measured, so no dB number here is measured. The Thermomix is never controlled. See `docs/house-plan.md`.

```bash
python scripts/house_plan_check.py   # live and safe: reads the vacuum, dry runs pause and home, one test list item added and removed
```

## Muse runs the house (issue #116)

Muse Spark Open plans the house and plain code arms it: at bedtime, at each wake-up, after a night feed and before each predicted nap, Muse returns a plan in a strict JSON schema (who is on duty, bottle pre-warm times, floor clean and quiet door windows, a white noise boost, what to tell each parent). The schema has no device field. `parenting_agent/house_brain.py` checks each item against the clock and the safety gate, arms the day engine and the night feed, and falls back to the fixed rules on any error, logged. It re-plans at once on a long sleep, a parent asking to sleep, a dog or a visitor, posts tonight's plan to Telegram and explains the night each morning. Replayed on the simulated day and six nights, it matched the fixed rules on every day check, changing no outcome there, and passed 3 of 4 adaptation cases the fixed rules fail. The long nap case fails for both. The shipped setting, which keeps the rota fixed unless a parent asks to sleep, was not rerun on the day. See `results/muse-house/README.md`.

## The 3 AM feed: ready when he wakes, never on a guess (issues #110 and #128)

The night feed predicts the next feed from the log, but a guess only pre-warms the bottle warmer, silently. The study light, the white noise and the push to the parent on duty wait for a real sign the baby is awake: a cry on the microphone, a parent saying "he's up", a wake-up or feed in the log. The warmer holds water only and has a 30 minute auto off plus a 90 minute total per night. On six simulated nights the parent was pushed 0 times and the white noise lowered 0 times while the baby slept (12 and 9 before the change), and 8 of 8 bottles had warm water when the feed started with the cry on the microphone. The plug is not bought yet, so the warmer is a dry virtual switch. See `results/night-feed/README.md`.

## The day engine: the whole house around the baby's day (issues #9 and #29)

Every useful device in the house has a job: 17 devices, 38 device to job pairs, from one read-only read of all 389 Home Assistant entities on Oct 29 (`results/house-jobs/README.md`, with a list of cheap missing devices). `parenting_agent/day_engine.py` runs six routines from the log and the house state, all in dry run: nap mode for the whole house (vacuum docked and resumed after, TVs muted, Echo on do not disturb, the door as a silent push, white noise), a floor clean before tummy time that waits for Gonza's yes and never reaches a predicted nap, a morning brief on Telegram and the Echo, supplies onto the shopping list, and quick Thermomix recipes after a hard night. A simulated day with the real house as its start is in `results/house-day/README.md`.

```bash
python scripts/house_day_sim.py   # the simulated day, dry run, add --read-house to read the real house first (read only)
```

## Telegram and channel picking (issues #3 and #8)

The agent hears and speaks on Telegram through @home_agent_example_bot, with long polling over plain HTTPS, so nothing is exposed. Only the family's chat ids are accepted: Gonza's (`TELEGRAM_CHAT_ID` in the env file, comma separated) and Ceci's (`TELEGRAM_CECI_CHAT_ID`, set on the Vostro), each tied to its person in the config so the log says who spoke. Other senders are ignored and logged as `channel_ignored` with their chat id only. Messages reach the same agent and the same memory as every other channel.

- `parenting_agent/channels/messaging.py`: one messaging adapter interface and the channel plug-in that runs it. WhatsApp later is a new adapter only.
- `parenting_agent/channels/telegram.py`: the Telegram adapter. Text and voice notes (getFile download, sendVoice reply).
- `parenting_agent/voice/`: the ears and the voice. `ear.py` sends the voice note to Muse Spark Open as audio input, `tts.py` speaks with MMS-TTS, `server.py` is the walled voice service on the Vostro. See `docs/voice.md`.
- `parenting_agent/channels/router.py`: picks one channel for each `notify` event and each agent reply on the channel `auto`. Help needed goes to the partner: the other parent's Telegram chat from the config's people block (since Oct 30). The router runs on the Mac only, and `config/agent.json` has no people block yet, so there it still records `partner_stub` and sends nothing. Away or unknown presence goes to Telegram. At home with a skill armed, or with the baby asleep, it goes to the ear (the Mac speaker for now). At home with hands free it goes to the kitchen Echo at low volume, and the volume is put back after. Presence comes from `person.gonza`, then `device_tracker.gonzas_iphone`.
- `scripts/channels_check.py`: the real checks, a Telegram round trip, one Echo announce and a reminder routed with presence simulated as away. Results in `results/channels/check.json`.

Home Assistant is reached through `ssh -f -N -L 127.0.0.1:18123:127.0.0.1:8123 vostro`, token `HA_MCP_TOKEN`.

## Before he arrives (issue #56)

Theo is not born yet, so the family agent helps get ready: prep lists for the nursery (from the home twin's measured plan), the hospital bag, the car seat and the white noise machine, appointments, a countdown to the due date, and one short morning nudge to Gonza on Telegram. Logistics only, never medical. Every message is a `turn` event with the person who sent it, so the daily-use KR is scored from the agent's own log. See `docs/before-he-arrives.md`. Until the birth the family agent runs in prep mode (`"baby": {"born": false}`): the baby log it reads is a test child, so no routine computed from it reaches the parents. One config change at birth switches the baby routines on (`parenting_agent/baby_phase.py`).

## Car seat coach (issue #30)

The agent coaches an infant carrier install with the car's seat belt, one step at a time by voice, in the order of a real install, and waits for the parent's "listo" before it judges a step. SAM 3.1 on the Mac checks what the head camera can see: the lap belt in each side guide and the shoulder belt in the rear guide (each up close), no twist, the level line, the handle upright. The harness pinch test (first, while the carrier faces the parent), the buckle click, the belt tightening and the movement test at the belt path are asked and logged. It speaks the language of the parent who asked (Spanish or English, the people block), on the glasses, as glasses cards and, when asked on Telegram, as Telegram messages to that parent, and its summary is its own words, never the brain's. Its lines never use "safe", "seguro" or "segura" (a filter on the coach's own lines, `parenting_agent/carseat/coach.py`), it lists what passed and what remains and suggests one check by a certified technician. The steps and limits come from the maker's manual (Joie i-Snug 2). The car rules come from Tesla's published child seat pages, not yet checked against the printed manual. An outgrow watch compares Baby Buddy weight and height with the seat's limits. Tested on 3D-rendered clips with planted mistakes, see `docs/car-seat-coach.md` and `results/carseat/`.

## The final guard on every text a parent reads

Muse sometimes writes its own machinery into an answer: "finish reason length", "not a JSON object", a tool or event name, its own name, "Parent A" for a rota label, an English sentence to a Spanish parent. One shared guard (`parenting_agent/agent/final_guard.py`) runs last on every path that can carry the brain's words to a parent: the agent's answers (the family agent, the families bot, the demo), the chat channels' sends (answers and pushes) and the glasses replies and cards. It drops each sentence that holds internal text or is in the wrong language for that parent, keeps the parent's own quoted words, never touches a red flag line, and logs a `final_guard` event with what it removed and why (the families bot logs only why and how long). The demo lets Muse Spark Open's name through, its page says which model answered. Numbers: `results/e2e-day/README.md`, "Final guard".

## Ray-Ban Meta glasses (issue #57)

`apps/glasses` is an iPhone app on Meta's Wearables Device Access Toolkit. It streams the glasses camera, sends 10 frames a second to the agent on the family's Mac over the home network (`parenting_agent/glasses.py`, pairing token, never a public address), sends the parent's phrases (a button or typed text, there is no speech recognition in the app yet), and shows and speaks what the agent answers. On Oct 28 the full loop ran in the iOS 27 simulator with DAT's mock Ray-Ban Meta playing the synthetic changing-table clip: "changing time", both hands off, "hand" spoken, "done", change logged. Real glasses are not paired yet. See `apps/glasses/README.md` and `results/glasses/README.md`.

```bash
python -m parenting_agent --config config/agent.glasses.json   # Muse Spark Open brain, glasses channel, changing table and bath on the glasses
```

## Public demo app

A phone-first web chat where anyone can talk to the real agent core about Demo Baby, a simulated baby on the simulated week, with a simulated house. Each visitor gets their own copy, health questions get the kind refusal, and the process carries only the brain keys. Live at https://baby.bygmv.com since Oct 28 2026. Since Oct 29 the Tonight's house card runs the real house brain on the visitor's simulated log, shows Muse's plan for the night and re-plans on "Let me sleep tonight", with the fixed rules as the fallback and nothing moving (issue #132, `results/demo-house/README.md`). See `docs/demo-app.md`.

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
| House sounds, a cry heard next to the log's last feed and diaper, white noise | #14, #32 | see PR | see PR |
| Sitter handover, time-boxed guest role, summary after | #16 | see PR | see PR |
| Invited families on Telegram, one private log per family, walled off | #40 | see PR | see PR |
| Bath skill, camera skills from config | #10 | #42 | see PR |
| Simulated Tesla: cabin ready, car naps, Child Left Alone Detection check | #31 | #43 | see PR |
| Daily house plan: vacuum around naps, shopping list, fast dinners, white noise | #29, #32 | #44 | see PR |
| Car seat coach: manual to steps, SAM 3.1 visible checks, hand checks, outgrow watch, rendered test clips | #30 | #47 | see PR |
| Touch versus hover ablation, reflex only against SAM 3.1, the voice waits for SAM 3.1 on near readings (Oct 28) | #6, #10 | see PR | see PR |
| Voice notes heard by Muse Spark Open, answers spoken with Meta MMS-TTS, walled voice service (Oct 28) | #58 | see PR | see PR |
| Hover lift check: hand growth toward the head camera, Meta depth models tried and not used (Oct 29) | #6, #10 | see PR | see PR |

| Muse Spark Open as the brain of the family agent, the families bot and the demo, Claude only as a logged fallback (removed from the runtime on Oct 31, the fixed rules answer instead) | #4 | #61 | 115dc2e |
| Red team round 1 closed, a regression test per attack | #60 | #63 | ed6c488 |

The first commits of Oct 26 (4f1898a to 90ca5a3) are an early skeleton that the issues above reviewed and partly rewrote. Commit f41acfa ported the reflex and the chime then voice alarm from the prior work below. On Oct 31 that code moved out to its own private library repository, `a private repo`, and this repo keeps only its own changes on top (see below). The Oct 26 port is still in this repo's git history.

**Planned, not built yet:** the glasses app on real glasses, live Home Assistant actions beyond the study light, the vacuum pause and dock and the shopping list add (#9, dry run today), demo and submission (#11).

## Prior work (Oct 21 to 25 2026, before the event)

Built in the prep repo `gonzalomelov/meta-hackathon-2026` (64 commits from Oct 21 to 25, private because it also holds the family's planning notes) and reused here. None of its numbers is used as event evidence.

| Prior work | Date | Reused here as |
|---|---|---|
| MediaPipe hand reflex with the contact rule, chime on every alarm then a spoken prompt after a 1.2 s hold | Oct 22 to 23 | The library `a private repo` v0.1.0, a separate private repository, the files exactly as ported in f41acfa. Installed with `pip install -r requirements-prior.txt`. Our event-time changes are separate code here: `parenting_agent/reflex.py` (near readings, the hands on the baby, their landmarks for the lift check) and `parenting_agent/alarm.py` (the bounded waits for SAM 3.1, returning hands, unseen and lifted alarms) subclass it. Without it, `"hands": "auto"` runs SAM 3.1 only (`parenting_agent/sam_hands.py`, no prior code) |
| SAM 3.1 run locally from Meta's weights, then on the Mac GPU (MPS) | Oct 23 to 24 | `scripts/sam3-setup.sh`, `sam3_worker.py` |
| Touch versus hover kill test, 21 of 21 hovers read off on one clip | Oct 23 to 24 | Not used. Replaced by the Oct 28 ablation in `results/hover/README.md` |
| iPhone Safari page as the head camera over Tailscale | Oct 23 | `sources.py`, `phone.html` |
| PANNs CNN14 labels under speech (18 of 24 events at 0 dB) and the thresholds, Tapo microphone listening | Oct 23 | `hearing.py` thresholds until Oct 31, when Meta's Perception Encoder Audio replaced PANNs with thresholds tuned during the event (`results/sounds/meta-hearing/`) |
| Home Assistant MCP check and actions driven by live events | Oct 21 to 23 | the house layer design |
| Generated changing-table clips (Oct 22), the generated bath clip and the hover clip (Oct 23) | Oct 22 to 23 | test clips outside git, the bath set was re-cut from it on Oct 28 |
| Positioning, the Baby Buddy safety vet, the day 1 runbook | Oct 23 to 25 | planning only |

**Public open-source tools used, not written by us:** Meta SAM 3.1 weights and code, Meta MMS-TTS weights (facebook/mms-tts-spa and facebook/mms-tts-eng, CC-BY-NC 4.0, non-commercial), FFmpeg, PyTorch and Hugging Face Transformers, Meta Perception Encoder Audio Frame weights (facebook/pe-a-frame-small, Apache 2.0), PANNs CNN14 (code MIT, weights CC BY 4.0, an offline baseline only since Oct 31), MediaPipe hand landmarker, OpenCV, NumPy, Baby Buddy (BSD-2-Clause), Home Assistant.
