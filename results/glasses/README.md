# Glasses loop in the iOS simulator, Oct 28 2026

Measured on Oct 28 2026, during the Meta hackathon, for issue #57. The companion app (`apps/glasses`) ran in an iOS 27.0 simulator (iPhone 18 Pro, Xcode 27.1) on an M3 Max. The glasses were Meta's own simulated Ray-Ban Meta from DAT MockDeviceKit 1.0.1, not real glasses. Real pairing is the next step, see the morning steps in `apps/glasses/README.md`.

## What ran

1. The app paired a mock Ray-Ban Meta through DAT (powered on, unfolded, worn) and set its camera feed to a synthetic changing-table video: 6 s with one hand on the baby, then 6 s where both hands leave, looped. The clips are generated (a generated baby, no real child), made on Oct 22 and 23 before the event. Nothing else was added.
2. DAT streamed the mock camera into the app (15 fps, decoded frames). The app sampled them and posted each sampled frame as a JPEG to the glasses endpoint of the agent on the same Mac (`127.0.0.1:8766`, pairing token on every request).
3. The app said "changing time", waited 26 s, and said "done". The agent was the real persistent agent (`python -m parenting_agent`) with the glasses channel and the changing-table skill on source `glasses`. Brain: Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten). Hand reflex: MediaPipe on the Mac. SAM 3.1 confirm was off in these runs because another agent held the GPU lock all evening, so the voice came from the reflex and the 1.2 s hold alone.
4. The skill's chime and spoken "hand" and the agent's replies came back to the app, shown as text and spoken with the iPhone voice.

Baby Buddy and Home Assistant were not reachable from these runs (only the brain key was loaded), so the change log and house actions were dry. Frames stayed in memory on the Mac.

## Files

| File | What it is |
|---|---|
| `loop-simulator.mp4` | Screen recording of the recorded run, 44.6 s, 0.9 MB, no audio track (simctl records video only) |
| `01-watching.png`, `02-hand-spoken.png`, `03-change-logged.png` | Screenshots from the same run: armed and watching, "hand" spoken, the change logged |
| `loop-run.json` | Numbers and the conversation of the recorded run |
| `rate-2fps.json`, `rate-5fps.json`, `rate-10fps.json` | 60 s runs at three sampling rates |

## The recorded run (`loop-run.json`)

| Step | Result |
|---|---|
| "changing time" to the skill armed | the phrase armed it at once, the Muse reply "Watching, let me know when you're done" came 3.3 s after the message |
| Frames processed while armed | 206 in 25.6 s, 8.0 per second, reflex 46 ms per frame (median) |
| Hands-off moments while armed | 2, both spoken: chime, then "hand" 1.25 s later |
| Chimes in the one-hand part | 1, dropped before any voice |
| "done" to "Logged, diaper change at 23:00" | 5.8 s |
| Brain calls | 5, all to inference.baseten.co, 1.4 to 4.2 s each |

## Sampling rate

Same loop, 60 s watch each. The expected count is the armed time divided by the 12.08 s feed loop, rounded down, one hands-off moment per loop.

| Set rate | Frames processed per second | Hands-off moments | "hand" spoken | Chime to "hand" | Chimes dropped (one-hand part) |
|---|---|---|---|---|---|
| 2 fps | 1.9 | 5 | 3 | 1.58 to 1.61 s | 3 |
| 5 fps | 4.8 | 4 | 4 | 1.22 to 1.27 s | 4 |
| 10 fps | 8.0 | 5 | 5 | 1.24 to 1.27 s | 0 |

At 2 fps two of five hands-off moments were missed: the voice waits until the reflex has read "off" for 1.2 s, and with a frame every 0.5 s a short hands-off stretch ends before three off frames arrive. So the app samples at 10 fps by default, not the 2 fps first planned. No run spoke "hand" during the one-hand part. Latency from the moment the hands leave on screen to the spoken word was not measured here, only chime to voice.

## What failed or is not proven

- Before the fix, Muse picked the wrong tool in 2 of 5 runs: once it answered "done" by calling `start_changing_table` again (1 of 4 runs that said a plain "done"), and once it answered "done, it was a wet one" with `log_baby_event` only. Both times the watch stayed on. The changing-table skill now has the same exact-phrase reflex as the bath ("changing time", "done", and a few more arm and finish it without the brain) and keeps "watch on" or "watch off" in the agent's memory. The recorded run is after that fix.
- The spoken audio was not captured. `simctl recordVideo` has no audio track. The app speaks with AVSpeechSynthesizer, and the text it speaks is what the screenshots show.
- After "done" the agent answers twice, once to the message and once to the skill's closing observation. That is how the agent loop already works for every channel.
- Not tested: real glasses, a real iPhone, the home network path, SAM 3.1 confirm on glasses frames, the bath skill on glasses (wired in `config/agent.glasses.json`, not run).

# Rerun with SAM 3.1 confirm on, Oct 29 2026 00:56 to 01:07

Same simulator setup as above (iOS 27.0, iPhone 18 Pro, DAT MockDeviceKit 1.0.1, Muse Spark Open as the brain), 10 fps, but now with SAM 3.1 confirm on, from Meta's open weights on the Mac GPU. Baby Buddy was reachable in these runs, so the change was logged.

