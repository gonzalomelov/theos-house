# Keeping the families log right (issue #77)

The folder name is the round 2 goal, not a result: the fifth blind set later scored 1 of 45 wrong with Muse log ops (`results/families-log-ablation/`).

**Update, later on Oct 29: the rule guards were replaced as the default by Muse log ops, which scored 1 of 45 on a fifth
blind set against 13 of 45 for the guards. See [../families-log-ablation/README.md](../families-log-ablation/README.md).**

## Blind numbers first

Four sets of 45 messages were written by agents that changed no code, and each was scored once before anyone read it.

| Blind set | Code | Wrong log states | Reply problems | Files |
|---|---|---|---|---|
| First | main at `58bce86`, before the fixes of PR #103 | **8 of 45** | 1 | [heldout/](heldout/README.md) |
| Second | main at `86d7c0e`, after every families fix of Oct 29 | **8 of 45** | 5 (4 are English replies to English messages) | [heldout2/](heldout2/README.md) |
| Third | main at `2eb896c`, after the meaning based guards of PR #105 | **5 of 45** | 3 (all English replies to English messages) | [heldout3/](heldout3/README.md) |
| Fourth | main at `8ab6568`, after the third set's fixes (PR #107) | **11 of 45** | 1 | [heldout4/](heldout4/README.md) |

The fixes after the first set did not carry over to new phrasings. Six of the 8 second-set misses have one cause, the
guards decide what the parent said from fixed word lists, and that is what the next fix targets. Everything below this
section is on sets the fixes were tuned on, so those numbers are tuned numbers, not blind ones.

## After the third set's fixes (Oct 29)

The third set's misses had six causes (clock forms, a feed length given as times, follow-ups whose words sat anywhere,
a reply stating a value the log never took, a message saying something did not happen, the agent's checks using up the
brain's rounds) plus an English message not seen as English. Each has a test in `tests/test_heldout3_misses.py`, see
[heldout3/](heldout3/README.md). The scorer now flags a reply in a different language from the parent's message, not
every English reply.

`heldout3-fixes-old-1`: one run of `--sets old,judge` on that code, Muse Spark Open, 0 fallbacks, 0.81 USD. Old set 0 of
70 wrong, review set 1 of 37 wrong, 0 reply problems. The one miss, review step 26, "tiene la nariz tapada y le cuesta
tomar": Muse answered with no text and no tool call, so the parent got "OK." and no note. The same message was noted in
the three earlier runs of this set. Fix after the run: an empty answer is asked again once, as one more brain call
(`test_empty_an_empty_answer_is_asked_again`). It was not rerun, the brief allowed one run.

## Tuned sets

All runs on Oct 29 2026, Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten), 0 fallbacks to Claude.

Review round 2 found that in 1 of 3 nights the bot logged 90 plus 70 ml for one bottle while saying "corregido", and that "se mando doble perdon" deleted the only breast feed. This run asks the same question on new phrasings: after each message, is the log what a careful parent would have written?

## The run

`scripts/families_never_wrong_run.py`: 70 new tired-parent messages over 3 simulated nights (Oct 29 to 31, Montevideo clock), two parents, the families service through `Families.handle` and `tick`, no Telegram. Typos, no accents, voseo, double sends of bottles and breast feeds, an unclear answer to the double-send question ("q?"), corrections of amounts ("nono 70", "nonono 110", "ahh no era 120", "me equivoque, eran 2 onzas", "dejo 30, o sea tomo 120"), of sides ("no perdon, fue el izquierdo"), of times ("no, fue a las 9 y media", "perdon, a las 13:40"), of a diaper ("ese pañal era solo pis"), of a duration, explicit deletes, a "se mando doble" with nothing sent twice, a sleep from "a las 3 y 20", questions, a health question and two observations. None of the messages comes from the judge's harness or from `scripts/families_3day_run.py`. As the judge did, `memory.now` is patched to the simulated clock.

After every message the whole log (kind, time, method and side, ml, milk type, duration, diaper contents, sleep start, notes) is compared with the expected log. A difference is one wrong log state, recorded with its diff, and the real log becomes the new truth so a miss is counted once. Replies are checked too: a claimed change that did not happen, a claimed log with nothing logged, "No pude anotarlo" for a question, a next-feed answer with neither a time nor how long ago.

