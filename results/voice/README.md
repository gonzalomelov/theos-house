# Voice notes: Muse hears, MMS-TTS speaks (issue #58)

All numbers below come from runs on Oct 28 and 29 2026, during the hackathon. All audio is synthetic: no family audio is in this folder.

**Does Muse really hear? Speech yes, other sounds no.** Checked on Oct 29 with clips Muse could not guess, and the harness checked for leaks: `results/audio-truth/README.md`. The ear prompt's example used to be "(90 ml, a las 3)", which matched note es01 word for word. It is now "(35 ml, a las 11)", matching no note, and run 3 below uses it.

## The test set

20 short voice notes in `notes/`, made by `scripts/voice_notes_make.py`: macOS `say` voices reading scripted lines, converted to OGG Opus like a Telegram voice note. 10 Spanish and 10 English. macOS has no rioplatense voice, so the Spanish lines use rioplatense wording ("le di la teta", "mamadera", "recién hizo caca", "pañal mojado y con caca") read by the Mexican (Paulina) and Spain (Mónica) voices. The English lines use Samantha and Daniel. They cover bottles with a named time, diapers (wet, dirty, both), falling asleep at a named time, waking, a breast feed with side and minutes, a question about today's bottles and a correction of the last bottle. `notes/notes.json` lists every line.

## The run

`scripts/voice_notes_run.py` sends each note through `FamiliesBot.poll_once_items`, the families bot's real voice path. Only Telegram is faked: the file id is the path of the OGG file, and sends are recorded. Each note is converted to WAV with ffmpeg, heard by Muse Spark Open (`meta-models/muse-spark-open-1026`, audio input), handled by the families service with Muse as the brain, and the answer is spoken with MMS-TTS and "sent" as an OGG Opus voice note. Two fictional families, one per language, each note at its own simulated time on Oct 29. A note scores when the log itself holds the right entry with the right values, or, for the question, when the answer has the right total.

| | Run 1, Oct 28 (`run-oct28-1.json`) | Run 2, Oct 28 (`run-oct28-2.json`, `run-oct28-2.md`) | Run 3, Oct 29, new ear prompt (`run.json`, `run.md`) |
|---|---|---|---|
| Notes logged right | **20 of 20** | **20 of 20** | **20 of 20** |
| Spanish / English | 10 / 10 | 10 / 10 | 10 / 10 |
| Answers sent as a voice note | 20 of 20 | 20 of 20 | 20 of 20 |
| Ear calls (a refusal is asked again) | not logged | not logged | 21, one retry on en09 |
| Prompt tokens per ear call | not logged | not logged | 243 to 284, audio_tokens 0 on every call |
| Hearing, median seconds (ffmpeg plus Muse) | 4.31 | 4.13 | 3.94 |
| Whole note to answer, median seconds | 8.54 | 8.71 | 7.55 |
| Muse spend for 20 notes (hearing plus brain) | $0.22 | $0.20 | $0.20 |

Target was at least 18 of 20. All three runs on the final code got 20 of 20. Run 3 kept every ear call's prompt tokens and audio tokens in `run.json` (`ear_calls`). `audio_tokens` reads 0 even when Muse writes down every word, so it is not a sign of hearing.

Before the final code, the same set scored 14, 18, 16, 17, 20 and 16 of 20 while it was being fixed. What failed and what fixed it:

- Muse sometimes answered "No tengo acceso al audio" instead of the words (2 of 20 notes in the first run). The ear now asks again, up to 3 times, and never takes such an answer as the parent's words.
- The families prompt gave the brain the real date, not the family clock, and the brain put "a las 4 y media" on the day before. The prompt now uses the family's clock, and a time the parent names is placed at the latest such moment, unless the parent named a day.
- The brain once logged a bottle at the time the message came, not at the "a las 3" the parent said. The time the parent names now wins.
- The brain split "she pooped, dirty diaper" into a wet and a dirty entry, and once logged an earlier bottle and diaper again inside a sleep note. One diaper note is now one entry, without a wet flag the parent did not say, and a note logs only the kinds it talks about.
- The scorer missed "210ml" written without a space. Fixed in the scorer.

These guards are in `parenting_agent/agent/rules.py` and `loop.py`, so typed notes get them too.

## The voice

MMS-TTS (`facebook/mms-tts-spa`, `facebook/mms-tts-eng`, CC-BY-NC 4.0, non-commercial), one sentence at a time, numbers written as words first.

| Where | Seconds per sentence | Sentences |
|---|---|---|
| Mac (Apple silicon, CPU, 2 threads), run 3 | median 0.43, max 1.33 | 21 |
| Mac (Apple silicon, CPU, 2 threads), run 2 | median 0.40, max 0.66 | 22 |
| Mac, run 1 | median 0.35, max 0.73 | 24 |
| Vostro (Intel i5-6200U, 2 CPUs for the container), the voice image | 6.48, 6.67, 9.62, 10.05, 10.38, 11.45, median 9.84 | 6 |

