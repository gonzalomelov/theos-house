# The "hand" alarm on SAM 3.1 alone

121 moments on recordings, hashed in `set.json` and committed before any run (`scripts/sam_hand_eval.py`). Scored once, no thresholds changed. One clip at a time in real time. Interrupted by a Mac crash and memory stops, carried on from the saved clips without scoring any clip twice. Caught means "hand" within 2.5 s of the cue, late within 5 s.

| Scene | Must alarm | Caught | Late | Missed | Must stay silent | False alarms |
|---|---|---|---|---|---|---|
| Changing table | 51 | 33 | 9 | 9 | 29 | 0 |
| Bath | 25 | 10 | 2 | 13 | 16 | 0 |

The recordings are generated or rendered, not a real Tapo. Per group in `summary.json`. The changing table's misses are all in the two sets with a held object or a harder leave. 4 of those misses had SAM never look at the clip, so they may be load and not the model, and they stay counted as misses. The bath doesn't hold: all of bath-b's hovers were missed.
