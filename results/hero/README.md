# Hero run: the changing table through the glasses, Muse and SAM 3.1 together, Oct 29 2026

Recorded on Oct 29 2026 between 03:18 and 03:50 Montevideo, during the Meta hackathon, for issues #57 and #6. Everything in it is synthetic: generated clips of a generated baby, no real child, no real parent.

**`hero.mp4`** (84 s, 588 x 1280, 1.9 MB) is one unedited run of the Ray-Ban Meta companion app in the iOS 27.0 simulator, with the agent's spoken lines on the sound track. **`run.json`** has every agent event, every brain call and every SAM 3.1 call of that run with timings.

## Models and where they ran

| Part | Model | Where |
|---|---|---|
| Brain (every reply, every tool choice) | Muse Spark Open, `meta-models/muse-spark-open-1026` | Baseten, `inference.baseten.co` |
| Lift check hand masks and the 0.8 s confirm frame | SAM 3.1, `facebook/sam3.1` open weights | this Mac, Apple GPU (MPS), frames never leave it |
| Hand reflex (on or off, every frame) | MediaPipe Hands (Google) | this Mac |
| Head camera | Meta's simulated Ray-Ban Meta, DAT MockDeviceKit 1.0.1 | iOS simulator on this Mac |
| Baby log | Baby Buddy, child `test-baby` | the Vostro home server, through the SSH tunnel on `127.0.0.1:18790` |
| Voice out | iOS AVSpeechSynthesizer, en-US | the companion app |

## The headline run (`run.json`, `hero.mp4`)

The app said "changing time", watched for 44 s, said "done", then asked "When was the last diaper change?". The feed (`hero-feed`, 21.5 s, looped) is one hand on the baby, then both hands leave, then one hand rests and hovers 2.5 cm above the baby.

| Moment, while armed | Times | "hand" spoken | Chime to "hand" |
|---|---|---|---|
| Both hands off | 2 | **2 of 2** | 1.25 to 1.29 s |
| Hover 2.5 cm | 2 | **2 of 2** | 1.24 to 1.25 s |
| One hand on, or one hand resting | 3 | **0 of 3** (silent, 0 chimes) | |

