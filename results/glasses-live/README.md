# The glasses HUD, live, Oct 30 2026

Run on Oct 30 2026 at 20:21 Montevideo, during the Meta hackathon, for issue #151. Until now the HUD clip (`apps/glasses/HUD.md`) replayed detector outputs saved on Oct 29. This run drives the same HUD from the running agent: frames go up from the mock glasses, the detectors and Muse run on them now, and every card on the lens comes from an event the agent sent.

Clip: `~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-live.mp4`, 68.4 s, 588 x 1280, with the app's tone and spoken lines laid on at their play times (simctl records no audio). Not committed. `hud-live-raw.mp4` next to it is the untouched screen recording. The clip is one take, in real time, not edited. On screen: "Live: detectors and agent running, glasses and lens simulated by Meta's mock".

`run.json` is that run: every agent event, every card the display accepted with what caused it, the brain calls and the Baby Buddy read back. Screenshots from the clip: `01-held-hidden-hands.png`, `02-hover.png`.

## What ran live

| Part | What ran | Where |
|---|---|---|
| Glasses camera to phone | DAT 1.0.1 camera stream from a mock Meta Ray-Ban Display (`MockDeviceKit`, `.metaRayBanDisplay`) playing our feed, 15 fps into the app, sampled to 10 fps | iOS 27.0 simulator, iPhone 18 Pro |
| Phone to agent | Each sampled frame as a JPEG to the glasses endpoint, the pairing token on every request, about 450 frames | `127.0.0.1:8766` on this Mac |
| The agent | `python -m parenting_agent --config config/agent.glasses-live.json`: the glasses channel, the changing-table skill, the bath skill (not armed), the dog look on the glasses frames | this Mac |
| Brain | Muse Spark Open, `meta-models/muse-spark-open-1026`. It armed the watch by calling `start_changing_table` and closed it with `finish_changing_table(solid: true)`. 4 calls, 0.79 to 3.45 s each | Baseten |
| Hand reflex | MediaPipe Hands on every frame, 366 frames while armed | this Mac |
| SAM 3.1 | `facebook/sam3.1`, float16 on MPS, **one process** for the whole run: lift anchors, the confirm, the held look and the dog look, 24 calls. Loaded in 11.9 s before the app started. Run under `/tmp/pa-gpu.lock`, stopped at the end, nothing else heavy ran | this Mac |
| Baby log | The diaper went to Baby Buddy, child `test-baby`, entry 220 (dirty), and was read back from its API | the Vostro, through the SSH tunnel |
| Display | `DisplayHUD` sent 36 cards through DAT's Display API (`MWDATDisplay`), drawn by Meta's `MockDisplayKit` | the simulator |
| Telegram | The dog alert went to a capture file (`data-glasses-live/telegram-captured.jsonl`): "Dog close to Theo in the changing table". Nothing was sent | this Mac |
| House | All four house actions were dry runs (`house_dry`): Do Not Disturb, mute, restore, the Echo announce. The run blanks every Telegram and Home Assistant variable for the agent | none |

## The scenes

The feed is 61.9 s of our synthetic changing-table clips and one licensed photo, in this order. Scene times are feed times. A cue is when the hands start to leave or rise.

| Scene | What happened, all live | Result |
|---|---|---|
| Armed by Muse | "changing time" went to Muse, Muse called `start_changing_table`. Words to watching 3.09 s, words to the "armed by Muse" card 3.10 s | yes |
| Held diaper (0 to 17 s) | The hands hold a diaper over the baby from the first frame, so MediaPipe never sees them. The tone sounded once when the watch started (an unseen alarm), then SAM 3.1's held look found the hands on the baby and cancelled it before any "hand": the card read "Hands hidden from MediaPipe, SAM 3.1 found the hand on the baby". At the cue the hands rose with the diaper: "hand" 1.64 s after the cue | spoken, no false "hand" |
| Both hands off (17 to 26 s) | Hands rest, then both leave: tone, then "hand" 1.51 s after the cue | spoken |
| One hand on (26 to 36 s) | One hand rests on the baby for 10 s, 83 frames | silent, no tone |
| Hover 2.5 cm (36 to 43 s) | SAM 3.1 hand masks anchor the lift check, the hand rises: "Hover, hand lifted 1.8 cm", lift up to 2.88 cm, "hand" 1.41 s after the cue | spoken |
| Logged (43 to 50 s) | "done, it was dirty": Muse closed the watch, entry 220 written and read back (dirty), the card "Logged, diaper at 20:22 · dirty, read back from Baby Buddy · entry 220", then Muse's line on it: "This change had 3 hand alerts. Logged dirty diaper at 8:22 PM." | yes |
| Dog near the baby (50 to 62 s) | SAM 3.1 on the glasses frame: dog 0.91, baby 0.89, gap 0.13 baby sizes, near, alert captured. 5 looks on the dog frames, all near. No dog alert on any table frame | yes |

Cue to "hand" here is wall clock: the agent's publish time of the voice minus that of the first frame at the cue.

## Latency, frame to card

From the moment the agent received the frame (`frame_unix`, set by the glasses endpoint) to the moment the display accepted the card (`DisplayHUD.onSent` in the app). Same Mac, same clock.

