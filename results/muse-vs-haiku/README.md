# Is Muse needed? Muse Spark Open against Claude Haiku on the two Muse jobs (issue #136)

**Log ops: a tie, 0 wrong log states for both models in every run. House planner: Muse passed 3 of 4 adaptation cases in both runs, Haiku 2 of 4 in both runs. Haiku costs about 11 to 15 times less per call.**

Review round 4 asked for a non-Meta arm on the two jobs where Muse was said to matter. All runs below are from Oct 30 2026, one process at a time, on this branch (origin/main `d52f121` plus the runner flags listed at the end).

- Muse: Muse Spark Open, `meta-models/muse-spark-open-1026` on Baseten, reasoning effort low, as shipped.
- Haiku: Claude Haiku 5.5, `claude-haiku-5-5`, the model the agent's Anthropic fallback calls (`config/agent.json`), thinking off as the agent's Claude brain runs it.
- Same prompts, same tools and schema, same code checks. Only the model changed. No prompt was edited for either model.
- Output cap: the same for both arms. Log ops at 2048 tokens (Muse's families cap, Haiku's shipped families cap is 400, and its longest answer was 534 tokens on the babylog set, 335 on heldout5). House planner at 6000 for both.
- Prices: the repo's configured list prices, Muse 1.25 and 4.25 USD per million tokens in and out, Haiku 0.10 and 0.50.

## The table

| Job and check | Muse run 1 | Muse run 2 | Haiku run 1 | Haiku run 2 |
|---|---|---|---|---|
| Log ops, fifth blind set (heldout5), wrong log states of 45 | 0 | 0 | 0 | 0 |
| Log ops, round 4 held-out set (babylog-r4), right of 36 | 36 | 36 | 36 | 36 |
| House, day: vacuum minutes while he slept | 0 | 0 | 0 | 0 |
| House, day: TV unmuted or Echo not on do not disturb while he slept, minutes | 0 | 0 | 0 | 0 |
| House, day: floor cleans while he was awake (fixed rules: 1) | 1 | 1 | **0** | 1 |
| House, day: loudest white noise at the crib (fixed: 48.1 dB) | 48.1 dB | 48.1 dB | 48.1 dB | 48.1 dB |
| House, six nights: pushes to the parent the rota names | 20 of 20 | 20 of 20 | 20 of 20 | 20 of 20 |
| House, six nights: bottles warm at the feed start | 8 of 8 | 8 of 8 | 8 of 8 | 8 of 8 |
| House: whole plans refused | 0 of 64 | 0 of 65 | 0 of 63 | 0 of 68 |
| House: plans with one or more items refused, those routines ran their fixed rule | 5 | 6 | 4 | 9 |
| House: adaptation cases passed of 4 (fixed rules: 0) | **3** | **3** | **2** | **2** |
| House: the parent who asked to sleep got a night push | 0 of 4 | 0 of 4 | **1 of 4** | **1 of 4** |
| Fallbacks to another model, failed calls | 0 | 0 | 0 | 0 |

## Latency and cost per call

| Job | Model | Calls | Median latency | p90 | USD per call | USD in total |
|---|---|---|---|---|---|---|
| Log ops, heldout5 (2 runs) | Muse | 90 | 1.52 s | 2.25 s | 0.00483 | 0.435 |
| Log ops, heldout5 (2 runs) | Haiku | 90 | 1.72 s | 2.65 s | 0.00045 | 0.041 |
| Log ops, babylog-r4 (2 runs) | Muse | 66 | 1.70 s | 2.68 s | 0.00507 | 0.335 |
| Log ops, babylog-r4 (2 runs) | Haiku | 66 | 1.80 s | 2.64 s | 0.00048 | 0.032 |
| House planner (2 runs) | Muse | 134 | 4.49 s | 6.60 s | 0.00786 | 1.053 |
| House planner (2 runs) | Haiku | 134 | 2.55 s | 3.89 s | 0.00053 | 0.071 |

Per call, Haiku is about 11 times cheaper on log ops and 15 times cheaper on the house planner. On log ops the two are equally fast. On the house planner Haiku answers in about half the time, because Muse reasons first (about 1,290 output tokens a call against about 390 for Haiku).

**Spend tonight: 1.98 USD.** Muse 1.82 USD, Haiku 0.15 USD, which includes one Haiku smoke run of the four cases (0.011 USD) made to check the client before the scored runs.

