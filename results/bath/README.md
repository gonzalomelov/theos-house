# Bath routine on the clips

`scripts/bath_run.py` streams the bath clips live: "bath time" to the agent, the reflex chimes and speaks when both hands leave the baby, an interruption arrives mid bath, then "bath done" logs the bath in Baby Buddy and reads it back.

| Brain | Run | Confirm | Armed by voice | Both hands off spoken within 2.5 s | Chime within 1 s | Logged and read back | Replies never say leave |
|---|---|---|---|---|---|---|---|
| **Muse Spark Open** | Oct 29 01:12, 10 baths, after the lift check (#75) (`bath-muse-sam-lift.json`) | SAM 3.1 and the lift check | 10 of 10 | 10 of 10, max 1.83 s, but **5 of 10 one-hand clips also spoke "hand"** | 10 of 10, max 0.29 s | 10 of 10 | 10 of 10 |
| **Muse Spark Open** | Oct 29 00:55, 10 baths, before #75 (`bath-muse-sam.json`) | SAM 3.1 | 10 of 10 | 10 of 10, max 1.49 s, one-hand clips silent 10 of 10 | 10 of 10, max 0.27 s | 10 of 10 | 10 of 10 |
| **Muse Spark Open** (`meta-models/muse-spark-open-1026`) | Oct 29 00:31, 5 baths (`bath-muse-no-sam.json`) | none, the hand reflex only | 5 of 5 | 5 of 5, max 1.51 s | 5 of 5, max 0.27 s | 5 of 5 | 5 of 5 |
| Claude Haiku 5.5 | Oct 28 afternoon, 10 baths (`bath.json`) | SAM 3.1 | 10 of 10 | 10 of 10, max 1.89 s | 10 of 10, max 0.61 s | 10 of 10 | 10 of 10 |

The 00:31 Muse run has no SAM 3.1, because another agent held the GPU lock then. The 00:55 run is the same measure with SAM 3.1 on and Muse as the brain: it passes everything, like the Claude run of Oct 28. SAM 3.1 answered "off" on every both-hands-off alarm (3 confirms per bath at most).

The 01:12 run is the same code after the lift check for hovering hands merged (#75), which also turned the lift check on in `skills/bath.json`. It brings a false "hand" in the one-hand clip in 5 of 10 baths, against 0 of 10 at 00:55. The only change between the two runs is #75. No SAM 3.1 confirm was asked on those one-hand alarms, which fits a lifted alarm, since a lifted alarm skips SAM 3.1 by design. A one-hand bath (one hand on the baby, the other reaching for something) is read as a hover. This is a regression that the hover set did not catch, because its bath clips are touches and hovers only. It is not fixed here.

The first Muse run that worked passed every measure but one: 3 of 5 interruption replies said things like "if you need to go grab shampoo, take her out of the water with you, then go". The check counts that as describing leaving, and it is right to. Muse was paraphrasing the bath's own fact, which said "if the parent must go, the baby comes out of the water with them". The fact now says never describe going anywhere, and while a camera skill is on, any reply sentence that trips the check is cut and replaced with "Keep a hand on the baby. I can say one moment on the house speaker, hold notifications or call your partner." (#73). The run above is after both fixes.

An earlier Muse run armed 0 of 5 because the worktree had no `.models/hand_landmarker.task`. That was the setup, not the brain.

Muse: 31 brain calls, p50 1.21 s, p90 2.09 s, $0.119, no fallback (`results/muse/calls-bath-no-sam.jsonl`). With SAM 3.1 at 00:55: 62 calls, p50 1.17 s, p90 2.46 s, $0.241, no fallback (`calls-bath-sam.jsonl`). At 01:12: 61 calls, p50 1.19 s, p90 2.29 s, $0.236 (`calls-bath-sam-lift.jsonl`).

```bash
python scripts/bath_run.py --baths 5 --confirm none --out results/bath/bath-muse-no-sam.json   # no GPU needed
mkdir /tmp/pa-gpu.lock && python scripts/bath_run.py --baths 10 --out results/bath/bath-muse-sam-lift.json; rmdir /tmp/pa-gpu.lock      # with SAM 3.1
```
