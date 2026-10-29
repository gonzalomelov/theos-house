# Muse Spark Open as the brain (issue #4)

Since Oct 28 night, Muse Spark Open (`meta-models/muse-spark-open-1026`, Meta's open weights, on Baseten's OpenAI-compatible API) is the brain of all three running agents: the family agent (@home_agent_example_bot), the families bot (pa-families) and the public demo (pa-demo). Claude Haiku 5.5 answers only when a Muse call errors. Each fallback is a `brain_fallback` event and a stderr line, and the stats below count them.

## Latency and cost, measured tonight

Each brain call wrote one JSON line through `PA_BRAIN_LOG` (numbers only, no text), summed by `scripts/brain_calls_stats.py`.

| Suite | Calls | Fallbacks | p50 | p90 | Cost a call | Cost |
|---|---|---|---|---|---|---|
| Families 3-day Spanish run, last run (`calls-families.jsonl`) | 49 | 0 | 1.34 s | 2.24 s | $0.0047 | $0.231 |
| Demo scripted visit (`calls-demo.jsonl`) | 19 | 0 | 1.26 s | 1.87 s | $0.0049 | $0.094 |
| Voice log into Baby Buddy (`calls-voice-log.jsonl`) | 12 | 0 | 1.62 s | 4.09 s | $0.0028 | $0.034 |
| Full day, no video (`calls-fullday-novideo.jsonl`) | 10 | 0 | 1.17 s | 1.48 s | $0.0038 | $0.038 |
| Bath, 5 baths, no SAM (`calls-bath-no-sam.jsonl`) | 31 | 0 | 1.21 s | 2.09 s | $0.0039 | $0.119 |
| Sitter brief (`calls-sitter.jsonl`) | 2 | 0 | 1.44 s | 1.52 s | $0.0033 | $0.007 |
| **All six** | **123** | **0** | **1.32 s** | **2.24 s** | **$0.0042** | **$0.52** |

A parent's message takes 1 or 2 brain calls (one to call a tool, one to answer). In the families run that came to $0.0068 a message. The same demo visit on Haiku cost $0.0084 in total against $0.094 on Muse, about 11 times less, with the same latency (p50 1.55 s, p90 2.04 s on Haiku).

Muse averages about 2,860 input tokens, 157 output tokens and 98 reasoning tokens a call. Its price is $1.25 input and $4.25 output per million tokens (Baseten library page, read Oct 28 2026).

All of tonight's runs, reruns and probes together came to about $2 of the $100 credit (my estimate from the per-run spend in `cost-log.txt`, not a Baseten bill).

## Real turns on the deployed agents, on the Vostro

Run inside each running container with its own config, through its own egress proxy. Questions and test families only, nothing sent to anyone.

| Agent | File | Brain calls on Muse | Fallbacks |
|---|---|---|---|
| Family agent, commit 1cd6b36 | `vostro-family-agent-turn.jsonl` | 4, to inference.baseten.co | 0 |
| Families bot, Spanish, test family in a temp folder | `vostro-families-turn.jsonl` | 4 | 0 |
| Demo, internal visitor in a temp folder | `vostro-demo-turn.jsonl` | 4 | 0 |

## Results next to Haiku

| Suite | Muse, Oct 28 night | Haiku, earlier |
|---|---|---|
| Families 3-day Spanish (`results/families`) | 29 of 29 in 4 runs in a row, 0 tuteo | 29, 28, 27 of 29 (Oct 28) |
| Demo scripted visit (`results/demo-app`) | 11 of 11 | 11 of 11 (same night) |
| Voice log (`results/kr222`) | 4 of 4 notes read back, 2 of 2 answers | 4 of 4, 2 of 2 (Oct 27) |
| Sitter brief (`results/sitter`) | one draft, tool ran | one draft (Oct 26) |
| Full day (`results/fullday`) | no video only: 4 of 5 steps run (see below) | 7 of 7 with video (Oct 27) |
| Bath (`results/bath`) | 5 baths, no SAM: armed 5 of 5, voice 5 of 5, logged 5 of 5, never left alone 5 of 5 | 10 baths with SAM 3.1, all 10 of 10 (Oct 28) |

## What Muse got wrong tonight, and the fix for each

| What happened | Fix |
|---|---|
| Em dashes, and a confirmation that listed an earlier bottle again | Reply rules: plain sentences, only what this message changed (#61) |
| On the deployed families bot, "¿cuánto tomó hoy?" logged a second bottle with no amount | A question about the log is never logged (#64) |
| A correction also touched a diaper and said "ya decía eso" | A no-op edit beside a real one is not said (#64) |
| A doorbell observation logged the morning bottle again | An observation never logs (#71) |
| It announced "one moment please" but did not ask before replying to the visitor | The rule for tools that wait for a yes now covers the door (#71) |
| The sitter's name came back as "mom" | The brief capitalises the name (#61) |
| In the bath, 3 of 5 interruption replies said "if you need to go, take her with you", which the never-left-alone check flags | The bath fact no longer describes going anywhere, and while a camera skill is on any such sentence is cut before it is said (#73) |

Muse's thoughts come back apart from the answer (`reasoning_content`). The brain never reads that field and cuts any `<think>` text from an answer. The demo run checks every reply for leaks and found 0.

## Not done tonight

- **Bath and the full day with SAM 3.1.** SAM needs the Mac GPU, and another agent held the GPU lock from 22:22 the whole night. The bath ran with `--confirm none` (the hand reflex, no SAM) and the full day with `--no-video` (`results/fullday/day-muse-no-video.md`). Its question step fails in that mode because its expected answer comes from the changing table step, which `--no-video` skips.
- **Channels round trip.** It replies in Gonza's Telegram chat and competes with the live bot for messages, so it was not rerun. The family agent turn on the Vostro covers the brain path.
