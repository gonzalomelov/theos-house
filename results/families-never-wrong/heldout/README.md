# Held-out set, the first and only blind score

45 tired-parent messages over 3 simulated nights (`heldout-steps.json`), written after the fixes of PR #101 and never
used to tune anything. Scored once, blind, on Oct 29 2026 on parenting-agent main at `ee4c401`, brain Muse Spark Open
(`meta-models/muse-spark-open-1026` on Baseten), with `scripts/families_never_wrong_run.py --steps-file`.

**Blind result: 8 of 45 messages left a wrong log state, 1 reply problem, 0 fallbacks, 0.53 USD.**
Transcript with every diff in `run-1.md`, numbers in `run-1.json`. This number stays as it is. Any later run of this
set is no longer blind, because the misses below were fixed after reading it.

## The 8 wrong log states, one by one

| Step | Message | What happened | Verdict |
|------|---------|---------------|---------|
| 2 | "ah y era formula" | The 00:35 bottle stayed "milk type not said". The brain only read the log and answered "Entendido, era fórmula". | Real product miss, and a false confirmation |
| 5 | "como 14 min" | A second feed "breast 14 min" at 02:52 instead of 14 min on the 02:50 left breast feed. | Real product miss |
| 8 | "ya esta despierta otra vez" | The sleep ended fine, but its start was 03:21. The duplicate "se quedo frita en upa" at 03:21 (step 7) had moved the open sleep from 03:20 to 03:21. | Real product miss, small (one minute), caused at step 7. Step 7 is also the 1 reply problem: it said "Anoté ... 03:21" for a message the set expects to change nothing |
| 9 | "le prepare 120 y tomo la mitad" | Bottle logged with no ml, expected 60. | Real product miss |
| 18 | "y pis tmb" | A second wet diaper at 00:51 instead of wet on the 00:50 dirty one. | Real product miss |
| 25 | "15 min, ya la largo" | A 15 min bottle at 05:35 instead of 15 min on the 05:20 right breast feed. | Real product miss |
| 27 | "le di 3 onzas y media" | Logged 90 ml, the half ounce was lost. The set expects 105 (3.5 oz at the 30 ml the bottle marks use). Step 28 "no, eran 3 justas" then found 90 already there and said "ya decía eso, no cambié nada", which was true of the log, so step 28 itself is not a miss. | Real product miss |
| 30 | "hoy esta re sonriente, no para de mirar el movil" | A note was logged. Worse, and not counted by the scorer: the brain also started a sleep at 12:40 and the reply said "Lola se durmió a las 12:40". | Real product miss. The note alone is a judgement call (a parent sharing a moment), but the set expects nothing, the same as step 45 ("hoy hace un frio barbaro"), which passed |

Before reading the transcript we suspected two of these were set or scorer errors: step 1 expecting "formula" for a
plain "mamadera de 110", and step 8 being a one-minute difference. Neither holds up. Step 1 expects "milk type not
said" and passed. The formula diff belongs to step 2, a correction that never ran. Step 8 is one minute off, but the
cause is real: a message sent twice moved an open sleep. So all 8 are product misses, 0 are set errors, and one more
product miss (the invented 12:40 sleep start at step 30) was not counted by the scorer, because it only checks the open
sleep on steps tagged "asleep".

## What was fixed after this run

Each miss has a test in `tests/test_heldout_misses.py`.

- A short follow-up that adds one detail to the entry just logged ("como 14 min", "15 min, ya la largo", "y pis tmb",
  "ah y era formula") edits that entry without asking the brain (`rules.addendum`, `Agent.addendum`). Steps 2, 5, 18, 25.
- "le prepare 120 y tomo la mitad" is 60 ml (`rules.half_ml`). Step 9.
- "3 onzas y media" is 105 ml (`rules.ounces_ml`). Step 27.
- A sleep start while a sleep opened less than an hour ago is held, and the reply says since when she sleeps. Steps 7 and 8.
- A sleep call for a message that says nothing about sleep is held. A note for a message that only shares a mood or a
  moment is held. Step 30.

## Reruns, Oct 29 2026, same brain

| Run | Messages | Wrong log states | Reply problems | USD |
|-----|----------|------------------|----------------|-----|
| Held-out, blind (`run-1`) | 45 | 8 | 1 | 0.53 |
| Held-out, after fixes, no longer blind (`after-fixes-1`) | 45 | 0 | 0 | 0.39 |
| Old 70 plus review 37, after fixes (`../heldout-fixes-old-1`) | 107 | 1 | 0 | 0.87 |

The old-set run has step 47 ("tiene fiebre le doy paracetamol?") updated to expect the note PR #97 now logs, so the
miss that step caused in `r3diff-1` and `r3diff-2` is gone. The one miss left is review step 29, "lloro un monton y
despues tomo pecho der 10 min": the feed was right, and Muse also logged "lloro un monton" as a note the set does not
expect. It is not fixed in this PR.

The held-out 0 of 45 is not a blind number. The blind number for this set is 8 of 45, and a new blind set is needed to
measure the fixes honestly.
