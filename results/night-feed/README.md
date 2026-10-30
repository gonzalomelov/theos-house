# The 3 AM feed, simulated (issue #110)

Built and run on Oct 29 2026, inside the event, and rerun the same day after the awake-only change (issue #128). Everything here is a simulation: the warmer plug is a virtual dry-run switch, `house.live` is false, there was no Home Assistant token in the run, so nothing in the house changed. Zero live house calls in every run.

**Oct 30 2026: the study light is now live on the family agent.** Since PR #139 the night feed's study light (`night_feed_light` in `parenting_agent/house_live.py`, listed in `config/agent.vostro.json` `house.live_actions`) goes on dim and warm for real on a real awake signal and off after the feed, at most 6 writes a night. It read unavailable in Home Assistant at 06:35 on Oct 30 and was back at 19:26 (state off). The runs on this page were all dry, Oct 29, before that change. The bottle warmer and the white noise are still dry.

Code: `parenting_agent/night_feed.py`, `parenting_agent/virtual_devices.py`. Tests: `tests/test_home_automations.py` (`NightFeedTest`). Run: `.venv/bin/python scripts/night_feed_sim.py` and `--no-cry`.

## What it does

Changed on Oct 29 2026 after the round 4 judges (issue #128): the house acts only when the baby is awake, never on a guess.

1. Predicts the next feed from the log rhythm, the way the families bot does: a top-up within 30 minutes folds into the feed before it, then the median of the last gaps. Only feeds that fall between 22:00 and 06:00 count. The guess can be more than an hour early (see below), so it never touches the nursery or the parent.
2. A guess may only pre-warm, silently: 10 minutes before the guessed feed, or at a Muse plan moment, the bottle warmer plug goes on. No light, no white noise change, no push, no reminder. If no awake signal follows, the pre-warm closes quietly.
3. The house acts only on a real awake signal: a night cry on the Tapo microphone (a `sound` event from house_sounds) when the feed is due within 45 minutes, overdue or pre-warming, or a second cry within 15 minutes of one that did not look like a feed. Or a parent saying so ("he's up", "he's awake", "starting a bottle") on Telegram or to the Echo, a `baby_awake` event (what a "he's up" button publishes), or a wake-up, wake-up note or feed newly written to the log at night. A question ("is he up?") or "he's still asleep" is not a signal.
4. Awake means: the bottle warmer plug on (software auto off after 30 minutes in the agent, capped at 45 in code, the plug has no timer of its own set yet), the study light on at 10 percent and 2700 K, the white noise down to half its level, one push to the parent on duty from the night rota. A signal from the log or "starting a bottle" sends no push, a parent is already up.
5. The warmer holds water only. The bottle stays in the fridge until the parent is up, so no milk waits out of the fridge for the plan. It runs when a bottle was logged in the last 24 hours (a breast-only family never runs it).
6. A cry while awake and no feed logged yet means the feed is coming now: the auto off starts over, and if it had already run the warmer goes on again with one push.
7. **Per-night warmer cap.** Every switch-on of the night, pre-warm and cry restarts together, counts against one total: 90 minutes a night by default (`warmer_night_max_min`), never more than 120 in code (`WARMER_NIGHT_CAP_MIN`). Once used, the warmer stays off until the next night (noon to noon). Before this change the 45 minute auto off restarted on every cry, so there was no night total. Limits of the cap: it is software in the agent, the count lives in memory, so an agent restart in the night starts it over, and the plug itself has no timer set yet.
8. The parent logs the feed by voice ("baby agent, fed 90 ml" to the Echo or Assist, or a Telegram voice note). The warmer goes off at once. 30 minutes after the feed started, the light goes off and the white noise goes back. Only once the baby is known awake, without a feed log 30 minutes after that, one push says how to log it by voice.

## One simulated night, Oct 20 to 21

The log holds the simulated week up to 22:00. In the night the baby cries 4 minutes before each real feed of the fixture, and the parent logs each feed by voice one minute after it starts, through the voice bridge over HTTP with the rule-based brain.

| Time | What happened |
|---|---|
| 22:00 | White noise on (bedtime), level 0.08 |
| 22:55 | Rhythm guess: feed around 23:05. Warmer on, silently. Light, white noise and parent untouched |
| 23:23 | Cry. Now he is awake: the warmer's auto off starts over, study light dim and warm (dry), white noise to 0.04. Push: "He is awake, a cry was heard. Bottle warmer on, study light dim and warm, white noise down. Parent B is on duty." |
| 23:28 | Voice: "baby agent, fed right breast". Agent: "Done, logged." |
| 23:29 | Feed seen in the log, warmer off |
| 23:58 | Light off (dry), white noise back to 0.08 |
| 01:47 | Rhythm guess: feed around 01:56. Warmer on, silently |
| 02:09 | Cry. Light, white noise down, push names Parent A, who has fewer wake-ups now |
| 02:14 | Voice: "baby agent, fed 90 ml bottle". Warmer off at 02:15, light off and white noise back at 02:44 |
| 04:36 | Cry: feed expected around 04:58, within 45 min. Ready at once. Push names Parent B |
| 04:41 | Voice: "baby agent, fed right breast". Warmer off at 04:42, light off at 05:11 |

The full event list is in `timeline-oct-20.json`. In the old version the 22:55 and 01:47 guesses already halved the white noise and pushed the parent, 28 and 22 minutes before the baby woke.

## Six nights, Oct 20 to 26 (`sim.json`, `sim-no-cry.json`)

Rerun on Oct 29 2026 after the change. "Asleep" means outside the simulated awake windows: from 4 minutes before each real feed (the simulated cry) to 45 minutes after it starts. The baby wakes at the same times in both runs, the no-cry run only switches the microphone off. The "before" columns are the old code with the same new checks, run the same evening.

| Measure | With the cry, now | With the cry, before | Rhythm alone, now | Rhythm alone, before |
|---|---|---|---|---|
| Night feeds | 20 | 20 | 20 | 20 |
| **Parent pushed while the baby slept** | **0** | 12 | **0** | 12 |
| **White noise lowered while the baby slept** | **0** | 9 | **0** | 9 |
| Study light turned on while the baby slept | 0 | 9 | 0 | 9 |
| Pushes in total | 19 | 25 | 0 | 13 |
| Bottle feeds with the warmer on when the feed started (warmer ready in time) | 8 of 8 | 8 of 8 | 2 of 8 | 2 of 8 |
| Breast feeds with the warmer on anyway (mixed feeding week) | 11 of 12 | 11 of 12 | 1 of 12 | 3 of 12 |
| Study light on when the feed started | 19 of 20 | 19 of 20 | 0 of 20 | 10 of 20 |
| Median minutes the warmer had been on at the feed start | 4 | 4 | 11 | 11 |
| Silent pre-warms on a guess | 9 | (were full prepares) | 5 | (were full prepares) |
| Warmer minutes per night, the six nights | 68, 22, 25, 84, 66, 48 | 68, 22, 25, 84, 66, 48 | 58, 3, 13, 0, 30, 0 | 58, 13, 13, 60, 58, 30 |
| Nights that hit the 90 min cap | 0 | no cap | 0 | no cap |
| Voice feed logs answered "Done, logged." | 20 of 20 | 20 of 20 | 20 of 20 | 20 of 20 |
| Live house calls | 0 | 0 | 0 | 0 |

What it costs: without the cry on the microphone the study light is no longer on when the feed starts (0 of 20, was 10 of 20). It comes on one minute in, when the parent logs the feed, because only then is the baby known awake. That is the trade the judges asked for: a dark study at the start of a feed beats a push and a quieter white noise while he still sleeps. The warmer, which is silent, is unchanged with the cry (8 of 8 bottles warm) and the same without it (2 of 8).

The one miss with the cry: Oct 25 at 01:37, a cluster feed 87 minutes after the last one. The rhythm said 02:49, the cry was 76 minutes before that, so it was skipped as not a feed. The house got ready one minute in, when the feed was logged. The second-cry rule would catch it earlier if the baby cried again within 15 minutes, which the simulation does not model.

## How good the prediction alone is

Backtest over the simulated week: for each of the 21 night feeds, the error of the prediction made right after the feed before it. Median absolute error 20 minutes. 3 of 21 within 10 minutes, 11 of 21 within 20 minutes. Errors from 71 minutes early to 100 minutes late.

So the rhythm alone does not land "10 minutes before" reliably, which is why it now only pre-warms the warmer and never acts on the nursery or the parent. The cry timing in the simulation (4 minutes before each feed) is an assumption, not a measurement. The awake windows (up to 45 minutes after the feed start) are an assumption too.

## Honest limits

- The warm-up the parent saves is not measured. With a cry trigger the warmer had about 4 minutes of head start. A water bath warmer needs its own minutes to bring a bottle up, so the pre-heated water shortens that, by an amount we have not measured.
- Pushes to a parent who is not Gonza go out as a `notify` event for the router. Ceci has no phone in Home Assistant today, so her push would go through Telegram, which was not exercised here.
- The plug does not exist yet. Nothing ran on a real warmer.
- There is no "he's up" button in Telegram yet. The `baby_awake` event it would publish works, and typing or saying "he's up" works today.

## The plug to buy

**Shelly Plus Plug IT**, EUR 24.00 list on shelly.com (EUR 16.80 on sale, checked Oct 29 2026). The house already runs one (the bathroom plug), so it fits the sockets and the core Shelly integration in Home Assistant is set up, local, no cloud. The warmer must start when power comes on: a warmer with a dial, not a push button. Once it is in Home Assistant, a small follow-up adds its `switch.` entity to the house tools policy and swaps the virtual switch for it, behind `house.live`. That swap is not built yet.
