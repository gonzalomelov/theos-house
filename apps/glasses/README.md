# Parenting Glasses, the Ray-Ban Meta companion app

An iPhone app that makes Ray-Ban Meta glasses the agent's head camera. Built during the Meta hackathon on Oct 28 2026 (issue #57).

- It connects to the glasses with Meta's Wearables Device Access Toolkit (DAT), the official Swift package from `github.com/facebook/meta-wearables-dat-ios`, pinned to 1.0.1 (`MWDATCore`, `MWDATCamera`, `MWDATDisplay`, `MWDATMockDevice`).
- On Meta Ray-Ban Display glasses it also draws the agent's HUD on the in-lens display (`HUD.md`).
- It streams the glasses camera at 15 fps, medium size (504 x 896), decoded frames, and samples them down to 10 fps (Settings, 1 to 15).
- Each sampled frame goes as a JPEG to the agent on the parent's own Mac (`parenting_agent/glasses.py`), over the home network, never the internet. A frame that arrives while the last one is still uploading is dropped, so the agent always sees the newest view.
- What the parent says goes to the agent as a message on the `glasses` channel: spoken (the glasses microphone over Bluetooth HFP, or the iPhone's, cut into utterances on the phone and heard by Muse Spark Open, `SPEECH.md`), typed, or the quick buttons.
- The agent's replies, the chime and the spoken "hand" come back as server-sent events. The app shows them and speaks them with the iPhone voice, which plays on the glasses speakers when they are connected.
- In a Debug build, "Mock glasses" pairs a simulated Ray-Ban Meta from DAT's MockDeviceKit and plays a video file as its camera. This is how it runs in the simulator.

## Files

| File | What it does |
|---|---|
| `ParentingGlasses/GlassesCamera.swift` | DAT registration, device session, camera stream, frame sampling, mock glasses |
| `ParentingGlasses/AgentLink.swift` | Frames up, messages up, events down, with the pairing token on every request |
| `ParentingGlasses/Companion.swift` | Wires glasses to agent, the conversation log, the simulator demo |
| `ParentingGlasses/Voice.swift` | Speaks replies, plays the chime |
| `ParentingGlasses/ContentView.swift` | The screen and the settings sheet |
| `ParentingGlasses/Speech/` | The microphone routes, the utterance cutter and the simulator's recorded microphone. See `SPEECH.md` |
| `ParentingGlasses/HUD/` | The glasses display (HUD) on Meta Ray-Ban Display through DAT's Display API, and the recorded HUD replay. See `HUD.md` |
| `Config/Info.plist` | DAT keys (`MWDAT`), Bluetooth, external accessory and local network entries, DAT analytics and crash reporting opted out |
| `scripts/make-mock-feed.sh` | Builds the mock camera feed from the synthetic clips (HEVC, kept out of git) |

## Run it in the simulator

```bash
apps/glasses/scripts/make-mock-feed.sh            # once, needs ffmpeg and the synthetic clips
xcodebuild -project apps/glasses/ParentingGlasses.xcodeproj -scheme ParentingGlasses -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' -derivedDataPath apps/glasses/build build
xcrun simctl install booted apps/glasses/build/Build/Products/Debug-iphonesimulator/ParentingGlasses.app
python -m parenting_agent --config config/agent.glasses.json      # prints the endpoint and the pairing token
xcrun simctl launch booted com.bygmv.parentingglasses -agentToken <token> -autoDemo YES
```

`-hudSpeech YES` runs the speech run: the parent's lines are recorded clips played into the microphone path (`scripts/glasses_hud_speech.py`, `results/glasses-speech/README.md`). `-hudLive YES` runs the live HUD: the mock Meta Ray-Ban Display streams `MockFeed/hud-live-feed.mp4` to the running agent and the lens shows its events (`scripts/glasses_hud_live.py`, `results/glasses-live/README.md`). `-hudReplay YES` runs the HUD replay instead: a mock Meta Ray-Ban Display whose in-lens display shows our checks, driven by recorded detector outputs, no agent needed (`HUD.md`).

Debug launch arguments for the simulator demo: `-mockFeed NAME` plays `MockFeed/NAME.mp4`, `-demoAsk TEXT` asks one more question after "done", and `-recordSpeech YES` also renders every line the app speaks to `Documents/speech/NNN.wav` with a play log, because the simulator's screen recording has no audio. `scripts/glasses_hero_run.py` uses all three for the recorded hero run (`results/hero/README.md`).

The first build downloads the DAT package from GitHub (about 230 MB of git history, the first build took 18 minutes on Oct 28). `scripts/glasses_sim_run.py` runs the whole loop and writes the numbers, see `results/glasses/README.md`.

## Morning steps for Gonza: real glasses

Nothing here needs a Meta developer account or an app ID. Developer Mode skips DAT's app attestation, so `META_APP_ID` and `CLIENT_TOKEN` stay empty.

1. Meta AI app on the iPhone: update it, open Settings, pick the Ray-Ban Meta glasses, turn on **Developer Mode**. The glasses may restart. Developer Mode turns itself off after a firmware update, so check it again after one.
2. Mac: open `apps/glasses/ParentingGlasses.xcodeproj` in Xcode 27. In the ParentingGlasses target, Signing and Capabilities, pick your Apple team. If Xcode says the bundle id is taken, change `com.bygmv.parentingglasses` to anything unique.
3. Plug in the iPhone, pick it as the run destination, build and run (Debug). On the iPhone, trust the developer profile if iOS asks (Settings, General, VPN and Device Management).
4. Start the agent so the phone can reach it on the home network. Find the Mac's address (`ipconfig getifaddr en0`, or the Tailscale 100.x address), then:
   ```bash
   PARENTING_AGENT_GLASSES_HOST=192.168.x.y python -m parenting_agent --config config/agent.glasses.json
   ```
   It prints `glasses endpoint: http://192.168.x.y:8766/ pairing token in data/glasses-token`. The token is never printed: read it with `cat data/glasses-token` (mode 600). A public address or 0.0.0.0 is refused. Set `PARENTING_AGENT_GLASSES_TOKEN` to keep the same token across restarts.
   The link is plain HTTP, so on a Wi-Fi other people share, anyone on it can read the token and send "yes" on `/say`. Prefer the Tailscale 100.x address of the Mac as the host, with Tailscale on the iPhone too: the traffic then goes over WireGuard and nothing on the Wi-Fi sees it.
5. In the app: the gear, set the agent address `http://192.168.x.y:8766` and the pairing token, Done. iOS asks for local network access the first time, allow it.
6. Put the glasses on, unfolded. Tap **Connect glasses**. The first time it opens the Meta AI app to approve this app and the camera, then comes back. The chips should read "Glasses · live" and "Agent connected".
7. Say or tap "changing time", work at the changing table with a doll, lift both hands, hear the chime and "hand", then "done".

If the stream sits at "waiting for glasses": Developer Mode is off, the glasses are folded or off your head, or Bluetooth is off. A single tap on the glasses touchpad pauses the stream, a second tap resumes it. If Wi-Fi streaming fails on the device, add the two Wi-Fi entitlements Meta's CameraAccess sample uses (`com.apple.developer.networking.wifi-info`, `com.apple.developer.networking.HotspotConfiguration`), which need a paid Apple team.

The app was not run on a real iPhone or real glasses yet. Everything above the simulator is untested until the morning.