The Vostro was about 25 times slower than the Mac. Why, and what was done about it, is in "Speed on the Vostro" below. Since Oct 29 the Vostro runs the decoder on ONNX Runtime in int8, about 2 times faster. The text answer still goes out first and the voice note follows in the background. Only the first 3 sentences are spoken.

Samples from run 3, OGG Opus mono 48 kHz, as Telegram receives them. Only the first 3 sentences are spoken:

| File | What it says | Length |
|---|---|---|
| `reply-es01.ogg` | Anotado, 90 ml de mamadera a las 3 para Tomi. | 4.6 s |
| `reply-es08.ogg` | Hoy Tomi tomó 210 ml de mamadera en 2 tomas, 90 ml a las 03:00 y 120 ml a las 07:30. Además tomó teta izquierda 10 min a las 06:40. | 16.4 s |
| `reply-en06.ogg` | Logged breastfeeding on the right for 12 minutes for Mia. | 4.4 s |

Can the voice be understood? `scripts/voice_roundtrip.py` speaks each of the 20 answers of run 2 (Oct 28) with MMS-TTS and lets Muse hear it back. The numbers came back in **18 of 20** (`roundtrip.json`, 9 Spanish, 9 English, "4 y media" counted as 4:30). The Spanish voice is clear apart from the baby's name ("Tomi" heard as "Tommy"). The English voice loses words more often: "Logged for Mia" came back as "Lod for Maya", "dirty diaper" once as "Debra". Muse is a machine listener, so this says whether the facts survive the voice, not how it sounds to a person.

## On the Vostro (Oct 29, 00:04 to 00:10)

Deployed: `pa-voice-family` and `pa-voice-families` (`sh deploy/voice.sh deploy`, commit ad05f04), then the family agent and the families bot (commit 1cd6b36). The voice check passed in both containers: both languages spoken and converted, weights offline, no proxy, `1.1.1.1:443`, `huggingface.co:443` and the host unreachable. The agent and families wall checks passed after the deploy.

The full handler, with a recorded note instead of a Telegram download (`deploy/voice/handler_check.py`):

| Where | Note | Heard by Muse | Text answer | Voice answer |
|---|---|---|---|---|
| `parenting-agent`, real Telegram messenger, sent to Gonza's chat | es08, "¿Cuánto tomó de mamadera hoy?" | "¿Cuánto tomó de mamadera hoy?" in 4.5 s | sent after 9.1 s (baby_summary on Baby Buddy, 2 Muse brain calls) | sent after 54.9 s, 45.8 s to speak 3 sentences |
| `pa-families`, temporary family, recording messenger, nothing sent | es01, "Le di noventa mililitros de mamadera a las tres." | "Le di 90 mililitros de mamadera a las 3" | "Anotado, 90 ml en mamadera para Tomi." | 16 KB OGG Opus, 21.1 s for the whole note |

The voice answer on the Vostro is slow: about 10 s a sentence on its CPU, more when the answer is long. The text answer is not held up by it.

## Speed on the Vostro (Oct 29, 00:10 to 02:30)

Target: the voice note arrives within 5 s after the text answer, for a typical two sentence reply, on the Vostro, over at least 10 replies. **Not met.** The voice note now comes about 2 times sooner, but still 6 to 15 s after the text.

### Why the Vostro is so slow

Each candidate cause was measured on the Vostro, in a throwaway container with the same limits as the service (2 CPUs, no network):

| Candidate | What the run showed |
|---|---|
| Model reload per request | No. The service loads both voices at start (`--preload`), and a warm in-process call is just as slow (10.2 to 11.9 s for one 4.5 s sentence). |
| First call warmup | No. The 2nd and 3rd calls are as slow as the 1st. |
| Thread count | 2 threads is best: 1 thread 14.2 to 17.5 s, 2 threads 10.2 to 11.9 s. 4 threads on 4 CPUs (2 cores with hyperthreading) was about 1.7 times slower (int8 image, busy host). |
| torch build | Fine: torch 2.15.0+cpu with MKL and oneDNN 3.13, AVX2 detected. oneDNN off made 2 of 3 decoder-sized convolutions 2.3 and 3.1 times slower. |
| Denormal floats | Small: flushing them took 1 thread from about 15.7 s to 12.9 s. Now on in torch and in ONNX Runtime. |
| Where the time goes | The HiFi-GAN decoder: 10.9 of 11.4 s (text encoder 0.13, duration 0.06, flow 0.27). The whole model is 182 GFLOP for 4.6 s of audio. |
| OGG encoding | 2.4 to 3.4 s for a 9 s reply at ffmpeg's default Opus compression level 10, 0.65 s at level 5. Now level 5. |
| **CPU clock** | **The main cause.** Under load the CPU runs at about 760 MHz, not its 2.3 to 2.8 GHz. `turbostat` shows 748 to 763 MHz busy at 2.7 W, 44 °C, so it is not heat. MSR 0x19C has PROCHOT active and 0x64F names PROCHOT as the limit reason. BD PROCHOT (MSR 0x1FC bit 0) is on. The battery reads 0 percent, "Not charging", and Dell firmware holds the CPU at its lowest clock when it sees a dead battery. A plain matrix multiply reaches only 21 GFLOPS on one thread. |

