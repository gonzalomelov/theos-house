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

## The sound as one more signal, on the Mac (issue #161, retired Oct 31)

Built Oct 30 2026 after Gonza asked to reconsider ChatterBaby: a small softmax head (`parenting_agent/assets/cry_reason_head.json`, trained on the Donate-a-Cry corpus, ODbL) read PANNs CNN14 embeddings of the cry as hungry, tired, discomfort, burping or belly pain. A class could be said only if it cleared a held-out test written before training. **None did:** balanced accuracy 0.19 on 120 held-out clips, chance 0.20 (`results/cry-reason/README.md`), so the parent only ever heard the log reason.

On Oct 31 PANNs left the runtime because it is not a Meta model, and the head went with it. The agent no longer computes an embedding and there is no `cry_model` setting. `parenting_agent/cry_sound.py` keeps the head for `scripts/cry_reason_train.py` to reproduce the Oct 30 result offline, and the wording rules any sound guess must follow (belly pain is never said as pain, it becomes "Check on him now", with the fixed call-the-doctor line from `agent/rules.py` after a red flag in the log). The cry notify still carries `source: house-sounds` and `routine: cry`, so the family push sends it to the parent on duty at night and the glasses show a cry card ("He is crying").

## Muse Spark Open listens to the cry (opt-in, blocked today)

