# Voice notes: Muse hears, MMS-TTS speaks (issue #58)

All numbers below come from runs on Oct 28 2026, during the hackathon. All audio is synthetic: no family audio is in this folder.

## The test set

20 short voice notes in `notes/`, made by `scripts/voice_notes_make.py`: macOS `say` voices reading scripted lines, converted to OGG Opus like a Telegram voice note. 10 Spanish and 10 English. macOS has no rioplatense voice, so the Spanish lines use rioplatense wording ("le di la teta", "mamadera", "recién hizo caca", "pañal mojado y con caca") read by the Mexican (Paulina) and Spain (Mónica) voices. The English lines use Samantha and Daniel. They cover bottles with a named time, diapers (wet, dirty, both), falling asleep at a named time, waking, a breast feed with side and minutes, a question about today's bottles and a correction of the last bottle. `notes/notes.json` lists every line.

## The run

`scripts/voice_notes_run.py` sends each note through `FamiliesBot.poll_once_items`, the families bot's real voice path. Only Telegram is faked: the file id is the path of the OGG file, and sends are recorded. Each note is converted to WAV with ffmpeg, heard by Muse Spark Open (`meta-models/muse-spark-open-1026`, audio input), handled by the families service with Muse as the brain, and the answer is spoken with MMS-TTS and "sent" as an OGG Opus voice note. Two fictional families, one per language, each note at its own simulated time on Oct 29. A note scores when the log itself holds the right entry with the right values, or, for the question, when the answer has the right total.

| | Run 1 (`run-1.json`) | Run 2 (`run.json`, `run.md`) |
|---|---|---|
| Notes logged right | **20 of 20** | **20 of 20** |
| Spanish / English | 10 / 10 | 10 / 10 |
| Answers sent as a voice note | 20 of 20 | 20 of 20 |
| Hearing, median seconds (ffmpeg plus Muse) | 4.31 | 4.13 |
| Whole note to answer, median seconds | 8.54 | 8.71 |
| Muse spend for 20 notes (hearing plus brain) | $0.22 | $0.20 |

Target was at least 18 of 20. Both runs on the final code got 20 of 20.

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
| Mac (Apple silicon, CPU, 2 threads), run 2 | median 0.40, max 0.66 | 22 |
| Mac, run 1 | median 0.35, max 0.73 | 24 |
| Vostro (Intel i5-6200U, 2 CPUs for the container), the voice image | 6.48, 6.67, 9.62, 10.05, 10.38, 11.45, median 9.84 | 6 |

The Vostro is about 25 times slower than the Mac, so there the text answer goes out first and the voice note follows about 10 s per sentence later, in the background. Only the first 3 sentences are spoken. Nearly all the time is in the HiFi-GAN decoder's convolutions (86 percent in `mkldnn_convolution` in a profile). Turning oneDNN off made it slower (13.7 s). A faster runtime for the Vostro is the next step.

Samples, OGG Opus mono 48 kHz, as Telegram receives them:

| File | What it says | Length |
|---|---|---|
| `reply-es01.ogg` | Anotado: mamadera de 90 ml de Tomi a las 3. | 4.5 s |
| `reply-es08.ogg` | Hoy Tomi tomó 210 ml en mamadera, en 2 tomas. La última fue de 120 ml a las 7:30. | 11.7 s |
| `reply-en06.ogg` | Logged breastfeed on the right side for Mia, 12 minutes at 5:50. | 5.9 s |

Can the voice be understood? `scripts/voice_roundtrip.py` speaks each of the 20 answers of run 2 with MMS-TTS and lets Muse hear it back. The numbers came back in **18 of 20** (`roundtrip.json`, 9 Spanish, 9 English, "4 y media" counted as 4:30). The Spanish voice is clear apart from the baby's name ("Tomi" heard as "Tommy"). The English voice loses words more often: "Logged for Mia" came back as "Lod for Maya", "dirty diaper" once as "Debra". Muse is a machine listener, so this says whether the facts survive the voice, not how it sounds to a person.

## What is not proven here

- No real voice note from a parent's phone yet. These are synthetic `say` voices, clean, with no baby crying behind them.
- No rioplatense accent in the audio, only rioplatense wording.
- The Vostro runs below were the full handler with a recorded file, see the PR. A real voice note sent from Telegram is the next check.