So the Vostro does the 182 GFLOP with 2 cores at about 760 MHz, against Apple silicon with its matrix units. About 3.5 times of the 25 is the clock.

### What changed

- The HiFi-GAN decoder runs on ONNX Runtime 1.31.1 in int8 (`parenting_agent/voice/onnx_decoder.py`). It is exported at image build from the same official, pinned `facebook/mms-tts-*` weights, quantized with per channel int8 weights, calibrated on 8 reply-like sentences per language that are not in the test set. The text encoder, duration predictor and flow stay in torch. Still MMS-TTS, still Meta's model, still CC-BY-NC 4.0 (non-commercial). Float32 ONNX alone was only about 20 percent faster than torch (8 s against 10 s for one sentence), int8 about 2 times (5.3 to 5.8 s).
- Opus at compression level 5.
- Denormals flushed.
- The voice check fails if the int8 decoder is not in use. ONNX Runtime telemetry is off (the container has no network anyway).

### Before and after, the same 10 replies

10 two sentence replies (`speed/replies10.json`): es08 and en08 from run 2, and 8 more made of two one-sentence replies from run 2 joined, 5 Spanish and 5 English. Each goes through `POST /speak`, the path the agent uses, timed from request to OGG bytes. Before is the old image (ad05f04) in a temporary container with the same limits. After is the deployed `pa-voice-families` (845463d). They ran one after the other for each reply, so both saw the same load on the Vostro (load average 2.5 to 3.7 from other services) (`speed/ab.jsonl`, `speed/ab.py`, `speed/one.py`).

| | Before (torch) | After (ONNX int8) |
|---|---|---|
| Median, 2 sentence reply, text to OGG | **23.8 s** | **11.7 s** |
| Range | 18.7 to 41.5 s | 8.0 to 17.4 s |
| Encoding and the rest, median | 1.29 s | 0.88 s |

An earlier before run on the deployed service, at 00:30, had a median of 27.0 s (`speed/before-service.jsonl`).

The full handler on the deployed families bot, with a recorded note, temporary family, recording messenger, nothing sent (`deploy/voice/handler_check.py`, which now prints when each answer went out):

| Note | Text answer | Voice answer | Voice after text |
|---|---|---|---|
| es01, a bottle | 14.9 s | 23.3 s | 8.5 s |
| es08, a question, 2 sentence answer | 6.7 s | 21.3 s | 14.6 s |
| en06, a breast feed, 1 sentence answer | 8.0 s | 14.3 s | 6.3 s |

Two earlier runs of the same check, before the extra timing: es01 13.6 s and es08 21.7 s for the whole note (es01 was 21.1 s on Oct 29 at 00:10).

### Does int8 still sound right?

The meter is the same Muse round trip as above (`scripts/voice_roundtrip.py --wavs`): the 20 replies of run 2, spoken on the Vostro, heard back by Muse.

| Voice | Numbers back |
|---|---|
| torch float32 on the Mac, Oct 28 (`roundtrip.json`) | 18 of 20 |
| torch float32 on the Vostro (`roundtrip-fp32-vostro.json`) | 19 of 20 |
| ONNX int8 on the Vostro, run 1 (`roundtrip-int8.json`) | 17 of 20 |
| ONNX int8 on the Vostro, run 2, the same WAVs (`roundtrip-int8-2.json`) | 19 of 20 |

The same int8 WAVs scored 17 and then 19, so the listener moves by 2 between runs, and int8 is inside that noise. The misses are the same kind as before: "3:45" as "3 y 40 y 5", "3:10" lost once. Against float32 the int8 waveform has a signal to noise ratio of 17.5 dB median (Spanish about 20 dB, English 9 to 18 dB, `speed/int8-vs-torch.jsonl`). The WAVs were checked by Muse, not by a person: nobody listened to them tonight.

### What would meet the target

- **Give the CPU its clock back.** At 760 MHz the int8 voice needs about 5.5 s for one 4.5 s sentence. At about 2.7 GHz it would need about 1.6 s, so a two sentence reply would be about 3 to 4 s with encoding: inside the target. This is an estimate from the clock ratio, not measured. Two ways: a working battery (or the right Dell adapter) so the firmware stops holding PROCHOT, or clearing BD PROCHOT at boot (`wrmsr 0x1FC` with bit 0 off, the ThrottleStop trick). Both change the home server's power behaviour, so they are Gonza's call. Nothing on the host was changed tonight.
- Sending the first sentence as its own voice note as soon as it is ready would bring the first audio about 5 s after the text, but splits the answer into two notes. Not done.

## What is not proven here

- No real voice note from a parent's phone yet. These are synthetic `say` voices, clean, with no baby crying behind them.
- No rioplatense accent in the audio, only rioplatense wording.
- On the Vostro the full handler ran with a recorded file, not a Telegram download. A real voice note sent from a phone is the next check.
- The voice note does not yet arrive within 5 s of the text on the Vostro (see "Speed on the Vostro").
