# Muse Spark Open's eyes on the car seat (issue #30), Oct 29 2026

All runs on Oct 29 2026, about 00:00 to 03:30 Montevideo, during the event. Model `meta-models/muse-spark-open-1026` on Baseten (inference.baseten.co), reasoning effort low. Script `scripts/carseat_muse_eval.py`, code `parenting_agent/carseat/muse_check.py`.

## Setup

- Seat and car: Joie i-Snug 2, the carrier of the Joie Litetrax travel system, installed rear facing with the car's 3-point belt and no ISOFIX base, coached for the Tesla Model 3.
- Frames: one still per clip at 3.0 s, after the camera has settled, from the rendered clips in `meta-hackathon-2026-synthetic/carseat/clips` (outside the repo, never committed, read into memory only). Dev set: 22 frames (8 correct, 12 wrong, 2 unseen). Test set: 28 frames (12 correct, 12 wrong across belt outside a guide, twisted belt, wrong recline and handle down, 4 unseen). The dev set was used for all the prompt work. The test set was scored once, with the prompts and rules fixed.
- Checks asked: lap belt in both side guides (the rear-facing guides), shoulder belt in the rear guide (the belt path), belt flat with no twist (the visible part of belt tight and locked, the lock itself cannot be seen), level line level, handle upright. Every answer schema also holds `movement_under_1_inch`, which only accepts `cannot_judge`: a still cannot show movement, so the coach asks the parent.
- SAM 3.1 numbers in the "second opinion" rows are the SAM verdicts already stored in `results/carseat/dev.json` and `test.json` (Oct 28, during the event), combined per frame with Muse's answer. SAM was not rerun.

## Test set result (frozen, scored once)

Per check, on the 28 test frames. "Wrong caught" counts frames where the planted mistake was not passed. "Pass on unseen" counts a pass where the carrier is covered or out of view, also a dangerous error.

| Check | Muse alone, right | Wrong caught | Correct passed | False pass on a wrong install | Pass on unseen frame |
|---|---|---|---|---|---|
| Handle upright (3 answers, majority) | 25 of 28 | 3 of 3 | 21 of 21 | 0 | 1 (a floor view read as handle raised) |
| Level line level (3 answers, majority) | 18 of 28 | 3 of 3 | 15 of 21 | 0 | 3 (2 of them covered carriers whose level window shows below the blanket) |
| Lap belt in both side guides (1 answer, advisory) | 15 of 28 | 1 of 1 | 15 of 23 | 0 | 4 |
| Shoulder belt in rear guide (1 answer, advisory) | 12 of 28 | 2 of 2 | 8 of 22 | 0 | 1 |
| No twist (1 answer, advisory) | 7 of 28 | 2 of 3 | 3 of 21 | 0 | 0 |

Whole installs, test set:

| | SAM 3.1 alone | Muse alone (handle and level) | SAM 3.1 and Muse, second-opinion rule |
|---|---|---|---|
| Wrong installs with the mistake not passed | 11 of 12 | 6 of 6 handle and recline errors | **12 of 12** |
| Wrong installs called correct on every check | 0 | 0 | 0 |
| Correct installs with a false fail | 1 of 12 | 2 of 12 | **0 of 12** |
| Correct installs passed on every check | 11 of 12 | n/a | 7 of 12, the other 5 get "unsure, check by hand" |
| Unseen frames with any pass | 0 of 4 | 3 of 4 | **0 of 4** |

What Muse added: test-24, where SAM never found the folded handle, Muse said lowered, so the rule fails it. Test-01, where SAM read an upright handle as 44 degrees and false-alarmed, Muse said raised, so it became "unsure" instead of a wrong fail. What it cost: 5 correct installs where Muse could not see or misread the level line now end with a hand check instead of a pass.

Latency and cost, test set: one Muse call took a median 8.1 s (3 answers in parallel, the slowest counts), at most 16.5 s, so a Muse step answers well after the 2 s target the SAM-only coach aims for. $0.011 per step with 3 answers, $0.022 per install for the two steps Muse votes on. The advisory belt calls were $0.0048 each, median 7.1 s. The two test runs cost $1.02.

## The dangerous error, and how it was fixed

Muse called wrong installs correct. On the dev set:

| Prompt | What it was | Planted mistake passed by Muse, of 12 wrong installs | False alarms on 8 correct |
|---|---|---|---|
| v1 | Whole frame, all checks in one answer, the maker's rules in the prompt | 5 | 7 |
| v2 | v1 plus a description of what a correct install looks like from the door | 10 | 6 |
| v3 | Whole frame, neutral observations only, rules in code | 2 (and most checks abstained, 3 answers broke the JSON) | 5 |
| v4 | One focused, neutral question per install step on a zoomed still (the middle of the view, 1.6 times) | 6 | 8 |
| v5 = v4 with 3 answers per step, majority wins, Muse votes on handle and level only | 2 (both recline, level read as horizontal) | 0 |

Told what correct looks like (v2), Muse mostly agreed with the prompt. The fixes that worked: never tell Muse the right answer, ask one question per step, zoom the frame, ask three times and take the majority. Muse still cannot be trusted alone, so the second-opinion rule is in the code: a check passes only when SAM 3.1 and Muse both say pass, a pass against a fail or against "cannot see" is "unsure" and never a pass, and the coach says so and asks for a check by hand. With that rule no wrong install and no unseen frame passed in any dev or test run.

Belt routing and twist stayed close to chance with every prompt (on the test set the twist question said "narrows" on 17 of 21 flat belts), and Muse passed belt checks on covered or floor views. So for those three checks Muse's answer is advisory and is not asked in the coach (`MUSE_VOTES` in `muse_check.py`).

## Limits

- Rendered clips, not a real car or a real seat. The renders are low poly, and Muse may do better or worse on real photos. The real run in the Tesla after Nov 5 is still open.
- 3 wrong installs per error type on the test set, so each rate is coarse.
- The level line truth on covered carriers counts as unseen, while Muse can see the window below the blanket. Scored strictly as a pass on an unseen frame.
- Muse's answers vary from call to call on the same frame. The majority of 3 cuts that, it does not remove it.
- The coach never says the seat is safe. It lists which checks passed, failed, were not seen or need a hand check, and always ends with a check by a certified child passenger safety technician (tests in `tests/test_muse_senses.py`).

## Files

`dev-v1.json` to `dev-v5-vote3.json`: the prompt work on the dev set. `test-final-belts.json` and `test-final-votes.json`: the frozen test runs. Each row holds the truth, Muse's answers and short notes, SAM's verdict and the combined result. No frames.
