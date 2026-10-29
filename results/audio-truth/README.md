# Does Muse Spark Open hear audio? Real calls, Oct 29 2026

Two PRs from Oct 28 and 29 said opposite things. PR #70 (the voice ear) said Muse heard 20 of 20 voice notes. PR #74 (the cry ears) said Muse got 0 audio tokens on every call and heard nothing. This folder settles it with calls made on Oct 29 between 00:40 and 01:20 Montevideo, on `meta-models/muse-spark-open-1026` at `inference.baseten.co`.

## Verdict

**Speech yes, other sounds no.** Muse writes down speech it cannot guess, in Spanish and English. It does not hear beeps, and on house sounds it mostly says it hears nothing or guesses. Both PRs were half right. The 20 of 20 is real. The "0 audio tokens" is a usage field that always reads 0, even when Muse writes down every word, so it proves nothing. The cry eval failed for speech too only because of how the request was worded, and that is fixed.

## The clips

Made with macOS `say`, converted to 16 kHz mono WAV with ffmpeg. The WAV files carry no text metadata (checked with `strings`, only the `Lavf` encoder tag). Nothing in the requests names the content.

| Clip | Voice | What it says | Length |
|---|---|---|---|
| en1 | Samantha | "The code word is blorvik. Seven three nine two four." | 3.1 s |
| es1 | Paulina | "La palabra secreta es trumbelo. Ocho cinco uno seis dos." | 4.0 s |
| en2 | Samantha | "Forty one zebras ate sixty eight purple quinces on Thursday." | 3.5 s |
| beep5 | `muse_senses.beeps(5)` | 5 beeps of 1 kHz | 3.0 s |

## The raw table (`matrix.json`, `control.json`)

Each clip sent 3 times in each shape. `ear` is the exact body `parenting_agent/voice/ear.py` sent (one user message, the ear prompt, then an `input_audio` WAV part). `cry` is the exact body `parenting_agent/cry_muse.py` sent through `MuseSenses.ask` before this fix (a system message with "If no audio reaches you, set heard_sound false", an `audio_url` data URL first, then the question, strict JSON schema). `cry_ia` is the same as `cry` with an `input_audio` part instead. For the beep clip the text asked for the number of beeps.

| Clip | Shape | Prompt tokens | audio_tokens | Answers (3 tries) | Content really heard |
|---|---|---|---|---|---|
| en1 | ear | 269 | 0 | "The code word is Blorvex, 73924", "Blorvic. 7 3 9 2 4", "Blorvic. 73924" | **3 of 3**, digits exact, made-up word close |
| en1 | cry | 218 | 0 | heard_sound false, 3 times | 0 of 3 |
| en1 | cry_ia | 218 | 0 | heard_sound false, 3 times | 0 of 3 |
| es1 | ear | 279 | 0 | "La palabra secreta es trunbelo, 85162", "trumbelo, 85162", "trunvelo. 85162" | **3 of 3**, digits exact |
| es1 | cry | 228 | 0 | heard_sound false, 3 times | 0 of 3 |
| es1 | cry_ia | 228 | 0 | heard_sound false, 3 times | 0 of 3 |
| en2 | ear | 273 | 0 | "41.00ibras 8.68 Purple quinces on Thursday", "41 zebras 868 purple quinces on Thursday.", "41 zebras 868 purple quinses on Thursday" | **3 of 3** heard, "41" right 2 of 3, "68" heard as "868" 3 of 3 |
| en2 | cry | 222 | 0 | heard_sound false, 3 times | 0 of 3 |
| en2 | cry_ia | 222 | 0 | heard_sound false, 3 times | 0 of 3 |
| beep5 | ear | 202 | 0 | "I don't have the ability to access or play attached audio files", 3 times | 0 of 3 |
| beep5 | cry | 215 | 0 | heard_sound false, beeps -1, -1, 0 | 0 of 3 |
| beep5 | cry_ia | 215 | 0 | heard_sound false, beeps 0, 1, 0 | 0 of 3 |
| en1, es1 | ear prompt, no audio part | 227 | 0 | empty answer | control: nothing to hear |

Muse never reports audio tokens. It reported `audio_tokens: 0` on all 39 calls, including the 9 where it wrote down the speech.

## The audio does reach the model (`ablate.json`)

Same ear prompt, different clips. The prompt token count grows with the clip's length, not its content, at about 13 tokens a second:

| Audio part | Length | Prompt tokens | Over no audio |
|---|---|---|---|
| none | 0 s | 227 | 0 |
| 5 beeps | 3.0 s | 267 | +40 |
| silence | 3.0 s | 267 | +40 |
| en1 | 3.1 s | 269 | +42 |
| en1 then 7 s of silence | 10.1 s | 356 | +129 |
| "nine apples" 10 times | 10.7 s | 364 | +137 |