### Results on the tuned 70 messages

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

## The review's own harness

`judge-harness-rerun.txt`: the review harness (35 messages) run once on this branch, 0.25 USD. The final log is right: one 70 ml bottle at 02:10 after "nono eran 70" (no added bottle, the day says 170 ml, not 260), the 05:20 breast feed kept as the right breast after "se mando doble perdon", the double-send question says "dos tomas de pecho", "teta izq y der" is both breasts, "vomito un poquito dsp de la toma" is noted with the no-advice line in one turn, "a q hr le toca" gets how long since the last feed, and "/proxima" on its sparse log no longer says "cada 12 h 40 min". In that run "respira raro hace un ruido como silbido" was noted without the no-advice line, which is the change above. On main after #80 that message hits the emergency gate (911 at once), so the families bot no longer sends it to the brain.

## Rerun on main after PRs #78 to #86 (Oct 29)

The runs above were on the #85 branch before it was rebased onto #78 to #84. On main at `779e4d0` (#86 merged) the eval ran 3 times and the 29-check script once. The four ran in parallel, so Baseten answered some calls with HTTP 429 and those turns fell back to Claude Haiku. The per-step brain is not recorded, so a miss cannot be put on one brain.

| Run | Code | Wrong log states | Reply problems | Fallbacks to Haiku | Spend |
|---|---|---|---|---|---|
| `main-1` | `779e4d0` | **1** | 0 | 9 | 0.571 USD |
| `main-2` | `779e4d0` | 0 | 0 | 12 | 0.550 USD |
| `main-3` | `779e4d0` | 0 | 0 | 6 | 0.539 USD |
| `fix-1` | `779e4d0` plus the wake-up fix, run alone | **0** | 0 | **0** | 0.545 USD |

The miss in `main-1`, step 31, "se desperto a las 5" while a sleep from 03:20 was open: the brain called a sleep `start` at 05:00, which replaced the open 03:20 start, then an `end` at 05:00, which failed because a sleep must end after it starts. It read the log twice, ran out of steps and answered in English "I stopped after too many steps". The 03:20 to 05:00 sleep was never logged. Fix: a message that says the baby woke up and says nothing about falling asleep never starts a sleep. The call is held and the brain is told to log the wake-up as the end of the open sleep (`tests/test_log_edit.py`, `WakeUp`, fails without the fix). In `fix-1` Muse called only `end` on that message, so the guard did not fire in the live run. The unit test is what shows it holds.

Only one run was done on the fix. Three more runs at about 0.55 USD each would have taken tonight's spend past the 3 USD cap (1.89 USD before the fix, 2.43 USD after `fix-1`). The 3 runs on main with no fix had 1 wrong state, and the one run with the fix had 0.

## A first entry is never a correction, and the reply follows the message's language (Oct 29)

On the live families bot at `845463d` the voice agent saw two bugs. A brand-new test family's first bottle note was answered "Corregí ... 15:00 → 02:15", a correction on a log with no earlier entry. An English voice note was answered in Spanish.

- First entry: the brain logged the bottle at the current time (15:00) and then edited that same new entry to the time the parent said, and the edit was reported as a correction. Now an edit or delete of an entry logged by the same message is part of logging it, and the reply says what the log holds, with the final time and no "→". A message with correction words ("perdon, eran 90") on an empty log is logged, never held as a fix. It did not happen again in 6 live tries (3 messages, before and after the fix), so the tests script the brain (`tests/test_log_edit.py`, `FirstEntry`, they fail without the fix).
- Language: a family kept the language it started in for every reply. Now each reply is in the language of the parent's message, and a message whose words say neither ("120") gets the family's language. A language chosen with /idioma or /language wins over the message. Pushes and summaries keep the family's language. Live before the fix (`scripts/families_first_entry_live.py`, Muse): "Gave her a 60 ml bottle at 2:15" in a family that started in Spanish was answered "Anoté la mamadera de 60 ml de las 14:15." After the fix it was answered "Logged the 14:15 bottle of 60 ml." Tests: `ReplyLanguage`. Two old tests changed with the rule: an English red flag in a Spanish family now gets the English emergency line, and the Spanish-mode leak test sends a Spanish fever message instead of "she has a fever".

