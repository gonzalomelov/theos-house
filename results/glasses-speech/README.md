# Speech on the glasses, live, Oct 30 2026

Run on Oct 30 2026 between 22:15 and 23:46 Montevideo, during the Meta hackathon, for issue #164. Until now the parent's words on the glasses were typed by the run's script (`results/glasses-live`, `results/glasses-day`). Here they are spoken: recorded audio goes into the app's microphone path, the phone cuts it into utterances, Muse Spark Open hears them on Baseten, a gate keeps out what was not meant for the agent, and the answer is a card on the mock Meta Ray-Ban Display. What DAT allows and how it is built: `apps/glasses/SPEECH.md`.

Result of the recorded take: **11 of 11 lines did what they should**, 10 cards and 1 line correctly kept from the agent. Word accuracy in that take was 78.6 % only because Muse wrote one Spanish line down in English (below). Over the bigger offline set the ear got **97.0 % of words** (94.3 % Spanish, 99.5 % English) and the gate decided **94 of 96** lines right, and none of 4 clips without speech got through.

Clip: `~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-speech.mp4`, 4 min 16 s, 588 x 1280, with sound: the parent's clips at the moment the app fed them to the microphone, and the app's own spoken replies, laid on at their play times (the simulator records no audio). Not committed. `hud-speech-raw.mp4` next to it is the untouched screen recording. One take, real time, not edited. On screen: "LIVE", "Live: spoken words heard by Muse Spark Open, the family agent running on this Mac", "Mocked: the microphone (recorded TTS voices, not a person), the glasses and lens (Meta's mock). No Telegram, house dry.", and for each line "Spoken: ..." with the voice that read it and what Muse heard. The earlier takes are next to it as `hud-speech-take1.mp4` to `take3.mp4`.

`run.json` is that take: every line with what was played, heard, decided, the card and its times, the conversation, the Baby Buddy read backs and the app's log. `run-take1.json` to `run-take3.json` and `rehearsal1.json`, `rehearsal2.json` are the other runs. Screenshots: `01-changing-time.png`, `02-red-flag.png`, `03-car-seat-si.png`.

## What ran live

