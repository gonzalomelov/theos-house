# Usage results

## Voice log (`voice-log.json`, `scripts/voice_log_run.py`)

Four spoken notes go through the agent and the brain into Baby Buddy on the Vostro, each record is read back by id, then two questions are answered from the log.

| Brain | Run | Notes read back from Baby Buddy | Questions answered from the log |
|---|---|---|---|
| **Muse Spark Open** (`meta-models/muse-spark-open-1026`, Baseten) | Oct 28 night | **4 of 4**, the right type each | 2 of 2 |
| Claude Haiku 5.5 | Oct 27, prior run in git history | 4 of 4 | 2 of 2 |

On Muse: 12 brain calls, p50 1.62 s, p90 4.09 s, $0.0028 a call, $0.0056 a message, no fallback (`results/muse/calls-voice-log.jsonl`). "How much did she drink today?" answered 240 ml in 2 feeds because an earlier Muse run tonight had also logged a 120 ml bottle on the test baby, which is what the log holds.

`table.json` and `reminder.json` do not call the brain (the changing table with SAM 3.1, and the rhythm reminders with the rule-based brain).
