# Bath: one hand on stays silent again, Oct 29 2026

Measured Oct 29 2026 between 01:25 and 02:15 Montevideo, during the Meta hackathon, for issue #10. PR #79 found that after the lift check (#75) the bath said "hand" during the one-hand clip in 5 of 10 baths, against 0 of 10 before.

`scripts/skill_loop_check.py` (first run as `bath_onehand_check.py`) streams the same loop `scripts/bath_run.py` builds (`bath-handoff-01`, both hands leave at 4.0 s, then `bath-onehand-01`, one hand on the doll the whole clip) through the bath skill alone, in real time, with no brain, no Baby Buddy and no Home Assistant. Both hands off must speak "hand" within 2.5 s of the cue. One hand must stay silent.

| Run | Both hands off spoken | One hand silent | File |
|---|---|---|---|
| Before, lift check as #75 left it, no SAM 3.1 | 4 of 4 | **2 of 4** | `before-lift-mediapipe.json` |
| Tried: drop readings when the head moved (scene zoom over 5 %, shift over 30 px) or the hand slid (over 50 px) | 6 of 6 | 5 of 6 | `tried-motion-gates.json` |
| After, the bath lift check needs both hands, no SAM 3.1 | 10 of 10 | **10 of 10** | `after-both-hands.json` |
| After, with SAM 3.1 confirm on (the bath skill as shipped) | 10 of 10 | **10 of 10** | `after-both-hands-sam3.json` |

## Why it spoke

Every false voice was a lifted reading on the one hand MediaPipe saw. In the one-hand clip the head camera pans and zooms (in a frame by frame replay the scene scale against the first frame reached 1.16 within 1.1 s) while the hand slides on the doll in the water. The lift reading of that resting hand swung between -4 and +3 cm and stayed above 1 cm for more than a second in one run (`before-lift-mediapipe.json`, `lift` per frame). With one hand, nothing else checks it.

## The fix

`skills/bath.json` sets `lift.min_hands` to 2. The lift check only measures when the reflex counts both hands on the baby, and a hover alarm needs both of them lifted. One hand on is never read as a hover. The reflex alone still raises "hand" when no hand is on.

The gates in the second row cut the false voices but did not remove them, so they are in the code (`max_scene_zoom`, `max_scene_shift_px`, `max_hand_shift_px` in `parenting_agent/lift.py`) but off by default.

## What it costs

A bath hover with only one hand in view is no longer caught by the lift check. On the hover dev set that is 6 of 13 bath hovers (all from the one-hand source). See `results/hover/blind/README.md` for the blind numbers.

```bash
python scripts/skill_loop_check.py --scene bath --runs 10 --out runs/bath/onehand.json                        # no GPU
mkdir /tmp/pa-gpu.lock && python scripts/skill_loop_check.py --scene bath --runs 10 --confirm sam3_local --out runs/bath/onehand-sam.json; rmdir /tmp/pa-gpu.lock
```
