# Hover: measure how far the hand rose, Oct 28 and 29 2026

Update Oct 29, wave 2: on the changing table the lift check now measures inside SAM 3.1 hand masks, and the bath needs both hands. On a fresh blind set: 22 of 32 hovers, 0 of 16 false voices, against 21 of 32 and 1 of 16 for this MediaPipe version (`../blind/README.md`, `../wave2/README.md`).

Measured Oct 28 22:20 to Oct 29 01:00 (Montevideo), during the Meta hackathon, for issue #6 (changing table), with the bath skill on the same set. The set and the rules are the ones in `results/hover/README.md`: a hover (hand 2 to 5 cm above the baby, no touch) must speak "hand" within 2.5 s of the cue, and a touch must stay silent. Before this change the reflex and SAM 3.1 together caught 2 of 26 test hovers, with 0 false voices on 16 touches.

Target: at least 24 of 26 hovers and at most 1 false voice on 16 touches.

## Result

The blind number first: on a fresh render made after the design was frozen, the lift check caught **15 of 16 hovers, with 2 false alarms on 16 touches**. The test set below was used to fix the method, so its 24 and 23 of 26 are not blind.

| Run (real time, M3 Max, SAM 3.1 confirm on) | Hovers spoken within 2.5 s | False voices on touch | Latency to "hand", median and max |
|---|---|---|---|
| Before, reflex and SAM 3.1 (`results/hover`, Oct 28) | 2 of 26 | 0 of 16 | 1.49 to 1.64 s |
| Test, first run of the design picked on dev (`test-sam3-lift.json`) | 17 of 26 | 1 of 16 | 1.51 s, 1.76 s |
| Test, after the fix below (`test-sam3-lift-v2.json`) | **24 of 26** | **1 of 16** | 1.56 s, 1.84 s |
| Test, same code run again (`test-sam3-lift-v2-repeat.json`) | 23 of 26 | 1 of 16 | 1.55 s, 1.74 s |
| Test, same code, no SAM 3.1 (`test-none-lift-v2.json`) | 22 of 26 | 1 of 16 | 1.57 s, 1.72 s |
| Fresh render, never seen (`fresh-sam3-lift.json`) | 15 of 16 | 2 of 16 | 1.61 s, 1.79 s |
| Fresh render, lift off (`fresh-sam3-nolift.json`) | 0 of 16 | 0 of 16 | none |
| Dev (`dev-sam3-lift-v6.json`) | 18 of 19 | 2 of 12 | 1.56 s, 2.34 s |

The target is met in one of the two identical test runs (24 and 23 of 26, 1 false voice in both). The runs differ by one hover (bath-a-m-hover-3.5cm) because the skill takes the newest frame in real time, so timing changes which frames it sees.

Be clear about one thing. The fix between the first and second test runs came from tracing a test miss: the lift check could get stuck when it could not match a hand against its baseline, and now it starts over after `refresh_s`. The rule is generic, and I checked it on dev before the second test run, but the test set is no longer blind. The fresh render is the blind check. It used the same method on the test sources, with other lifts (2.5 and 4 cm) and other points in each stretch, was rendered after the design was frozen, and is labelled by construction: 15 of 16 hovers caught, with 2 false voices on 16 touches.

Per clip: every row in the JSON files has `spoken`, `latency_s`, the reflex string per frame (`1` on, `0` off, `^` lifted), `max_lift_cm_after_cue` and the lift reading per frame (`lift_series`).

Misses in the second test run: table-b-m-hover-3.5cm and table-b-m-hover-5cm. The false voice is on table-b-touch-p0 (the lift read 1.1 cm on a resting hand). Traced offline, the table-b-m misses have one failure mode. The baseline refreshed during the 0.3 s lift, because the 5-frame median lags, and then MediaPipe dropped one hand for a frame, which restarts the baseline at the raised hand. That is the next fix, and it needs a fresh blind set to check it.

## Depth models: tried, not used

