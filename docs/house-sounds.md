# House sounds, why is he crying, and white noise (issues #14 and #32)

Built during the Meta hackathon, Oct 28 2026. The living room camera's microphone becomes labels the agent acts on. A cry gets a likely reason from the baby log. White noise is one of the agent's hands, simulated until the DIY machine exists.

## What it does

| Sound | What the agent does |
|---|---|
| Doorbell during a skill (hands on the baby) | A `notify` the router sends to the ear: "Doorbell at the front door. Your hands stay on the baby, I can ask the visitor to wait." An observation lets the brain offer to answer the visitor, which waits for the parent's yes |
| Doorbell, hands free | A `notify` the router sends where the parent is |
| Cry | A `cry_reason` event with the ranked reasons and the evidence, then a `notify` with the top reason |
| Short cry at night (30 s or less) | White noise on with a 20 min timer first. A parent is told, with who is on duty, only if the crying comes back within 2 min |
| Dog bark | A `house_sound` event only |

## Why is he crying

The reason comes from the log, not the sound. `parenting_agent/cry_reason.py` reads only what already happened at the moment of the cry:

- **Hungry:** time since the last feed against his usual gap, the same estimate the daily rhythm uses for the next feed.
- **Diaper:** a feed with no change after it, since a change usually follows each feed. Otherwise time since the last change.
- **Tired:** time awake since he last woke against his usual awake time before a sleep, day and night apart.
- **Comfort:** when nothing in the log stands out.

Cry length and voicing move a score by at most 0.05, a weak extra signal only. Example output: "Probably hungry: last feed 2 h 51 min ago, he eats about every 2 h 26 min."

It never names pain, illness or any medical cause. Every text passes `no_medical()` and the rhythm's `no_advice()`, and a test runs both over every output. ChatterBaby cannot be used: its model and data are not public and the app sends each cry to UCLA's servers (docs/research/cry-reason.md). No third-party cloud audio service is called. The one exception is Muse Spark Open, the agent's own brain, below.

**Evaluation on the simulated week**, where the true reason is known. The same rhythm assumptions build the week and the reasoner, so this checks the logic, not real cries. `simweek/cries.py` puts a cry 1 to 12 minutes before what the week does next: a feed (hungry), the diaper change after a feed (diaper), or falling asleep (tired).

| Set | Top guess right |
|---|---|
| Fixed sample of 10 (4 hungry, 3 tired, 3 diaper) | 9 of 10 |
| Whole week | 166 of 184 (hungry 60 of 66, tired 55 of 63, diaper 51 of 55) |

Details in `results/sounds/cry-eval.json`. The miss in the 10 is a night diaper cry read as tired, since night awake times are short.

## The sound as one more signal, on the Mac (issue #161, logged only today)

Built Oct 30 2026 after Gonza asked to reconsider ChatterBaby. `parenting_agent/cry_sound.py`: on a cry, the Ear hands the cry's samples (in memory, at most 10 s used) to PANNs CNN14, which gives a 2048 number embedding, and a small softmax head (`parenting_agent/assets/cry_reason_head.json`, trained on the Donate-a-Cry corpus, ODbL) reads it as hungry, tired, discomfort, burping or belly pain. Nothing leaves the Mac. Turn it on with `"house_sounds": {"cry_model": {"enabled": true}}`.

- The log's reason stays first. When a class may be said, the sound adds "The sound agrees." or "From the sound alone, a guess: ...".
- Belly pain is never said as pain. It becomes "Check on him now", which skips the white noise at night and makes the glasses card an alert. With a red flag in a log note of the last 24 h, the fixed call-the-doctor line from `agent/rules.py` follows.
- A class is said only when it cleared the bar on a held-out test written before training. **None did:** balanced accuracy 0.19 on 120 held-out clips, chance 0.20 (`results/cry-reason/README.md`). So today each guess is a `cry_sound_guess` event only and the parent hears the log reason alone.
- The cry notify now carries `source: house-sounds` and `routine: cry`, so the family push sends it to the parent on duty at night and the glasses show a cry card ("He is crying"). Live run on the Mac with two licensed recordings: `scripts/cry_reason_live.py`, `results/cry-reason/live.json`.

## Muse Spark Open listens to the cry (opt-in, blocked today)

