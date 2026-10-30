# The glasses display (HUD)

Researched and built on Oct 30 2026, during the Meta hackathon, for issue #151. Sources are Meta's own developer docs and the DAT SDK we pin (1.0.1), read on Oct 30.

## What an outside developer can show on the Meta Ray-Ban Display today

**There is a real display API, and we use it.** Meta's Wearables Device Access Toolkit (DAT) has had a Display capability since 0.7.0 (May 14 2026). It is in the 1.0.1 we already pin, as the `MWDATDisplay` module. It is not marked experimental, unlike Inputs, Motion, Speech, audio streaming and photo capture.

| Question | Answer | Source |
|---|---|---|
| Which glasses have a display | Only Meta Ray-Ban Display. One display, in the right lens | [Display access overview](https://wearables.developer.meta.com/docs/develop/dat/display-overview/) |
| Size | 600 x 600 pixels. "There is no benefit to sending larger images" | same, and [Simulate Display content](https://wearables.developer.meta.com/docs/develop/dat/display-simulation/) |
| How it renders | Additive light: a black pixel adds nothing, bright pixels add light over the world | [Web Apps: Display and layout](https://wearables.developer.meta.com/docs/develop/webapps/build/display-and-layout/) |
| Route 1, a phone app (DAT) | The iOS or Android app opens a `DeviceSession`, adds `Display`, and sends one root view at a time. The SDK serializes it and sends it over Bluetooth. Each `send()` replaces the whole display, there are no partial updates | [Integrate Display capability into your iOS app](https://wearables.developer.meta.com/docs/develop/dat/display-ios/) |
| Components | `FlexBox` (row or column), `Text` (heading, body, meta, in primary or secondary color only), `Image` (URL or a bundled `UIImage`), `Button`, `ButtonGroup`, `Icon` (a fixed catalog of about 120 glyphs), `VideoPlayer` (HTTPS MP4, at most 400 px a side and 70,000 pixels), one `card` background | same, and the [icon catalog](https://wearables.developer.meta.com/docs/develop/dat/display-icons/) |
| Input | Taps on buttons and tappable views come back to the app. Back (two-finger tap) ends the session. The touchpad and the Meta Neural Band drive the focus. Raw Neural Band and touchpad events are the separate `MWDATInputs` capability, experimental and gated by approval in the Wearables Developer Center | [Display access overview](https://wearables.developer.meta.com/docs/develop/dat/display-overview/), [Inputs](https://wearables.developer.meta.com/docs/develop/dat/inputs/) |
| Limits | The display dims after 20 s without a change and sleeps at 25 s, the session stays. The system can interrupt the session for calls and notifications. The user must start the session, and the app has the display alone while it runs | [display-ios](https://wearables.developer.meta.com/docs/develop/dat/display-ios/), [overview](https://wearables.developer.meta.com/docs/develop/dat/display-overview/) |
| Real glasses setup | Meta AI app and glasses firmware at the versions DAT lists, Developer Mode on (Settings, App Info, tap the version 5 times), then the DAT app is installed on the glasses from there | [Display access overview](https://wearables.developer.meta.com/docs/develop/dat/display-overview/) |
| Route 2, a web app | A Chromium browser on the glasses runs HTTPS web apps with the 600 x 600 viewport, the Neural Band's orientation (W3C `RelativeOrientationSensor`), text to speech and WebMCP tools for Meta AI. A web app cannot use the camera or record the microphone, so it cannot run our checks | [Wearables docs index](https://wearables.developer.meta.com/llms.txt), [Web Apps setup](https://wearables.developer.meta.com/docs/develop/webapps/setup/) |
| Without hardware | MockDeviceKit pairs a simulated `.metaRayBanDisplay`. `MockDisplayKit.createPreviewView()` renders the 600 x 600 display surface in our own app, transparent around the content, from the same `Display` calls. A Chrome extension (Meta Ray-Ban Display Simulator) can show it too, with additive blending and background brightness settings | [Simulate Display content](https://wearables.developer.meta.com/docs/develop/dat/display-simulation/), DAT [CHANGELOG 1.0.0](https://github.com/facebook/meta-wearables-dat-ios/blob/main/CHANGELOG.md) |
| Hardware numbers outside the dev docs | 20 degree field of view, 42 pixels per degree, up to 5,000 nits, launched Sept 2025 at 799 USD with the Neural Band. These come from launch coverage, not from the dev docs | [Road to VR](https://www.roadtovr.com/meta-ray-ban-smart-glasses-display-price-release-date-specs/), [UploadVR](https://www.uploadvr.com/meta-ray-ban-display-glasses-officially-announced/), [Meta newsroom](https://about.fb.com/news/2025/09/meta-ray-ban-display-ai-glasses-emg-wristband/) |

So the agent can draw its own cards on the lens from the iPhone app it already has: the same app that streams the camera. That is what this change does.

## What we built

- `ParentingGlasses/HUD/HUDState.swift` folds events into one card: the watch armed by Muse, hand on or off, the hover with its lift in cm, "hand" spoken (headline for 1.6 s), the hand hidden by a held diaper and found by SAM 3.1, the diaper logged and read back from Baby Buddy, and a dog near the baby. The same reducer takes live agent events (`state`, `chime`, `voice`, `reply`, `skill`) and recorded ones.
- `ParentingGlasses/HUD/DisplayHUD.swift` attaches DAT's `Display` to the device session as soon as it starts and sends each changed card as a `FlexBox` (icon and title, status, detail, meta, `card` background). Only a changed card is sent, and only the newest waits while a send is in flight. On glasses without a display `addDisplay()` throws and the HUD stays off, so Ray-Ban Meta keeps working as before.
- `ParentingGlasses/HUD/HUDReplayScreen.swift` (Debug only) shows the wearer's view in the simulator: the head camera with Meta's mock display preview added on top with plus-lighter blending, the way the additive display adds light.
- `scripts/glasses_hud_replay.py` writes `HUD/hud-replay.json` from recorded detector outputs and, with `--feed`, cuts `MockFeed/hud-feed.mp4` (30 fps HEVC, kept out of git).

## Real and simulated, exactly

| Part | Real or simulated |
|---|---|
| Display API calls (`addDisplay`, `start`, `send(FlexBox)`, `statePublisher`) | **Real** DAT 1.0.1 API, the same calls real glasses get |
| What draws the cards | **Simulated**: Meta's `MockDisplayKit` preview in the iOS simulator, not the glasses' waveguide |
| The glasses and their camera | **Simulated**: a `.metaRayBanDisplay` from DAT MockDeviceKit, whose camera plays our feed |
| Camera pictures | Our generated changing-table clips (no real child), and one Wikimedia Commons photo (CC BY 2.0, credited on screen) |
| Detector outputs | **Recorded, replayed**: MediaPipe reflex states, alarms, tones, "hand" and SAM 3.1 confirms from hero2 take 2 (`results/hero2/run.json`, Oct 29), the held diaper hover from `results/hover/held/blind2/after.json` (Oct 29), the dog verdict from `results/dog-near-baby/blind.json` (Oct 29), with the saved SAM 3.1 masks drawn on the held clip and the dog photo. No model ran for the HUD clip |
| Muse lines and the Baby Buddy read back | Recorded in hero2 take 2 (entry 174, 04:59, dirty) |
| Timing | Inside the three hero2 scenes every event keeps its recorded time against the feed. Between scenes, and inside the held, logged and dog scenes, gaps are shortened (for example the dog look took 3.83 s, the HUD shows it 0.4 s in) |
| On-screen size | The 600 x 600 square is drawn about 255 points wide over the camera, enlarged for legibility. On the glasses it covers about 20 degrees of view. The camera is dimmed by 30 percent so the added light reads on video |
| Sound | The app plays the tone and speaks "hand", but simctl screen recordings have no audio track |

## The live run (Oct 30)

`-hudLive YES` drives the same HUD from the running agent instead of a recording: the mock glasses stream `MockFeed/hud-live-feed.mp4` to the agent, MediaPipe, one SAM 3.1 process and Muse run on the frames, and every card comes from an agent event (`parenting_agent/glasses.py` `TO_APP`, one entry per event kind, mapped to one card kind in `HUDState.live`). `scripts/glasses_hud_live.py` builds the feed and runs the whole thing. Results, latency and what is still simulated: `results/glasses-live/README.md`.

## Run it

```bash
python scripts/glasses_hud_replay.py --feed      # needs ffmpeg, the synthetic clips and video-v5/rec/sam
xcodebuild -project apps/glasses/ParentingGlasses.xcodeproj -scheme ParentingGlasses -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' -derivedDataPath apps/glasses/build build
xcrun simctl install booted apps/glasses/build/Build/Products/Debug-iphonesimulator/ParentingGlasses.app
xcrun simctl launch booted com.bygmv.parentingglasses -hudReplay YES
apps/glasses/scripts/test-hud.sh                 # the HUD logic tests, on the Mac
```

`-hudReplay YES` needs no agent. The replay clock starts at the first camera frame. MockDeviceKit plays the feed at 30 frames per second whatever the file says, so the feed is encoded at 30 fps (a 24 fps feed ran 1.25 times fast and drifted from the replay).

## The recorded clip (Oct 30)

`~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud.mp4`, 18.9 s, 1206 x 2622, silent, not committed. `hud-raw.mp4` next to it is the untrimmed recording. Six scenes: armed by Muse, both hands off and "hand", the 2.5 cm hover and "hand", the held diaper found by SAM 3.1 and "hand", the diaper logged and read back, the dog near the baby. In video-v5 it fits right after the glasses hero run, as the answer to "what does the parent see in the lens".

## Not done

- Not run on real Meta Ray-Ban Display glasses, only on the mock. The live path (frames up, the running agent with MediaPipe, SAM 3.1 and Muse, its events to the display) ran on Oct 30: `results/glasses-live/README.md`.
- No Neural Band input. Inputs is experimental and needs approval in the Wearables Developer Center.
- The HUD is text and icons. Sending the SAM 3.1 mask picture to the display as an `Image` would work through the API but was not built.