Each one was run on 4 frames per moment (one before the cue, three after). It compared the depth of the hand (SAM 3.1 hand mask over the baby) with the depth of the baby in a ring around it (SAM 3.1 baby mask). Numbers in `depth.json`, code in `probe/`.

| Meta model, license | Per frame on the Mac (MPS) | Gap change when the same frame is lifted 2 / 3.5 / 5 cm, median | Hover against touch, AUC dev / test |
|---|---|---|---|
| DINOv2 + DPT head, NYU, large (`facebook/dpt-dinov2-large-nyu`, Apache 2.0) | 0.20 s | +1.1 / +1.6 / +1.6 cm, with 10 to 90 percent spread from -2 to +10 cm | 0.50 / 0.66 |
| DINOv2 + DPT head, NYU, giant (`facebook/dpt-dinov2-giant-nyu`, Apache 2.0) | 0.60 s | +0.3 / 0.0 / -0.3 cm | 0.52 / 0.41 |
| Sapiens depth 1B (`facebook/sapiens-depth-1b-torchscript`, CC BY-NC 4.0) | 2.86 s | about 0 | 0.43 / 0.45 |

None of them separates a hover from a touch: an AUC of 0.5 is chance. The NYU models also put the baby about 1.2 m from the camera, against about 0.45 m in the scene, so their metric depth cannot even set the scale here. One caveat: the rendered hovers are a 2D zoom plus a shadow, so they carry no real depth cues such as focus or parallax. A real hand might do better, but nothing here shows it. VGGT (CC BY-NC) and DINOv3 (its depth head is only for the 7B model) were not tried.

## What works: perspective growth

A head camera looks down at the baby from about 45 cm. A hand lifted h cm toward it grows in the image by 45 / (45 - h): 4.7 % at 2 cm and 12.5 % at 5 cm. The baby and the table do not grow. `parenting_agent/lift.py` matches SIFT features of the resting hand against each new frame, and divides the hand's scale by the scale of the rest of the scene, which absorbs the parent's head moving. That gives a lift in cm. It runs only while the reflex reads on, which is exactly when the reflex misses a hover. It takes 21 ms per frame on the M3 Max CPU (median per moment), next to 43 ms for the reflex. The hand regions are the MediaPipe hands that the reflex counts as on.

When every hand is lifted at least 1.0 cm (median of 5 readings), the frame counts as off. That alarm skips SAM 3.1, because SAM 3.1 reads a hovering hand as on and would cancel it, and the alarm can re-raise one that SAM 3.1 cancelled. SAM 3.1 still confirms or cancels every other alarm (`docs/sam3-local.md`).

The settings were picked on dev: `min_lift_cm` 1.0 against 0.8 and 1.5, a 5-frame median against 3 to 5 frames in a row, and keeping the baseline through a reflex flicker shorter than 1 s against dropping it at once. Dev has no bath clips, because the only other bath clip is the same generation as test bath-a. So the bath results are out of domain. Every dev false voice comes from table-f, a 0.8 s stretch where the reflex itself flickers off on most frames.

## Limits

- A hand that arrives already hovering and never rests has no resting baseline, so it reads as on.
- A lift slower than about 0.5 cm per second is absorbed into the baseline.
- The rendered hovers model a lift as a zoom about the image centre plus a shadow. That is the physics this check measures, so the set flatters it. It is untested on a real parent's hand.

## Reproduce

```bash
SET=~/Engineering/gonza/meta-hackathon-2026-synthetic/hover/set
python scripts/hover_ablation.py --set $SET --split test --confirm sam3_local --lift on --out runs/hover/test-sam3-lift.json
python scripts/hover_ablation.py --set $SET --split test --confirm none --lift on --out runs/hover/test-none-lift.json
python scripts/hover_render.py --synthetic ~/Engineering/gonza/meta-hackathon-2026-synthetic --out fresh --splits test \
    --lifts 2.5,4 --touch-phases 0.25,0.75 --hover-phase 0.33 --no-natural
python scripts/hover_ablation.py --set ${SET%/set}/fresh --split test --confirm sam3_local --lift on --out runs/hover/fresh.json
```