| Card | What decides it | Frame to card |
|---|---|---|
| Hand state (on, off, lifting, lift in cm) | MediaPipe and the lift check | 0.04 to 0.09 s (14 cards), one at 0.25 s |
| Tone card ("Hands off", "Hover") | the alarm on that frame | 0.09 s (3 cards), one at 0.25 s |
| "hand" spoken | the 1.2 s hold | 0.05 to 0.08 s from the frame that spoke it |
| SAM 3.1 confirm and the held look | one SAM 3.1 look | 2.76 s |
| Dog near the baby | one SAM 3.1 dog look (about 2.0 s on the GPU) | 2.09 to 2.19 s |
| From the parent's words | | "changing time" to the armed card 3.10 s, "done" to the logged card 5.66 s, to Muse's line on it 6.76 s |

The HUD adds almost nothing: the slow parts are SAM 3.1 (2 to 3 s a look) and Muse (one call took 3.45 s in "done").

## What we fixed to make it run

- **One SAM 3.1 process.** The dog look used to load its own SAM 3.1 worker. Now the confirm worker answers prompt masks too (`PROMPTS` in `sam3_worker.py`, `Sam3Local.prompt_masks`), `sam3_local.live()` is the running worker, and the changing table keeps it between changes (`keep_confirm`) instead of closing it and loading another.
- **The dog look on the glasses** (`dog_watch.GlassesDogWatch`): the newest glasses frame through the shared worker, paused while a skill watches and from the moment the parent says "changing time". In rehearsal 5 a dog look held the GPU when the watch started, the held look answered after 4.9 s, and "hand" was spoken over hands that were on the baby. With the pause the held look answered in about 2.8 s.
- **A failed arm no longer loses the detector.** The first rehearsal failed to arm (MediaPipe's model files were missing in the worktree). The arm had taken the preloaded SAM 3.1, so the next arm would have loaded a second one. Now it reuses it, and stop closes it.
- **The agent sends what the HUD shows** (`glasses.TO_APP`): armed and by whom, the alarm and its clear, the confirm, the held look, the read back, the dog look, the lift in cm, each with the arrival time of its frame.
- **The feed.** A spliced feed has cuts a real camera does not. A cut while a resting hand was anchored read as a 3.1 cm lift and spoke "hand" (rehearsal 4). Every cut now falls where the hands are gone or the watch is not armed, and resting stretches play forwards then backwards instead of jumping. `table-handsoff-01` was replaced by `table-handsoff-02`: in 01 the hands are away for under a second and come back holding a diaper over the baby, and SAM 3.1 read that as a hand on, twice (rehearsal 6).
- **The screen.** The "600 x 600 in-lens display, enlarged" label sat over the "HEAD CAMERA" label. It is now under the lens.

## Still simulated, and why

| Part | Why |
|---|---|
| The glasses and their camera | No Meta Ray-Ban Display here. DAT MockDeviceKit pairs a simulated one, its camera plays our feed |
| The lens | MockDisplayKit draws what our app sends through the real Display API, not the waveguide |
| The camera picture | Generated clips of a generated baby and one Wikimedia Commons photo (CC BY 2.0, credited on screen). No real child |
| The parent's words | Typed by the app at fixed feed times (`HUD/hud-live.json`), sent on the same `/say` path as the app's text box. The app has no speech recognition yet |
| Telegram and the house | Captured and dry, on purpose: no real messages, no real devices |
| Audio | The app played the tone and spoke "hand" and Muse's lines. The simulator records no sound, so they are laid on from the app's own recordings (`-recordSpeech`) |

## What is weak

- **The tone at the start of the held scene.** When the watch starts with the hands hidden, the tone sounds once before SAM 3.1 finds them (2.8 s later). No "hand" was spoken. The held set showed the same (`results/hover/held`, chimes on 9 of 12 touches).
- **SAM 3.1 did not name the diaper** in this run. Its diaper mask lies inside the baby mask, which the held look reads as the baby's own diaper, so the card says "Hands hidden from MediaPipe". In rehearsal 6 it named a wipe.
- **One take.** Seven rehearsals came before it, the last three with this design (rehearsals 6 and 7 and a recorded rehearsal): in all three every scene above passed except the hands-off miss in rehearsal 6, which was the clip, fixed by the swap. That is three runs, not a rate.
- The words-to-card times include Muse. "done" to the logged card was 3.2 to 3.4 s in the rehearsals and 5.7 s here, because one Muse call took 3.45 s.

## Run it

```bash
python scripts/glasses_hud_live.py --build-feed     # HUD/hud-live.json and MockFeed/hud-live-feed.mp4
xcodebuild -project apps/glasses/ParentingGlasses.xcodeproj -scheme ParentingGlasses -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' -derivedDataPath apps/glasses/build build
xcrun simctl install booted apps/glasses/build/Build/Products/Debug-iphonesimulator/ParentingGlasses.app
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro  # Baby Buddy
python scripts/glasses_hud_live.py --udid SIM --out-dir results/glasses-live --name run \
  --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-live.mp4
```

The script takes the GPU lock, starts the agent, waits for SAM 3.1, records the screen, launches the app with `-hudLive YES`, stops everything when the feed ends and frees the lock. The MediaPipe model files must be in `.models/` (git ignored).
