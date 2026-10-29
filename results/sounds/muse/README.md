# Muse Spark Open's ears on the house sound set (issue #14), Oct 29 2026

Run: `python scripts/sounds_muse_eval.py`, Oct 29 2026 around 01:00 Montevideo, during the event. Raw rows in `run.json`.

## Result in one line

Muse Spark Open on Baseten (`meta-models/muse-spark-open-1026`) does not hear audio on this endpoint today. Every request was accepted and answered, but 0 audio tokens were counted and Muse said it heard nothing. So Muse cannot guess a cry reason from the sound yet, and the cry path stays PANNs plus the baby log. The code to send the cry clip is built, tested offline and switched off behind a canary that fails today.

## Numbers

46 licensed clips from the meta-hackathon-2026 hearing set (4 cries, 10 coughs, 8 dogs, 9 doorbells, 7 splashes, 8 negatives), first 5 s of each, through the camera's 8 kHz A-law channel, decoded in memory.

| Method | What it got right | Notes |
|---|---|---|
| PANNs CNN14, local, the current reflex | 41 of 46 labels right, 4 of 4 cries heard as cries | A cough or a negative counts as right when PANNs stays quiet. Misses: 2 splashes, 1 dog and 1 doorbell not heard in the first 5 s, and 1 negative read as a splash |
| Muse Spark Open, audio_url with a WAV data URL | 10 of 46 sound labels right, 1 of 4 cries | Said it heard sound on 1 of 46 clips, a dog it named right with 0 audio tokens, so a guess. 30 of 46 answered "silence" |
| Canary, 3 synthetic beeps in WAV, MP3, FLAC and OGG | 0 of 4 formats heard | heard_sound false, beeps 0 or -1, 0 audio tokens |

One open question: with the same text prompt, the input token count varied from 244 to 302 across clips, so something from the audio part reaches the token count, but Muse neither hears it nor reports audio tokens. Baseten support would know why.

Muse cost $0.094 for 50 calls (46 clips and 4 canary formats), median 5.0 s and at most 6.7 s per call. PANNs is local and free.

On cry reasons: the current method reads the baby log, not the sound (`docs/house-sounds.md`, 166 of 184 right on the simulated week, earlier during the event). There is no labeled cry-reason audio in the hearing set, and with no audio reaching Muse a reason accuracy would only measure guessing, so none is reported.

## What was tried to make Muse hear (Oct 28 and 29, about $0.05 in probes)

| Try | Outcome |
|---|---|
| `audio_url` with a base64 WAV data URL, the shape in Baseten's audio guide (docs.baseten.co/inference/model-apis/audio, read Oct 28) | Accepted, 0 audio tokens, "no audio" |
| `audio_url` with Baseten's own public sample URL (jfk.wav on Hugging Face) | Accepted, 0 audio tokens, "no audio". Once, with no "say no audio" escape in the prompt, Muse wrote the famous JFK line: a guess from the file name pattern, not hearing, since the same request with an escape said "no audio" |
| `input_audio` with base64 WAV and MP3 | Accepted, 0 audio tokens, "no audio" |
| `input_audio` with a data URL inside | HTTP 400, "Only base64 data is allowed" |
| `file` part | HTTP 400 |
| `video_url` with an MP4 whose sound track holds speech | Muse described the black frames and said it cannot listen to the sound track |
| Audio before or after the text, reasoning effort none or low | No change |
| The slug in Baseten's audio guide, `meta-models/muse-spark-open` | HTTP 403 for our key, which is scoped to `meta-models/muse-spark-open-1026` |

## What the code does now

- `parenting_agent/cry_muse.py`: on a cry PANNs detected, the first 5 s of that cry only, as a WAV made in memory, with a strict schema (heard_sound, sound, reason_guess in hungry, tired, diaper, comfort or cannot_tell, confidence). The answer is framed as a guess from the sound alone, never medical, and adds one sentence to the log-based reason without changing its ranking. A reason counts only when Muse says it heard a baby crying.
- Before any cry clip is sent, a synthetic beep clip (never house audio) must be counted right. It is re-checked every 6 hours. While it fails, no cry audio leaves the house.
- Off by default (`house_sounds.muse_audio.enabled`). The privacy text in `README.md`, `docs/architecture.md` and `docs/house-sounds.md` names this one opt-in flow.

## What would change the result

Baseten enabling audio on the `-1026` deployment, or giving our key the `meta-models/muse-spark-open` slug. Then rerun `scripts/sounds_muse_eval.py`: the canary will say so first. Measuring cry reasons also needs labeled cry audio, for example the Donate-a-cry corpus (ODbL), kept outside the repo.
