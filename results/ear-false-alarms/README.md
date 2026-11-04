# The Ear's false alarms from people and rooms (Nov 4 2026)

A person making noise near the camera fired "a baby crying" about 15 s after the listener started. The record then said 339 of 348 cries with 1 false of 51, and those 51 held almost no one making noise close up. No audio is kept, so that noise can't be replayed here, and neither can the 6 detections of Nov 3 to 4.

## Result

Same held-out cries as Oct 31, new held-out negatives, one pass through the real worker, Ear and sink, Tapo channel included (`eval.json`). The old rule ran in the same pass and missed the same 9 cries as Oct 31.

| Held out | Old rule: bare logit 4.43 | New rule |
|---|---|---|
| **Cries sent** | 339 of 348 (97.4%) | **323 of 348 (92.8%)** |
| **Human noise sent** | 26 of 157 (16.6%) | **1 of 157 (0.6%)**, a looped cough |
| Room and house sounds sent | 0 of 90 | 0 of 90 |
| Other sounds per hour of audio | 25 | 1 (one event in 1.04 h) |
| Report, 7 s clips, median from clip start | 11 s | 10 s |
| Report, 2 long cries of 48 and 54 s | 9 s, 9 s | 9 s, 9 s |

Tune side, for comparison (`tune.json`, `tune-path.json`): 106 of 113 cries against 112, 0 of 209 others against 40. These were chosen on this side, so they flatter the rule. The real path gave the same numbers and the same 7 misses as the cached choice.

**The price is 16 more missed cries of 348.** Every one is a Donate-a-Cry clip of about 7 s, so a longer cry has more chances, and the 4 long clips were all sent at 9 s. That's 4 clips, not proof.

**Numbers to quote instead of 339 of 348 with 1 false of 51:** 323 of 348 cries, 0 false of the same 51 (`results/ear-path/recordings.json`), and 1 false of 157 human sounds, most of them synthetic.

## The rule

`hearing.CRY_RULE`: a 40 ms frame counts when its cry logit reaches 5.5 **and** it beats the best of "a man's voice", "a radio broadcast" and "a person laughing" by 5. A window fires on one such frame. `--report-after` stays 8 s, and the cooldown stays 120 s. A short cry is still sent when it ends.

What the tune side backed, cries and negatives of 113 and 209:

| Lever alone | Cries | Negatives |
|---|---|---|
| Nothing | 112 | 40 |
| Logit threshold 6.5 | 102 | 8 |
| 3 fired seconds | 96 | 21 |
| 20 of 50 frames in a window | 98 | 16 |
| Beat all 20 rival prompts by 1 | 97 | 7 |
| **Beat these 3 by 5** | **106** | **0** |

Beating every rival hurt because cries also score high on prompts like "a quiet room" and "people talking". The 3 were picked one at a time on the tune side, by how well they separate cries from negatives, stopping when the gain fell under 0.001 AUC. Requiring sustained frames or seconds cost cries without earning it, partly because these clips are short. A steadiness check on the signal was not tried, since the rule left nothing on the tune side for it to remove.

## How thin this is

- **Most human noise is synthetic.** Of the 157 held-out items, 134 are the Mac's `say` or a synthetic reader. Real people are one person reading aloud (8 items, 72 s of audio each way) and 5 cough recordings (15 items). The tune side adds a 1944 radio broadcast and a 1918 song.
- **No real person made noise at this microphone or any other in this test.** "Hot" is a 24 dB boost with clipping, not a mouth near a camera. The Nov 4 noise is not in the set.
- **Items aren't independent.** Plain and hot copies share a source, and `say` items are one phrase looped to 12 s.
- **Small numbers.** 1 of 157 still allows up to about 3.5% at 95% confidence.
- **"A man's voice" came from this data.** The selection ran on the tune side and held on separate voices, but the set can't speak for every voice.
- **Room noise doesn't prove anything new.** Both rules sent 0 of 90 here, over about 0.45 h, including a copy 30 dB quieter. So the 6 detections of Nov 3 to 4 are not reproduced or explained, and whether the rule stops them isn't known.
- **Distance isn't measured.** Every 4th Donate-a-Cry clip, lowered before the Tapo channel: 78 of 87 at -12 dB and 79 of 87 at -24 dB, against 82 and 83 for the old rule. Neither reaches the real camera's level, and the earlier microphone test caught 0 of 10 at about -65 dBFS (`results/ear-path/README.md`).

## Repeat it

```bash
python3 scripts/ear_negatives.py                                            # renders outside git, writes split.json
PY=.venv-hearing/bin/python
$PY scripts/ear_fa_eval.py frames --set tune && $PY scripts/ear_fa_eval.py tune
$PY scripts/ear_fa_eval.py path --set held_out
```

`split.json` was committed first, `tune.json` and the rule before the held-out set ran, and nothing was changed after it.
