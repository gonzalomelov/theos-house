# Touch versus hover ablation, Oct 28 2026

Measured on Oct 28 2026, during the Meta hackathon (Oct 27 to Nov 4), for issues #6 (changing table) and #10 (bath). Numbers in `ablation.json`. It replaces the pre-event number (21 of 21 hovers, Oct 23 and 24, one Kling clip with the forearm far above the baby).

## The question

Can the agent tell a hand resting on the baby from a hand held 2 to 5 cm above it, and does SAM 3.1 add anything to the MediaPipe reflex? A hover means no hand touches the baby, so the voice must say "hand" within 2.5 s. A touch must stay silent.

## The set

- Built from the generated changing-table and bath clips (a generated baby and a doll, never a real child) by `scripts/hover_render.py`. Clips stay outside git.
- Rendered hovers: the resting hands lifted 2, 3.5 or 5 cm, with perspective growth for a head camera 45 cm above and a shadow on the baby. Natural hovers: two moments the generated clips already show, hands well above the baby.
- Labelled by eye before any model ran. At 2 cm I could not see the gap myself, at 5 cm the shadow gap is visible.
- Split by source stretch. Thresholds were picked on dev only. Test: 26 hovers (24 rendered, 2 natural) and 16 touches, half changing table and half bath. Dev: 19 hovers and 12 touches, changing table.
- fal was not used. No new generation was needed, and the Oct 23 balance (about 0.28 USD) does not cover a video clip.

## Test results

Each moment streamed in real time through the skill on an M3 Max. Latency is from the cue on screen to the spoken word.

| Configuration | Hovers spoken, table | Hovers spoken, bath | False voices on touch | Alarm cancels | Latency to "hand" |
|---|---|---|---|---|---|
| Reflex only | 1 of 13 | 1 of 13 | 0 of 16 | 0 | 1.58 to 1.65 s |
| Reflex only, voice waits 2.3 s on a near reading (control) | 1 of 13 | 1 of 13 | 0 of 16 | 0 | 1.50 to 1.62 s |
| Reflex and SAM 3.1, hold 1.2 s (before) | 1 of 13 | 1 of 13 | 0 of 16 | 0 | 1.48 to 1.62 s |
| Reflex and SAM 3.1, voice waits for SAM up to 2.3 s (new) | 1 of 13 | 1 of 13 | 0 of 16 | 0 | 1.49 to 1.64 s |

The spoken hovers are the two natural ones. All 24 rendered 2 to 5 cm hovers were missed by every configuration.

## What it means

- Neither model tells a 2 to 5 cm hover from a touch on this set. The reflex reads a hovering hand as on, because its box still covers the baby, so it never raises the alarm and SAM 3.1 is never asked.
- Asked directly on one frame per moment, SAM 3.1 read 0 of 12 rendered changing-table hovers as off. In the bath it read 11 of 12 hovers off but also 6 of 8 touches off, so it does not separate them there either.
- With hands well above the baby, both the reflex and SAM 3.1 get it right. SAM 3.1 agreed but answered after the voice had already spoken.
- SAM 3.1 took 2.2 to 3.2 s per frame here (median 2.5 s), slower than the 1.5 s in the docs. With the 1.2 s hold it answers after the voice.
- No test touch raised a chime, so there was nothing to cancel on test. On dev, SAM 3.1 cancelled 7 alarms but one touch still got a false voice because the hold spoke first.

## Design change

On a near reading (off, but a hand box still overlaps the baby box) the voice now waits for SAM 3.1 up to `alarm.confirm_wait_s`, and the chime stays instant. A clear off reading, or an unsure answer, goes back to the 1.2 s hold. On dev, 1.6 s and 2.0 s left the false voice and 2.3 s removed it with SAM 3.1, while the reflex-only control at 2.3 s did not. 2.3 s is the most the 2.5 s target allows. It is on in `skills/changing-table.json` only. In the bath SAM 3.1 reads most touches as off, so waiting for it would not cancel anything. On test it changed nothing, because no test touch raised an alarm.

## Reproduce

```bash
python scripts/hover_render.py --synthetic ~/Engineering/gonza/meta-hackathon-2026-synthetic
SET=~/Engineering/gonza/meta-hackathon-2026-synthetic/hover/set
python scripts/hover_ablation.py --set $SET --split test --confirm none --out runs/hover/test-none.json
python scripts/hover_ablation.py --set $SET --split test --confirm sam3_local --confirm-wait-s 2.3 --out runs/hover/test-sam3-w2.3.json
python scripts/hover_frames.py --set $SET --out runs/hover/frames.json
```
