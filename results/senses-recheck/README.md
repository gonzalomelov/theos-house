# The local senses, rechecked on recordings (Nov 3 2026)

`scripts/senses_recheck.py`, committed before it ran, with every threshold frozen earlier. Numbers only.

## Hearing: Perception Encoder Audio Frame small

The frozen held-out set of `results/sounds/meta-hearing`, through the Tapo audio channel (8 kHz A-law), with the thresholds of `tune.json`. This set was read on Oct 31, so this repeats that test on today's code. It isn't a new test.

| Label | Hits | False alarms |
|---|---|---|
| Cry | 339 of 348 | 1 of 51 (a cough) |
| Doorbell | 3 of 4 | 3 of 395 (all cries) |
| Dog | 3 of 3 | 3 of 396 (all cries) |
| Splash | 3 of 3 | 1 of 396 (a kitchen recording) |

Same counts as Oct 31. One 2 s window: 0.067 s median, 0.183 s p95, on the Mac's GPU. Doorbell, dog and splash have 3 or 4 clips each, so those rows show it works on these clips and not how often.

## Vision: SAM 3.1, dog near the baby

The 69 images of the dog watch's blind split, read on Oct 29, with the rule's settings unchanged. The channel is new: a real H.264 encode and decode at the Tapo C200's sizes and bitrates. These are stock photos and composites through a simulated channel. **No real Tapo frame was used, and neither a real dog nor a baby in this house.**

| Channel | Dog near the baby caught | Photos | Composites | False alerts | SAM look, median |
|---|---|---|---|---|---|
| Image as it is | 15 of 20 | 3 of 8 | 12 of 12 | 0 of 49 | 2.66 s |
| 1080p, 2 Mbit/s | 16 of 20 | 4 of 8 | 12 of 12 | 0 of 49 | 3.24 s |
| 360p, 400 kbit/s | 14 of 20 | 3 of 8 | 11 of 12 | 0 of 49 | 3.09 s |
| 360p, gray and noisy, as under infrared | 15 of 20 | 6 of 8 | 9 of 12 | 0 of 49 | 3.09 s |

No false alert in any channel. About 1 near case in 4 is missed in every channel, and on real photos about half or more in three of the four, so this watch shouldn't be described as reliable. The small differences between channels are a few images out of 20, too few to rank them.
