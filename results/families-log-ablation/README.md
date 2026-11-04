# Which log architecture generalizes (issue #77)

**Fifth blind set, scored once each: Muse log ops 1 of 45 wrong log states, main 13 of 45.**

Four blind sets of 45 tired-parent messages had scored 8, 8, 5 and 11 wrong log states, and every round of rule fixes
made the tuned sets pass without carrying over. This folder measures architectures instead of patching phrases. All
runs on Oct 29 2026 with Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten), one run at a time, 0
fallbacks to Claude in every run. Total spend 6.45 USD of the 8 USD budget.

## The variants

| Variant | What decides the log |
|---|---|
| `main` | Main at `9ad0571`: Muse calls the log tools, and the rule guards in `loop.py` and `rules.py` (said_only, addendum, amount_said, time parsing, claims guards and the rest) check, change or hold each call |
| `safety` | The same loop with every guard that judges Muse switched off. Only safety stays: the emergency and newborn red flag lines, the health refusal, codes kept out of replies and the bounds on amounts, lengths and times. The prompt asks about double sends because the agent no longer does |
| `ops-verify` | Muse gets the log as it stands with ids, the open sleep, today's and yesterday's totals, the rhythm line and the last 12 messages with their times, and returns the log operations as data (`log_ops`). A second Muse call checks them against the message and the log and can keep, correct or drop them |
| `ops` | The same as `ops-verify` with one call and no check |

In `ops` and `ops-verify` code does only what code is sure about: ounces to ml at 30 ml an ounce, a clock time put on the latest such moment that is not in the future, the bounds, and the confirmation built from the log diff. No rule decides what the parent said. `parenting_agent/agent/log_ops.py`.

## The four seen sets, now a dev benchmark

These 180 messages were all read before this work, and the ops prompt was written after reading them, so the ops rows
are tuned numbers. Main's first three sets were tuned too (fixes after each blind score), its fourth was not.

| Variant | Set 1 wrong / reply | Set 2 | Set 3 | Set 4 | Wrong of 180 | Reply problems | Seconds per message | USD per message |
|---|---|---|---|---|---|---|---|---|
| main | 1 / 1 | 3 / 0 | 2 / 0 | 11 / 1 | 17 | 2 | 3.0 | 0.0093 |
| safety | 14 / 4 | 11 / 4 | 11 / 4 | 16 / 5 | **52** | 17 | 3.7 | 0.0112 |
| ops-verify | 0 / 0 | 0 / 0 | 0 / 1 | 0 / 0 | **0** | 1 | 3.2 | 0.0091 |
| ops | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 1 | **0** | 1 | 1.7 | 0.0047 |

Main's set 4 row is the blind run of `../families-never-wrong/heldout4/run-1.json` on `8ab6568`, the same code as
`9ad0571` (PR #108 changed only results). Its seconds are not in that file, so main's seconds come from sets 1 to 3.
Files: `<variant>-heldout<n>.json` and `.md`, every step with its reply, tool calls and diff.

What the table says:

- Switching the guards off inside the old loop is much worse (52 of 180). The guards were patching a structure where
  Muse logs blind: it never saw the log, only tool results, so it could not tell a follow-up from a new entry.
- Giving Muse the log and asking for operations as data removes the misses on all four sets, at half main's cost and
  latency.
- The verify call found nothing to fix that mattered: same 0 of 180, twice the cost and latency. So the winner is `ops`.
- The reply problems left in ops and ops-verify are scorer false positives: the double-send question says "ya tengo
  anotada" about the first entry, and the scorer reads that as a claimed log.

## The fifth set, blind

Written by a separate agent that read no code, hashed and committed before any run (`heldout5/steps.sha256`,
`8115cf41...`, closest similarity 0.7467), never opened by the agent that built `ops`. Scored once each on the shipping
code (`ops` is the families default), then read.

| Variant | Wrong log states | Reply problems | Seconds per message | USD per message |
|---|---|---|---|---|
| ops | **1 of 45** | 1 | 1.9 | 0.0049 |
| main | **13 of 45** | 1 | 3.0 | 0.0096 |

Files: `heldout5/ops-run-1.*` and `heldout5/main-run-1.*`. This set is now read, so any later score on it is tuned.

- The one ops miss, step 42 "un cuarto de hora de pecho": Muse answered that call without a `log_ops` call, so the
  agent fell back to the guarded loop, which logged the breast feed and lost the 15 minutes, the same miss main made.
  Fix after reading it: a missing `log_ops` answer is asked for once more before the guarded loop takes over
  (`tests/test_log_ops.py`, `OpsRetry`). Not rescored.
- Main's 13: clock times after midnight read as noon ("a las 12 y media", "12 y 50 clavadas", each also breaking the
  wake-up after it), numbers in words lost ("quince minutos", "cuatro onzas" as 118 ml, "ciento veinte"), "dejo la
  mitad", a shared moment logged as a note, a second diaper asked about as a double send and then lost, and the same
  "un cuarto de hora".
- The one reply problem for each is the same scorer false positive on the double-send question.

## What shipped

`PA_FAMILIES_LOG_MODE` picks the mode, `ops` by default, `ops-verify` and `guards` stay available. The rule brain that
answers after the spend cap never returns `log_ops`, so those messages take the guarded loop as before. The emergency,
red flag, safe sleep and health gates run before either mode, unchanged.

Rerun: `.venv/bin/python scripts/families_log_ablation.py --keys-env <env> --variants main,safety,ops-verify,ops`, then
`--table`. One set: `scripts/families_never_wrong_run.py --steps-file <steps.json> --variant ops`.
