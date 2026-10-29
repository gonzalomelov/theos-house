# The 3 AM feed, simulated (issue #110)

Built and run on Oct 29 2026, inside the event. Everything here is a simulation: the warmer plug is a virtual dry-run switch, `house.live` is false, there was no Home Assistant token in the run, so nothing in the house changed. Zero live house calls in every run.

Code: `parenting_agent/night_feed.py`, `parenting_agent/virtual_devices.py`. Tests: `tests/test_home_automations.py` (`NightFeedTest`). Run: `.venv/bin/python scripts/night_feed_sim.py` and `--no-cry`.

## What it does

1. Predicts the next feed from the log rhythm, the way the families bot does: a top-up within 30 minutes folds into the feed before it, then the median of the last gaps. Only feeds that fall between 22:00 and 06:00 count.
2. Gets the house ready once, 10 minutes before that feed, or the moment a night cry starts on the Tapo microphone (a `sound` event from house_sounds) when the feed is due within 45 minutes or overdue. A second cry within 15 minutes of one that did not look like a feed also counts.
3. Ready means: the bottle warmer plug on (hard auto off after 30 minutes, capped at 45 in code), the study light on at 10 percent and 2700 K, the white noise down to half its level, one push to the parent on duty from the night rota.
4. The warmer holds water only. The bottle stays in the fridge until the parent is up, so no milk waits out of the fridge for the plan. It runs when a bottle was logged in the last 24 hours (a breast-only family never runs it).
5. A cry while the house is ready and no feed is logged yet means the feed is coming now: the auto off starts over, and if it had already run the warmer goes on again with one push.
6. The parent logs the feed by voice ("baby agent, fed 90 ml" to the Echo or Assist, or a Telegram voice note). The warmer goes off at once. 30 minutes after the feed started, the light goes off and the white noise goes back. Without a feed log 30 minutes after the expected time, one push says how to log it by voice.

## One simulated night, Oct 20 to 21

The log holds the simulated week up to 22:00. In the night the baby cries 4 minutes before each real feed of the fixture, and the parent logs each feed by voice one minute after it starts, through the voice bridge over HTTP with the rule-based brain.

| Time | What happened |
|---|---|
| 22:00 | White noise on (bedtime), level 0.08 |
| 22:55 | Rhythm: feed expected around 23:05. Warmer on, study light dim and warm (dry), white noise to 0.04. Push: "Night feed around 23:05. Bottle warmer on, study light dim and warm, white noise down. Parent B is on duty." |
| 23:23 | Cry. The feed is later than predicted, the warmer's auto off starts over |
| 23:28 | Voice: "baby agent, fed right breast". Agent: "Done, logged." |
| 23:29 | Feed seen in the log, warmer off |
| 23:58 | Light off (dry), white noise back to 0.08 |
| 01:47 | Rhythm: feed expected around 01:56. Ready again. Push names Parent A, who has fewer wake-ups now |
| 02:09 | Cry, auto off starts over |
| 02:14 | Voice: "baby agent, fed 90 ml bottle". Agent: "Done, logged." Warmer off at 02:15 |
| 02:44 | Light off, white noise back |
| 04:36 | Cry: feed expected around 04:58, within 45 min. Ready at once. Push names Parent B |
| 04:41 | Voice: "baby agent, fed right breast". Warmer off at 04:42, light off at 05:11 |

The full event list is in `timeline-oct-20.json`.

## Six nights, Oct 20 to 26 (`sim.json`)

| Measure | With the cry on the microphone | Rhythm alone (`sim-no-cry.json`) |
|---|---|---|
| Night feeds | 20 | 20 |
| Study light on when the feed started | 19 of 20 | 10 of 20 |
| Bottle feeds with the warmer on when the feed started | 8 of 8 | 2 of 8 |
| Breast feeds with the warmer on anyway (mixed feeding week) | 11 of 12 | 3 of 12 |
| Median minutes the warmer had been on at the feed start | 4 | 11 |
| Cries skipped as not a feed | 1 | 0 |
| Voice feed logs answered "Done, logged." | 20 of 20 | 20 of 20 |
| Live house calls | 0 | 0 |

The one miss with the cry: Oct 25 at 01:37, a cluster feed 87 minutes after the last one. The rhythm said 02:49, the cry was 76 minutes before that, so it was skipped as not a feed. The second-cry rule would catch it if the baby cried again within 15 minutes, which the simulation does not model.

## How good the prediction alone is

Backtest over the simulated week: for each of the 21 night feeds, the error of the prediction made right after the feed before it. Median absolute error 20 minutes. 3 of 21 within 10 minutes, 11 of 21 within 20 minutes. Errors from 71 minutes early to 100 minutes late.

So the rhythm alone does not land "10 minutes before" reliably. It gets the house ready early or late, and the cry is what makes it ready at the right moment: 19 of 20 with the cry against 10 of 20 without. The cry timing in the simulation (4 minutes before each feed) is an assumption, not a measurement.

## Honest limits

- The warm-up the parent saves is not measured. With a cry trigger the warmer had about 4 minutes of head start. A water bath warmer needs its own minutes to bring a bottle up, so the pre-heated water shortens that, by an amount we have not measured.
- Pushes to a parent who is not Gonza go out as a `notify` event for the router. Ceci has no phone in Home Assistant today, so her push would go through Telegram, which was not exercised here.
- The plug does not exist yet. Nothing ran on a real warmer.

## The plug to buy

**Shelly Plus Plug IT**, EUR 24.00 list on shelly.com (EUR 16.80 on sale, checked Oct 29 2026). The house already runs one (the bathroom plug), so it fits the sockets and the core Shelly integration in Home Assistant is set up, local, no cloud. The warmer must start when power comes on: a warmer with a dial, not a push button. Once it is in Home Assistant, a small follow-up adds its `switch.` entity to the house tools policy and swaps the virtual switch for it, behind `house.live`. That swap is not built yet.
