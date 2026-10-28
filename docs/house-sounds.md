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

It never names pain, illness or any medical cause. Every text passes `no_medical()` and the rhythm's `no_advice()`, and a test runs both over every output. ChatterBaby was ruled out (audio goes to UCLA servers, and pain is a medical reading), and so is any cloud audio service. The Donate-a-cry corpus (ODbL, mostly hungry clips) is not used yet.

**Evaluation on the simulated week**, where the true reason is known. `simweek/cries.py` puts a cry 1 to 12 minutes before what the week does next: a feed (hungry), the diaper change after a feed (diaper), or falling asleep (tired).

| Set | Top guess right |
|---|---|
| Fixed sample of 10 (4 hungry, 3 tired, 3 diaper) | 9 of 10 |
| Whole week | 166 of 184 (hungry 60 of 66, tired 55 of 63, diaper 51 of 55) |

Details in `results/sounds/cry-eval.json`. The miss in the 10 is a night diaper cry read as tired, since night awake times are short.

## White noise

`parenting_agent/white_noise.py` has a simulated device with the controls the ESP32-S3 + MAX98357A ESPHome machine will have: on, off, noise type (white, pink, brown), level and a sleep timer. Nothing plays. Every change is a `white_noise` event with `dry: true`.

- **Cap in code:** at most 50 dB at the crib. A calibration maps device level to dB measured at the crib, and every level asked for is clamped to the highest level under the cap. Until the machine is measured, a placeholder assumes 70 dB at the crib at full level, so the cap is level 0.1 and the usual level 0.08 (48 dB).
- **From the rhythm:** on 5 minutes before the nap or sleep the log expects and at bedtime (20:30 by default), a 30 min timer once he is asleep, off when it runs out. On one simulated day: 8 on, 8 timers, 7 off, never above 48.1 dB.
- **Night fuss:** on with a 20 min timer before a parent is woken.

The Echo fallback is not wired, there is no real playback in this item.

## The listener

PANNs CNN14 (16 kHz, AudioSet) with related classes summed and the thresholds chosen in meta-hackathon-2026 issue #2: 18 of 24 events heard under speech at 0 dB, 0 false alarms on held-out kitchen noise and speech.

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
