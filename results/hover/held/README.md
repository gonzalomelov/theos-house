# Hands holding a diaper, a wipe or a bottle above the baby, Oct 29 2026

## Update Oct 29 evening: follow the hand's SAM 3.1 region when MediaPipe loses it (v3)

Measured on Oct 29 2026 between 18:47 and 20:08 Montevideo, during the Meta hackathon, for issue #6. Synthetic clips only, no real child. Every run streamed in real time on the M3 Max, one SAM 3.1 process at a time, under the GPU lock. Other agents' work (a Docker sandbox, an iOS simulator) ran on the Mac all evening, so the 1 minute load average is given next to each number. Load matters: a SAM 3.1 answer that takes more than about 3 s pushes the prompt past the 2.5 s limit.

| Fresh blind held set (`blind2`, 24 hovers, 12 touches) | Hovers spoken within 2.5 s | False "hand" on touches | Load | File |
|---|---|---|---|---|
| Target | at least 20 | at most 1 | | |
| Before, origin/main 7b76ee9 (scored 20:03) | 6 (5 strict) | 10 | 6.0 | `blind2/before.json` |
| **After, v3 (scored once, 19:52)** | **19** | **1** | 6.1 | `blind2/after.json` |

**The hover target is missed by one: 19 of 24, not 20. The false voice target is met: 1 of 12. But the chime sounded on 9 of the 12 touch moments (11 chimes in all, `touch_chimes` in `blind2/after.json`), so a parent holding a wipe on the baby still hears the tone most of the time. Before, on main: chimes on 11 of 12.** The 5 missed hovers were all spoken, but late, 2.59 to 3.33 s after the cue: the SAM 3.1 look took 2.3 to 3.3 s, and the lift is read only once its anchor lands. The one false voice (`table-a-hold-touch-wipe-both-s0`) came after the followed region was lost while the hand still rested and MediaPipe flickered in and out: a new alarm was raised, and SAM 3.1 read that frame as off.

