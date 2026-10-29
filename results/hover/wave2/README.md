# Hover, wave 2: can SAM 3.1 do the measuring? Oct 29 2026

Measured Oct 29 2026 between 01:05 and 02:35 Montevideo, during the Meta hackathon, for issues #6 (changing table) and #10 (bath). The blind result is in `../blind/README.md`. This page is the dev work that picked the design.

## The question

Round 2 judges: the hover win (24 of 26) came from a SIFT and MediaPipe lift check, the same code with no SAM 3.1 got 22 of 26, and the lift alarm skipped SAM 3.1. So is SAM 3.1 essential, or only present?

## Rules I kept

1. A fresh blind set was rendered, frozen and hashed before any design change (`../blind/set.sha256`, pushed as commit 55cadb5 at 01:09, rebased later as b954754).
2. All tuning used the dev set. For wave 2 the dev set is the whole old set (`hover/set`, its dev and test splits, 45 hovers and 28 touches), because the old test split was no longer blind. The blind set uses the same four source clips with new poses, so it is new moments, not new scenes.
3. The design was committed (b3c31d4) before any blind run, and each blind configuration ran once.

## What SAM 3.1 costs per frame on this Mac

`probe/speed.py`, one 640 x 352 frame, M3 Max, MPS, Oct 29:

| Precision | Image encoder | "hand" prompt | "baby" prompt |
|---|---|---|---|
| float32 (what the skill runs) | 1.39 to 1.61 s | 0.33 to 0.59 s | 0.30 to 0.45 s |
| float16 autocast | 1.13 to 1.16 s | 0.40 to 0.55 s | 0.30 to 0.35 s |
| bfloat16 autocast | 1.02 to 1.06 s | 0.23 to 0.25 s | 0.22 to 0.23 s |

About 2 s a frame. A hover must be spoken within 2.5 s of the cue, so SAM 3.1 cannot look at the frame after the lift and still answer in time. Whatever SAM 3.1 does here has to be done on a frame from before the lift.

## Tried on dev

### SAM 3.1 mask signals, offline (`probe/feats.py`, `sam-mask-signals.json`)

SAM 3.1 hand and baby masks on 4 frames per moment (0.5 s before the cue, then 0.8, 1.5 and 2.2 s after), the parent's hands only (at least 1.2 % of the frame, touching the baby). AUC of hover against touch, the median over the 3 frames after the cue (0.5 is chance):

