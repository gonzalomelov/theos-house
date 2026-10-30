# Muse runs the house, replayed and scored (issue #116)

Built and run on Oct 29 2026, inside the event. Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten, reasoning effort low) plans the house. Plain code checks every plan and arms the fixed routines. Every house write is a dry run, `house.live` is false, there was no Home Assistant token in any run. Zero live writes in every run.

Code: `parenting_agent/house_brain.py`, hooks in `day_engine.py` and `night_feed.py`. Tests: `tests/test_house_brain.py` (fake Muse, offline). Replay: `scripts/muse_house_sim.py`.

## How it works

1. **Muse plans.** At bedtime, at each wake-up, after each logged night feed and 15 min before each predicted nap, Muse gets the last 24 h of the log, the usual sleep and awake minutes, the predicted sleeps, the next feed, the night rota, the floor clean gate, the house state (read only), the weather and the calendar. It answers in a strict JSON schema: `on_duty`, `floor_clean` windows, `bottle_prewarm` times, `door_quiet` windows, `white_noise_boost` windows, messages per parent, a one sentence summary and a one sentence `why_changed`. The schema names routines and times only. There is no device field, so Muse cannot name a device.
2. **Plain code checks.** Each item: HH:MM, within 12 h, window length limits, a floor clean at least 41 min long, in the day and never over a predicted sleep, a pre-warm only at night and at least 60 min apart. A plan that is not a plan (wrong shape, unknown parent) is refused whole and every routine runs its fixed rule. An item that fails the clock or the safety gate is refused and only that routine runs its fixed rule. Texts that fail the no-advice guard are dropped. The routines keep their own run-time checks: nap mode always docks the vacuum when a sleep starts, the floor clean re-checks that he is awake and out of the room and waits for a yes, the warmer has its hard auto off, the white noise its 50 dB cap.
3. **Muse adapts.** A sleep 40 min longer than usual, a parent asking to sleep, a dog bark on the house microphone, or a visitor note trigger a re-plan at once, with one sentence of why on Telegram.
4. **Muse explains.** Each morning Muse writes what the house did overnight from the house's own events (never a parent's free text). Telegram gets it, the kitchen Echo gets a short version that passes a speaker filter (dry run).
5. **Fallback.** A Muse error, a timeout, an answer that is not JSON, a refused plan or a spent budget leaves the fixed routines running. Every fallback is a `house_brain_fallback` event, every plan a `house_plan` event.
6. **Visible.** "Tonight's plan" goes to Telegram at bedtime. On the Vostro, Telegram goes only to Gonza's chat, whoever a message is for.

## Replay against the fixed routines

