# Third blind set, Oct 29 05:52

45 new tired-parent messages over 3 simulated nights, written by an agent that changed no code and read the earlier sets only to avoid overlap (closest normalized similarity 0.733). The hash in `steps.sha256` was recorded before the run and matches `steps.json`.

Scored once on main at 2eb896c (PR #105), after every families fix of the night, with Muse Spark Open as the brain, 0 fallbacks, 0.48 USD.

| Blind set | Code | Wrong log states | Reply problems |
|---|---|---|---|
| First (`heldout/`) | 58bce86 | 8 of 45 | 1 |
| Second (`heldout2/`) | 86d7c0e | 8 of 45 | 5 |
| Third (this folder) | 2eb896c | 5 of 45 | 3 |

Each wrong state is in `run-1.md` under WRONG LOG STATE, with the expected and actual entries.

**This set is now tuned.** The 5 of 45 above is its only blind number. The fixes below were made after reading it, so any later score on these 45 messages is a tuned number, not a blind one.

## The 5 wrong log states, by cause

| Step | Message | What the log held | Cause | Fix |
|---|---|---|---|---|
| 5 | pecho derecho, arranque 2:15 y largo recien | right breast at 02:15, no length | span: a length given as two times, start and "recien", was dropped, only "N min" counted | `rules.feed_minutes` fills the length from the times, 20 min |
| 7 | se desperto 4 y 55 llorando | sleep ended 05:05 | clock: "4 y 55" was not a time the parser knew, it only read "a las 3" and "at 3" | `rules.clock_times` reads every form ("4 y 55", "2:25", "3 menos cuarto", "3pm", "noon", "medianoche") |
| 28 | uh no, tambien tenia pis | diaper stayed dirty only, reply "No pude terminar eso" | follow-up: the words that point back at the entry just logged had to sit first or last, so "uh no," sent it to the brain, which read the log until it ran out of rounds | `rules.diaper_patch` finds "tambien", "tenia" and the like anywhere, and the agent edits the diaper without the brain |
| 40 | no wait, dejo un poco, ponele 100 | bottle stayed 110 ml, reply "Entendido, lo dejamos en 100 ml" | follow-up and claim: an amount for the bottle just logged went to the brain, which only answered, and the answer stated the new value as done | `rules.amount_followup` sets or subtracts the amount without the brain, and a brain reply that repeats the parent's number on a turn with no log change becomes the honest "nothing changed" |
| 45 | wet diaper at noon | diaper at 12:15 | clock: "noon" was not a time | same clock fix |

Step 42, "mire el pañal y esta seco, no la cambie", has no wrong state (nothing was logged), but the reply was "No pude terminar eso": the message says nothing happened and was still pushed to the brain as a log. Cause denied: a log of a kind the message says did not happen is now held, and `log_kind` no longer calls it a note. Step 41, a total question, got the same "No pude terminar eso" after 5 brain calls for 2 tool calls: the agent's own one-time checks (language, asked to log, asked to edit) each used one of the brain's tool rounds. Cause budget: a check is now one more brain call, never a lost round. The same pass also fixed the two open steps of the second set, a sleep start sent twice at the open start's time answered "Anoté", and "dejo como media onza igual" logging a second bottle.

## The 3 reply problems

All three (steps 11, 19 and 45) were English replies to English messages ("how much did she drink overnight?", "sorry 85 not 75", "wet diaper at noon"). The product rule since PR #89 is that a reply follows the language of the parent's message, so these were scorer errors, not agent errors. The scorer now flags a reply whose language differs from the message's, with the family's Spanish for a message that says neither. With that rule it would have caught one real problem it missed: step 18, "took 75ml of formula", was answered in Spanish because none of its words were on the English list. Cause language: "took", "of", "with" and a few more now mark English.

Every cause has a test in `tests/test_heldout3_misses.py`. Each test fails on 2eb896c and passes with the fix.