| Part | What ran | Where |
|---|---|---|
| The microphone path | `MockMicrophone` played each clip into `UtteranceCutter` in real time, 20 ms at a time. The cutter cut it into an utterance and the app posted it as a WAV to `/hear` with its end time | iOS 27.0 simulator, iPhone 18 Pro, its own simulator device (no other agent's runs on it) |
| The ear | Muse Spark Open, `meta-models/muse-spark-open-1026`, 3 calls at once per utterance, first transcript wins (`glasses_speech.race`) | Baseten |
| The gate | `glasses_speech.Gate`: start phrases, short answers only while the agent waits for them, the wake word "agente" or "agent" for the rest | this Mac |
| The agent | `parenting_agent.agent` with the glasses channel on port 8767, the changing table skill (MediaPipe on the glasses frames, SAM 3.1 confirm off) and the car seat coach, Muse as the brain, 15 brain calls | this Mac |
| SAM 3.1 | the car seat coach's `sam3_prompts_worker`, one process, under `/tmp/pa-gpu.lock`, killed at the end | this Mac |
| Baby log | Baby Buddy, child `test-baby`: entries 239 (dirty) and 240 (wet) written by the changing table and read back | the Vostro, through the SSH tunnel |
| Display | DAT's Display API (`MWDATDisplay` 1.0.1), drawn by Meta's `MockDisplayKit` | the simulator |
| Telegram, Home Assistant | off: their variables blanked for the run. House actions dry | none |

## The lines of the recorded take

Times are seconds from the end of speech in the clip to the moment the display accepted the card. "Ear" is the race of Muse calls, "agent" is from the words heard to the card (the brain, Baby Buddy, the skill).

| Said (voice) | Heard by Muse | Gate | Card | Ear | Agent | End of speech to card |
|---|---|---|---|---|---|---|
| "Changing time." (Samantha) | Changing time | start phrase | Cambiador · Mano en el bebé · armed by Muse | 4.25 s | 3.65 s | **8.47 s** |
| "Hola Theo, ¿quién es el bebé más lindo de la casa?" (Paulina) | Hola tío, ¿quién es el bebé más lindo de la casa? | not for the agent | none, no message, no brain call | | | |
| "Done, it was dirty." (Daniel) | Done. It was dirty. | finish, the watch was on | Anotado · Diaper at 23:41 · dirty | 4.87 s | 2.64 s | **8.10 s** |
| "Hora del cambio." (Mónica) | Hora del cambio | start phrase | Cambiador · Mano en el bebé | 3.67 s | 3.08 s | **7.35 s** |
| "Listo, solo pis." (Paulina) | Listo, solo pis, ¿viste? | finish | Anotado · Diaper at 23:42 · wet | 3.41 s | 2.68 s | **6.63 s** |
| "Agente, ¿cuándo comió por última vez?" (Paulina) | the same | wake word | Respuesta · Comió por última vez hoy a las 08:10, biberón de 90 ml. | 4.01 s | 7.23 s | **11.79 s** |
| "Agent, how many diapers has he had today?" (Samantha) | the same | wake word | Respuesta · Today he has had 20 diapers: 5 wet and 13 dirty. | 4.47 s | 7.06 s | **12.10 s** |
| "Agente, el bebé está azul y no respira." (Mónica) | **Agent the baby is blue and not breathing** | wake word | Llamá al 911 ya · Puede ser una emergencia (the safety gate's fixed line, sticky) | 4.16 s | 0.03 s | **4.79 s** |
| "Ya llamé." (Paulina) | ya llamé | ack, a red flag was up | the red flag card goes | 2.83 s | 0.01 s | **3.41 s** |
| "Agente, ayudame a instalar la silla del auto." (Paulina) | Agente, ayúdame a instalar la silla de la auto. | wake word | Silla del auto · ¿Silla atrás, mirando hacia atrás? (Muse started the coach, then SAM 3.1 loaded) | 3.77 s | 14.21 s | **18.55 s** |
| "Sí." (Mónica) | Sí (the first 2 of 3 calls answered nothing, the third heard it) | answer, the coach was asking | Silla del auto · Cinturón de cadera en las dos guías (step 2, SAM 3.1 on the car seat clip) | 4.24 s | 0.01 s | **4.83 s** |

Every line breaks down the same way: the cutter found the end of speech within 0.06 s of the clip's real end (ffmpeg's silence detector), then 0.6 s to be sure the parent stopped and to upload, then the ear (median 4.08 s here, 2.8 to 4.9 s), then the agent. Commands it answers itself (the red flag, "ya llamé", "sí" to the coach) reach the lens 3.4 to 4.8 s after the parent stops talking. Commands that go to the brain take 6.6 to 8.5 s, questions 12 s, and starting the car seat coach 18.6 s (Muse's call, then SAM 3.1 loads).

Word accuracy in this take: 44 of 56 words (78.6 %). 8 of the 12 errors are the red flag line written in English, the others "Theo" heard as "tío", "del" as "de la", and "¿viste?" added. The safety gate reads English too, so the red flag still fired.

## Every take

| Run | Lines right | Word accuracy | What went wrong |
|---|---|---|---|
| Rehearsal 1 | 4 of 11 | 92.7 % | The app was still speaking its answer when the next clip played, and the microphone is muted while the app speaks, so "Hola Theo..." and "Listo, solo pis" were never heard. With "listo" lost the watch stayed on and its hand alarm covered the next cards. "está azul y no respira bien" was heard as "está azulino respira bien" and **the red flag did not fire**. "Done, it was dirty" was cut to "Done" and logged dry |
| Rehearsal 2 | 11 of 11 | 98.2 % | Fixed: the run waits until the app stops speaking, the red flag line names the baby, a short answer keeps all its sentences |
| Take 1, recorded | 9 of 11 | 92.9 % | Heard right, but Muse (the brain) answered "Si estás listo, sigo por voz y cámara" instead of starting the car seat coach, so nothing asked for the "sí" and the gate kept it out |
| Take 2, recorded | 11 of 11 | 98.2 % | none. The banner said "Telegram captured", wrong for this run (Telegram was off), so it was fixed and taken again |
| Take 3, recorded | 9 of 11 | 95.8 % | The run played the car seat line while the agent's answer to "ya llamé" was about to be spoken: the microphone muted 0.2 s in and the line was lost. Muse heard "Sí." as "Sí, agente" (the wake word from its prompt) |
| **Take 4, recorded, the clip** | **11 of 11** | 78.6 % | The red flag line written in English (above) |

So the speech path heard every line it was given in 4 of 6 runs, and the misses were the app talking over the parent (twice, a run timing fault, fixed in the run by waiting for the agent's answer) and the brain not starting the coach once. That is 6 runs, not a rate.

## The bigger set, no app (`batch.json`)

24 lines (12 Spanish, 12 English: every command, 3 questions with the wake word, 2 lines to the baby or the other parent) in 2 macOS voices each, clean and with pink noise added 15 dB under the speech (approximate), 96 utterances, plus 4 clips with noise or silence and no speech. Each one through the same race and gate `/hear` uses, one utterance at a time, with the wait the line needs open (a "listo" while the watch is on). This checks the ear and the gate, not the cutter.

| | Ear: one call at a time, up to 3 attempts (the voice notes' way, `batch-sequential.json`) | Ear: 3 calls at once, glasses prompt (`batch.json`) |
|---|---|---|
| Word accuracy, all | 94.0 % (22 errors in 368 words) | **97.0 %** (11 in 368) |
| Spanish / English | 90.3 % / 97.4 % | 94.3 % / 99.5 % |
| Clean / noise | 98.4 % / 89.7 % | 95.7 % / 98.4 % |
| Lines heard as nothing | 5 | 3 ("No." and "Done." in noise, one line to the baby) |
| Gate right | 89 of 96 | **94 of 96** |
| No-speech clips let through | not run | **0 of 4** |
| Ear seconds, median (max) | 3.69 (10.75) | 3.54 (13.09) |

The race costs up to 3 Muse calls per utterance (6 when the first 3 hear nothing, 11 of 100 here). A first race run sent 4 utterances at once, 24 calls, and Baseten answered HTTP 429 to 22 of them. One utterance at a time, as on the glasses, had no 429.

What still fails in the set: "Agente" heard as "La gente" once (not a wake word, "la gente" is ordinary Spanish, see below), "No." and "Done." in noise heard as nothing.

## What is weak

- **The ear is slow for a command.** About 3.5 to 4 s of Muse before anything happens, on every utterance. "Listo" on a red flag clears it 3.4 s after the parent stops. On real glasses the DAT Speech route recognizes on the glasses and skips this (wired, not measured, it needs glasses).
- **Muse sometimes translates or adds words.** The red flag line came back in English in the recorded take, and "Sí." once as "Sí, agente". It sometimes answers instead of writing down: in a probe of 18 calls on three red flag phrasings, 4 answered with emergency advice, 3 of them after writing the words. Only the first line of an answer is taken now, so that advice never becomes the parent's words.
- **A mishearing can hide a red flag.** "está azul y no respira bien" heard as "está azulino respira bien" did not fire the safety gate in rehearsal 1, and 1 of 3 calls in a probe heard it so. The live run uses "el bebé está azul y no respira", whose words came back in 5 of 6 probe calls (the sixth heard nothing). Fixed after this run in #167 (`results/spoken-red-flags`): every ear call is read for a red flag with a tolerant reading, before the speech gate, so a misheard word or a missing wake word no longer hides one.
- **Half duplex.** The microphone is muted while the app speaks, so a parent who talks over the agent is not heard (rehearsal 1 and take 3). On real glasses with HFP the agent's voice comes back into the same microphone, so the mute stays.
- **The wake word.** "Agente" is sometimes split into "a gente" (accepted) or "la gente" (not accepted, it is ordinary Spanish).
- **All voices are macOS voices.** No person spoke. macOS has no rioplatense voice, so the Spanish is Mexican (Paulina) and Spain (Mónica) voices reading rioplatense lines.
- **Ambient talk still goes to Baseten.** The gate runs after the ear, so every utterance near the glasses is sent to Muse once (up to 6 calls) and then dropped. It is the configured brain call, nothing is kept, but the cutter on the phone is the only filter before it.

## Still mocked, and why

| Part | Why |
|---|---|
| The microphone input | No glasses here, and no DAT mock feeds audio: MockDeviceKit 1.0.1 times out a camera stream that asks for audio, and `MockSpeechKit` gives text or the Mac's own microphone (`apps/glasses/SPEECH.md`). The recorded clips go into the cutter the real microphones feed |
| The voices | macOS `say` voices. No family audio anywhere |
| HFP, the in-stream audio and DAT Speech routes | Built, not run: they need real glasses |
| The glasses, camera and lens | DAT MockDeviceKit and MockDisplayKit, as in `apps/glasses/HUD.md` |
| The camera picture | Our synthetic clips: a hand resting on the generated baby (`hover/fresh/table-a-hover-2.5cm.mp4`, the first 2.5 s forwards and backwards) for the changing table, then the car seat clip (`carseat/clips/test/test-02-correct.mp4`) |
| Changing table confirm | SAM 3.1's confirm was off in this run so only one SAM 3.1 process ran (the car seat's). MediaPipe watched the hands |

## Run it

```bash
python scripts/glasses_hud_speech.py --clips      # the clips (MockMic/*.wav) and the feed (MockFeed/hud-speech-feed.mp4), git ignored
python scripts/glasses_hud_speech.py --batch      # batch.json, about 7 min and 300 Muse calls
# build and install the app (apps/glasses/README.md), open the Baby Buddy tunnel, then:
python scripts/glasses_hud_speech.py --udid SIM --out-dir results/glasses-speech --name run \
  --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-speech.mp4
```

The run takes the GPU lock, starts the agent in the script's own process on port 8767, launches the app with `-hudSpeech YES`, plays each clip through a `mock_mic` event (Debug builds only), waits for the agent's card and its spoken answer, and frees the lock at the end. The MediaPipe model files must be in `.models/` (git ignored).
