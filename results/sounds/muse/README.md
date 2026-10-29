# Muse Spark Open's ears on the house sound set (issue #14), Oct 29 2026

Run: `python scripts/sounds_muse_eval.py`, Oct 29 2026 around 01:05 Montevideo, during the event, in the request shape fixed that night (`results/audio-truth/README.md`). Raw rows in `run.json`.

## Result in one line

Muse Spark Open hears speech but not house sounds well enough to use. In the cry path's own request shape it wrote down a spoken random number 3 of 3 times, failed the beep canary 3 of 3 times, and got 11 of 46 house sound labels right against 41 for PANNs. So the cry path stays PANNs plus the baby log, and the Muse sound guess stays off behind the canary.

## Numbers

46 licensed clips from the meta-hackathon-2026 hearing set (4 cries, 10 coughs, 8 dogs, 9 doorbells, 7 splashes, 8 negatives), first 5 s of each, through the camera's 8 kHz A-law channel, decoded in memory.

| Method | What it got right | Notes |
|---|---|---|
| Speech control, a random 5 digit number read by `say` | **3 of 3** | Proves the request shape and the audio path work |
| Beep canary, 3 synthetic beeps | **0 of 3** | heard_sound false every time |
| PANNs CNN14, local, the current reflex | 41 of 46 labels right, 4 of 4 cries heard as cries | A cough or a negative counts as right when PANNs stays quiet. Misses: 2 splashes, 1 dog and 1 doorbell not heard in the first 5 s, 1 negative read as a splash |
| Muse Spark Open | 11 of 46 labels right, 3 of 4 cries called a cry | But it called 14 of the 42 clips that are not cries a cry too, and 18 clips silence. It said it heard sound on 10 clips and was right on 8 of those (5 dogs, 2 cries, 1 doorbell). It gave no cry a reason: 3 "cannot tell", 1 "not a cry" |

`usage.prompt_tokens_details.audio_tokens` read 0 on every call, as it does when Muse writes down speech word for word, so that field is not a sign of hearing. Prompt tokens went from 252 to 310 with the clip.

Muse cost $0.119 for 52 calls (46 clips and 6 controls), median 5.5 s and at most 8.0 s per call. PANNs is local and free.

On cry reasons: the current method reads the baby log, not the sound (`docs/house-sounds.md`, 166 of 184 right on the simulated week, earlier during the event). There is no labeled cry-reason audio in the hearing set, and Muse gave no reason for any cry, so no reason accuracy is reported.

## Before the fix (first run, Oct 29 about 01:00)

The first run used a system message with "If no audio reaches you, set heard_sound false" and an `audio_url` part first. It got 10 of 46, the canary failed in WAV, MP3, FLAC and OGG, and the README then said Muse does not hear audio on this endpoint. That was wrong for speech: the same wording makes Muse say it heard nothing even for speech it otherwise writes down. `results/audio-truth/README.md` has the calls. For house sounds the conclusion holds.

## What the code does now

- `parenting_agent/cry_muse.py`: on a cry PANNs detected, the first 5 s of that cry only, as a WAV made in memory, in one user message, the instruction first, then the clip, with a strict schema (heard_sound, sound, reason_guess in hungry, tired, diaper, comfort or cannot_tell, confidence). The answer is framed as a guess from the sound alone, never medical, and adds one sentence to the log-based reason without changing its ranking. A reason counts only when Muse says it heard a baby crying.
- Before any cry clip is sent, a synthetic beep clip (never house audio) must be counted right. It is re-checked every 6 hours. It fails today, so no cry audio leaves the house.
- Off by default (`house_sounds.muse_audio.enabled`).

## What would change the result

A Muse audio path that hears sounds that are not speech. The canary will say so first. Measuring cry reasons also needs labeled cry audio, for example the Donate-a-cry corpus (ODbL), kept outside the repo.
