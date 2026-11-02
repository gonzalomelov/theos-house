# End-to-end day: the family agent through one first-month day and night

Oct 30 2026. Gonza's ask: the always-on agent should feel like an assistant, smooth, with only what is relevant to each parent, and nothing mock. This runs the real family agent, as deployed on the Vostro, through a full day and night on a fast clock and scores what a parent would feel.

```bash
python -m parenting_agent.e2e --label before                      # config/agent.vostro.json as it is
python -m parenting_agent.e2e --label after --set baby.born=true  # the same day once Theo is born
python -m parenting_agent.e2e --score results/e2e-day/before      # score a run again
```

Needs the Baby Buddy and Home Assistant tunnels (`docs/deploy-agent.md`) and the secrets file. One run takes about 26 minutes of real time.

## What is real and what the harness replaces

| Part | In the run |
|---|---|
| Plug-ins, their own run loops, the config | Real: `config/agent.vostro.json`, every plug-in it lists, started the way `python -m parenting_agent` starts them |
| Brain | Real: Muse Spark Open on Baseten, Claude Haiku as its fallback |
| Voice note | Real: Muse hears `results/voice/notes/es01.ogg` ("Le di noventa mililitros de mamadera a las tres"). ffmpeg runs on the Mac, because the voice service is on the Vostro's internal network. The spoken reply is recorded as text, not synthesized |
| Baby Buddy | Real, on the Vostro. The run has its own child, "E2E Baby" (`e2e-baby`), that only the harness writes to. Before each run the harness deletes every entry it holds and writes the fixed history again (`parenting_agent/e2e/history.json`, Test Baby's test entries up to Oct 29 05:05), so demo, video and glasses runs on Test Baby cannot leak into the run. The day is Oct 29 06:00 to Oct 30 08:30 |
| Home Assistant | Real reads (states, weather, the shopping list, calendars). Every write is forced dry: `house.live_actions` is emptied and any Home Assistant POST that is not a read is refused before it leaves the Mac |
| Clock | Virtual: freezegun moves it one minute per step, each plug-in loop waits in virtual time (`parenting_agent/e2e/clock.py`) |
| Telegram | A capturing messenger with made-up chat ids for Gonza and Ceci. A call to api.telegram.org is refused at the socket level |
| Night cry | A "sound" event marked simulated: no microphone feeds the family agent on the Vostro |

## The day (`parenting_agent/e2e/day.py`)

Both parents write in Spanish. Gonza and Ceci log 9 feeds (bottle and breast), 9 diapers, 8 sleeps and a bath by message, Gonza says how many diapers are left, the grandmother writes to the bot from her own chat (there is no grandma user in the people block) and then through Ceci, Ceci asks for a handover for her mother from 15:00 to 18:00, Gonza asks for diapers on the shopping list, Ceci asks to sleep tonight at 20:00, a cry at 02:50, a voice note for the 03:00 bottle, then the morning.

## How it is scored (`parenting_agent/e2e/score.py`)

- Every message that left: noise when it has an English sentence to a Spanish parent, internal words (finish reason, Muse, JSON, Parent A or B, snake_case names), prep lines after the birth, the same push twice, a night push to Ceci after she asked to sleep, or a night push to the parent who just said he is up.
- 34 things a parent must get: one morning message each day, a next feed reminder before each day feed, nap mode on after each sleep, the night handover, tonight's plan once, the cry push to the parent on duty, nothing to Ceci at night, diapers running low once each, the shopping list once, the sitter brief and its summary, the grandmother's question answered, the voice note heard, no doorbell, and each morning message clean.
- 25 log entries the parents asked for, looked up in Baby Buddy (kind, time, amount or side).

## Before and after

Both runs are scored by the same final scorer (`python -m parenting_agent.e2e --score`). After is the same day with the fixes of #148 and the Vostro config with one override, `baby.born=true`, the switch Gonza flips when Theo is born.

| Number | Before (`before/`) | After (`after/`) |
|---|---|---|
| Things a parent must get | 11 of 34 | 30 of 34 |
| Messages out (proactive, replies) | 55 (17, 38) | 58 (19, 39) |
| Noise | 16 of 55 | 0 of 58 |
| Log entries right | 24 of 25, 2 entries nobody asked for | 25 of 25, none nobody asked for |
| Brain | 0.57 USD, 95 Muse calls | 0.60 USD, 97 Muse calls |

The 4 misses after, said plainly:

- Next feed reminders before the 08:15 and the 10:40 feeds. The rhythm guesses from the median of the last two gaps, and Test Baby's own test history ends with two feeds a minute apart at 01:12 and a 4 h 43 min gap, so the first guesses of the day landed after the real feeds. From the third feed on every day feed got its reminder (12:20, 15:25, 17:58, 20:28), in Spanish, once, to both.
- The next feed reminder before the 06:15 feed: the rhythm expected it at 05:45, which is night, and at night the night feed gets the house ready on a real awake signal instead of a guess. By design.
- Diapers running low: Gonza said 26 at 06:20, the day used 7, so 19 were left at about 8 a day, 2.4 days, over the 2 day line, and no low push went out. The morning message on day 1 said "Se está terminando: Pañales (quedan unos 2.9 días)" to both. In the second after run (`after-run2/`, 31 of 34) the same routine pushed both parents once at 18:41 in Spanish, because a stray diaper entry made the count lower (that stray entry is one of the bugs fixed after it).

The three after runs, in order, all scored by the final scorer: 30 of 34 with noise 7 of 62 (the floor clean question still in English, and "Gonza comió por última vez" about the baby, both fixed), 31 of 34 with noise 0 of 60 and one stray diaper entry (fixed), and the final one above. `after/` is the last and `after-run2/` the second, the first is not kept. Spend on the e2e in all: about 3.4 USD of Muse (6 full runs, one of them lost to a dropped tunnel, plus 4 ear checks).

## Before: current main and the Vostro config as deployed (`before/`)

Commit 4a5af73, `before/timeline.md`. Brain spend 0.57 USD (95 Muse calls).

| Number | Before |
|---|---|
| Things a parent must get | 11 of 34 |
| Messages out (proactive, replies) | 55 (17, 38) |
| Noise | 16 of 55: 14 with English to a Spanish parent, 4 prep lines after the birth, 4 repeated pushes, 1 internal text, 1 night push to the parent who just said it (one message can have several) |
| Log entries right | 24 of 25 |

What a parent would have felt:

1. No next feed reminder all day (0 of 6): the rhythm plug-in is not loaded on the Vostro.
2. Nap mode never came on (0 of 8 sleeps): "se durmió" starts a Baby Buddy timer, and the routines read only finished sleeps, so they see a sleep only once he is awake again.
3. Three floor clean questions in English to both parents ("I could run the floor clean before 08:56, but the log does not say where he is..."), the same one each nap.
4. Tonight's plan in English to both, then each parent's plan line in English too ("For Gonza: On duty...").
5. The night push for 22:20 went to Gonza, who had just written "Se despertó", and every night push was in English.
6. The morning messages carried "Antes de que llegue: Unos 47 días para la fecha de parto" a day after the birth, and Gonza's had "La casa de noche: At 06:11 a plan was armed... Muse..." in English. "te levantaste 0 veces".
7. Diapers: "Tenemos 26 pañales en casa" was kept as a free note ("Gonza: Tenemos 26 pañales en casa") that the supplies routine cannot read, so nothing said diapers were running low. The shopping list reply ended in English: "Dry run: house.live is off, so this was only written down".
8. "Mi mamá pregunta cuándo comió por última vez." got "No pude anotarlo, ¿me lo repetís?": no question mark and a feed word made it a log request.
9. The sitter plug-in is not loaded: the brain wrote its own summary for the grandmother (it read well), but there was no guest window and no summary after.
10. The voice note was heard as "Le di 90 ml de mamadera a las 11": the ear prompt's example said "a las 11", and the 03:00 bottle went into the log at 22:45.
11. A camera fired the door routine 9 times in 26 minutes of real time (dry Echo announcements, no message).
12. What worked: every log by text landed right (24 of 25, the miss is the voice note), the answer to Ceci at 20:00 named Gonza for the night, the cry push reached only Gonza, nothing reached Ceci at night, the grandmother's own chat got nothing (no grandma user exists), one morning message each day.

## After: what changed (`after/timeline.md`)

| Before | After |
|---|---|
| No next feed reminder | One per feed, 20 min before, by day, both parents: "Próxima toma en unos 20 min, cerca de las 12:40. Las tomas vienen cada 2 h 15 min más o menos." (`rhythm.engine:RhythmPlugin` loaded) |
| Nap mode never on | On within a minute of each "se durmió", and quiet all night (an open Baby Buddy sleep timer is a sleep going on) |
| Floor clean question in English after every nap | In Spanish, once a day |
| Tonight's plan and each parent's line in English | "Plan de esta noche. De turno: Gonza. Calentador de mamadera (solo agua) a las 23:50, 02:30, 05:15." Muse's English sentences stay in the event log |
| Ceci asks to sleep: the brain answers her | Also one push to Gonza: "Ceci pidió dormir esta noche, así que esta noche estás de turno vos, Gonza." Night pushes go to him only |
| Night push to the parent who just wrote "Se despertó", in English | No push to him (he knows), the cry push in Spanish: "Se despertó, se oyó un llanto. Luz del estudio tenue: solo anotada (prueba en seco)..." |
| Nobody noted who got up, the morning said "te levantaste 0 veces" | "Night wake-up handled by Gonza" in the log per wake-up: day 1 says "te levantaste 2 veces" to Gonza, "no te levantaste. Esta noche te toca a vos." to Ceci |
| Prep lines and English Muse text in the morning after the birth | No prep lines after the birth. The house's night only to the parent who was on duty, only when it got ready for a feed, in Spanish |
| "Tenemos 26 pañales" a free note, and later a diaper too | `set_supply_stock` keeps "Stock: diapers 26" once, no diaper logged |
| "Mi mamá pregunta cuándo comió..." got "No pude anotarlo" | "Fue a las 10:40, tomó 90 ml de mamadera." |
| No sitter plug-in | Draft in Spanish to Ceci at 12:00, and at 18:00 "Mamá de Ceci cuidó a Theo de 15:00 a 18:00. En el registro de esas horas: 1 toma (80 ml), 1 pañal." |
| Voice note heard "a las 11", logged at 22:45 | "Le di 90 mililitros de mamadera a las 3", logged at 03:00 (no example values in the ear prompt, 4 of 4 checks right) |
| Door routine false alarms | 0 |
| English dry-run note under a Spanish reply | "Prueba en seco: solo quedó anotado, no se movió nada en la casa." |

Still open, not scored: the brain named the grandmother "Mamá de Ceci" in the draft, and after the draft it offered to send it although sending to a sitter is not built (the draft itself says "Reenviáselo vos"). There is no grandma user, so a grandmother who writes to the bot herself gets nothing: adding her needs her chat id, which only Gonza has.

## Final guard, the coach in Spanish, and blind round 1 (Oct 30 to 31, issue #165)

The same harness, before and after the changes of issue #165, on the same day. Before is origin/main at 3f27109 run from a clean worktree, after is the PR branch. Both with `--set baby.born=true`, the after day of #148. The glasses day scenes are the 11 scenes of `scripts/glasses_hud_day.py` with no simulator and no SAM 3.1 (`scripts/glasses_day_noise.py`): both parents' glasses are event-stream listeners and the car seat coach looks at the unit tests' fixed picture of a correct install, so its camera steps pass without a heavy model. Every text that reached a parent counts: Telegram, glasses cards, glasses replies and the coach's spoken lines.

Two scores. "Scorer noise" is `parenting_agent/e2e/score.py` as it was: English to a Spanish parent or its internal words. "Strict noise" adds what the scorer misses: any sentence the final guard would remove for a Spanish parent, and any "0.0 h".

| Run | Texts to a parent | Scorer noise | Strict noise | Muse |
|---|---|---|---|---|
| After day, before (`guard-before/`) | 58 | 0 | 0 | 0.58 USD |
| After day, after (`guard-after/`) | 58 | 0 | 0 | 0.59 USD |
| Glasses day scenes, before (`glasses-before.json`) | 64 | 11 (all 14 coach lines were English, 11 long enough to count) | 15 (the 11, plus "el sueño más largo 0.0 h" in both morning messages and both morning cards) | 0.13 USD |
| Glasses day scenes, after (`glasses-after.json`) | 62 | 0 | 0 | 0.11 USD |

Muse spend for the four runs: 1.40 USD.

What the numbers say, plainly:

- The after day was already clean before (0 of 58, as in the #148 after run). The final guard removed nothing in either after run: there were no `final_guard` events. The guard is a net for Muse's bad days, these two runs had none. The unit tests show it removing finish reason, JSON, tool and model names, Parent A or B and English sentences on every path (`tests/test_coach_language_and_final_guard.py`).
- The glasses scenes carried the real noise, and it is gone: the car seat coach now speaks Spanish to Gonza (all 14 lines, "Te guío con la Joie i-Snug 2 en el Tesla Model 3...", the summary "Chequeos con cámara que pasaron: ..."), and its summary is its own last line. Before, Muse rewrote it as "Instalación casi lista, Gonza", a near verdict.
- "el sueño más largo 0.0 h" came from the night summary counting only sleeps that started after 22:00, so the night's sleep from 19:40 counted as nothing. After: "el sueño más largo 2.7 h".
- "¿Cuándo comió por última vez?" on the glasses: before Muse answered "La última toma fue a las 8:10, 90 ml en mamadera.", after plain code from the log with no brain call, "La última toma fue la mamadera de 90 ml de fórmula de 15 min de las 08:10.", the same every time.
- Things to get stayed at 30 of 34 on the after day and log entries right at 25 of 25. The glasses scenes passed 9 of 11 in both runs: nap mode on and off never drew a card in this no-simulator harness, before and after, so that is the harness, not this change (the recorded day with the app passed both).
- `log_extra` went from 8 to 21 between the two after-day runs. Those are Baby Buddy entries on the test child timed Oct 30 23:01 UTC to Oct 31 02:42 UTC, real time, outside the run's window (Oct 29 09:00 to Oct 30 11:30 UTC): another agent working on the test child at the same time, not this run.

Regression tests for blind round 1: `tests/test_blind_round1_clean_replies.py` (the last feed in one line on the family agent, the families bot and the demo, no brain call, three times the same; no 0.0 h; the Spanish demo never mixes Parent B, Persona B and English "why" lines; the cry text in Spanish).

```bash
python -m parenting_agent.e2e --label guard-after --set baby.born=true --out results/e2e-day/guard-after
python scripts/glasses_day_noise.py --out results/e2e-day/glasses-after.json
```

## Rerun after #187 to #198 (Nov 1, PR #200)

The same after day (`--set baby.born=true`) on E2E Baby, from a clean worktree.

| Run | Things to get | Noise | Log right | Muse |
|---|---|---|---|---|
| main at a0e4a87 (`nov1/`) | 29 of 34 | 2 of 62 | 25 of 25, 0 extra | 0.59 USD |
| main at da87075, after PR #200 (`nov1-fix/`) | 30 of 34 | 0 of 60 | 25 of 25, 0 extra | 0.60 USD |

The regression: Ceci got "Cambió el plan" at 22:05 and 01:46 after she asked to sleep. Round b5 gave Muse a Spanish why for a re-plan, so a Spanish family now reads it, and a re-plan was a shared push. Since PR #200 a re-plan at night goes to the parent on duty only. The 4 misses are the same as before (two first feeds and the 06:15 feed without a reminder, no diapers low push at 2.4 days). The 02:50 cry push reached Gonza only, with the side bed line.

## Rerun after PR #202 (Nov 2)

The same after day on E2E Baby, from a clean worktree at main 27e2635, the family agent deployed with it.

| Run | Things to get | Noise | Log right | Muse |
|---|---|---|---|---|
| main at 27e2635, after PR #202 (`nov2-fix/`) | 34 of 34 | 0 of 65 | 24 of 25, 1 extra | 0.60 USD |

The 4 misses are gone. The next feed median skipped the history's 19 h and 29 h log holes, so reminders came at 08:10 and 10:02, before the 08:15 and 10:40 feeds. The 06:15 feed, expected at 05:30, got its reminder at 05:10 to Gonza only, on duty after Ceci asked to sleep, and the 20:25 reminder went to Gonza only too. Diapers low reached both parents once at 16:01 in Spanish, 22 left at 8 a day (2.75 days, under the new 3 day line), before Gonza asked for the shopping list at 16:10. The one log miss is not from #202: at 03:30 "Se durmió" got "Sigue dormido desde las 22:55", so the 22:55 sleep was never closed, and at 06:05 "Se despertó" wrote a sleep from 03:00 to 06:05 instead of ending the 03:30 one.

## Rerun after the stale open sleep fix (Nov 2, `nov2-run3/`)

At 03:30 "Se durmió" had got "Sigue dormido desde las 22:55" (a sleep opened at 22:55 was still open after the 02:45
feed), so "Se despertó" at 06:05 wrote a sleep from 03:00. Now a new "se durmió" with a sleep open since before a logged
feed closes that sleep at the feed's start and opens the new one (`log_ops.stale_sleep_ops`).

| Run | Things to get | Noise | Log right | Muse |
|---|---|---|---|---|
| `nov2-run3/` | 34 of 34 | 0 of 65 | 25 of 25, 1 extra | 0.59 USD |

The 03:30 reply: "Anoté el sueño de 22:55 a 02:45, 3 h 50 min y que el bebé se durmió a las 03:30", and 06:05 closed
03:30 to 06:05. The 1 extra entry is that closed 22:55 to 02:45 sleep: no parent said when he woke, the agent ends it at
the feed by design, and the scorer counts any entry nobody asked for.
