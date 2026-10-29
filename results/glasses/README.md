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
