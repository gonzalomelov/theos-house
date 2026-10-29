# Hero run 2: Muse arms the watch, closes it, logs the diaper and says what it logged, Oct 29 2026

Recorded on Oct 29 2026 between 04:56 and 05:06 Montevideo, during the Meta hackathon, for issues #57 and #6. Everything in it is synthetic: generated clips of a generated baby, rendered car seat clips of a doll, no real child, no real parent.

Round 3 judges read Meta's models as optional in the first hero run (`results/hero/`): "changing time" armed the watch by an exact phrase before Muse picked a tool, so Muse only said "already watching", the diaper went into Baby Buddy empty (wet false, solid false), the chime was a 0.02 s Tink, and SAM 3.1's essential job (the car seat coach) was not in the recording. This run changes all four.

**`hero2.mp4`** (127 s, 588 x 1280, 2.6 MB) is take 2 of 3, one unedited run of the Ray-Ban Meta companion app in the iOS 27.0 simulator with its sounds muxed on, followed by the car seat segment (`carseat.mp4`). **`run.json`** is that take: every agent event, brain call and SAM 3.1 call with timings. `takes/` has all three takes, `regions/` the MediaPipe regions run, `carseat.json` the car seat segment.

## Models and where they ran

| Part | Model | Where |
|---|---|---|
| Brain: arms the watch, closes it with the diaper's content, writes the spoken summary, answers the question | Muse Spark Open, `meta-models/muse-spark-open-1026` | Baseten, `inference.baseten.co` |
| Lift check hand masks, the 0.8 s confirm frame, and the car seat checks | SAM 3.1, `facebook/sam3.1` open weights | this Mac, Apple GPU (MPS), frames never leave it |
| Car seat coach's voice | MMS-TTS, `facebook/mms-tts-eng`, int8 ONNX decoder | the Vostro home server, voice service `pa-voice-family`, CPU. Only the coach's text goes there |
| Hand reflex (on or off, every frame) | MediaPipe Hands (Google) | this Mac |
| Head camera | Meta's simulated Ray-Ban Meta, DAT MockDeviceKit 1.0.1 | iOS simulator on this Mac |
| Baby log | Baby Buddy, child `test-baby` | the Vostro, through the SSH tunnel on `127.0.0.1:18790` |
| Glasses voice | iOS AVSpeechSynthesizer, en-US | the companion app |
| Alert tone | two sine notes, 988 Hz then 1319 Hz, 0.26 s, generated in the app's code (`AlertTone`, `Voice.swift`) | the companion app, no sound asset, no license needed |

## What Muse does now

In take 2, on the app's screen and sound track:

1. The parent says "changing time". The exact phrase no longer arms anything. It goes to Muse, and Muse calls `start_changing_table`. The agent logs who armed the watch (`changing_armed`, `via: brain`) and every time the phrase fallback fires (`phrase_fallback`). Muse answers "Watching the changing table."
2. The watch runs on the glasses frames. Each alert plays the new tone, then "hand" after the 1.2 s hold.
3. The parent says "done, it was dirty". No exact phrase matches this, so only Muse can close the watch. Muse calls `finish_changing_table` with `solid: true, wet: false`. The skill closes, the change goes to Baby Buddy with that content, and the entry is read back from the Baby Buddy API and handed to Muse as the tool's result. Muse writes the spoken summary from it: **"4 hand alerts this change. Logged diaper at 04:59, dirty."**
4. "When was the last diaper change?" Muse: "Last diaper change was at 04:59, dirty."

| Step, take 2 | Seconds |
|---|---|
| "changing time" to watching | 3.15 (the Muse call itself 1.15, the watch starts 0.52 after the tool runs). In PR #95 the shortcut armed in 0.51, so Muse deciding costs about 2.6 s |
| "done, it was dirty" to the watch closed and logged | 3.88 |
| to the entry read back from Baby Buddy | 3.92, entry 174 on `test-baby`, wet false, solid true |
| to Muse's spoken summary | 4.89 |

Between the parent's words and the Muse call there is about 1.5 s of the agent's own turn before the request goes out, measured, not yet explained. The phrase fallback did not fire in any of the three takes.

## Three takes