On this code the 29-check script passed 29 of 29 with 0 fallbacks (0.246 USD, `results/families/three-day-first-entry.md`). The never-wrong eval ran 3 more times on it later with a separate 2.5 USD budget, see Final below. Spend tonight: 2.68 USD in eval runs plus about 0.03 USD in live checks.

## Final: 3 runs in a row on main with #87 and #89 (Oct 29)

Run one at a time on `fbbd7ce` plus this PR's change (fixed agent texts in the reply language), Muse Spark Open. The script now records which brain answered every call of every step (`steps` and `fallback_steps` in the JSON, a `brain:` line in the transcript), and counts an English reply to these Spanish parents as a reply problem.

| Run | Wrong log states | Reply problems | Steps with a fallback | Spend |
|---|---|---|---|---|
| `final-1` | **0** | 0 | 0 | 0.587 USD |
| `final-2` | **0** | 0 | 0 | 0.566 USD |
| `final-3` | **0** | 0 | 0 | 0.552 USD |

Every brain call in the three runs was answered by Muse. The bar, 0 wrong log states in 3 runs, holds on the final code.

The English "I stopped after too many steps" from `main-1` is gone: every fixed agent text is now in English and Spanish and follows the reply language (out of steps, and the Done, Not done and Nothing was waiting lines after a yes). When the brain runs out of steps after something was logged, the reply says what was saved, so the parent does not send it again (`tests/test_log_edit.py`, `FixedTextsInTheReplyLanguage`, fails without the fix). The rule brain that answers after the spend cap already answered in Spanish.

## Round 3: confirmations from the log diff, plus the review's 37 messages (Oct 29)

Review round 3 ran 37 new phrasings and the log ended wrong in 7 of 9 nights, 3 of them under a confident "Anoté", "Corregí" or "ya anoté el sueño, no hace falta que lo mandes de nuevo". The fix is structural: every confirmation is built from the diff of the log before and after the turn (`docs/families.md`, "Every confirmation from the log diff"). Its 37 messages are now `JUDGE_STEPS` in the eval, with the log a careful parent keeps, and the default run plays the team's 70 and its 37, each in a new family. These 37 were the dev set for this fix, so the review set is not a held-out number.

| Run | Code | Team 70: wrong states | Review 37: wrong states | Reply problems | Fallbacks | Spend |
|---|---|---|---|---|---|---|
| `r3diff-1` | diff-based confirmations, before the breast minutes fix | 1 | 1 | 0 | 0 | 0.887 USD |
| `r3diff-2` | final branch | 1 | **0** | 0 | 0 | 0.885 USD |

Both runs ran one at a time, Muse Spark Open, 1.77 USD in all.

- `r3diff-1`, review step 4, "pecho izquierdo 15": Muse logged the left breast with no duration. Fix: a single bare number after a breast side, with no bottle word and no time, is minutes. In `r3diff-2` it kept 15 min.
- Both runs, team step 47, "tiene fiebre le doy paracetamol?": the newborn fever red flag from PR #97 now logs a note before the call-now line. The eval still expects no entry for that message. The log is not wrong, the expected op is out of date, and that path belongs to the safety work, so it was left as it is.

In `r3diff-2` the review's misses all ended right: "ya se levanto" closed the 09:10 sleep ("Anoté el sueño de 09:10 a 10:20"), "no espera, fue a las 12" moved the bottle to 12:00, "en realidad tomo 3, dejo una" after "mamadera 4 onzas" became 90 ml, "hizo una siestita de 40 min" was one 40 min sleep, the half bottle was 60 ml, "de mamadera digo" changed nothing and said so, "q comio ayer en total" said 3 feeds and 150 ml for Oct 30 only, and "durmio 2 horas recien se desperto" was one sleep from 13:00 to 15:00.

To score another message file through the same harness, write it as JSON in the STEPS shape (see the script's docstring) and run:

    .venv/bin/python scripts/families_never_wrong_run.py --keys-env ~/.parenting-agent.env \
        --steps-file path/to/steps.json --out results/families-never-wrong/heldout-1

## What did not get tested

- No real parent, no voice notes, no Telegram in these runs.