The set was rendered with seed 1052 from table-a and table-b, hashed into `blind2/set.sha256` and committed (dd5813a) before any design change. It matched its hash (38 of 38) right before the run. Its per-clip results were not looked at until the design was final, and v3 was scored on it once. The before row was run after that, on main, as a baseline. The old blind set (PR #102, below) gave 5 of 24 and 10 of 12 on main.

### Main hover set and bath, as regression checks

| Check | Before (prior run) | After, v3 | Load |
|---|---|---|---|
| Main blind hover set, hovers of 32 | 22 (Oct 29 morning, `../blind/final.json`) | 20 at 19:46, **23** at 19:57 (same code, run twice) | 7.0, 4.8 |
| Main blind hover set, false voices of 16 touches | 0 | **0 and 0** | |
| Bath, both hands off spoken | 10 of 10 | **10 of 10** | 5.4 |
| Bath, one hand on stays silent | 10 of 10 | **10 of 10** | |

The main blind set was already scored before, so it is a regression check, not a blind test. The two runs of the same code (20 and 23) show the run to run spread from load. The two table hovers lost in the first run were lost on time, 2.51 and 3.15 s, with no SAM 3.1 call in them.

### Dev, where v3 was tuned

| Dev run | Held dev hovers of 36 | Held dev false of 18 | Main dev hovers of 19 | Main dev false of 12 | Load | Files |
|---|---|---|---|---|---|---|
| origin/main (held dev prior run 04:xx, main dev 19:08) | 9 | 11 | 13 | 4 | 7.0 | `dev/after-v2.json`, `dev/main-before.json` |
| **v3**, 18:47 and 19:00 | **31** | **0** | **18** | **0** | 4.9, 7.1 | `dev/after-v3.json`, `dev/main-after-v3.json` |
| v3, 14:23 (busier Mac) | 23 | 0 | | | 3.9 | `dev/after-v3-run2.json` |
| v3 without the hand-return wait, 14:30 | 27 | 0 | | | 5.1 | `dev/after-v3-noreturn.json` |

Tried and dropped, on dev:
- **A shorter voice hold for lifted alarms**: 0.5 s gave 33 of 36 held hovers, but 2 false voices on main dev touches. 0.8 s gave 1 false on main dev. The same hold only for lifts read on a region the held look anchored gave 30 of 36 and 1 false: no gain. Not shipped.
- **The hand-return wait from #102 is kept.** It was a wash on hovers (31 against 32, and 23 against 27, in paired runs), and without it held dev got 2 false voices of 18 in one run. With it, v3 never gave a false voice on dev.

### What v3 does

1. **The hidden hand is found by SAM 3.1, not MediaPipe.** When the reflex never saw a hand (a grip on a diaper hides every landmark), the alarm waits up to `alarm.unseen_wait_s` (4 s) for one SAM 3.1 look. That look prompts hand, baby, diaper, wipe and bottle, and draws each hand together with what it holds. A diaper that lies mostly inside the baby mask is worn, not held, and is left out. A hand region on the baby cancels the alarm and becomes the lift anchor. No hand speaks.
2. **The region is followed while MediaPipe stays blind** (`lift.held`). The frame counts as on while the anchored region stays where it rested, as lifted once it rises 1.7 cm, and as off once it is not found for 0.6 s. A SAM 3.1 hand mask also covers the forearm, which stays put while the hand rises. So each region's matches that move with the scene are set aside, and the rest give the hand's lift (`lift.split_scene`).
3. **One decoder pass for all the words.** The five prompts go through SAM 3.1's grounding head as one batch, 0.82 s against 1.79 s one word at a time on this Mac. The worker warms each batch size at start.
4. **PNG frames to the worker.** A JPEG at quality 90 could halve a partly hidden hand's mask.

## Earlier, Oct 29 04:00 to 05:00 (v2, PR #102)

Measured on Oct 29 2026 between 04:00 and 05:00 Montevideo, during the Meta hackathon, for issue #6. Everything here is synthetic: generated changing-table clips of a generated baby with drawn objects, no real child.

| Headline | Before | After |
|---|---|---|
| Hero loop, "both hands off" spoken, 3 takes | 4 of 6 | **5 of 6** |
| SAM 3.1 confirm in the hero loop, request to answer, median | 3.12 s | **1.48 s** |
| SAM 3.1 confirm on the blind set, median and p90 | 1.75 s, 2.74 s | **1.60 s, 2.16 s** |
| Blind held object hovers spoken (of 24) | 5 | 5 |
| Blind false voices on touches holding an object (of 12) | 7 | **10, worse** |

The held object hover is not solved. The object hides the hand from MediaPipe in most of these moments, and then nothing downstream sees a hand at all.

## Why

In the hero run (`../../hero/README.md`, PR #95) "both hands off" was spoken 4 of 6 times. Both misses were the hands coming back over the baby holding a fresh diaper: MediaPipe read that as a hand on, so the alarm cleared before the 1.2 s voice hold. In take 1 SAM 3.1 read the frame as off, which was right, but its answer came 3.1 s later because it waited behind a lift anchor on the same GPU worker.

## The set

`scripts/held_render.py`, the same method as `results/hover`: the generated changing-table stretches where the hands rest on the baby, each also mirrored. A drawn object sits in the hand from the first frame, over the lower part of the hand the way a grip covers it: a diaper, a wipe or a bottle. "both" puts one object between both hands, "one" gives it to one hand. Three kinds, labelled by construction:

| Kind | What happens at the cue | Label |
|---|---|---|
| hold-touch | nothing, the hand keeps resting on the baby with the object (a hand on the baby holding a wipe) | touch, must stay silent |
| hold-hover | hand and object lift 3 to 15 cm over 0.25 to 0.45 s and stay up (perspective growth, shadow, the baby inpainted under them) | hover, "hand" within 2.5 s |
| hold-arrive | the hands leave the view, then 0.5 to 0.9 s later come back already lifted 3 to 15 cm with the object (the hero miss) | hover, "hand" within 2.5 s |

- **dev** (`held-dev`, seed 1031): sources table-d, table-e, table-f, 54 moments (18 touches, 24 hovers, 12 arrivals).
- **blind** (`held-blind`, seed 1030): sources table-a and table-b, the scenes of the old hover test set, 36 moments (12 touches, 16 hovers, 8 arrivals). Rendered at 04:00, hashed into `blind/set.sha256` and committed (377324d after a rebase, b903037 before it) at 04:08, before the first dev run. Checked against the hash before it was scored. Scored once per configuration.
- The clips stay outside git, in `meta-hackathon-2026-synthetic/hover/held-dev` and `held-blind`.

Each moment streams in real time through the changing-table skill on this Mac (M3 Max): the MediaPipe reflex, the lift check with SAM 3.1 hand masks, the alarm, and the SAM 3.1 confirm, as in `results/hover/blind`. "Strict" counts a hover only when the voice belongs to an alarm raised after the cue, not one left over from the resting part.

## What the dev set showed: the object hides the hand from MediaPipe

| Dev, 54 moments | Hovers spoken (of 36) | False voices on touches (of 18) |
|---|---|---|
| Reflex sees the hand while it rests (20 moments) | 8 of 12 | 0 of 8 |
| Reflex loses the hand behind the object (34 moments) | 0 of 24 | 10 of 10 |
| All, before (origin/main c7cc3d5) | 8 of 36 | 10 of 18 |

So of the three suspects (landmark occlusion, hand scale, the contact rule), the one that decides is **occlusion of the hand landmarks by the object**. When MediaPipe still finds the hand, the lift check works on a hand holding an object, up to 15 cm: it measured lifts of 5.9 to 14.2 cm and spoke on 8 of 12 hovers with 0 false voices. When the object covers the palm, MediaPipe finds no hand at all from the first frame, reads off, and every touch raises a false alarm while every hover is spoken during the rest, before anything lifts. Hand scale did not show up as a cause: the 15 cm lifts (1.5 times bigger) that MediaPipe found were measured.

The SAM 3.1 confirm has the matching problem. Its contact ring around a hand that holds a wipe meets the wipe, not the baby, so it read 9 of 12 touch frames as off (`dev/before.json`).

## What I tried on dev

| Dev, 54 moments | Hovers spoken | Strict | False voices on touches | SAM 3.1 touch verdicts on / off | SAM 3.1 confirm s, median and p90 | File |
|---|---|---|---|---|---|---|
| Before (origin/main) | 8 of 36 | not recorded | 10 of 18 | 3 / 9 | not recorded | `dev/before.json` |
| v1: ring around the hand plus what it holds, every alarm waits for SAM 3.1, delay 0.5 s | 21 of 36 | most early | **12 of 18** | **15 / 2** | 2.26, 3.35 | `dev/after-v1.json` |
| v2 (shipped): returning hands wait for SAM 3.1, the confirm goes before anchors, float16 | 9 of 36 | 7 | 11 of 18 | 6 / 13 | **1.48, 1.72** | `dev/after-v2.json` |

- **v1 fixed SAM 3.1's reading and lost on time.** Prompting SAM 3.1 for "diaper", "wipe" and "bottle" too, and drawing the contact ring around the hand together with the objects it touches, turned its touch verdicts from 3 on and 9 off into 15 on and 2 off. But three more prompts cost about 0.5 s per frame, so the answer came 2.3 to 3.7 s after the alarm, after the 2.3 s voice cap, and the false voices went up, not down. Its 21 hovers are not real: most of them are a voice from an alarm raised during the rest that happens to land near the cue. It is in the code (`confirm.held_words`, `alarm.confirm_wait_all`) and off.
- **v2 is what ships.** It does not fix the hidden-hand moments (still 0 of 24). It fixes the hero miss, and makes SAM 3.1 answer faster.

## The fix that ships (v2)

1. **Hands that come back wait for SAM 3.1.** `alarm.return_waits_for_confirm`: when the alarm is raised and not yet spoken and the reflex reads on again, neither the clear nor the hold voice happens on the reflex alone. SAM 3.1's answer decides, off speaks, on cancels, for at most `alarm.return_wait_s` (2.0 s), then the reflex clears as before. A hand holding a diaper above the baby reads on in 2D, a real hand back on the baby reads on to SAM 3.1 too.
2. **The confirm never waits behind a lift anchor.** While an alarm is raised or its confirm is due or pending, the skill sends no lift anchor to the shared SAM 3.1 worker. In hero take 1 that wait was what made SAM 3.1's right answer 3.1 s late.
3. **float16 on the Apple GPU.** `confirm.autocast: "float16"` runs SAM 3.1 under torch autocast on MPS. On 24 frames from the dev set: 1.73 s median (p90 1.81 s) in float32 and 1.56 s median (p90 1.73 s) in float16, with the same 24 verdicts.
4. **A lifted alarm never waits for that answer.** SAM 3.1 is never asked about a lifted alarm, so the wait in 1 skips it. This bug showed in the first three hero takes (a hover alarm whose reading flickered from lifted to on lost its voice) and was fixed and unit tested after the dev and blind runs above, which ran without it. It only touches lifted alarms, which the held object set barely raises.
5. **Smaller input size: not possible as is.** SAM 3.1's ViT uses rotary position tables built for 1008 px, and a 672 px input fails an assertion in `vitdet.py`. Caching the image embedding of the resting frame does not help the confirm, which has to look at a new frame each time.

Confirm time, request to answer, inside the real-time stream (so it includes the wait behind the GPU): median 1.48 s and p90 1.72 s on dev with v2, against 2.26 s and 3.35 s with v1. On the blind set, before and after: median 1.75 s and p90 2.74 s on origin/main, 1.60 s and 2.16 s with v2.

## Blind set, scored once

Scored between 04:32 and 04:40, once per configuration, after v2 was committed (5853e9b after a rebase, a5c55c9 before it). The set matched its hash.

| Blind, 36 moments | Hovers spoken (of 24) | Strict | Arrivals spoken (of 8) | False voices on touches (of 12) | SAM 3.1 confirm s, median and p90 | File |
|---|---|---|---|---|---|---|
| Before (origin/main c7cc3d5) | 5 | 3 | 1 | **7** | 1.75, 2.74 | `blind/before.json` |
| After (v2) | 5 | 3 | 1 | **10** | 1.60, 2.16 | `blind/after.json` |

| Blind, split by what MediaPipe saw while the hand rested | Before | After |
|---|---|---|
| Hovers, hand seen (7) | 5 spoken | 5 spoken |
| Hovers, hand hidden by the object (17) | 0 | 0 |
| Touches, hand seen (6) | 1 false voice | **4 false voices** |
| Touches, hand hidden by the object (6) | 6 false voices | 6 false voices |

So on the blind set v2 did not catch more held object hovers, and it made false alarms worse: 10 of 12 touches against 7 of 12. The likely cause shows in `blind/after.json`, table-b-m-hold-touch-diaper-one-s1, where SAM 3.1 answered on twice and the voice still spoke: the reflex flickers between on and off on a hand gripping a diaper. Before, each return to on cleared the alarm within 0.5 s. With v2 the clear waits for SAM 3.1, so the alarm stays raised, and the next flicker to off lets the 1.2 s hold speak, even though SAM 3.1 then answers on. The waiting clear needs to hold back the voice on later flickers too. Frame timing differs between real-time runs, so this is the likely mechanism, not a proven one. I found it on the blind set, so it is not fixed in this PR, and the blind set is spent for it.

SAM 3.1 answered faster: confirm median 1.75 to 1.60 s and p90 2.74 to 2.16 s. The p90 drop is the confirm no longer waiting behind a lift anchor.

## The hero loop again

`scripts/glasses_hero_run.py`, the hero feed, three takes between 04:44 and 04:49, details in `../../hero/README.md`.

| Hero loop, 3 takes | Both hands off spoken | Hover 2.5 cm | One hand, silent | SAM 3.1 confirm, request to answer |
|---|---|---|---|---|
| Before (PR #95) | **4 of 6** | 6 of 6 | 9 of 9 | median 3.12 s, 5 confirms from 1.70 to 3.14 s |
| After (this PR) | **5 of 6** | 6 of 6 | 9 of 9 | median 1.48 s, 5 confirms from 1.36 to 1.61 s |

The miss after the fix was spoken, but 1.6 s before the scripted cue: the lift check read the hands as lifted while they rose to leave, and the script counts only a voice after the cue.

## What failed or is limited

- **A hand the object hides from MediaPipe is not handled.** On dev that is 34 of 54 moments, and the agent false-alarms on every such touch and speaks during the rest of every such hover. The fix needs a reflex that keeps a hand it was tracking when the hand vanishes in place, or a hand detector that sees a gripping hand. SAM 3.1 with the held object prompts reads these right but answers too late for the 2.5 s target.
- The objects are drawn (flat shapes with noise for texture), not generated or filmed. "both" lays one object across both palms, which hides more of the hands than a real two-handed grip at the diaper's corners would, so the share of hidden-hand moments is likely higher here than in life.
- The blind set uses the same two generated scenes as the old hover test set, new moments not new scenes.
- No real parent, no real baby, no real glasses.

## Reproduce

```bash
S=~/Engineering/gonza/meta-hackathon-2026-synthetic
python scripts/held_render.py --synthetic $S --out held-dev --splits dev --seed 1031
python scripts/held_render.py --synthetic $S --out held-blind --splits test --seed 1030
(cd $S/hover/held-blind && shasum -a 256 -c path/to/results/hover/held/blind/set.sha256)
mkdir /tmp/pa-gpu.lock
python scripts/hover_ablation.py --set $S/hover/held-dev --split dev --confirm sam3_local --out dev/after-v2.json
# v1: skills/changing-table.json with alarm.confirm_wait_all true, confirm.delay_s 0.5 and
# confirm.held_words ["diaper", "wipe", "bottle"], then the same command with --out dev/after-v1.json
python scripts/hover_ablation.py --set $S/hover/held-blind --split test --confirm sam3_local --out blind/after.json
rmdir /tmp/pa-gpu.lock
```
The "before" rows ran the same harness on a checkout of origin/main at c7cc3d5.
