# Car seat coach

The agent coaches a parent through installing an infant carrier with the car's 3-point seat belt and no base, one step at a time by voice. The head camera checks what a camera can see, with Meta's SAM 3.1 on the Mac's GPU. What a camera cannot see, the agent asks and logs. Built during the Meta hackathon (issue #30).

The coach never says the install is safe. It says which visible checks passed, which failed or were not seen, which hand checks remain, and it always ends by suggesting one check by a certified child passenger safety technician. It gives no medical advice.

## The pieces

| Piece | Code | What it does |
|---|---|---|
| Seat profile | `parenting_agent/carseat/manual.py`, `skills/carseat/joie-i-snug-2.json` | Reads the maker's manual (text only, extracted locally with pdftotext) and keeps the belt install steps, the warnings, the child limits, the handle position for the car and the level line rule |
| Car profile | `skills/carseat/tesla-model-3.json` | Tesla Model 3 rules: never rear facing in front with the airbag on, ISOFIX on the outer rear seats only, the center seat takes a belted seat only |
| Visible checks | `parenting_agent/carseat/checks.py` | From SAM 3.1 masks: lap belt in both side guides, shoulder belt in the rear guide, no twist, level line level, handle upright. Each check says pass, fail or unseen. Unseen is never turned into pass |
| SAM 3.1 masks | `parenting_agent/carseat/sam3_masks.py`, `parenting_agent/sam3_prompts_worker.py` | Text prompts to masks on the Mac's GPU, same weights and setup as the changing table (`docs/sam3-local.md`). Frames go through a local pipe and are never saved |
| Muse second opinion | `parenting_agent/carseat/muse_check.py`, `scripts/carseat_muse_eval.py` | One zoomed still per camera step to Muse Spark Open, neutral question, strict JSON, majority of 3. A pass needs SAM and Muse both. Opt-in |
| Coach | `parenting_agent/carseat/coach.py`, `skills/car-seat.json` | Speaks each step, checks the newest frame taken after the step was spoken, asks the hand checks, speaks the summary |
| Plug-in | `parenting_agent/carseat/plugin.py` | Tools `start_car_seat_coach`, `answer_car_seat_check`, `car_seat_outgrow` for the agent |
| Outgrow watch | `parenting_agent/carseat/outgrow.py`, `simweek/growth.py` | Weight and height from Baby Buddy against the seat's limits, with a heads up 4 weeks before |
| Test clips | `scripts/carseat_render.py` | 3D-rendered clips with exact labels and planted mistakes |
| Scoring | `scripts/carseat_eval.py` | Streams each clip through the coach in real time and scores it, results in `results/carseat/` |

## The steps

1. Carrier on a rear seat, facing the back, never in front with the airbag on. Asked.
2. Lap belt through both side guides. Camera.
3. Shoulder belt in the rear guide. Camera.
4. Belt tight and flat, no twist. Camera.
5. Level line on the side of the carrier level with the ground. Camera, with the phone held level.
6. Handle upright, position 1, the car position. Camera.
7. Movement at the belt path under 2.5 cm. Asked, the camera cannot feel it.
8. Harness pinch test. Asked.
9. Summary and one check by a certified technician.

Hand checks are never skipped. An unanswered one stays open in the summary.

Every line is in the language of the parent who started the coach: their "lang" in the people block, else Spanish for a request in Spanish, else the family's language (`LINES`, `CAMERA_STEPS`, `SUMMARY` and `NAMES` in `coach.py`, `ask_es` and `technician_es` in `skills/car-seat.json`, `text_es` for the car rule). The same words are spoken (each voice event carries its `lang`, and `say` on the Mac uses a Spanish voice for Spanish), shown on the glasses card and, when the coach was started from Telegram, sent to that parent's chat. The summary is the coach's last line and is kept in the conversation, it is never handed to the brain to say again. The coach refuses "safe", "safely", "seguro" and "segura" in either language. "Cinturón de seguridad" is the seat belt's name and is allowed.

## Seat profile from a manual

```bash
python -m parenting_agent.carseat.manual MANUAL.pdf --seat "Joie i-Snug 2" --url URL > skills/carseat/joie-i-snug-2.json
```

The Joie Litetrax travel system ships with the i-Snug 2 carrier in the EU and NZ listings (the Gemm in the US). The manual comes from Joie's own download server, linked from Joie's UK support page for the "litetrax TS w/ i-Snug 2". The PDF stays outside the repo. The profile keeps its URL and SHA-256, and a test checks that the parser rebuilds the committed profile from the real PDF when it is on this machine.

Limits from the manual: 40 to 75 cm, up to 13 kg, up to 12 months. Handle position 1 for the car. The level line must be level with the ground.

## The camera

SAM 3.1 finds the parts by text: `strap` for the belt, `blue clip` for the belt guides, `handle`, and `green line` for the level line. The words live in `skills/car-seat.json`, because the guide color and the level indicator differ between seats. The geometry then decides:

- a guide holds the belt when enough of the ring around it is belt and the belt runs between the two side guides
- the two side guides are the pair that lines up across the view, the rear guide is the other one
- a twist shows as the belt narrowing to under 45% of its usual width between the guides
- the level line passes when it is within 8 degrees of level in the image, so the phone must be held level and side on
- the handle passes when it stands within 40 degrees of vertical. Where SAM reads the same pixels as a strap more surely than as a handle, they count as belt