Built Oct 29 2026 (issue #14). The Ear's local listener stays the fast reflex that hears "a baby is crying" (PANNs until Oct 31, Meta's Perception Encoder Audio since). On a cry, the first 5 s of that cry only can go to Muse Spark Open on Baseten, in one call with a strict schema: did it hear a baby crying, a guessed reason in the same four categories (hungry, tired, diaper, comfort, or cannot tell) and a confidence. The guess is framed as a guess from the sound alone, never medical, and adds one sentence to the log-based reason, for example "From the sound alone, a guess: hungry." It does not change the log's ranking. Code: `parenting_agent/cry_muse.py`, wired in `house_sounds.py` and `hearing.py`.

**Privacy.** This is the one flow where house audio may leave: the first 5 s of a cry the Ear detected, as a WAV made in memory, to the brain host (inference.baseten.co), dropped after that call. No other room audio is ever sent. It is off by default (`"house_sounds": {"muse_audio": {"enabled": true}}` turns it on), and before any cry clip is sent a synthetic beep clip, never house audio, must be heard and counted right. Each call is a `cry_sound_guess` event with its host.

**Result on Oct 29: Muse hears speech, not house sounds.** In the cry path's request shape Muse wrote down a spoken random number 3 of 3 times and failed the beep canary 3 of 3 times. On the 46-clip hearing set PANNs got 41 of 46 labels right and Muse 11 of 46, and Muse called 14 clips that are not cries a cry. A first run that night said Muse heard no audio at all: its prompt offered "if no audio reaches you" as a way out, which makes Muse say it heard nothing even for speech (`results/audio-truth/README.md`). The `audio_tokens` usage field reads 0 even when Muse writes down speech, so it is no sign either way. So the canary blocks the call, and the cry reason stays the Ear plus the log. Details and every try in `results/sounds/muse/README.md`.

## White noise

`parenting_agent/white_noise.py` has a simulated device with the controls the ESP32-S3 + MAX98357A ESPHome machine will have: on, off, noise type (white, pink, brown), level and a sleep timer. Nothing plays. Every change is a `white_noise` event with `dry: true`.

- **Cap in code:** at most 50 dB at the crib. A calibration maps device level to dB measured at the crib, and every level asked for is clamped to the highest level under the cap. Until the machine is measured, a placeholder assumes 70 dB at the crib at full level, so the cap is level 0.1 and the usual level 0.08 (48 dB).
- **From the rhythm:** on 5 minutes before the nap or sleep the log expects and at bedtime (20:30 by default), a 30 min timer once he is asleep, off when it runs out. On one simulated day: 8 on, 8 timers, 7 off, never above 48.1 dB.
- **Night fuss:** on with a 20 min timer before a parent is woken.

The Echo fallback is not wired, there is no real playback in this item.

## The listener

Every model the Ear calls is a Meta model since Oct 31 2026. Meta's **Perception Encoder Audio Frame small** (`facebook/pe-a-frame-small`, 450M parameters, Apache 2.0, not gated) scores every 40 ms of the last 2 s against text prompts, zero shot: four prompts per label ("a baby crying", "a doorbell ringing", "a dog barking", "water splashing" and close variants). A label fires when its best prompt's logit in the best frame reaches its threshold. Prompts were written and thresholds chosen on a tune set before a held-out set was scored once (`results/sounds/meta-hearing/README.md`):

| Held out | Before: PANNs | After: Perception Encoder |
|---|---|---|
| Cry | 331 of 348, 0 false alarms | 339 of 348, 1 false alarm (a cough) |
| Doorbell | 4 of 4, 0 false alarms | 3 of 4, 3 false alarms (cries) |
| Dog | 3 of 3, 104 false alarms (cries) | 3 of 3, 3 false alarms (cries) |
| Splash | 3 of 3, 4 false alarms | 3 of 3, 1 false alarm |

Plain signal processing (`parenting_agent/cry_signal.py`: loudness, voicing and pitch in the 250 to 600 Hz infant cry band, no learned model) heard 283 of 348 cries with 2 false alarms, so it is an option, not the default. PANNs stays offline only, as the before baseline (`scripts/panns_baseline.py`, `scripts/panns_worker.py`, `scripts/fetch-panns.sh`).

- `parenting_agent/hearing.py`: the Ear. ffmpeg decodes the Tapo RTSP audio (or a test file) to 16 kHz PCM on a pipe. Every second the last 2 s are scored. Only labels, scores, times and a cry's length, loudness and pitch go on the bus. Samples stay in numpy arrays and are dropped when the cry is reported. A test checks that nothing opens a file for writing. `hearing.default_listener` builds the listener the held-out test chose (`OWNERS`). Each listener brings its own thresholds.
- `parenting_agent/hearing_worker.py`: Perception Encoder in its own process, in a Python with torch and transformers 5.21 (`HEARING_PYTHON`, default `.venv-hearing/bin/python`), weights from a local folder (`HEARING_MODEL_DIR`, default `.models/pe-a-frame-small`), no network. CPU by default so it never holds the GPU SAM 3.1 uses (`HEARING_DEVICE=mps` or `"listener": {"device": "mps"}` to change it). About 0.2 s per 2 s window on CPU.
- `scripts/hearing-setup.sh`: the venv (pip: torch, transformers 5.21.0, numpy, safetensors) and the model files pinned to commit e5fc71c, every file checked by SHA-256.
- `parenting_agent/house_sounds.py`: the agent plug-in, and the `why_crying` tool for the brain.

## Run

```bash
scripts/hearing-setup.sh                                 # once: .venv-hearing and .models/pe-a-frame-small
python -m unittest tests.test_sounds -v                  # offline, a tone listener stands in for the model
python scripts/sounds_run.py                             # licensed clips through the Meta listener and the agent
python scripts/sounds_run.py --camera-seconds 60         # also listen live to the living room camera
python scripts/meta_hearing_eval.py test                 # the held-out tally from the cached scores
```

`sounds_run.py` plays cry-04 (CC BY-SA 4.0) and doorbell-01 (public domain) from the meta-hackathon-2026 hearing set through the 8 kHz camera channel into the Ear. Oct 31 2026 with the Meta listener on CPU: the cry was heard as one 20 s cry at a simulated moment whose true reason is hunger, and the agent said "Probably hungry: last feed 2 h 51 min ago, he eats about every 2 h 26 min." The doorbell with the changing table armed was routed to the ear. Nothing else fired (`results/sounds/meta-hearing/live/run.json`). The Oct 28 run with PANNs, and a 20 s live listen on the camera that heard a quiet room, are in `results/sounds/`.

To run it inside the agent, add `"parenting_agent.house_sounds:HouseSounds"` to `plugins`, with `"house_sounds": {"source": "camera"}` and the `rhythm` block for the log. Add `why_crying` to `allowed_tools` so the brain can call it without asking.
