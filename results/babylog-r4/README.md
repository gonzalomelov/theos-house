# Baby log, round 4 real-new-parent findings (issue #126)

**Fresh held-out set of 36 Spanish messages, scored once each with Muse Spark Open in log ops mode: origin/main 29 of 36 right, this branch 36 of 36.**

The round 4 real-new-parent judge (meta-hackathon-2026 `judges/rounds/r4/real-new-parent.json`) ran 36 new messages three times and found five problems. All runs below are from Oct 29 2026, Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten), `PA_FAMILIES_LOG_MODE=ops`, 0 fallbacks to Claude.

## What changed

| Finding | Fix | Code |
|---|---|---|
| "tomo 70 y vomito un poco" was only a note, the 70 ml left the day total in 3 of 3 judge runs | A symptom told with a feed amount or minutes goes to the log, not to the note-only path. The note with the parent's words and the feed are both kept, whatever Muse proposed. Code adds the feed only when Muse proposed none and the log has no such feed in the last 30 minutes. Without log ops, and on the red flag line ("tomo 40 y vomito todo"), plain code reads the amount | `rules.health_route`, `rules.symptom_feed`, `log_ops.observation_ops`, `Agent.log_observation` |
| The "No puedo darte consejo médico" tail after a symptom nobody asked about | The tail follows only a question or a fever. Every red flag, fever and refusal line stays as it was | `rules.asks_advice`, `Agent.note_observation`, `log_ops.decide` |
| "sii lo mande dos veces sorry" got "No worries, left it as one bottle" in 3 of 3 judge runs | The turn's language is the family's unless the message is clearly in the other language, so one "sorry" no longer flips it. A log ops reply in the wrong language is asked for once more, and a second wrong one is never sent | `rules.turn_lang`, `rules.clearly_english`, `FamilyService.talk`, `log_ops.decide`, demo `message_lang` |
| "a las 2 le di pecho 15 min" said at 15:00 was logged at 02:00 in 1 of 3 judge runs | A clock hour said with no half of the day ("a las 2", "a las 5 menos cuarto") lands on the latest of its two readings in code. "de la mañana", "anoche", "ayer" or a 24 hour time keep Muse's reading, and so does a correction of an existing entry | `log_ops.bare_hours`, `log_ops.clock` |
| "La última registrada de ayer fue a la 01:05" when 01:05 was today | A summary with an end time names its own last entries, feeds and sleeps carry their date, and the totals Muse reads are labeled with their dates | `BabyLog.summary`, `log_ops.context` |
| Demo `/api/state` unusual lines in English with Spanish selected | The unusual notes come in Spanish ("dom 25: 12,3 h de sueño en total, menos que las 14,8 h de siempre.", read from the demo's own state in a test run) | `patterns.unusual_notes(lang=)`, demo `proactive` |
| A demo correction that changed nothing said "lo último que tengo es la mamadera de 60 ml de las 12:12" right after it said the last was 100 ml at 19:11 | When the brain aims at an old entry, the reply names the real latest entry of that kind and asks if that is the one | `EDIT_WHICH` in `loop.py` |

## Regression tests

`tests/test_babylog_r4.py`, 22 tests built from the judge's exact messages. 19 of the 22 fail on origin/main `ad22532` and all pass on this branch. The full suite passes: 1005 tests, 4 skipped.

## The judge's own messages on this branch

The judge's harness (`martin4.py`, its 36 messages, real Muse, log ops) run once on this branch: `judge-messages-branch-1.txt`, 0.1697 USD, 0 fallbacks. "tomo 70 y vomito un poco" logged the 70 ml bottle and the note, with no advice tail, and the 20:00 push said "4 tomas, 160 ml en total" where the judge's three runs said 90 ml. "sii lo mande dos veces sorry" got "Perfecto, gracias por avisar. Queda solo la de las 03:45." "a las 2 le di pecho 15 min" at 15:00 went to 14:00, "le dimos 60 a las 11 menos cuarto" to 10:45. "cuantas mamaderas ayer" named 14:00 as yesterday's last, not today's 01:05. One run, and these are the messages the fixes were built from, so this is a check, not a blind score.

One thing this run shows that is not fixed here: the same 20:00 push says "la última a las 14:00" and then "Ya pasaron 6 h 15 min desde la última toma anotada, a las 13:45". The overdue line counts from when the 15 minute breast feed started, the summary from when it ended.

## Held-out set

`heldout.json` was written and committed before any code change (commit `Held-out set for the round 4 baby log fixes, frozen before any code change`). sha256 `27ed816c3d04359f246266108ad8e7d130c8a69d1b228a009b12239af6ad9407` (`heldout.sha256`). 36 Spanish messages from two tired parents, baby Lola, Nov 2 22:10 to Nov 4 13:30, two nights. Every message was grepped against `tests/`, `scripts/`, `results/` and `parenting_agent/` with 0 hits. Each message names the log change it must make and what the reply must or must not say, and every reply must be in Spanish. A message is right only when every check passes. `score.py` runs it through `Families.handle` and `tick` with a simulated clock, no Telegram.

| Run | Right | Spanish replies | Fallbacks | Spend |
|---|---|---|---|---|
| origin/main `ad22532` (`main-1.md`) | 29 of 36 | 36 of 36 | 0 | 0.1428 USD |
| this branch (`branch-1.md`) | **36 of 36** | 36 of 36 | 0 | 0.1707 USD |

The 7 misses on main: three symptom-with-feed messages stored as notes only (80, 120 and 60 ml lost) with the unasked tail, "tomo 40 y vomito todo" with the red flag line and the 40 ml lost, "vomitó un poco, nada más" with the unasked tail, and two total questions whose answers were wrong because of those lost feeds ("cuanto tomo hoy en total?" said 90 ml for 210, "cuanto tomo ayer de mamadera?" said 190 for 370).

Honest limits:

- On this run main answered every reply in Spanish and put all four bare clock hours on the right half of the day, so the language and clock fixes are proven by the tests and the judge's own messages, not by this held-out score. Muse got those right by itself this time, as it did in 2 of 3 judge runs for the clock.
- One run each. Muse varies from run to run.
- The set was written by the same agent that wrote the fixes, before the fixes, from the judge's finding types. It targets those types on purpose, so 36 of 36 says the fixes generalize to new phrasings of these problems, not that the log is right on every message a parent can write.
