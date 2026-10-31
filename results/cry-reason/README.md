# Cry reason from the sound, kept on the Mac (issue #161)

All numbers below come from runs on Oct 30 2026. Research behind the choice: docs/research/cry-reason.md.

## What was measured

A softmax head on PANNs CNN14 embeddings, trained on the Donate-a-Cry cleaned set (ODbL 1.0, contents DbCL 1.0). Each clip went through the Tapo camera's 8 kHz A-law channel first, as at home.

1. `split.json` was committed first, in its own commit, before any feature was extracted: the split by app install (no phone on both sides) and the decision rule for when the sound may be said.
2. `tune.json`: settings chosen on the train split only, 5-fold cross validation grouped by install. Best: L2 0.1 with class weights, cross-validated balanced accuracy 0.25.
3. `eval.json`: the held-out test, read once.

| On the held-out test (120 clips, 52 installs) | Value |
|---|---|
| Balanced accuracy (mean recall over 5 classes) | **0.19**, 95% interval 0.16 to 0.29 |
| Chance, and the always-hungry baseline | 0.20 |
| Plain accuracy | 0.68 |
| Always-hungry plain accuracy | 0.80 |
| Hungry vs not hungry, ROC AUC | 0.51 |

| Class | Test clips | Recall | Predicted | Precision |
|---|---|---|---|---|
| hungry | 96 | 0.83 | 100 | 0.80 |
| tired | 6 | 0 | 7 | 0 |
| discomfort | 10 | 0.10 | 8 | 0.13 |
| burping | 2 | 0 | 2 | 0 |
| belly pain | 6 | 0 | 3 | 0 |

**The model is at chance.** It does no better than always saying hungry, and it cannot tell hungry from the rest (AUC 0.51). The rule written before training says the sound may be said only if the low end of the interval is above 0.20, so it is not said: `speak` is empty in `parenting_agent/assets/cry_reason_head.json`. The model still runs on every cry and its guess is a `cry_sound_guess` event, so the log keeps what it would have said.

Why, as far as we can tell: the Donate-a-Cry tags are one parent's guess with no second rater, 84% are hungry, the four other classes have 8 to 27 clips from 7 to 16 installs, and half the installs gave a single clip. This matches the research: ChatterBaby's 71.5% came from cries a three person panel agreed on, and its pain class from cries recorded at vaccinations, which is a clean label.

## The live run (`live.json`)

`scripts/cry_reason_live.py` on this Mac. Two licensed recordings from the meta-hackathon-2026 hearing set played into the Ear one second at a time through the camera channel: cry-01 (public domain, 19 s heard) and 60 s later cry-04 (CC BY-SA 4.0, 30 s heard). The moment is 00:09 on Oct 21 of the simulated week.

| Step | What happened |
|---|---|
| PANNs hears cry-01 | one cry, 18 s, phase end. The local model guessed hungry (0.93), logged only |
| Short night fuss | white noise on with a 20 min timer, dry. Nobody woken |
| 60 s later PANNs hears cry-04 | one cry, 30 s, still going. The local model guessed hungry (1.00), logged only |
| Log reason | nothing likely: last feed 43 min ago, diaper 13 min ago, awake 47 min. The week's true next step was sleep (tired) |
| Telegram | one message, to Gonza only (on duty), into the capture file |
| Glasses | one cry card on Gonza's glasses event stream, title "Está llorando". Ceci's stream got nothing |
| Network | every call off 127.0.0.1 refused for the run, none was tried. No audio written |

The live run shows the wiring end to end, not accuracy: both recordings are unlabeled, and the head says hungry with high confidence for both, which fits a model that leans on its biggest class.

## What stays limited

- The sound guess is not said to parents until a labeled set clears the bar. The way there is our own data after Theo is born: each cry heard, then what the log shows next (fed, changed, asleep), all kept in the house.
- The cry message is English only, from cry_reason.py. Both parents read Spanish. The card's title is in Spanish, its text is not.
- No microphone at home feeds an agent, so this ran on the Mac with recordings. The Vostro agent does not load house sounds.
- Head confidence is not calibrated: 1.00 on a cry the model cannot really read.
