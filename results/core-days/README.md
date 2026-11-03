# Simulated days (Nov 3)

The real core through its one event path, on the mock home, with a simulated clock and faults on purpose. The harness is
`parenting_agent/core/days.py`. No real device moved and no real message went out.

## Scripted model, in the suite

`tests/test_core_days.py`: 14 days with every kind of fault, about 20 s. It tests the machinery, not Muse's judgement: the scripted
model behaves well except where told to misbehave. Three other checks take a guard away or feed a bad result, to prove the invariants can fail.
Also run by hand, seeds 11 and 23: 42 days each, 628 and 677 events, 0 violations.

| Measured over 42 days | Result |
|---|---|
| Thread size | Flat at 16,000 tokens once trimming starts, about day 3 |
| Checkpoints in PostgreSQL | Sawtooth under 45 MB after pruning. Before pruning: 85 MB in 14 days and climbing |
| Process memory | 142 to 149 MB |
| Tasks | 8 at most |
| Facts in every prompt | 15 at the end, all the scripted model's own plans. Nothing but rota entries is pruned, so it depends on Muse using forget |

## Real Muse, on the mock home

`scripts/core_days_eval.py`, 5 simulated days each, every kind of fault on purpose. The prompt was not changed for or after these runs.

| | Round 1, seed 101 | Round 2, seed 202 |
|---|---|---|
| Events | 72 | 81 |
| Violations, what code must hold | 0 | 0 |
| Findings, Muse's judgement | 1, an evening check that told nobody | 0 |
| Events failed | 4, all with the brain gone on purpose | 4, the same |
| Model calls | 186 | 207 |
| Input tokens per call | 16391 | 16333 |
| Seconds per model call, median and p95 | 1.23, 2.0 | 1.23, 2.15 |
| Seconds per event, median and p95 | 4.1, 6.6 | 4.4, 7.5 |
| Cost of those calls | $3.86, $0.77 a day | $4.28, $0.86 a day |

Round 1 also listed "the lasting plan is gone" 4 times. That was the harness looking for one key name, Muse had kept the plan under its own, so the check now reads the values. Costs leave out the red flag screen's own calls.

## Bugs these days found, all fixed

| Bug | What it did |
|---|---|
| A trim's update was read as new calls | Once the thread reached the limit, old calls landed on each event's record and the second ask for an unanswered parent never fired |
| A dropped database connection was handed out again | The event was lost, and wakes broke |
| A power cut lost what was queued | Queued events stayed queued forever. They now run on start, and older than 15 minutes is on record as missed |
| The brain away meant silence | A night cry told nobody. It is now asked 3 times, then a fixed line goes out: a cry to the parent on duty, an alarm to both, a parent is told to retry |
| A parent or a night cry still unanswered after the second ask | Silence. The same fixed lines now |
| Telegram failing during a red flag | The other parent never got the line. Each phone now has its own 2 tries |
| Telegram or Home Assistant failing inside a tool | The whole run ended. Muse now hears it and goes on |
| 8 tool rounds hit the recursion limit | The run failed with its work half done. The limit is now about 20 rounds |
| Checkpoints grew without end | Now pruned every 25 events |
| Past rota entries stayed in the prompt, and only 100 facts were read | Tonight's entry could fall out. Past ones now go |
| One failed poll or dropped database under a source | That source stopped for good with health still green. Sources now restart |

## Not proven

- Real Muse ran 10 simulated days in total, on the mock home, in about 10 real minutes. A real calendar's week has not passed.
- A long PostgreSQL outage, tried once by hand: the worker lives and works again when it returns, but an event arriving during the outage is lost after 30 s.
- Home Assistant away while the agent starts: the start fails and Docker's restart is what retries. Not exercised.
- The real Telegram, Echo and Baby Buddy under these faults. Only the mocks failed here.
- Muse's facts over months: only rota entries are pruned.