Built Oct 29 2026 (issue #14). PANNs stays the fast local reflex that hears "a baby is crying". On a cry, the first 5 s of that cry only can go to Muse Spark Open on Baseten, in one call with a strict schema: did it hear a baby crying, a guessed reason in the same four categories (hungry, tired, diaper, comfort, or cannot tell) and a confidence. The guess is framed as a guess from the sound alone, never medical, and adds one sentence to the log-based reason, for example "From the sound alone, a guess: hungry." It does not change the log's ranking. Code: `parenting_agent/cry_muse.py`, wired in `house_sounds.py` and `hearing.py`.

**Privacy.** This is the one flow where house audio may leave: the first 5 s of a cry PANNs detected, as a WAV made in memory, to the brain host (inference.baseten.co), dropped after that call. No other room audio is ever sent. It is off by default (`"house_sounds": {"muse_audio": {"enabled": true}}` turns it on), and before any cry clip is sent a synthetic beep clip, never house audio, must be heard and counted right. Each call is a `cry_sound_guess` event with its host.

**Result on Oct 29: Muse hears speech, not house sounds.** In the cry path's request shape Muse wrote down a spoken random number 3 of 3 times and failed the beep canary 3 of 3 times. On the 46-clip hearing set PANNs got 41 of 46 labels right and Muse 11 of 46, and Muse called 14 clips that are not cries a cry. A first run that night said Muse heard no audio at all: its prompt offered "if no audio reaches you" as a way out, which makes Muse say it heard nothing even for speech (`results/audio-truth/README.md`). The `audio_tokens` usage field reads 0 even when Muse writes down speech, so it is no sign either way. So the canary blocks the call, and the cry reason stays PANNs plus the log. Details and every try in `results/sounds/muse/README.md`.

## White noise

`parenting_agent/white_noise.py` has a simulated device with the controls the ESP32-S3 + MAX98357A ESPHome machine will have: on, off, noise type (white, pink, brown), level and a sleep timer. Nothing plays. Every change is a `white_noise` event with `dry: true`.

- **Cap in code:** at most 50 dB at the crib. A calibration maps device level to dB measured at the crib, and every level asked for is clamped to the highest level under the cap. Until the machine is measured, a placeholder assumes 70 dB at the crib at full level, so the cap is level 0.1 and the usual level 0.08 (48 dB).
- **From the rhythm:** on 5 minutes before the nap or sleep the log expects and at bedtime (20:30 by default), a 30 min timer once he is asleep, off when it runs out. On one simulated day: 8 on, 8 timers, 7 off, never above 48.1 dB.
- **Night fuss:** on with a 20 min timer before a parent is woken.

The Echo fallback is not wired, there is no real playback in this item.

## The listener

PANNs CNN14 (16 kHz, AudioSet) with related classes summed and the thresholds chosen in meta-hackathon-2026 issue #2. That is prior work from Oct 23, before the event: 18 of 24 events heard under speech at 0 dB, 0 false alarms on held-out kitchen noise and speech (meta-hackathon-2026 `results/muse_hearing.json`). It was not re-measured during the event.

- `parenting_agent/hearing.py`: the Ear. ffmpeg decodes the Tapo RTSP audio (or a test file) to 16 kHz PCM on a pipe. Every second the last 2 s are scored. Only labels, scores, times and a cry's length, loudness and pitch go on the bus. Samples stay in numpy arrays and are dropped when the cry is reported. A test checks that nothing opens a file for writing.
- `parenting_agent/hearing_worker.py`: PANNs in its own process, in the Python that has torch (the SAM 3.1 venv, `HEARING_PYTHON` to change it). The checkpoint already holds the STFT kernels and the mel filters, so torchlibrosa and librosa are replaced by a small stub. The strict weight load fails if the stub does not match.
- `scripts/fetch-panns.sh`: model code pinned to commit 542c8c8 and the Zenodo weights, all checked by MD5, into `.models/panns`.
- `parenting_agent/house_sounds.py`: the agent plug-in, and the `why_crying` tool for the brain.

## Run

```bash
scripts/fetch-panns.sh                                   # once
python -m unittest tests.test_sounds -v                  # offline, a tone listener stands in for PANNs
python scripts/sounds_run.py                             # licensed clips through PANNs and the agent
python scripts/sounds_run.py --camera-seconds 60         # also listen live to the living room camera
```

`sounds_run.py` plays cry-04 (CC BY-SA 4.0) and doorbell-01 (public domain) from the meta-hackathon-2026 hearing set through the 8 kHz camera channel into the Ear. Oct 28 2026: the cry was heard as one 20 s cry at a simulated moment whose true reason is hunger, and the agent said "Probably hungry: last feed 2 h 51 min ago, he eats about every 2 h 26 min." The doorbell with the changing table armed was routed to the ear. A 20 s live listen on the camera heard a quiet room (median -72 dBFS) and fired nothing. Results in `results/sounds/`, numbers and labels only.

To run it inside the agent, add `"parenting_agent.house_sounds:HouseSounds"` to `plugins`, with `"house_sounds": {"source": "camera"}` and the `rhythm` block for the log. Add `why_crying` to `allowed_tools` so the brain can call it without asking.
