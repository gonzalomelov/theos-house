# The coach starts from the core (Nov 3)

`scripts/coach_listener.py` on this Mac, a local core on the mock home, real Muse on Baseten, SAM 3.1 on this Mac. The camera was 60 s of a public install video (kept outside the repo) in a loop, and a script played the parent. One run. No glasses.

- Muse called `start_car_seat_coach` once for Gonza and nothing else, across all the parent's answers, and wrote no steps of its own.
- The coach ran all 10 steps in 214 s, 20 lines back through `POST /coach`, ending in its summary.
- SAM saw only the handle. The other camera steps ended "not seen", because the loop didn't match the step and nobody moved the camera. This run proves the path, not the coach's vision. The coach's own scores are in results/carseat.

Not run: the real glasses app, and the `--ssh` link carrying a coach line to a real channel.
