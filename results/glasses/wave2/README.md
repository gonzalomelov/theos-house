# Glasses follow-ups from PR #79, Oct 29 2026

Measured Oct 29 2026 between 02:00 and 02:30 Montevideo, during the Meta hackathon, for issues #57 and #6. No simulator in these runs: `scripts/skill_loop_check.py` streams the glasses feed itself (the live changing-table clips, one hand then both hands off, resampled to the 10 fps the glasses app sends) through the changing-table skill in real time, with SAM 3.1 on the Mac GPU.

## (a) SAM 3.1 read every hands-off alarm as "on"

PR #79 saw SAM 3.1 answer "on" for all 4 hands-off alarms through the glasses. Reproduced here: 8 of 8 "on". The frames show why. The reflex raises at about 2.9 s into the hands-off clip, when the right hand leaves for the diapers, but the left hand still rests on the baby until about 3.4 s. SAM 3.1 is right about the frame it gets. The alarm is early.

| Confirm frame (`confirm.delay_s`, `confirm.retries`) | Hands off spoken | One hand silent | SAM 3.1 verdicts on the hands-off alarm | File |
|---|---|---|---|---|
| The raise frame (0 s, before) | 8 of 8 | 8 of 8 | 8 "on" | `confirm-delay0.json` |
| 0.4 s after the raise | 8 of 8 | 8 of 8 | 8 "on" | `confirm-delay0.4.json` |
| **0.8 s after the raise** | 8 of 8 | 8 of 8 | **8 "off"** | `confirm-delays0.8.json` |
| The raise frame, then ask again while the reflex still reads off (2 retries) | 8 of 8 | 8 of 8 | 8 "on", then 6 "off" | `confirm-retries2.json` |

The changing table now sends SAM 3.1 the newest frame 0.8 s after the raise (`skills/changing-table.json`, `confirm.delay_s`). In every run the 1.2 s hold spoke first, 0.9 s after the cue by eye, so the change does not move the voice. It makes SAM 3.1's verdict right, and on a near reading, where the voice waits for SAM 3.1, it stops a correct but early "on" from cancelling an alarm that becomes real 0.5 s later. On the hover dev set the 0.8 s delay went with 0 of 20 false voices on the table against 1 of 20 without it (`results/hover/wave2`). Retries are in the code (`confirm.retries`) and off.

## (b) The first hover after arming was missed through the glasses (6 of 7)

Not reproduced outside the simulator. The fresh 2.5 cm hover clip PR #79 used, looped at 10 fps through the skill with the lift check as it was then (MediaPipe regions, 1.0 cm, no SAM 3.1):

| Where in the clip the skill armed | First hover spoken | File |
|---|---|---|
| At the start (hands resting) | 3 of 3 runs, 1.50 s | `first-hover-armed-at-start.json` |
| 1.0 s and 2.0 s in (hands resting) | 2 of 2 each | `first-hover-armed-at-1.0-s.json`, `-2.0-s.json` |
| 3.5 s and 5.0 s in (hand already hovering) | 2 of 2 each | `first-hover-armed-at-3.5-s.json`, `-5.0-s.json` |

So the lift check alone catches the first hover in every phase I tried. The difference must be in the glasses path: frames arriving as JPEGs over HTTP while SAM 3.1 loads (about 10 s at arm, PR #79) and the first seconds of the stream. I could not run the simulator tonight, so the cause is open. One thing is new and certain: with SAM 3.1 regions on the changing table, the lift check reads nothing until SAM 3.1 has anchored a resting frame, about 2 s after the hands first rest. A hover that comes sooner than that after arming is missed by design. The glasses run should be repeated with this branch.

```bash
mkdir /tmp/pa-gpu.lock && python scripts/skill_loop_check.py --scene changing_table --fps 10 --runs 8 --confirm sam3_local \
    --confirm-cfg '{"delay_s": 0.8}' --out runs/glasses/confirm.json; rmdir /tmp/pa-gpu.lock
```
