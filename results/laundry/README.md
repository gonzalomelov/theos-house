# Daily baby laundry, simulated (issue #111)

Built and run on Oct 29 2026, inside the event. The washer plug is a virtual dry-run power sensor, `house.live` is false and the run had no Home Assistant token, so every push was a dry run. Zero live house calls.

Code: `parenting_agent/laundry.py`, `parenting_agent/virtual_devices.py`. Tests: `tests/test_home_automations.py` (`LaundryTest`). Run: `.venv/bin/python scripts/laundry_sim.py`.

## What it does

- **Cycle.** Running once the plug reads at least 8 W for a minute. Finished once it stays under 3 W for 6 minutes. A cycle under 15 minutes (the door lock, a blip) is dropped.
- **Pushes.** At the start: "Washer started. If it is the baby's laundry, say "baby load"." At the end: "Washer done after N min: move the laundry to the dryer." At 19:00, once a day, when no baby load ran that day: "No baby load today yet. About N clean bodysuits left."
- **Clean bodysuits.** A simple count. It starts from the stock (12 by default, or what the parents say). It goes down by one per day, and by one for each log entry that mentions a blowout, a leak, spit-up, or a bodysuit or outfit change. When a baby load finishes, the count is back to the stock. The parents correct it by saying how many are clean (`set_clean_bodysuits`), which resets the count there.
- **Tools for the agent.** `laundry_status`, `mark_baby_load` (the parent says "baby load"), `set_clean_bodysuits`. They change only the agent's own count, nothing in the house.
- With `"source": "home_assistant"` the watts are read, read only, from the plug's power sensor. A test checks the read makes no service call.

## Detection on synthetic washes (`detection.json`)

300 synthetic washes (seed 29). The shape is an assumption, not a measured washer: fill 2 to 5 min at 5 to 15 W, heat 0 to 25 min at 1800 to 2200 W, 4 to 8 drum phases of 5 to 12 min at 80 to 500 W, each followed by a quiet pause of 1 to 5 min at 0.5 to 4 W, a spin of 6 to 15 min, then standby. Each wash also gets a door-lock blip of 1 to 4 min at 20 to 40 W.

| Quiet that ends a cycle (end_min) | One start and one finish | Ended too early | Missed | Blips counted as a load | Finish pushed after |
|---|---|---|---|---|---|
| 2 min | 58 of 300 | 242 | 0 | 0 | 2 min |
| 3 min | 158 of 300 | 142 | 0 | 0 | 3 min |
| 4 min | 236 of 300 | 64 | 0 | 0 | 4 min |
| 5 min | 300 of 300 | 0 | 0 | 0 | 5 min |
| **6 min (default)** | **300 of 300** | **0** | **0** | **0** | **6 min** |
| 8 min | 300 of 300 | 0 | 0 | 0 | 8 min |

The start was seen a median of 2 minutes after the wash began. 6 minutes is the default because the assumed pauses go up to 5 minutes, and 5 minutes sits right at that edge. A real washer can pause longer (a soak program). The first real wash on the plug sets this number.

## Two simulated days (`two-days.json`)

The simulated week's log for Oct 21 and 22, with four added notes, labeled `[simulated laundry]`: spit-up at 08:40, a blowout at 13:15, spit-up on the bodysuit at 17:50, an outfit change after a leak on Oct 22 at 07:30. Stock 12 from 07:00 on Oct 21.

| Time | What happened |
|---|---|
| Oct 21 09:13 | Washer started (power since 09:12). Push asks if it is a baby load. Nobody says so |
| Oct 21 11:01 | Finished after 103 min. Push: "Washer done after 103 min: move the laundry to the dryer." |
| Oct 21 19:00 | No baby load that day. Push: "No baby load today yet. About 9 clean bodysuits left." |
| Oct 22 10:11 | Washer started |
| Oct 22 10:20 | Voice through the bridge: "baby agent, baby load". Agent: "mark baby load: the running load is the baby's, bodysuits count clean again when it finishes." |
| Oct 22 11:59 | Finished after 103 min. Move-to-dryer push. Bodysuits back to 12 |
| Oct 22 19:00 | Reminder skipped, a baby load ran that day |

Clean bodysuits through the two days: 12 at 08:00, 11 at 12:00, 9 at 18:00 and 22:00, 7 at 08:00 the next day (one for the new day, one for the leak), 12 after the baby load. Five pushes, all dry.

The rule-based test brain reads back only the first sentence of a tool result, so the voice status answer was "Washer idle." The tool's own answer at the end was "Washer idle. Loads today: 10:10 baby. Baby load today: yes. Clean bodysuits: about 12."

## Honest limits

- The washer power shapes are synthetic. Nothing ran on a real washer.
- "Baby load" needs the parent's word. A load nobody marks counts as household laundry.
- The bodysuit count follows words in the log. A bodysuit changed without a note is missed until the parents correct the count.

## The plug to buy

**Shelly Plus Plug IT**, EUR 24.00 list on shelly.com (EUR 16.80 on sale, checked Oct 29 2026). 16 A with power metering, enough for a washer heating at about 2 kW. The 12 A Shelly Plug S Gen3 (EUR 23.68) is too close to a washer heater. Same plug as the one already in the bathroom, local, through the core Shelly integration Home Assistant already runs. Its power sensor goes in `laundry.power_entity` with `"source": "home_assistant"`.
