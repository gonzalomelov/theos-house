# The families log is never wrong (issue #77)

All runs on Oct 29 2026, Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten), 0 fallbacks to Claude.

The round 2 real-new-parent judge found that in 1 of 3 nights the bot logged 90 plus 70 ml for one bottle while saying "corregido", and that "se mando doble perdon" deleted the only breast feed. This run asks the same question on new phrasings: after each message, is the log what a careful parent would have written?

## The run

`scripts/families_never_wrong_run.py`: 70 new tired-parent messages over 3 simulated nights (Oct 29 to 31, Montevideo clock), two parents, the families service through `Families.handle` and `tick`, no Telegram. Typos, no accents, voseo, double sends of bottles and breast feeds, an unclear answer to the double-send question ("q?"), corrections of amounts ("nono 70", "nonono 110", "ahh no era 120", "me equivoque, eran 2 onzas", "dejo 30, o sea tomo 120"), of sides ("no perdon, fue el izquierdo"), of times ("no, fue a las 9 y media", "perdon, a las 13:40"), of a diaper ("ese pañal era solo pis"), of a duration, explicit deletes, a "se mando doble" with nothing sent twice, a sleep from "a las 3 y 20", questions, a health question and two observations. None of the messages comes from the judge's harness or from `scripts/families_3day_run.py`. As the judge did, `memory.now` is patched to the simulated clock.

After every message the whole log (kind, time, method and side, ml, milk type, duration, diaper contents, sleep start, notes) is compared with the expected log. A difference is one wrong log state, recorded with its diff, and the real log becomes the new truth so a miss is counted once. Replies are checked too: a claimed change that did not happen, a claimed log with nothing logged, "No pude anotarlo" for a question, a next-feed answer with neither a time nor how long ago.

## Results

| Round | Code | Run 1 | Run 2 | Run 3 | Reply problems | Spend |
|---|---|---|---|---|---|---|
| First | first fixes | 2 wrong states | 0 | 2 | 1 | 1.75 USD |
| Second | plus ounces, "q?" | 0 | 3 | 0 | 1 | 1.71 USD |
| Final | plus no earlier amount or edit rides along | **0** | **0** | **0** | **0** | 1.64 USD |

Every miss, with its log diff (files `first-*.json`, `second-*.json`):

- First rounds 1 and 3, "tomo 3 onzas": Muse logged 89 ml (29.6 ml an ounce), expected 90, and the correction "eran 2 onzas" became 59 ml. Fix: an ounce is 30 ml, as the bottle marks read, applied to logs and edits.
- First round 1, the answer "q?" to the double-send question went to the brain, which asked again in its own words. Fix: a 1 to 3 letter answer is unclear, so the agent keeps one and asks once more itself.
- Second round 2, "pañal pis nomas": Muse logged the diaper twice (once with `solid: false`) and also called `edit_baby_event` on the 00:40 bottle. Extra: a second wet diaper at 01:30. Fix: a diaper's missing field is false when two calls are compared, and an edit or delete on a message that corrects nothing never touches an earlier entry.
- Second round 2, "teta izq 15 min": Muse logged the 00:40 bottle's 120 ml again and then edited that new entry into a breast feed, so the log held a left breast feed of 120 ml with no milk type, and the reply said "Corregí". Then the repeat "teta izq 15 min" was logged a second time, because the first one did not look like the same feed. Fix: an amount the message never names is dropped, and a message that says teta or pecho and no bottle word is a breast feed.
- Before any of this, the dev run found "se quedo dormida a las 3 y 20" logged as 03:00. Fix: "a las 3 y 20" is 03:20.

The final change after these runs only adds the no-advice line to a note the brain logged when the brain's answer spoke of the pediatrician or 911. It changes no log state.

## The judge's own harness

`judge-harness-rerun.txt`: his `martin.py` (35 messages) run once on this branch, 0.25 USD. The final log is right: one 70 ml bottle at 02:10 after "nono eran 70" (no added bottle, the day says 170 ml, not 260), the 05:20 breast feed kept as the right breast after "se mando doble perdon", the double-send question says "dos tomas de pecho", "teta izq y der" is both breasts, "vomito un poquito dsp de la toma" is noted with the no-advice line in one turn, "a q hr le toca" gets how long since the last feed, and "/proxima" on his sparse log no longer says "cada 12 h 40 min". In that run "respira raro hace un ruido como silbido" was noted without the no-advice line, which is the change above. On main after #80 that message hits the emergency gate (911 at once), so the families bot no longer sends it to the brain.

## What did not get tested

- The old 29-check script `scripts/families_3day_run.py` is kept, it was not rerun tonight.
- No real parent, no voice notes, no Telegram in these runs.
