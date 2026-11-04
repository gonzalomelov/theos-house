# Families bot, 3 scripted days in Spanish

`scripts/families_3day_run.py`: two parents of a fictional baby, 34 Spanish messages over 3 simulated days (Oct 29 to 31), 29 checks on the log or the reply. The clock is simulated, the brain is real.

| Brain | Run | Checks passed | Bookkeeping talk | Tuteo instead of voseo | Fallbacks to Claude | Spend |
|---|---|---|---|---|---|---|
| **Muse Spark Open** (`meta-models/muse-spark-open-1026`, Baseten) | Oct 28 night, 4 runs (`three-day-muse.md` is the last) | **29 of 29** in each run | 0 | 0 | 0 | $0.21 to $0.23 a run |
| Claude Haiku 5.5 | Oct 28 earlier, 3 runs (`three-day-after.md`, `-2`, `-3`) | 29, 28 and 27 of 29 | 0 | 0 (counted tonight on `three-day-after-3.json`) | not tracked then | $0.022 (run 3) |

Rerun on main at `779e4d0` (after #78 to #86, Oct 29): **29 of 29**, 0 bookkeeping talk, 0 tuteo, 0.227 USD (`three-day-main.md`). It ran in parallel with three never-wrong runs, so 5 brain turns fell back to Claude Haiku after Baseten rate limits (HTTP 429).

After the first-entry and language fix (#77, Oct 29): **29 of 29**, 0 fallbacks, 0.246 USD (`three-day-first-entry.md`).

Muse costs about 10 times more per run and passed every check in all four runs. The Haiku misses were a missing tool call ("teta 10 min" once, "borrá la última" once).

Tuteo is counted with a word list (`tienes`, `puedes`, `dime` and 16 more) on every reply and every message the bot sent first.

What Muse did wrong tonight and how it was fixed:
- It wrote em dashes and once repeated an earlier entry in its confirmation. The reply rules now ask for plain sentences and only what this message changed (#61).
- On the deployed bot, "¿cuánto tomó hoy?" made it log a second bottle with no amount. A question about the log is now never logged (#64). The four runs were after the first fix, the last two after both, and the last one also after the doorbell rule (#69).

Muse latency and cost on the last run: 49 brain calls, p50 1.34 s, p90 2.24 s, $0.0047 a call, $0.0068 a parent message (`results/muse/calls-families.jsonl`).

```bash
PA_BRAIN_LOG=results/muse/calls-families.jsonl .venv/bin/python scripts/families_3day_run.py \
  --keys-env ~/.parenting-agent.env --out results/families/three-day-muse
.venv/bin/python scripts/families_3day_run.py --brain claude ...   # Haiku, for comparison
```
