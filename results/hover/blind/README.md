# Hover, blind set, Oct 29 2026

Rendered and frozen at 01:09 Montevideo on Oct 29 2026, during the Meta hackathon, before any wave 2 design change. Scored between 02:35 and 03:04, after the design was committed (b3c31d4). Each configuration ran once, and I looked at per-clip results only after the last run. Dev work and the design: `../wave2/README.md`.

## The set

`scripts/hover_render.py --out blind --splits test --seed 1029 --hovers-per-tag 4 --no-natural`, the same method as `results/hover`: the old test source stretches (table-a, table-b, bath-a, bath-b, each also mirrored), a generated baby or a doll, never a real child. The seed draws new poses: each moment starts at its own point in the stretch, and each hover has its own lift (2.0 to 5.0 cm, stratified), ramp (0.25 to 0.45 s), cue (2.2 to 2.8 s) and centre of perspective (up to 40 px off the image centre). 32 hovers and 16 touches, half table and half bath, labelled by construction (`labels.json`). The clips stay outside git. `set.sha256` holds the SHA-256 of every clip and of `labels.json` and `moments.json`, and the set was checked against it before the runs.

The same four source clips as the old test set, so this is new moments, not new scenes. bath-b and table-a show one hand on the baby.

## Result

A hover must speak "hand" within 2.5 s of the cue. A touch must stay silent. Real time on an M3 Max, each moment streamed through the skill.

| Configuration | Hovers spoken | Table | Bath | False voices on 16 touches | Latency to "hand", median and max | File |
|---|---|---|---|---|---|---|
| Reflex only | 0 of 32 | 0 of 16 | 0 of 16 | 0 | none | `reflex-only.json` |
| Lift only, MediaPipe regions, no SAM 3.1 | 21 of 32 | 14 of 16 | 7 of 16 | **1** | 1.63 s, 1.86 s | `lift-mediapipe.json` |
| Lift, MediaPipe regions, SAM 3.1 confirm | 21 of 32 | 14 of 16 | 7 of 16 | **1** | 1.66 s, 1.73 s | `lift-mediapipe-sam3-confirm.json` |
| Lift with SAM 3.1 hand masks (both scenes), SAM 3.1 confirm | **23 of 32** | 15 of 16 | 8 of 16 | **0** | 1.72 s, 2.22 s | `lift-sam3-masks.json` |
| Final: table SAM 3.1 masks, bath MediaPipe regions and both hands, SAM 3.1 confirm | 22 of 32 | 15 of 16 | 7 of 16 | **0** | 1.72 s, 2.06 s | `final.json` |
| SAM 3.1 only, no MediaPipe (`"hands": "sam3_only"`, Oct 31, scored once) | 22 of 32 | 16 of 16 | 6 of 16 | **0** | 1.67 s, 2.29 s | `sam3-only.json` |

The final combination keeps false voices at 0 of 16, under the 1 of 16 limit.

## SAM 3.1 only, Oct 31 2026

Added after the hackathon Discord review, in case the organizers rule that MediaPipe (Google's) cannot run next to Meta's models. `"hands": "sam3_only"` (`parenting_agent/sam_hands.py`) runs no MediaPipe and none of the Oct 22 to 23 prior work: SAM 3.1 looks at the newest frame again and again on a background thread (hand masks with what they hold, about 1.5 to 3 s a look), a hand mask on the baby anchors the lift check, the lift check runs on every frame between looks, a look with no hand on the baby speaks at once, and a lift speaks after the 1.2 s hold. It was checked on 3 dev moments first, then run on this blind set once on Oct 31 at 13:42 Montevideo, with the GPU lock, one process, nothing tuned on the set. The bath used the SAM 3.1 mask threshold chosen on dev for the table (1.7 cm), not its MediaPipe one.

- 22 of 32 hovers spoken within 2.5 s, the same count as the final design. On the changing table 16 of 16, one more than the final. In the bath 6 of 16: the 8 one-hand bath-b hovers are missed by design as in every row, and 2 bath-a hovers were missed (bath-a-hover-s2, bath-a-m-hover-s3).
- 0 of 16 touches said "hand". 2 table touches chimed (table-a-touch-s0, table-b-touch-s1), the same count as the final design.
- Latency median 1.67 s, max 2.29 s. Lift check 0.04 s a frame (median of moments).

So, on this set, dropping MediaPipe costs nothing on the table and one bath hover. A blind set this small cannot tell the two apart. What SAM 3.1 only gives up is speed when both hands leave at once: the MediaPipe reflex chimes in under a second, a SAM 3.1 look takes 1.5 to 3 s. This set has no such moment, the KR runs (`results/kr222/`) do and were not rerun this way.

## What it means

- 8 of the 16 bath hovers come from bath-b, where only one hand is in view. The bath lift check now needs both hands (the one-hand bath fix, PR #92), so every configuration misses all 8 by design. Counting only the 24 hovers with both hands in view: MediaPipe regions 21 of 24 with 1 false voice, SAM 3.1 masks 23 of 24 with 0, final 22 of 24 with 0.
- SAM 3.1 hand masks did measurable work: 2 more hovers and 1 fewer false voice than the same lift check on MediaPipe regions. On the table they fixed table-b-hover-s2, table-b-m-hover-s2 and the false voice on table-b-touch-s1, and missed table-b-hover-s0, the lowest lift in the set (2.01 cm against a 1.7 cm threshold). This is a small blind margin, the size of one or two moments, not the 32 of 32 dev showed.
- SAM 3.1 confirm on top of MediaPipe regions changed nothing here (21 and 1 in both rows).
- In the bath SAM 3.1 masks caught 8 of 8 two-hand hovers on blind against 7 of 8 for MediaPipe, the opposite of dev (3 of 13 against 6 of 13). The final keeps MediaPipe in the bath, because the design was frozen on dev. With a set this small, neither bath number is solid.
- Is SAM 3.1 essential to the hover check? It makes it better. It does not make it possible: the MediaPipe lift check alone still gets 21 of 24. Where SAM 3.1 is essential is the car seat coach, see `../../meta-models/README.md`.

## Reproduce

```bash
B=~/Engineering/gonza/meta-hackathon-2026-synthetic/hover/blind
(cd $B && shasum -a 256 -c path/to/results/hover/blind/set.sha256)
python scripts/hover_ablation.py --set $B --split test --confirm none --lift off --out reflex-only.json
python scripts/hover_ablation.py --set $B --split test --confirm none --lift on --out lift-mediapipe.json
mkdir /tmp/pa-gpu.lock
python scripts/hover_ablation.py --set $B --split test --confirm sam3_local --lift on --lift-cfg '{"regions":"mediapipe","min_lift_cm":1.0}' --out lift-mediapipe-sam3-confirm.json
python scripts/hover_ablation.py --set $B --split test --confirm sam3_local --lift on --lift-cfg '{"regions":"sam3","min_lift_cm":1.7}' --out lift-sam3-masks.json
python scripts/hover_ablation.py --set $B --split test --confirm sam3_local --lift on --out final.json
rmdir /tmp/pa-gpu.lock
```
