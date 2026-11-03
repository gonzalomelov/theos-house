# The jobs moved to Muse: which cases were tuned on (Nov 3)

Run with `scripts/core_jobs_eval.py`, on the mock home, real Muse on Baseten, each run from a fresh thread. Prompt changes in `parenting_agent/core/agent.py`, in this order.

| Round | What changed | Result |
|---|---|---|
| 0 | No prompt change, tools only | morning 0/2, voice note 0/2, Echo 1/2, car seat 2/2, warmer due 0/2, warmer just fed 2/2, evening 0/2, wake 2/2, recipe 0/2 |
| 1 | Job lines added to the prompt | 8 of 9 cases 3/3, Echo 2/3 because the check didn't accept spoken numbers, fixed in the check |
| 1b | Rota line in the event: Muse told the wrong parent about tonight in 2 of 3 mornings | morning 3/3, with a check for it added |
| Held-out 1 | Written after round 1b, first run with no tuning | 24 of 27: 8 cases 3/3, "wake just fed" 0/3 |
| 2 | Prompt line for that failure: check next_feed when the wake comes | "wake just fed" 3/3, so that case is now tuned on |

| Held-out 3 | 12 new cases written before any run, after the claim check and the record from the calls. Not tuned on in this pass | 33 of 36: 10 cases 3/3, "dry room plug off" 1/3 (the plug stayed on at 41 %), "clean seat no coach" 2/3 (no reply at all to the parent once) |
| After round 3 | Round 3's two failures fixed: dehumidifier lines in the prompt, a second ask in code when a parent or a night cry got nothing. Night wake rule moved to code | Round 3 re-run 36/36, now spent. Tuned jobs 26/27 ("warmer cry due" 2/3: warmer on, nobody told, which led to the cry check). Live cases 21/21 |
| Held-out 4 | 14 new cases written before any run, committed first (`5260ede`). Not tuned on | **41 of 42**: 13 cases 3/3, "barking at night" 2/3 (woke the parent on duty about a dog, and said "Theo sigue durmiendo", which nothing showed) |

## Tuned on
morning, voice note, Echo question, car seat, warmer cry due, warmer just fed, evening plans prewarm, wake prewarms, wake just fed.

## Not tuned on (Held-out 1, once)
voice note from Ceci, Echo diaper count, quiet morning, dog by day, recipe in English, car seat from Ceci, red flag at the Echo, dose by voice. These were then run a second time, all 3/3, so they are spent: a new held-out round needs new cases.

## Spent, not to be reused as held-out
Round 3 (fixed after it) and round 4.

## Seen in the texts and not counted by the checks
- Muse added things the log doesn't say in 1 of 6 tuned mornings ("durmió bien entre medio") and one quiet morning ("noche tranquila").
- One car seat run sent "I'm here if you need anything else!" right after starting the coach.
- "pañal seco" and "los 3 secos" come from how the eval seeds diapers, with a type the log doesn't read as wet. Not Muse's mistake.

Limits: 3 runs per case on a mock home and a mock channel. The car seat case proves the tool is called and no steps are written, not the coach itself, which runs on the Mac with the glasses.
