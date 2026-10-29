# Before he arrives, results (issue #56)

All numbers from runs on Oct 28 2026, during the hackathon.

## Tests

`tests/test_prep.py`: 25 tests, all pass. Full suite: 412 tests, all pass, 4 skipped.

## Real turns through the Claude stand-in brain, on the Mac

Config `config/agent.vostro.json` with a scratch data folder and the offline baby log. Brain `claude-haiku-5-5`. Every message started with "Test:", so none counts for the KR.

| Message | Tools called | Answer, short |
|---|---|---|
| what is next before Theo arrives? | `prep_next` | about 48 days to Dec 15 (an estimate), then the three car seat items due Nov 4 and 5 |
| we bought the MAX98357A amplifier | `prep_check` twice | ticked, 7 items left on the white noise list. The second call is now a no-op ("already done") and logs nothing |
| hospital tour on Nov 3 at 10am at the main entrance, bring our IDs | `add_appointment` | saved for Tue Nov 3 10:00, main entrance, bring IDs |
| where should the shelf go in the nursery? | `nursery_plan` | layout A passes every check, in layout B the shelf hangs 60 cm over the crib's end |

## Nursery checks on the home twin plan

| Check | Layout A | Layout B |
|---|---|---|
| Walkway between dresser and crib | 70 cm, pass | 70 cm, pass |
| Door swing | pass | pass |
| Nothing on the wall above the crib | pass | fail, 60 cm over the crib's end |
| White noise machine 2 m from the crib | fail, 187 cm at most | fail, 187 cm at most |

These are geometry checks on the plan's numbers, not a check of the real room.
