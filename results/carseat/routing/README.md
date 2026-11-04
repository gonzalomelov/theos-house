# Can the coach tell a belt routed right from one routed wrong? (Nov 4 2026)

No. So the coach asks the parent to look and confirm, and the camera doesn't judge the route.

Two real stills from a third-party install video, one of a correct route and one of the commonest mistake (shoulder belt in the side guides, lap belt round the back). They were used for this test only, read into memory, and are not in this repo. A burned-in caption and the player's bars were cut off the wrong one before anything saw it. They are different seats at different angles, so this is two scenes, not a dataset, and the crops and tilts are the same two scenes again.

Muse is Muse Spark Open on Baseten. "A look" is one verdict: 3 calls with a majority for the existing checks, as the agent's config has them, 5 calls for the route question.

## The existing checks, unmodified (`before.json`, `sam.json`)

| Check | Right still | Wrong still |
|---|---|---|
| Muse, lap belt in both side guides, 5 looks | 4 pass, 1 unseen | **4 pass**, 1 unseen |
| Muse, shoulder belt in rear guide, 5 looks | 4 pass, 1 fail | **2 pass**, 3 unseen |
| Muse, no twist, 5 looks | 5 fail | 5 fail |
| SAM 3.1, lap guides from the door, 1 frame | unseen | **pass** |
| SAM 3.1, close-ups of the near and far guide, 1 crop each | not found | **pass, pass** |

Muse doesn't vote on the belts in the coach, and the Mac's listener runs SAM 3.1 alone. SAM reads the mistake as a pass by design: a shoulder belt in a side guide is a belt in a guide.

## A route question, tried and dropped (`after.json`)

Ten wordings were tried on these same stills, so this one is tuned on them. It asks which band goes through the near guide, the one from high up or the one from low down. Whole frame, reasoning effort high, 5 calls. A pass takes 4 of 5 with none against, a fail 3 of 5. The rules were set before this run.

| | Right still: pass, fail, unseen | Wrong still: pass, fail, unseen |
|---|---|---|
| Base, 5 looks | 3, 0, 2 | **2**, 0, 3 |
| 8 crops, tilts and light changes, 2 looks each | 5, 0, 11 | **3**, 6, 7 |
| All, 21 looks each | 8, 0, 13 | **5**, 6, 10 |

False "correct" on the wrong still: **5 of 21 looks, 2 of 5 on the plain still**. Accuracy over the 42 looks, counting unseen as not right: 14 of 42. Muse never called the right still wrong, and caught the wrong one 6 times in 21, which is too few to show on camera or rely on. A shorter trial of another wording called the wrong still fine in 2 of 5 looks too, after a probe had looked good, so small probes here mislead. A look also took about 20 s.

## What the coach does instead

A step after the rear guide, `belt_routing`: the coach says what is usual for a belt-fitted carrier, that seats differ, and to compare with the seat's manual and the blue guides. It says its camera can't confirm it. A "no" gets the fix line and a "listo", then the question again, up to three times. The summary lists it as a hand check. The summary now says "a belt in both side guides", not "the lap belt", since that is all the camera saw.

`e2e.json` is the whole path on the mock home and mock channel with real Muse and SAM 3.1: the tool call, the Mac's listener, each line through `POST /coach`, 24 lines to the asking parent, none to the other, none written by Muse.

Found on that path:

- `POST /coach` cut lines at 600 characters. The summary is longer, so "not a verdict" and the technician were lost. The limit is now 1500.
- A parent's "sí, se mueve poco" to the movement question brought the 911 line to both parents, as the gate reads it as Theo. That is the safe side, and the gate isn't changed for it. The scripts now say "sí, menos de dos centímetros".

Reproduce: `scripts/carseat_routing_eval.py`, `scripts/carseat_core_e2e.py`. The emergency list passed 3 of 3 runs at 56 of 56 (`results/core-jobs/emergency-list-round-14.json`).