The same command three times in a row on main at ee4c401 (PR #102, SAM 3.1 in float16 and the hand-return wait) plus this branch. `run.json` is take 2. The feed is `hero-feed` from PR #95, **padded**: the hover clip's resting first 2.5 s plays twice so the hand rests 5 s before it hovers. The unpadded cut feed was not run. PR #102 fixed the diaper-holding miss (hands off), not the lift anchor that needs a resting hand after a cut, which is why the cut feed was padded.

| Take | Armed by, "changing time" to watching | Both hands off spoken | Hover 2.5 cm spoken | One hand, silent | SAM 3.1 calls, median and max s | Brain calls, fallbacks | Baby Buddy read-back | Muse's summary |
|---|---|---|---|---|---|---|---|---|
| 1 | Muse, 3.12 s | 2 of 2 | 2 of 2 | 4 of 4 | 14, 1.70, 2.91 | 5, 0 | 173, 04:57:28, solid true | "4 hand alerts this change. Logged diaper at 04:57, dirty." |
| 2 (the video) | Muse, 3.15 s | 2 of 2 | 2 of 2 | 3 of 3 | 14, 1.54, 1.90 | 5, 0 | 174, 04:59:01, solid true | "4 hand alerts this change. Logged diaper at 04:59, dirty." |
| 3 | Muse, 3.03 s | 2 of 2 | 2 of 2 | 4 of 4 | 15, 1.53, 2.01 | 5, 0 | 175, 05:00:38, solid true | "4 hand alerts this change. Logged diaper at 05:00, dirty." |
| **All** | **Muse 3 of 3, fallback 0** | **6 of 6** | **6 of 6** | **11 of 11** | 43 | **15, 0** | **3 of 3 dirty** | |

| Also per take | Take 1 | Take 2 | Take 3 |
|---|---|---|---|
| "done, it was dirty" to closed and logged | 4.54 s | 3.88 s | 4.38 s |
| to Muse's spoken summary | 6.02 s | 4.89 s | 5.56 s |
| Tone to "hand" | 1.23 to 1.50 s | 1.25 to 1.51 s | 1.24 to 1.50 s |
| SAM 3.1 confirms | off, off | off, off | off, off (all right) |
| Muse tokens in and out | 14,980 and 630 | 14,950 and 508 | 14,942 and 653 |

All 15 brain calls went to `meta-models/muse-spark-open-1026` on `inference.baseten.co`, 0.86 to 2.08 s each. In the first hero run both hands off was spoken 4 of 6. Here it is 6 of 6, with PR #102's fix in place.

The tone is two sine notes, 0.26 s, written by the app's code and saved as `tone.wav` next to the speech files, so the mux plays the same file the app played. Its mean level is -6.3 dB against -15.6 to -18.7 dB for the spoken lines (ffmpeg volumedetect). Tink was 0.02 s.

## SAM 3.1 regions against MediaPipe regions, same feed

Once, the same feed with the lift check's hand regions from MediaPipe instead of SAM 3.1 (`--regions mediapipe`, SAM 3.1 still confirms), `regions/mediapipe.json`:

| | SAM 3.1 regions (3 takes) | MediaPipe regions (1 run) |
|---|---|---|
| Both hands off spoken | 6 of 6 | 1 of 1 |
| Hover 2.5 cm spoken | **6 of 6** | **1 of 2** |
| One hand, silent | 11 of 11 | 3 of 3 |
| SAM 3.1 calls | 43 (anchors and confirms) | 2 (confirms only) |

On this feed the second hover was missed without SAM 3.1's hand masks. One run, two hovers, so read it as consistent with the blind set (`results/hover/blind/`: SAM 3.1 masks 23 of 32, MediaPipe regions 21 of 32), not as a new rate.

In this run Muse answered "Watching the changing table." without calling `start_changing_table`. The phrase fallback fired at the end of the turn and armed the watch 4.45 s after the words, and the run logged it (`phrase_fallback`). The watch started later, so fewer moments played whole. Muse picked the tool in 3 of 3 takes and missed it in this 1 run: 3 of 4 runs with SAM 3.1 tonight.

## The car seat segment

`carseat.mp4` (42.9 s, joined after the glasses take in `hero2.mp4`) and `carseat.json`. The car seat coach runs as in `scripts/carseat_eval.py` on two rendered test clips, one correct install and one with a twisted lap belt. For every check the screen shows the frame the verdict came from, with SAM 3.1's masks for that call drawn on it ("strap" for the belt, "blue clip" for the guides, "green line" for the level line, "handle"), the verdict, and the coach's line spoken by MMS-TTS.

| Clip | Planted mistake | Lap guides | Shoulder guide | No twist | Level line | Handle |
|---|---|---|---|---|---|---|
| test-02-correct | none | pass | pass | pass | pass | pass |
| test-16-twisted | twisted lap belt | pass | pass | **fail** | pass | pass |

13 SAM 3.1 calls, median 1.38 s, at most 1.60 s, float16 on MPS. The twist was caught and nothing was flagged on the correct clip. Two clips only. The full scored set stays `results/carseat/` (prior work, 11 of 12 wrong installs flagged). MMS-TTS ran in the Vostro voice service with the int8 ONNX decoder: 44 s for the first line (the model loading cold), 2.6 to 4.5 s for each later new line. The narration is laid on afterwards, not live.

## What failed or is limited

- **Muse once said it was watching without calling the tool** (the MediaPipe regions run). The phrase fallback caught it, and that is why the fallback stays. Muse picked the tool in 3 of 3 takes.
- **Arming through Muse takes about 3.1 s**, against 0.51 s for the exact-phrase shortcut. A hover in the first 3 s after "changing time" is not watched.
- **The glasses voice is still the iPhone's AVSpeechSynthesizer.** The app gets text from the agent and speaks it. It has no path to play a WAV from the agent, so MMS-TTS speaks only the car seat segment, laid on after the run.
- The hero feed is padded (see above). Hovers are rendered hovers. Not real glasses, not a real iPhone, not the home network path. Baby Buddy is the real server, with child `test-baby`.
- Muse wrote the summary from the read-back each time, but the wording follows the tool's instruction closely ("hand alerts", time, content). It is Muse's text, not a template, and it varied in take 3's answer to the question.
- "4 hand alerts" counts every spoken "hand" in the change, hands off and hover together.

```bash
apps/glasses/scripts/make-mock-feed.sh   # then build and install the app (apps/glasses/README.md)
mkdir /tmp/pa-gpu.lock
python scripts/glasses_hero_run.py --udid SIM --out-dir results/hero2/takes --name take-1 --feed hero-feed --watch 44 \
    --done "done, it was dirty" --ask "When was the last diaper change?" --ask-after 14 --mux
python scripts/glasses_hero_run.py --udid SIM --out-dir results/hero2/regions --name mediapipe --feed hero-feed --watch 44 \
    --done "done, it was dirty" --regions mediapipe
python scripts/carseat_hero_segment.py --out-dir results/hero2 --name carseat
rmdir /tmp/pa-gpu.lock
```
