# Public demo, scripted visit

`scripts/demo_run.py`: 11 messages through the demo's real code (log a bottle and a diaper, two questions, the next feed, three simulated house actions, a health question, a Spanish correction, an open question), each with a check. Local, nothing deployed or sent. Run on Oct 28 night with both brains.

| Brain | Checks passed | Reasoning leaks | Fallbacks | Spend | p50 / p90 per call |
|---|---|---|---|---|---|
| **Muse Spark Open** (`meta-models/muse-spark-open-1026`) | **11 of 11** | 0 | 0 | $0.094 (19 calls) | 1.26 s / 1.87 s |
| Claude Haiku 5.5 | 11 of 11 | 0 | 0 | $0.0084 (19 calls) | 1.55 s / 2.04 s |

Before the fixes both brains failed "when is the next feed?" in substance: the demo had no `next_feed` tool, so Muse said it had no time and Haiku said the tool was missing. The demo now has the same `next_feed` tool as the families bot (#61). On the first Muse run the confirmation of a diaper also repeated the earlier bottle, and a correction also touched a diaper and said so. Both are fixed (#61, #64).

A leak is any reply with `<think`, "we need to", "the user says" or similar. Muse returns its reasoning apart, in `reasoning_content`, and the brain never reads it.

The deployed demo (baby.bygmv.com, commit f650139) answered two real turns on Muse on the Vostro: `results/muse/vostro-demo-turn.jsonl`.

`demo-390x844.png` is the page at phone size, prior work from Oct 28 before Muse.