A miss at the far side guide alone cannot be seen from the door side, because the belt projects onto the guide. In real use the coach needs a view from the other side for that guide. The rendered set does not include that case.

## Test material

No seat has been bought yet and the Tesla arrives on Nov 5, so the tests run on rendered clips. `scripts/carseat_render.py` is a small software renderer in NumPy and OpenCV, no extra packages, no Blender. It draws the rear bench, a carrier, a doll, the guides, the handle, the level line and the belts, and plants one mistake per wrong clip: the belt outside a guide (near side, both side guides, or the rear guide), a twisted belt, a wrong recline (12 to 20 degrees off), or the handle in position 2 or 3. Unseen clips keep the carrier out of view or cover it with a blanket.

```bash
python scripts/carseat_render.py --out ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips --set test
python scripts/carseat_eval.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips/test
```

Two sets with different seeds. The dev set (8 correct, 12 wrong, 2 unseen) was the only one used to pick the prompts and the thresholds. The test set (12 correct, 12 wrong, 4 unseen) was rendered once and scored once with the thresholds fixed. Clips live outside the repo and are never committed. Public install videos may be used for local accuracy checks only, stored outside the repo, never in the demo.

## Results

Test set, scored once with the thresholds fixed on the dev set (`results/carseat/test.md`, `test.json`):

| Measure | Target | Result |
|---|---|---|
| Wrong installs flagged | at least 9 of 10 | 11 of 12 (outside guide 3 of 3, twisted 3 of 3, recline 3 of 3, handle 2 of 3) |
| False alarms on correct installs | at most 1 | 1 of 12 (the handle read 44 degrees from vertical, the limit is 40) |
| Abstains when it cannot see | yes | 4 of 4 unseen clips, no belt verdicts |
| Result spoken within 2 s of the step being visible | every step | 100 of 116 steps, median 1.69 s, max 4.11 s |
| Spoken texts with "safe" | none | none |
| Hand checks asked and logged | every run | every clip |

The 2 s target is not met for every step. One SAM 3.1 pass with two prompts takes about 1.5 s on the M3 Max, three prompts about 1.8 s. The misses are mostly the first camera step, where the camera pans onto the carrier while a pass on the floor view is still running, so the result comes from the next pass, 2.0 to 2.5 s after the carrier is in view. The handle missed once (test-24, never found) and false-alarmed once (test-01).

Dev set, used to choose the prompts and thresholds (`results/carseat/dev.md`): 12 of 12 flagged, 0 false alarms, 2 of 2 abstained, 86 of 95 steps within 2 s.

These are renders, not a real car. The numbers say the checks work on clean geometry with exact labels. They do not say how SAM 3.1 does on a real belt in a real car, which needs the Tesla run.

## Muse Spark Open as a second pair of eyes

Built Oct 29 2026. With `"car_seat": {"muse": {"enabled": true, "samples": 3}}` in the agent config, the coach also sends one still frame per camera step to Muse Spark Open on Baseten (`parenting_agent/carseat/muse_check.py`). The frame is zoomed on the middle of the view and comes with one neutral question for that step and a strict JSON schema, for example "is the handle raised or lowered", three times in parallel, majority wins. Every schema holds `movement_under_1_inch`, which only accepts `cannot_judge`: a still cannot show movement, so the parent is asked.

Second-opinion rule: a check passes only when SAM 3.1 and Muse both say pass. Both fail, or one fails and the other cannot see, is a fail. A pass against a fail or against "cannot see" is "unsure": the coach says its two checks disagree, does not count it as passed and asks for a check by hand. If Muse cannot be reached, SAM's verdict stands and is marked single. Muse votes on the handle and the level line only. On belt routing and twist it stayed near chance and passed covered views, so it is not asked there.

On the 28 test renders, scored once (`results/carseat/muse/README.md`): Muse alone got the handle right 25 of 28 times and the level line 18 of 28, with no wrong install passed, but it passed 4 checks on covered or floor views. With the rule, 12 of 12 wrong installs were not passed (SAM alone 11 of 12, Muse caught the folded handle SAM never found), no false alarm (SAM alone 1), no unseen view passed, and 5 of 12 correct installs ended with a hand check instead of a pass. A Muse step takes a median 8.1 s and $0.011, so it answers well after the 2 s target.

**Privacy.** With Muse on, frames leave the Mac: one zoomed still per voting step, made in memory, sent once to inference.baseten.co, never saved. Each call is a `carseat_muse` event with its host. With Muse off (the default), frames stay on the Mac as before.

## Outgrow watch

```bash
python -m simweek.growth load --anchor 2026-10-27   # three weights and heights in the simulated week, tagged
```

`car_seat_outgrow` reads weight and height from Baby Buddy and fits the recent pace. Early weeks grow fastest, so the straight line reaches a limit sooner than real growth will and the heads up comes early, never late.

On the simulated week in Baby Buddy (`results/carseat/outgrow-simweek.json`): Test Baby is at 4.38 kg and 54.8 cm, the height limit (75 cm) comes first, in about 21 weeks, around Mar 26 2027. No heads up yet.

## What is still open

- A real run in the Tesla with the real seat (after Nov 5 and after the seat is bought).
- The before-each-trip check (harness snug, coat off on cold days) and the recall check from the issue scope.
- Check the car rules against the printed Tesla manual. Tesla's site refused automated downloads.