## What the differences were

- **The parent who asked to sleep.** In the hard night of Oct 23, Parent A writes "I'm exhausted, let me sleep tonight" at 21:50. Both models moved the night to Parent B at bedtime. Muse kept Parent B on duty through all four wake-ups in both runs. Haiku kept the request for two wake-ups, then at 03:23 wrote "the rota now hands night duty to Parent A, who is next by rota" and pushed Parent A at 05:43, in both runs. In the smoke run Haiku passed this case, so Haiku passed it in 1 of 3 runs, Muse in 2 of 2 (and in 3 of 3 prior runs on Oct 29, `results/muse-house`).
- **The day's floor clean.** In Haiku run 1, every plan of the day left the floor clean list empty, so no clean ran and neither tummy time had a clean before it. The fixed rules and every Muse run cleaned once. Haiku run 2 cleaned once.
- **Refused items.** For both models most were a floor clean window over a predicted sleep. Haiku also put bottle pre-warms in the day (07:30, 16:54, 19:30 to 20:00), which the night-only check refused at least 9 times over its two runs. Muse had none of those.
- **The long nap case** failed for both models in every run, as it did on Oct 29: no floor clean in the 57 minutes between the late wake-up and the next nap.
- **Log ops replies.** The scorer flagged 1 or 2 replies per heldout5 run for both models. Most are the known false positive on the double send question. One Haiku reply said the 120 ml bottle twice in one message ("Anoté la mamadera de 120 ml ... Anoté la mamadera de 4 onzas"), with the log right.

## Conclusion

- **Log ops: Muse is not needed. It is a tie.** Both models made 0 wrong log states in 2 runs of 45 and 2 runs of 36, with the same prompts and the same code. The design (the model sees the log and proposes operations, code applies them) is what wins over the old guards, not the model. Haiku does it for about a tenth of the price at the same speed.
- **House planner: Muse did better, by a small and consistent margin.** 3 of 4 adaptation cases in both runs against 2 of 4 for Haiku, because Haiku forgot a parent's request to sleep after two wake-ups, and in one run it planned no floor clean all day. Haiku is 15 times cheaper and twice as fast on this job.
- So the honest claim is: Muse is the brain because it is Meta's open model. On log ops any capable model works. On the house planner Muse held a parent's request across the night where Haiku did not, in every scored run.

## Honest limits

- Both log sets are no longer blind. Heldout5 was read on Oct 29 and the ops retry was added after it, and the babylog fixes were built from the same finding types as its set. The prompts were written with Muse in the loop. Both models see the same seen sets, so this is a fair comparison, but the 0 of 45 is not a fresh blind score. Muse made 1 of 45 on this set blind, before the retry.
- 2 runs per arm. The house difference is one case per run. Both models vary from run to run, as Haiku's smoke run shows.
- The house runs are the simulated day and week, not a real family. The night checks run on the current night feed code (awake-only pre-warm since issue #128), so the night numbers differ from `results/muse-house`, which was run before that change.
- Haiku runs with thinking off, as the agent's Claude brain does. Haiku with thinking on was not tried.

## Files and how to rerun

- `logops/heldout5-<model>-<run>.{json,md}` and `.calls.jsonl` (one line per brain call: model, seconds, tokens, USD, no text)
- `babylog/r4-<model>-<run>.{json,md}` and `.calls.jsonl`
- `house-muse/run.json`, `house-haiku/run.json`, every call in `calls`

```bash
set -a; . ~/.parenting-agent.env; set +a
PY=.venv/bin/python
PA_BRAIN_LOG=calls.jsonl $PY scripts/families_never_wrong_run.py --keys-env <env> --out <prefix> \
  --steps-file results/families-log-ablation/heldout5/steps.json --variant ops --brain claude --claude-max-tokens 2048
PA_BRAIN_LOG=calls.jsonl $PY results/babylog-r4/score.py . <prefix> claude        # baseten for Muse
$PY scripts/muse_house_sim.py --brain haiku --runs 2 --budget 0.5 --out results/muse-vs-haiku/house-haiku
```

Runner changes in this PR, no product code: `--claude-max-tokens` in `families_never_wrong_run.py`, an optional brain argument in `babylog-r4/score.py`, and `--brain haiku` in `muse_house_sim.py` (a client with the same `ask()` as `MuseClient`, the schema sent as a structured output).