| Step | Number |
|---|---|
| "changing time" to watching | 0.51 s (SAM 3.1 was already loaded, see the fix below) |
| Frames processed | 349, 8.0 per second at a 10 fps send rate, reflex 45 ms and lift check 22 ms per frame (median) |
| SAM 3.1 calls | 15 (13 lift anchors, 2 confirms), 1.65 to 3.03 s each, median 1.75 s. Both confirms read "off", which was right |
| Brain calls | 6, all Muse on `inference.baseten.co`, 0.87 to 2.16 s, 0 fallbacks, 16,946 tokens in and 923 out, about $0.025 at $1.25 in and $4.25 out per million tokens |
| "done" to the change in Baby Buddy | 0.97 s, entry 159 on `test-baby`, read back from the Baby Buddy API after the run with time 03:46:58 |
| The question after "done" | Muse: "Last diaper change finished at 03:47 today." (answered from the agent's own memory of the change, no tool call in this take) |

Every chime to "hand" is the 1.2 s voice hold. SAM 3.1 does two jobs here: its hand masks anchor the lift check that catches the hover (a hand held above the baby, which the MediaPipe reflex reads as on), and it confirms the hands-off alarms on the frame 0.8 s after the raise. In this run both confirms came after the voice and agreed with it.

## Three takes of the same run

The same command three times in a row (`takes/take-1.json`, `run.json` is take 2, `takes/take-3.json`):

| Take | Both hands off | Hover 2.5 cm | One hand, silent | SAM 3.1 seconds (median, max) | Brain calls, fallbacks |
|---|---|---|---|---|---|
| 1 | 1 of 2 | 2 of 2 | 3 of 3 | 1.78, 3.14 | 6, 0 |
| 2 (the video) | 2 of 2 | 2 of 2 | 3 of 3 | 1.75, 3.03 | 6, 0 |
| 3 | 1 of 2 | 2 of 2 | 3 of 3 | 1.78, 3.28 | 6, 0 |
| **All** | **4 of 6** | **6 of 6** | **9 of 9** | | **18, 0** |

The two missed hands-off moments are the reflex, not SAM 3.1 (addressed later the same night, see "After the held object fix" below). In this clip the hands come back over the baby holding a fresh diaper. MediaPipe reads that as a hand on (2D overlap), so the off stretch lasts about 1.2 s and the alarm clears before the 1.2 s hold. In take 1 SAM 3.1 read the frame at 9.66 s as "off" while the reflex read it as "on", and SAM 3.1 was right, but its answer came 3.1 s later (it waited behind a lift anchor), after the alarm had cleared.

## After the held object fix, Oct 29 04:44 to 04:49

The same command, three more takes, on the code of the held object PR (`held-fix/take-1` to `-3`, `results/hover/held/README.md` for the fix and its own measurements). Hands that come back over the baby while the alarm waits unspoken now wait for SAM 3.1 before the alarm clears, the confirm no longer waits behind a lift anchor, and SAM 3.1 runs in float16.

| Takes | Both hands off | Hover 2.5 cm | One hand, silent | SAM 3.1 confirm, request to answer | Brain calls, fallbacks |
|---|---|---|---|---|---|
| Before (take 1, 2, 3 above) | **4 of 6** | 6 of 6 | 9 of 9 | 1.70, 2.98, 3.12, 3.14, 3.14 s (median 3.12 s) | 18, 0 |
| After (`held-fix/take-1` to `-3`) | **5 of 6** | 6 of 6 | 9 of 9 | 1.36, 1.38, 1.48, 1.52, 1.61 s (median 1.48 s) | 18, 0 |

- Four of the five "before" confirms took 3.0 to 3.1 s from request to answer, about a lift anchor plus a confirm on the one SAM 3.1 worker. After, every confirm answered in 1.36 to 1.61 s.
- The one "both hands off" not counted (take 3, second loop): the lift check read the hands as lifted while they rose to leave, the voice said "hand" at 29.08 s, 1.6 s before the scripted cue at 30.7 s, and that alarm was still up when the hands left, so no new one was raised. The script only counts a voice after the cue, so it counts as a miss. The cue carries about 0.5 s of feed phase error.
- Every brain call went to Muse Spark Open on `inference.baseten.co`, 0 fallbacks. The three changes are Baby Buddy entries 168, 169 and 170 on `test-baby`.
- `held-fix/first-try/` has three earlier takes from 04:40 with a bug in the new wait: a hover alarm whose reading flickered from lifted to on waited for a SAM 3.1 answer that is never asked for a lifted alarm, and its voice was dropped. Fixed and tested before the takes above. Those takes gave both hands off 5 of 6 and hover 5 of 6.
- 5 of 6 is one moment better on three takes, not a proven rate. Which of the three changes made the difference was not separated.

## The first hover after arming, through the glasses

The 2.5 cm hover clip alone, looped, 5 runs each, `first-hover/`. "main" is origin/main at 9092ad0 plus logging only (a Unix time on each event, an event when a lift anchor is sent).

| | "changing time" to watching | First hover after watching starts | Every later hover |
|---|---|---|---|
| main (`main-1` to `-5`) | **7.8 to 9.9 s**, SAM 3.1 loads at arm | the hover that started within about 2 s of the watch, before any SAM 3.1 anchor: missed in 5 of 5 | 10 of 10 spoken |
| SAM 3.1 preloaded (`preload-1` to `-5`) | **0.42 to 0.50 s** | spoken in 5 of 5, 3.8 to 4.4 s after the watch began | 10 of 10 spoken |

So on current main the first hover is not lost to frame buffering or a bad lift baseline. The skill is blind while SAM 3.1 loads after "changing time", about 8 to 10 s, and a hover in that window is never seen. The fix: `changing_table.preload_confirm` loads SAM 3.1 when the agent starts and again after each change, so arming takes half a second (`parenting_agent/changing_table.py`, tests in `tests/test_changing_table.py`, `ConfirmPreload`). It is on in `config/agent.glasses.json`. With it the first hover was caught in all 5 runs, 1.23 to 1.26 s after its chime but late against the hover itself (3.8 to 4.4 s after the watch began, with the hover starting about 0.7 s in), because the SAM 3.1 anchor needs a resting frame and about 2 s to answer.

## What failed or is limited

- **A hover less than about 4 s after the hand lands in a new view is missed.** The first version of the hero feed cut straight from the hands-off clip to the hover clip, which rests 2.5 s before it hovers. The lift anchor from the old view could not be matched in the new one, the next anchor came while the hand was already up, and the hover was missed in 3 of 4 takes (`cut-feed/`: hovers 5 of 8, hands off 7 of 8, one hand silent 4 of 4). The hero feed now plays the hover clip's resting first 2.5 s twice, so the hand rests 5 s before it hovers. That is a change to the synthetic feed, not to the agent.
- Both hands off spoken in 4 of 6 hero moments, see above.
- The voice is the iPhone's AVSpeechSynthesizer, not MMS-TTS. The app renders each line it speaks to a WAV with the same voice and rate (`speech/`, `-recordSpeech YES`, Debug builds only) and logs when it started and stopped playing. `scripts/glasses_hero_run.py` lays them on the screen recording at those times. The agent's events and the app's play log share the Mac clock: each line reached the app at most 0.11 s after the agent sent it. The chime is the system sound the app plays (1057, `Tink.caf` from the iOS 27.0 simulator runtime), 0.02 s long, so it is barely audible.
- The hover numbers are on rendered hovers (the hand zoomed about a point, plus a shadow), the physics the lift check measures. No real parent's hand was measured.
- The feed's phase against the agent's stream clock is known to within about 0.5 s, so "cue to hand" times in `run.json` carry that error. Chime to "hand" does not.
- Muse answered "Already watching" to "changing time", because the exact phrase armed the watch before Muse picked a tool. After "done" the agent answers twice (to the message and to the change's closing observation), as on every channel.
- Not real glasses, not a real iPhone, not the home network path.

All brain calls in this folder: 93, every one `meta-models/muse-spark-open-1026` on `inference.baseten.co`, 0 fallbacks, median 1.22 s. All SAM 3.1 calls: 146, median 1.78 s, at most 8.4 s (`cut-feed/take-2`, when the GPU was slow for a whole run, cause unknown).

```bash
apps/glasses/scripts/make-mock-feed.sh   # then build and install the app (apps/glasses/README.md)
mkdir /tmp/pa-gpu.lock
python scripts/glasses_hero_run.py --udid SIM --out-dir results/hero --name take-2 --feed hero-feed --watch 44 \
    --ask "When was the last diaper change?" --ask-after 14 --mux
python scripts/glasses_hero_run.py --udid SIM --out-dir results/hero/first-hover --name preload-1 --feed table-a-hover-2.5cm --watch 20
rmdir /tmp/pa-gpu.lock
```