These runs are from Oct 29, before the night feed became awake-only the same day (issue #128). In them a pre-warm also lit the study light, lowered the white noise and pushed the parent. Since then a Muse pre-warm, like the rhythm guess, only turns the warmer on silently. The nights were not rerun with Muse after that change, see `results/night-feed/README.md` for the fixed rules after it.

The same simulated day (`results/house-day`, Sat Oct 24 06:00 to Sun 07:00) and the same six nights (`results/night-feed`, Oct 20 to 26, 22:00 to 06:00, with the cry on the microphone). Runs 1 and 2 had Muse choose the parent on duty every time. Run 3 is the shipped setting, after the change below.

| Check | Fixed | Muse run 1 | Muse run 2 | Muse run 3 (shipped) |
|---|---|---|---|---|
| Day: minutes the vacuum ran while he slept | 0 | 0 | 0 | not rerun |
| Day: minutes a TV was on and unmuted, or the Echo not on do not disturb, while he slept | 0 | 0 | 0 | not rerun |
| Day: floor cleans while he was awake | 1 | 1 | 1 | not rerun |
| Day: loudest white noise at the crib | 48.1 dB | 48.1 dB | 48.1 dB | not rerun |
| Nights: bottle feeds with the warmer on at the feed start | 8 of 8 | 8 of 8 | 8 of 8 | 8 of 8 |
| Nights: study light on at the feed start | 19 of 20 | 19 of 20 | 20 of 20 | 19 of 20 |
| Nights: breast feeds with the warmer on anyway | 11 of 12 | 11 of 12 | 12 of 12 | 11 of 12 |
| Nights: pushes to the parent the rota names | 19 of 19 | 20 of 21 | 21 of 22 | 20 of 20 |
| Live writes | 0 | 0 | 0 | 0 |

The day engine did the same with or without Muse on every day check: Muse's floor windows and door windows did not change an outcome in that day. The nights match on warm bottles. Muse prepared the house 1 to 3 more times over six nights than the fixed rule, so the warmer ran more often.

**Where Muse did worse, and what we kept fixed.** In runs 1 and 2 Muse named the wrong parent once each, on the night of Oct 23: after a feed it kept the parent who had just been up instead of the one the rota named. The rota never does that. So the shipped setting keeps the rota fixed and lets Muse choose the parent only after a parent asked to sleep in the last 12 h (`parts: on_duty_on_request`). Run 3 with that setting: 20 of 20.

## Adaptation cases the fixed rules do not handle

| Case | Check | Fixed | Muse run 1 | Muse run 2 | Muse run 3 |
|---|---|---|---|---|---|
| A parent asks to sleep (21:50 "I'm exhausted, let me sleep tonight", the hard night of Oct 23) | no night push to that parent, every bottle warm in time | fail, 2 of 4 pushes to them | pass, 0 of 4 | pass, 0 of 4 | pass, 0 of 4 |
| Dog barks at 15:10 during the 14:51 nap | white noise up within 3 min, never over 50 dB | fail, nothing happens | pass, up at 15:10, 50.0 dB | pass | pass |
| Grandma rings at 14:47, 4 min before the 14:51 nap, after a note at 14:20 | no kitchen Echo line within 15 min of a sleep, the parent still gets a push | fail, the Echo says "Someone is at the door" | pass, silent push | pass | pass |
| The 11:57 nap runs 40 min past its end | a floor clean while he is awake before tummy time, 0 vacuum minutes asleep | fail, no clean | fail | fail | fail |

The long nap case fails for both. Muse re-planned at 14:18 and again when he woke at 14:34, but each time it said no window fit before the next predicted nap at 15:31, although 57 min was enough for the 41 min the run needs. The fixed rule holds the vacuum because he is asleep in its window. No vacuum ran during a sleep in either.

Sentences Muse wrote in these runs, as they went out:

- "Plan changed: Parent A asked to sleep tonight at 21:50, so night duty changed from Parent A to Parent B."
- "Plan changed: Added white noise boost 15:10-16:10 because dog barking was heard during the ongoing nap at 15:10."
- "Tonight's plan. On duty: Parent B. Bottle warmer and dim light at 23:50, 02:10, 04:30. Floor clean window 07:00 to 07:45."

## Muse calls, latency, cost, fallbacks

| Run | Calls | Failed calls | Median latency | p90 | Max | Cost |
|---|---|---|---|---|---|---|
| Runs 1 and 2 (day, nights, cases, twice) | 134 | 0 | 4.6 s | 6.4 s | 10.7 s | 1.01 USD |
| Run 3 nights | 31 | 0 | 4.9 s | 6.0 s | 6.4 s | 0.23 USD |
| Run 3 cases | 19 | 0 | 5.0 s | 5.9 s | 7.7 s | 0.15 USD |

About 0.008 USD a plan. The scored runs cost 1.38 USD. Building and debugging the prompt and the checks tonight took about 100 more calls in short case runs, about 0.8 USD by our estimate from those runs, so tonight stayed under 3 USD in all.

Fallbacks in runs 1 and 2: 0 whole plans refused, 5 partial fallbacks per run. All but one were a floor clean window Muse put over a predicted sleep, the other was two pre-warms less than 60 min apart. In each case only that routine ran its fixed rule. Run 3: 4 partial fallbacks in the nights and 1 in the cases, all floor clean over a predicted sleep. While the checks were built, Muse also returned windows with empty times, kept windows that were already over, and twice hit its token limit with broken JSON. The checks now treat empty and expired items as left out, and broken JSON is a full fallback.

## Honest limits

- The day and nights are the simulated week, not a real family. The cry timing (4 min before each feed) is an assumption from `results/night-feed`.
- In the replay the plan is applied in the same minute Muse is asked. Live, Muse takes about 5 s, and the fixed routines run until the plan lands.
- The morning explanation was Muse's in 17 of 18 nights. In the last night of run 3 Muse answered but its text failed the guard, so the fixed words went out. Muse's explanations read like a list of events more than plain words.
- One test in `tests/test_one_message_one_entry.py` fails on origin/main too, before this change. Not touched here.

## Run it

```bash
set -a; . ~/.parenting-agent.env; set +a
.venv/bin/python scripts/muse_house_sim.py --runs 2 --budget 2.5    # run.json
.venv/bin/python scripts/muse_house_sim.py --only nights            # run-nights.json
.venv/bin/python scripts/muse_house_sim.py --only cases             # run-cases.json
```

Every Muse call is in `calls` in each file, with its seconds, tokens and cost.
