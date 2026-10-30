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
| Baby Buddy | Real, on the Vostro. The agent's API user cannot create a child (by design, `docs/deploy-babybuddy.md`), so the run uses the test child "Test Baby" in a window after its last entry (Oct 29 05:05) and before now: Oct 29 06:00 to Oct 30 08:30. Its earlier test entries are the history. Before each run the harness removes what an earlier run added in that window and nothing else |
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