## The headline loop with SAM 3.1 (`sam/run-10fps-sam.json`, 60 s watch)

| Measure | Hand reflex only (Oct 28, `rate-10fps.json`) | With SAM 3.1 confirm (Oct 29) |
|---|---|---|
| Frames processed per second | 8.0 | 8.0 |
| Hands-off moments while armed | 5 | 4 (50.5 s armed, SAM 3.1 takes about 10 s to load when the skill arms) |
| "hand" spoken | 5 of 5 | 4 of 4 |
| Chime to "hand" | 1.24 to 1.27 s | 1.25 to 1.31 s |
| False alarms ("hand" in the one-hand part) | 0 | 0 |
| SAM 3.1 verdicts | none | 4, all "on" (a hand on the baby), 1.7 to 2.4 s after the chime |

Every "hand" was spoken by the 1.2 s hold, not by SAM 3.1. SAM 3.1 got all 4 wrong: it said a hand was still on the baby when both hands had left. It answered after the voice had already played, so it changed nothing the parent heard, but had it been faster it would have silenced all 4 real alarms.

Why: the skill sends SAM 3.1 the frame the alarm rose on, the very first frame the reflex reads off, when the hands are only starting to leave. I ran SAM 3.1 on the feed itself (`sam/sam-feed-probe.json`): the frame 0.06 s after the hands start to leave reads "on", and every frame from 0.36 s on reads "off". The hands-on and one-hand frames read "on", which is right. So the fix is to send SAM 3.1 a frame about 0.4 s after the raise, not the first one. That is not done in this PR.

The hand delay (hands leave on screen to "hand" spoken) cannot be read exactly here, because the mock feed and the agent share no clock. The chime plays on the first frame the reflex reads off (`off_frames_to_alert` is 1), so the delay is the chime to voice time above plus the sampling and upload lag, at most 0.1 s at 10 fps plus a 46 ms reflex.

Muse said "Watching the changing table. Let me know when you're done and what you found for the diaper." on "changing time", and "Got it, all done." on "done".

## The changing table with the new hover check, end to end through the glasses (`hover/`)

After the lift check merged (#75), I ran the glasses loop on two clips from the fresh render the lift check never saw (`hover/fresh` in the synthetic set, rendered on Oct 29): one hand hovering 2.5 cm above the baby (`table-a-hover-2.5cm`, the lowest hover in that set), and one hand resting on the baby (`table-a-touch-p16`). Each 7 s clip was looped as the glasses camera, so the hover comes back every 7 s. SAM 3.1 confirm was on. A lifted alarm skips SAM 3.1 by design, so SAM 3.1 was never asked in these runs.

| Clip | Watch | Hovers while armed | "hand" spoken | Chime to "hand" | False "hand" |
|---|---|---|---|---|---|
| Hover 2.5 cm | 30 s (`table-a-hover-2.5cm.json`) | 2 complete, a third cut off by "done" | 1 of 2 | 1.25 s | |
| Hover 2.5 cm | 60 s (`table-a-hover-2.5cm-60s.json`) | 7 | **6 of 7** | 1.25 to 1.26 s | |
| Touch | 30 s (`table-a-touch-p16.json`) | none | | | 0, and no chime |
| Touch | 60 s (`table-a-touch-p16-60s.json`) | none | | | **0**, and no chime |

The miss is the same in both hover runs: the first hover after arming. The lift reads lifted for 3 frames and falls back to on, so the alarm rose and cleared before the voice. Every later hover was read lifted for its whole 3.4 s and spoken. It looks like the lift baseline is still settling on the first hover, the known limit in `results/hover/lift/README.md`. Not fixed here.

What the agent said, hover run (60 s): "Watching the changing table. Let me know when you're done." Then on "done": "Got it, finished." and "Noted, the changing table finished with 6 hand alerts. Try to keep one hand on baby when you can."

Touch run (60 s): "Watching the changing table. Tell me when you're done." Then "All set." and "Logged the finished change."

Screenshots and a screen recording of each 30 s run are in `hover/table-a-hover-2.5cm/` and `hover/table-a-touch-p16/`.

Brain on these glasses runs: 26 Muse calls, p50 1.12 s, p90 1.65 s, about $0.09 at $1.25 in and $4.25 out per million tokens (the glasses config carries no prices, so this is computed from the token counts), no fallback (`results/muse/calls-glasses-sam.jsonl`, `calls-glasses-hover.jsonl`).

```bash
# the app plays MockFeed/NAME.mp4 with -mockFeed NAME (copy the clip there re-encoded to HEVC, then build)
python scripts/glasses_sim_run.py --config CONFIG --udid SIM --fps 10 --watch 60 --out results/glasses/sam/run-10fps-sam.json
python scripts/glasses_sim_run.py --config CONFIG --udid SIM --fps 10 --watch 60 --mock-feed table-a-hover-2.5cm --feed-s 7 \
    --out results/glasses/hover/table-a-hover-2.5cm-60s.json
```

# Hero run with Muse and SAM 3.1 together, Oct 29 2026

The recorded end-to-end run (Muse Spark Open brain, SAM 3.1 lift masks and confirm, real Baby Buddy, the spoken lines muxed onto the screen recording) and the first-hover-after-arming reruns are in `results/hero/README.md`.