So the audio is encoded every time. Muse can read the words in it, not the other sounds. Its reasoning shows how it sees the clip: "The system says Code word is Blorvic 73924 ... There's no audio actually" (`ablate2.json`). The words arrive, and Muse does not believe it is listening.

## Why the cry shape heard nothing (`ablate.json`, `ablate2.json`, `shape3.json`)

On en1 or es1, one change at a time:

| Request | Answer |
|---|---|
| Ear prompt, then audio (the ear) | Transcribed |
| Ear prompt, `audio_url` data URL instead of `input_audio` | Transcribed 1 of 2, the other empty |
| Audio part before the ear prompt | Empty answer |
| Ear prompt plus the cry system message ("If no audio reaches you, set heard_sound false") | Empty answer, reasoning "There's no audio actually" |
| "Write down exactly the words spoken in the attached audio clip." | "I don't have the ability to access or play attached audio files" |
| The cry shape without its system message, or without its schema | heard_sound false, "No audio was received" |
| "Transcribe this audio." | Transcribed |
| "This is a voice note from a parent. Write down exactly what the parent said", then audio | Transcribed 2 of 2 |
| Same, with a strict JSON schema `{"words": ...}` | Transcribed 2 of 2 |

The format was never the problem: WAV works as `input_audio` and as `audio_url`. What breaks it is wording that tells Muse an audio clip is "attached" and gives it a way out ("if no audio reaches you"), and a system message. Muse's habit is to say a text model cannot hear, and that wording lets it.

## Other sounds (`nonspeech.json`, and the cry eval rerun)

Six house clips from the hearing set in the working shape, asked "which one is the main sound: baby crying, dog barking, doorbell, coughing, water splashing, speech, or other?": 5 of 6 answers were "I don't have the ability to hear audio", and cry-02 got "baby crying", which the question's nursery framing makes the easy guess.

The full cry eval was rerun in the fixed shape (`results/sounds/muse/README.md`): a spoken random number came back right 3 of 3 in that shape, the beep canary 0 of 3, and Muse labelled 11 of 46 house clips right against 41 for PANNs, with 14 non-cries called a cry.

## Could the 20 of 20 voice notes have leaked the answer?

Read `scripts/voice_notes_run.py`, `parenting_agent/families/bot.py`, `parenting_agent/voice/client.py` and `ear.py`:

- The note goes in as an `Incoming` with empty text and no caption. Its file id is the OGG path, read from disk by the fake Telegram. The path never reaches Muse.
- The ear sends only its fixed prompt and the WAV. The scripted line (`notes.json`) and the expected values (`CHECKS`) are used only to score after the run.
- The brain gets the words the ear heard, not the script.
- The OGG notes carry no text tags (`ffprobe`: only `encoder`), and the WAV made from them has none.
- One weak spot, found by a round 2 judge: the ear prompt's example "(90 ml, a las 3)" matched note es01 word for word. It is now "(35 ml, a las 11)", which matches no note, and the 20 notes were rerun.
- The heard text has real mishearings that a leak would not make: "Change the wet diaper" for "Changed a wet diaper", "Sorry" dropped from en09 in an earlier run.

**Rerun on Oct 29, 01:10, new ear prompt: 20 of 20 again** (10 Spanish, 10 English), 21 ear calls (one refusal retried on en09), prompt tokens 243 to 284 per call, audio_tokens 0 on every call, $0.20 in all. Per call tokens are in `results/voice/run.json`.

## What changed

- `parenting_agent/muse_senses.py`: an audio question is one user message, the instruction first, then an `input_audio` WAV part. No system message for audio, no "no audio" way out in any prompt. Images are unchanged.
- `parenting_agent/cry_muse.py`: prompts reworded the same way. The beep canary stays the gate for cry audio, since a cry is not speech and Muse does not count beeps.
- `parenting_agent/voice/ear.py`: example values that match no test note, and every call's prompt tokens and audio tokens kept in `ear.calls`.
- `scripts/sounds_muse_eval.py`: a spoken random number as a positive control next to the beep canary.
- The probe scripts are in `scripts/` here. They were run from the folder that held the clips.

## Cost

About 70 probe calls (about $0.10 at $1.25 in and $4.25 out per million tokens), the cry eval rerun $0.119, the voice notes rerun $0.20. About $0.42 in all, my sum from the token counts, not a Baseten bill.

## Not settled

- Whether Baseten's deployment turns speech into text before the model, or the model's own audio encoder only learned speech. The token count grows with length for silence and beeps too, so the audio is encoded either way. Baseten support would know.
- Real voice notes from a phone, a rioplatense accent, and a crying baby behind the voice are still untested.
