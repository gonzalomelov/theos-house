# Second blind set, scored after every fix

45 new tired-parent messages over 3 simulated nights, written by an agent that changed no code and never saw the
fixes. Scored once, blind, on Oct 29 2026 on parenting-agent main at `24bd72b` (after PRs #101 and #103, every families
fix of the night), brain Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten), with
`scripts/families_never_wrong_run.py --steps-file steps-oct.json`.

**Blind result: 8 of 45 messages left a wrong log state, 5 reply problems, 0 fallbacks, 0.53 USD.**

That is the same count as the first blind set (8 of 45, `../heldout/`), which was taken before those fixes. The fixes
made the first set pass, and they did not carry over to new phrasings. Transcript with every diff in `run-1.md`,
numbers in `run-1.json`. This number stays as it is. This set is now read, so it is no longer blind and is not rerun as
a result. A third blind set will be written separately.

`steps.sha256` is the hash of the set as written (`steps.json`, days 1 to 3). `steps-oct.json` is the same 45 steps
with the days renumbered to 29 to 31 so the harness clock works, so its own hash differs.

## The 8 wrong log states

| Step | Message | What happened | Cause |
|------|---------|---------------|-------|
| 2 | "dejo como media onza igual" (after "fueron 4 oz de formula") | Muse logged a new bottle and then edited it to 105 ml, so the 120 ml bottle stayed and the log held two bottles at 00:30 | Brain tool choice: a log plus an edit for one correction |
| 10 | "3 onzitas en la mamadera" | Bottle logged with no ml, expected 90 | The said-only guard dropped the amount: "onzitas" is not on its ounce list and 90 is not a number in the message |
| 11 | "de materna, la q sacaste ayer" | Milk type stayed unknown. Muse only read the log and answered "Anotado ... de materna de 90 ml aprox" | The addendum path did not fire (its milk type rule wants "era" or "fue"). Also a false confirmation the scorer does not count |
| 13 | "pis y caquita clarita" | Diaper logged wet only, expected wet and dirty | The said-only guard dropped `solid`: "caquita" is not on its dirty list |
| 21 | "esta dormida desde las 2 y 10" | Sleep start 02:30 (the message time), expected 02:10 | The said-only guard dropped the time: "desde las" is not on its time list |
| 22 | "ta, arriba y a los gritos" | The sleep closed fine but kept the 02:30 start | Carried over from step 21, no new error |
| 38 | "prepare 110 y sobraron 20" | Bottle logged with no ml, expected 90 | The said-only guard dropped the amount: 90 is not a number in the message, it is 110 minus 20 |
| 39 | "la de recien fue con formula" | Milk type stayed unknown, and a note "la de recién fue con fórmula" was logged instead | The addendum path did not fire ("fue con formula" has a "con" its rule does not allow) |

All 8 are product misses. None is a set or scorer error. Six of them (10, 11, 13, 21 with 22, 38, 39) come from one
cause: the guards that keep the brain honest decide what the parent "said" from fixed word and number lists. When the
parent says it in a form the list does not have, the guard throws away the brain's right value or does not fire, and
the log loses a detail the parent did give. Step 2 is the brain's own tool choice.

## The 5 reply problems

| Step | Reply | Verdict |
|------|-------|---------|
| 8 | "Anoté que Lola se durmió a las 03:15." for a repeat of step 7 that changed nothing | Real product miss: a claimed log with nothing new logged |
| 17, 25, 26, 36 | English replies to "diaper change, just pee", "fed her 2 oz formula", "actually that was at 7", "she's asleep" | Scorer rule, not a product miss in our view: the family is set to Spanish, the parent wrote in English, and the bot answered in the language of the message. The scorer counts that as wrong |

The scorer does not count three more reply faults we found reading the transcript: step 11's false "Anotado", step 39's
"No hace falta que lo mandes de nuevo" for a message sent once, and step 43, which says "2 tomas" while listing 3 and
says it cannot compare with yesterday.

## What was done after this run

See the next PR on issue #77: the root cause above, fixed in the guards, with tests built from these steps. It is not
measured on this set, because this set is no longer blind.
