# Speech on the glasses

Researched and built on Oct 30 2026, during the Meta hackathon. Sources are Meta's developer docs (read on Oct 30 through `wearables.developer.meta.com/llms.txt`) and the DAT SDK we pin, 1.0.1 (its `swiftinterface` files, its `CHANGELOG.md`, and a run of its MockDeviceKit in the iOS 27 simulator).

Until now the parent's words reached the agent typed: the app's text box, its quick buttons, or a run's script on `/say`. Now the glasses microphone hears the parent, Muse Spark Open writes the words down, and only words meant for the agent become a message.

## What DAT 1.0.1 allows for audio and speech

There are four ways for an iPhone app to hear the wearer. Three are in DAT and one is plain iOS. None of them is open to a Web App on the glasses: "Only the Device Access Toolkit can use the glasses' camera or capture microphone audio. Web Apps get spoken input only as text dictated into a text field" ([docs index](https://wearables.developer.meta.com/llms.txt)).

| Route | What the app gets | Status in DAT 1.0.1 | Source |
|---|---|---|---|
| **Bluetooth HFP** | The glasses microphones as an iOS audio input: `AVAudioSession` `.playAndRecord` with `.allowBluetoothHFP`, the `.bluetoothHFP` port as preferred input, an `AVAudioEngine` tap. Mono 16 or 8 kHz. The glasses beamform to the wearer's voice, which "significantly reduces the volume of ambient sounds and other speakers". Output drops from A2DP to mono voice quality while HFP is on. The HFP route must settle (Meta waits 2 s) before the DAT camera stream starts | **Not beta**, plain iOS audio, no DAT call. Mic permission is the iOS dialog | [Use device microphones and speakers](https://wearables.developer.meta.com/docs/develop/dat/microphones-and-speakers/), [Integration overview](https://wearables.developer.meta.com/docs/develop/dat/build-overview/) |
| **Audio in the camera stream** | `StreamConfiguration(videoCodec:audioCodec:resolution:frameRate:)` with `.pcm(sampleRate: .rate16000, numberOfChannels: 1)`, then `Stream.audioFramePublisher` hands `AudioFrame` (`AVAudioPCMBuffer` plus a timestamp aligned with the video). No HFP, output stays on A2DP. Not beamformed: the room is heard at its natural level | **Beta**: "available in the development and beta release channels only" | same page, "Capture audio while streaming from the camera", and DAT [CHANGELOG 1.0.0](https://github.com/facebook/meta-wearables-dat-ios/blob/main/CHANGELOG.md) |
| **Speech (`MWDATSpeech`)** | Recognition on the glasses: `session.addSpeech()`, `start()`, `transcriptionPublisher` with `TranscriptionResult(text, isFinal, confidence)`, `localePublisher` with the device's locale. No audio reaches the app. Needs `Permission.microphone` through the Meta AI app. It can stop after a quiet spell. The app cannot choose the language: the locale is the glasses' own | **Beta** (experimental in the changelog, "Do not depend on it in a production build") | [Transcribe speech on the glasses](https://wearables.developer.meta.com/docs/develop/dat/speech/), [Speech API](https://wearables.developer.meta.com/docs/reference/ios_swift/dat/1.0/mwdatspeech_speech) |
| **Hey Meta voice invocations** | "Hey Meta, start {app name}" launches or foregrounds the app and hands it a `VoiceInvocation`. Only a launch, not the parent's words | **Beta**, needs a Wearables Developer Center configuration | [Respond to Hey Meta voice invocations](https://wearables.developer.meta.com/docs/develop/dat/voice-invocations/) |

What MockDeviceKit can feed without glasses, checked in the simulator on Oct 30:

| Mock | What it does | What we found |
|---|---|---|
| `MockSpeechKit.simulateTranscription(text:isFinal:confidence:)` (source `.injected`, the default) | Hands the app a transcription as if the glasses had recognized it | Text only. It skips hearing entirely, so it cannot test a microphone |
| `MockSpeechKit.setTranscriptionSource(.liveDeviceAsr)` | "Host mic + platform `SFSpeechRecognizer`" ([MockSpeechSource](https://wearables.developer.meta.com/docs/reference/ios_swift/dat/1.0/mwdatmockdevice_mockspeechsource)) | In the simulator the host mic is the Mac's microphone, and the recognizer is Apple's, not the glasses'. Not used: feeding it means playing audio into the Mac's input, and it would not test the glasses' recognizer anyway |
| `MockCameraKit.setCameraFeed(fileURL:)` with an audio track in the file | The camera feed plays the video | **No audio**. With an audio codec in the stream configuration the mock stream never leaves "starting" and fails after about 5 s with "The operation timed out", with an MP4 holding AAC at 48 kHz or at 16 kHz. Without the audio codec the same file streams. So the in-stream audio route cannot be exercised on MockDeviceKit 1.0.1 |
| HFP | Not a DAT mock. In the simulator the input is the Mac's | Not used, for the same reason as `.liveDeviceAsr` |

So no DAT mock can feed recorded audio into the glasses microphone path. The app mocks exactly that one thing itself, see below.

## What we built

```
glasses mic (HFP, or the camera stream, beta)  ─┐
iPhone mic (HFP code path with no glasses)     ─┼─> UtteranceCutter (on the phone) ──WAV──> POST /hear ─> Muse's ear ─┐
recorded clip (simulator only, MockMicrophone) ─┘                                                     (Baseten)      │
glasses that transcribe (DAT Speech, beta) ──────────────────────────text────────> POST /hear ──────────────────────┤
                                                                                                                    v
                                                    speech gate (glasses_speech.Gate) ─ meant for the agent? ─> the same
                                                    message as typed words: changing table, car seat, questions, red flag
```

**On the phone** (`ParentingGlasses/Speech/`):
- `MicSource` picks the route in Settings, "Your voice": the glasses mic over HFP (the default, and with no glasses connected iOS gives the iPhone mic on the same code path: the fallback), the glasses mic in the camera stream (beta), recognition on the glasses (DAT Speech, beta), or off.
- `HFPMicrophone` follows Meta's HFP recipe step by step, and `Companion.connect()` starts it before the camera stream, as Meta's ordering rule asks.
- `UtteranceCutter` cuts the 16 kHz mono stream into utterances with an energy gate: 20 ms frames, speech after 60 ms over the gate, 0.2 s kept before, the end after 0.6 s under it, at most 15 s, a click under 0.25 s dropped. The gate is 12 dB over the quietest recent level, never under -50 dBFS. Only speech leaves the phone, as a 16-bit WAV, with the wall clock of its last voiced moment (`X-Speech-End-Unix`).
- While the app speaks (the agent's reply through the same glasses) the cutter is muted, and 0.3 s after, so the agent never hears itself.
- `GlassesCamera` attaches DAT's `Speech` when that route is picked: final transcriptions go to `/hear` as text, it restarts after a stop, and it reports the glasses' locale.

**On the agent** (`parenting_agent/glasses.py`, `parenting_agent/glasses_speech.py`):
- `POST /hear` takes a WAV or `{"text"}`, with the pairing token like every other call, and answers 202 at once.
- **Muse Spark Open is the ear**, the same `voice/ear.py` call that hears Telegram voice notes, with a glasses prompt that keeps the wake word. Only the first line of its answer is taken: on an emergency it sometimes writes the words and then advice. Muse sometimes does not believe audio came with the request and answers with nothing, or answers as an assistant ("Hola, ¿en qué puedo ayudarte?"), most often on a single short word. So the agent **races 3 ear calls at once** and takes the first real transcript, and asks again (3 more) only if none was. On 96 test lines (`results/glasses-speech/README.md`) the race and the glasses prompt took word accuracy from 94.0 % to 97.0 %, lines heard as nothing from 5 to 3, and the gate from 89 to 94 right.
- **The gate.** The microphone is always on near a baby, and most of what it hears is not for the agent. A start phrase passes any time ("changing time", "hora del cambio"). A short answer passes only while the agent waits for it: "done" or "listo" while the changing table watches, "sí" or "no" while the car seat coach or the agent asked, "ya llamé" or "entendido" while a red flag card is up. Anything else needs the wake word first, "agente" or "agent" (the wake word alone opens the next 8 s). Everything else is dropped: never a message, never a brain call, not kept.
- What passes takes the same path as typed words (`Glasses.heard`), so every skill, the car seat coach's yes and no, and the red flag acknowledgement work unchanged.

Why Muse and not on-device iOS speech recognition: Muse writes down both languages from one call with no language setting, and it is the agent's own model on the one configured brain call. Its race takes about 3.5 to 4 s (median 3.54 s on the test set), so a command the agent answers itself reaches the lens 3.4 to 4.8 s after the parent stops talking, see the results. That is slow for "listo" on a red flag, workable for everything else. On real glasses the DAT Speech route recognizes on the glasses and sends text at once, skipping Muse's ear: it is wired, and only needs glasses to measure.

## Real and mocked, exactly

| Part | Real or mocked |
|---|---|
| The microphone input | **Mocked**: recorded clips of macOS voices (`say`), played by `MockMicrophone` into the same `UtteranceCutter` the real microphones feed, in real time, 20 ms at a time. The run's script only names the clip to play (a `mock_mic` event, Debug builds only), never its words |
| Cutting, upload, Muse's ear, the gate, the agent, the cards | **Real**, live |
| HFP, the in-stream audio and DAT Speech routes | **Built, not run**: they need real glasses (MockDeviceKit 1.0.1 does not feed audio, see above) |
| Glasses, camera, lens | **Mocked** by DAT MockDeviceKit and MockDisplayKit, as in `HUD.md` |

## Run it

```bash
python scripts/glasses_hud_speech.py --clips          # MockMic/*.wav and MockFeed/hud-speech-feed.mp4 (git ignored)
python scripts/glasses_hud_speech.py --batch          # word accuracy and the gate on 96 lines and 4 no-speech clips
xcodebuild -project apps/glasses/ParentingGlasses.xcodeproj -scheme ParentingGlasses -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' -derivedDataPath apps/glasses/build build
xcrun simctl install booted apps/glasses/build/Build/Products/Debug-iphonesimulator/ParentingGlasses.app
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro   # Baby Buddy
python scripts/glasses_hud_speech.py --udid SIM --out-dir results/glasses-speech --name run \
  --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-speech.mp4
apps/glasses/scripts/test-hud.sh                      # the HUD and cutter tests, on the Mac
```

## Real glasses, when they come

1. In the app's Settings, "Your voice", keep "Glasses mic (Bluetooth HFP)". iOS asks for the microphone once.
2. Connect. The screen line under the chips says the route: "Listening · glasses (HFP)" means the glasses mic, anything else is the iPhone's.
3. Say "changing time". Then "agente, ¿cuándo comió por última vez?".
4. To try recognition on the glasses, pick "Transcribed on the glasses". The Meta AI app asks for the microphone. Its language is the glasses' own.
