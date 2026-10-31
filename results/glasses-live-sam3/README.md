# The glasses HUD, live, SAM 3.1 only, Oct 31 2026

Run on Oct 31 2026 at 18:53 Montevideo to re-record the hands scene of the hackathon video on today's code. Same run as `results/glasses-live` (Oct 30), with one change: `--hands sam3_only`, so the changing-table skill watches with SAM 3.1 alone (`parenting_agent/sam_hands.py`), no MediaPipe and no prior work library. Everything else is today's main: Muse Spark Open on Baseten arms and closes the watch, one SAM 3.1 process (`facebook/sam3.1`, MPS, loaded in 15.8 s) under `/tmp/pa-gpu.lock`, the cards drawn by DAT's `MockDisplayKit`, Telegram captured, the house dry (`house.live` false).

```bash
python scripts/glasses_hud_live.py --build-feed
python scripts/glasses_hud_live.py --udid SIM --hands sam3_only --out-dir results/glasses-live-sam3 --name hands-sam3-oct31 \
    --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v10/rec/hands-live/hands-sam3-oct31.mp4
```

`hands-sam3-oct31.json` is the run: every agent event, every card the display accepted, the brain calls and the Baby Buddy read back. The screen recording and the app's sounds are next to the video, not committed.

| Scene | Result |
|---|---|
| Armed by Muse | "changing time" to watching 2.47 s |
| Held diaper | **missed**: the hands rose with the diaper and no "hand" was spoken. SAM 3.1 kept finding a hand on the baby |
| Both hands off | tone and "hand" together, 3.31 s after the hands left (one SAM 3.1 look is about 2 s, the next look decides) |
| One hand on | silent, 84 frames |
| Hover 2.5 cm | "hand" 1.56 s after the cue, lift up to 2.6 cm |
| Done | Muse closed the watch, entry 257 (dirty) written and read back, test child |
| Dog near the baby | near on 4 dog frames, none elsewhere, alert captured |

385 frames, 21 SAM 3.1 hand looks and 6 dog looks on the one process, 5 Muse calls (0.92 to 1.76 s), 54 cards.

What looked wrong:

- Muse's reply to "changing time" was "Nothing was sent. I only did this: start changing table." It was spoken and stays as the detail line of the "Changing table" card until the alarm. It names a tool on the lens.
- With SAM 3.1 alone the lens says "Hand on the baby" for about 3 s after both hands left, then "hand" lands as the next scene's hand comes back.
