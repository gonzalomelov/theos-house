# The Ear hears with a Meta model (Oct 31 2026)

The hackathon rule says every model the agent calls at runtime is a Meta model. Until today the Ear used PANNs CNN14, which is not. All numbers below come from runs on this Mac on Oct 31 2026.

**Result:** Meta's Perception Encoder Audio Frame small (`facebook/pe-a-frame-small`, Apache 2.0), zero shot with text prompts, now hears cry, doorbell, dog and splash. On the held-out set it heard 339 of 348 cries with 1 false alarm, where PANNs heard 331 with 0. PANNs is no longer called anywhere in `parenting_agent/`.

## How it was measured

1. `split.json` was committed first, in its own commit, before any listener scored any clip: the items, the prompts, the tuning rule and the rule for choosing the winner.
2. `tune.json`: every choice made on the tune set only (score mode, thresholds, the signal listener's limits).
3. `eval.json`: the held-out set, scored once after `tune.json` was committed.

Every item went through the Tapo camera channel (8 kHz G.711 A-law and back, `hearing.from_file camera_channel=True`) and into the real Ear, 2 s windows every second. An item fires a label when any window reaches that label's threshold.

| Set | Cries | Doorbell | Dog | Splash | No label (cough, speech, kitchen, radio, a song) |
|---|---|---|---|---|---|
| Tune | 113 (2 hearing set, 111 Donate-a-Cry) | 5 | 5 | 4 | 23 |
| Held out | 348 (2 hearing set, 346 Donate-a-Cry) | 4 | 3 | 3 | 41 |

The hearing set is the 48 licensed clips of meta-hackathon-2026 (`hearing_sources.json`, which includes the 31 audio2 clips), dev split for tune, test split held out. Donate-a-Cry (ODbL 1.0, contents DbCL 1.0) is split by app install with a seeded hash, so no install is on both sides. A long clip with no label gives up to 6 items of 10 s, so false alarms are counted on more room sound. Clips stay outside the repo, only file names and labels are in `split.json`.

## Held-out results

Hits out of items of that label, then false alarms out of items of any other truth.

| Label | Before: PANNs as it ran | After: Perception Encoder (runtime) | Signal processing, no model |
|---|---|---|---|
| **Cry** | 331 of 348, **0** false alarms of 51 | **339 of 348**, **1** false alarm of 51 | 283 of 348, 2 false alarms of 51 |
| Doorbell | 4 of 4, 0 of 395 | 3 of 4, 3 of 395 | not built for it |
| Dog | 3 of 3, **104** of 396 | 3 of 3, 3 of 396 | not built for it |
| Splash | 3 of 3, 4 of 396 | 3 of 3, 1 of 396 | not built for it |
| All false alarms | 108 | 8 | 2 |

The two cries of the licensed hearing set were heard by all three listeners. On the tune set the Meta model heard 112 of 113 cries with no false alarm, PANNs 108 with none, the signal listener 98 with 2.

**The winner rule** written before scoring gives the cry to the Meta model when it hears at least as many held-out cries as the signal listener with no more false alarms: 339 against 283, 1 against 2. So the Meta model hears every label. The signal listener stays in `parenting_agent/cry_signal.py` as an option (`"listener": {"owners": {"cry": "signal"}}`), not the default.

## Where it fails

- **A cough was heard as a cry** (`cough-06`, CC BY 2.0). At night that would wake a parent. Coughs score high on the cry prompts in general: all 5 held-out coughs scored between 2.8 and 5.7 on the logit scale, against a cry threshold of 4.43.
- **Six cries were heard as something else as well:** 3 Donate-a-Cry clips also fired doorbell and 3 also fired dog. At home a cry that fires doorbell would also say "Doorbell at the front door", a wrong message. PANNs did this far more often for dog (104 cries also fired dog, which only writes a `house_sound` event), and never for doorbell.
- **One doorbell was missed** (`doorbell-03`, an old trill bell, logit 8.03 against the threshold 8.32). PANNs heard all 4.
- **One kitchen recording fired splash** (`negative-02` at 0 s, it may hold real running water).
- **The non-cry sets are tiny:** 3 to 5 items per label on each side. Those rows say the Meta model works on these clips, not how often it will fail at home. The thresholds the tuning rule picked are high (sigmoid 0.988 for cry, 0.9998 for doorbell), so quieter or farther sounds at home may be missed.
- **Nine held-out cries were missed**, all from Donate-a-Cry. The signal listener missed 65, so loudness and pitch alone are not enough.
- **Muse Spark Open's own audio input cannot do this job**, measured Oct 29 (`results/sounds/muse/README.md`): 11 of 46 labels right against 41 of 46 for PANNs, beep canary 0 of 3. It was not run again.

## Cost on the Mac

| | PANNs | Perception Encoder small |
|---|---|---|
| Weights | 359 MB | 1.76 GB (`model.safetensors`, SHA-256 checked by `scripts/hearing-setup.sh`) |
| One 2 s window, median | 0.016 s on CPU | 0.062 s on the GPU (MPS) in the eval, about 0.2 s on CPU in a smoke test |
| Start | 1.4 s | 2.7 to 4.7 s |

The agent runs it on CPU by default (`"listener": {"device": "cpu"}`, or `HEARING_DEVICE=mps`), so it never holds the GPU that SAM 3.1 uses. A 2 s window every second leaves room at about 0.2 s.

## Live path, once

`scripts/sounds_run.py --out results/sounds/meta-hearing/live` played cry-04 (CC BY-SA 4.0) and doorbell-01 (public domain) through the camera channel into the real Ear and the house sounds plug-in, Meta listener on CPU, no Telegram, no Home Assistant writes, brain fake. `live/run.json`:

- The cry was heard as one 20 s cry (peak logit 9.73, sigmoid 0.99994) at a simulated moment whose true reason is hunger, and the agent said "Probably hungry: last feed 2 h 51 min ago, he eats about every 2 h 26 min." The 20 s took 4.7 s to process on CPU.
- The doorbell with the changing table armed fired at its first second and was routed to the ear: "Doorbell at the front door. Your hands stay on the baby, I can ask the visitor to wait."
- No other label fired. No audio was written.

## Rerun

```bash
scripts/hearing-setup.sh                                                     # venv and weights, once
python scripts/meta_hearing_eval.py scores --listener meta --split tune      # HEARING_PYTHON from the setup
python scripts/meta_hearing_eval.py scores --listener signal --split tune
python scripts/meta_hearing_eval.py tune
python scripts/meta_hearing_eval.py scores --listener panns --split held_out # before baseline, SAM 3.1 venv
python scripts/meta_hearing_eval.py scores --listener meta --split held_out
python scripts/meta_hearing_eval.py scores --listener signal --split held_out
python scripts/meta_hearing_eval.py test
```

The Meta model is above 1 GB, so take the GPU lock (`mkdir /tmp/pa-gpu.lock`) for the eval and the live run.
