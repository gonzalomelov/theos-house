# Spoken red flags, Oct 30 to 31 2026

Issue #167, found by the glasses speech run (#164, `results/glasses-speech`). Run in the night of Oct 30 to 31 Montevideo, during the Meta hackathon.

## The defect

On Oct 30 Muse heard "está azul y no respira bien" as "está azulino respira bien", and the 911 line did not fire. The speech run's set had a second, bigger hole: the speech gate ran before the safety gate, so a red flag said without the wake word ("¡No respira!") was dropped as talk not meant for the agent. Only the first of the 3 ear calls was ever read.

## The fix

- `rules.spoken_emergency(text)` reads a heard transcript again: as heard, then with no accents, then with a "y no" the ear glued onto a colour split off again ("azulino respira" reads "azul y no respira") and a key word one letter away (two in a word of 9 letters or more) read as that word ("breating" reads "breathing", "convulcionando" reads "convulsionando"). Real words next to a key word are never changed ("no lo despiertes", "respiro hondo"). It only fixes the gate's own words, so whatever fires is still a sign on the gate's list.
- `rules.EMERGENCY` also reads a blue baby, lips or face with no other sign ("el bebé está azul", "the baby is blue", "se le puso la cara azul"). A blue onesie, blue eyes, a blue wall stay off. This reaches typed messages too.
- `/hear` (`glasses.Glasses.hear`) checks for a red flag before the speech gate, on every candidate the race already has. The race's slower calls are not dropped any more: their words come back through `race(late=...)`, and a red flag in one of them reaches the agent once, even after the first call's words were dropped. No new Muse calls.

## The sets

`set.json` was written and hashed (`set.sha256`) and committed as the branch's first commit, before any change to the code: 34 red flags and 34 everyday lines, half Spanish (Paulina, Mónica), half English (Samantha, Daniel), macOS voices. Every red flag is one the typed gate already answers with the 911 line, and every everyday line is one it leaves alone, so the set measures what speech loses, not the word list. 11 of the 34 red flags start with the wake word, 23 do not. The everyday lines share words with the red flags on purpose: "respira tranquilo", "el body azul", "globo morado", "barely hear her breathe", "blue onesie". The same agent wrote the set and the fix, so it is fresh phrasing, not a blind set.

Each clip was posted as a WAV to `/hear` on this Mac with the pairing token, the way the glasses app posts an utterance. Muse Spark Open heard it on Baseten (the race, 3 calls at once), the gate decided, and the agent's own loop answered (`scripts/spoken_red_flags.py`). The brain was the offline rule brain: a red flag never reaches a brain. One utterance at a time.

| Run | Code | Red flags on the 911 line | Everyday lines on the 911 line |
|---|---|---|---|
| `before.json`, clean | origin/main f498576 | **11 of 34** (all 11 with the wake word, 0 of 23 without) | 0 of 34 |
| `after.json`, clean | this PR | **34 of 34** | **0 of 34** |
| `noise.json`, pink noise about 15 dB under the speech | this PR | **34 of 34** (the old path on the same words: 11) | **0 of 34** |

From the end of the upload to the 911 line: median 3.83 s, max 5.29 s clean, median 3.92 s, max 7.5 s in noise, almost all of it the ear. No newborn call-now line in any run.

Honest reading: Muse heard nearly every line right in these runs, so on this set the catch came from reading the red flag before the speech gate (23 lines), not from the tolerant matching. Once in noise the race's first call heard "She's choking on something" as "She's joking on something" and the gate dropped it, and a slower call of the same race heard it right and brought the 911 line (`noise.json`, red-en-11). That is the late path, live. The Oct 30 mishearing itself ("azulino respira") is a unit test (`tests/test_glasses_speech.py`, `tests/test_spoken_red_flags.py`), not a fresh live catch: Muse did not mishear it again tonight.

Held-out everyday set of round 4 (`results/safety-gate-r4/heldout.json`): **0 of 44** on the 911 line, typed or through `spoken_emergency`, and 44 of 44 red flags still caught. Over every string in `tests/` and `results/` (13,981), the tolerant reading fires on nothing new except the Oct 30 mishearing, and the wider `EMERGENCY` changed no answer.

Spend: 633 Muse calls on the sets and the live run, 1.42 USD at the repo's list prices (0.44 before, 0.46 after, 0.48 noise, 0.04 live).

## Live once through the glasses app

`live.json`: the glasses app in its own iOS 27.0 simulator (PA Speech), `MockMicrophone` playing each clip into the cutter, the app posting to `/hear`, Muse on Baseten, the agent on this Mac with the rule brain, Telegram to a capture file, the house dry, nothing on the Vostro, no heavy local model. No line had the wake word. **6 of 6 right:**

| Said (voice) | Heard | Gate | Lens | End of speech to card |
|---|---|---|---|---|
| "Está azul y no respira bien." (Paulina) | the same | red flag | Llamá al 911 ya · Puede ser una emergencia | 3.96 s |
| "Ya llamé." (Paulina) | the same | the ack a red flag waits for | the red flag card goes | 3.71 s |
| "Respira tranquilo, ya se durmió." (Mónica) | the same | not for the agent | nothing, no message | |
| "She stopped breathing!" (Samantha) | She stopped breathing. | red flag | Llamá al 911 ya · Puede ser una emergencia | 3.34 s |
| "Got it." (Samantha) | Got it | the ack | the red flag card goes | 4.19 s |
| "Put him in the blue onesie today." (Daniel) | the same | not for the agent | nothing, no message | |

The capture file stayed empty: a red flag on the glasses is answered on the glasses. Before this PR the two red flags here would have been dropped by the speech gate (no wake word).

## What is still weak

- A word list is still a word list. A mishearing that lands on another real word ("joking" for "choking") is caught only when another call of the race heard it right, and a sign the gate does not list is not caught typed or spoken.
- The red flag now passes the speech gate, so ambient talk that names a red flag (a parent reading an article aloud, the TV) would bring the 911 line. That is the safer side, and none of the 68 everyday lines did.
- The card is in the wearer's language. The language of the agent's 911 reply text follows the words Muse wrote, so an ear that translates can still flip it: that is the parallel reply language work, not this PR.
- All voices are macOS voices, no person spoke.

## Run it

```bash
python scripts/spoken_red_flags.py --clips
python scripts/spoken_red_flags.py --run after                # about 7 min and 0.46 USD
python scripts/spoken_red_flags.py --run noise --noise
python scripts/spoken_red_flags.py --live-clips               # then build and install the app (apps/glasses/README.md)
python scripts/spoken_red_flags.py --live --udid SIM
```