| Signal | Changing table | Bath | All |
|---|---|---|---|
| Hand mask area growth (SAM 3.1 hand mask after / before) | 0.84 | 0.96 | 0.87 |
| Baby mask hidden under the hand (baby area after / before, lower is more) | 0.65 | 0.58 | 0.63 |
| Contact edge (share of the hand's ring that is baby, drop after the cue) | 0.65 | 0.77 | 0.67 |
| SIFT scale inside the SAM 3.1 hand mask, scene as reference | 0.94 | 0.92 | 0.94 |
| SIFT scale inside the SAM 3.1 hand mask, baby as reference | 0.94 | 0.92 | 0.94 |
| SIFT scale inside the MediaPipe hand region, scene as reference | 0.95 | 0.86 | 0.93 |

The mask itself is a weak height signal. On the changing table the SAM 3.1 hand mask takes in the forearm, which does not grow, so a 5 cm hover grows the mask by only 1 to 3 %. The useful part is where the mask puts the measuring, not the mask area.

### SAM 3.1 video tracking across frames (`probe/video.py`)

SAM 3.1's multiplex video predictor is written for CUDA: module level `torch.cuda.get_device_properties(0)`, `.cuda()` calls, CUDA autocast and FlashAttention 3. With those patched to MPS and FlashAttention off it built, then failed in `start_session` (`init_state() got an unexpected keyword argument 'offload_state_to_cpu'`). I stopped there. Even working, each tracked frame needs the same image encoder (1.0 to 1.6 s above), so tracking cannot run at frame rate on this Mac. Not measured, and that is the honest state.

### SAM 3.1 hand masks as the lift check's regions, real time

The design that respects the 2 s cost: while the hands rest, the skill sends one resting frame to SAM 3.1. Its answer lands about 2 s later. The parent's hand masks from it (the ones touching the baby mask) become the lift check's baseline, measured against that same frame. The check asks for a new anchor where it used to refresh its baseline. Until an anchor lands there is no reading. The MediaPipe reflex still decides that a hand is on, and still triggers the check (`parenting_agent/lift.py`, regions `sam3`, `parenting_agent/skill.py`).

Dev, real time, each moment streamed through the skill:

| Configuration (dev, 45 hovers, 28 touches) | Table hovers | Table false voices | Bath hovers | Bath false voices | File |
|---|---|---|---|---|---|
| Lift, MediaPipe regions, no SAM 3.1 (bath needs both hands) | 28 of 32 | 5 of 20 | 6 of 13 | 0 of 8 | `dev-lift-mediapipe.json` |
| Lift, MediaPipe regions, SAM 3.1 confirm | 27 of 32 | 2 of 20 | 5 of 13 | 0 of 8 | `dev-lift-mediapipe-sam3-confirm.json` |
| Lift, SAM 3.1 regions, 1.0 cm, SAM 3.1 confirm | **32 of 32** | 2 of 20 | 3 of 13 | 0 of 8 | `dev-lift-sam3-masks-1.0cm.json` |
| Final: table SAM 3.1 regions at 1.7 cm, bath MediaPipe regions, SAM 3.1 confirm | 30 of 32 | 1 of 20 | 5 of 13 | 0 of 8 | `dev-final-no-delay.json` |
| Final, with the confirm frame 0.8 s after the raise (see the glasses) | **32 of 32** | **0 of 20** | 6 of 13 | 0 of 8 | `dev-final.json` |

With SAM 3.1 regions the lift reading is close to the truth on the changing table: rendered 2 cm hovers read 2.0 to 3.3 cm, 3.5 cm read 3.8 to 5.0, 5 cm read 5.4 to 6.3, and every touch stayed at or under 0.9 cm except one at 1.39 cm (table-b-m-touch-p0, a resting hand that moves in the source clip). So the threshold for SAM 3.1 regions is 1.7 cm, the middle of 1.39 and 2.01. The MediaPipe hull, grown 18 % around the landmarks, takes in baby and background, which do not grow, so it reads lower and noisier.

The last two rows are the same design except the confirm frame, and their 2 hover difference is mostly run to run noise (the old README saw 1 hover of noise between identical runs).

In the bath, SAM 3.1 regions did worse (3 of 13): the bath source clips have a moving head camera, and a baseline that is 2 s old by the time it lands is measured against a scene that moved (`sam-anchor-bath-offline.json`, offline: the same anchors read a resting bath hand above 1 cm on 6 to 7 frames per touch). So the bath keeps MediaPipe regions.

### The bath asks for both hands (the PR #79 regression)

PR #75 turned the lift check on in the bath. In the bath loop (both hands off, then one hand on), the one-hand clip then said "hand" in 5 of 10 baths (PR #79, `results/bath`). Traced in `../../bath/onehand/README.md`: with one visible hand and a moving camera, the lift reading of a resting hand swings from -4 to +3 cm. The bath lift check now needs two hands on the baby (`min_hands` 2). One hand on is never read as a hover. The cost: a bath hover where only one hand is in view is not caught by the lift check (6 of the 13 dev bath hovers, all from the one-hand source).

## Limits

- The rendered hovers zoom the hand about a point plus a shadow. That is the physics the lift check measures, so the set flatters it. No real parent's hand has been measured.
- SAM 3.1 regions need a resting frame about 2 s before the lift. A hand that rests less than about 2 s before it hovers has no SAM 3.1 anchor yet and is not read.
- Dev has no bath clip that is not also a blind source. The bath numbers are thin.
