# Daily rhythm and night shifts (issue #7)

The agent learns the baby's pattern from the log and speaks first. Built during the Meta hackathon, Oct 27 2026.

## What it does

- **Next feed.** Estimates the next feed from the last two gaps between feeds and warns 20 minutes before it. On the simulated week the estimate is off by 20.8 min on average over 66 feeds.
- **Unusual days.** Notes full days that differ from the rest of the log: feeds much closer together than usual, or much more or less sleep. Notes state facts from the log only. Every text passes `no_advice()`, which refuses advice and health words.
- **Night shifts.** Reads who handled each night wake-up and picks who is on duty next: fewer wake-ups so far wins, a tie goes to whoever did not take the last one. Over the simulated week the wake-ups alternate, 12 for Parent A and 11 for Parent B.
- **Night summary.** In the morning: the night's feeds, the longest sleep, wake-ups per parent, who is on duty next and the next expected feed.

Each reminder fires once, carries the log entries it was computed from, and is spoken through the agent on one channel (`telegram` by default, also `ear`, `speaker`, `partner_phone`). A `proactive` event records it on the bus with `asked: false`. Real delivery on those channels comes with the channel issues (#3, #8).

## Code

- `parenting_agent/rhythm/log.py`: read-only views of the log. `FixtureLog` for tests, `BabyBuddyLog` for Baby Buddy (GET requests only, optional tag filter).
- `parenting_agent/rhythm/patterns.py`: next feed, unusual days, night wake-ups, shift splitting, night summary, the no-advice guard.
- `parenting_agent/rhythm/engine.py`: `Rhythm.tick(now)` returns what is due, `RhythmPlugin` runs it on the agent on a timer, `deliver()` speaks it.
- `parenting_agent/rhythm/__main__.py`: replays the log's last day and writes `results/kr222/reminder.json`.

## Run

```bash
python3 -m unittest discover -s tests -p test_rhythm.py -v          # per-feed errors, notes, shifts per night
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro                   # Baby Buddy tunnel
python3 -m parenting_agent.rhythm --source babybuddy --out results/kr222/reminder.json
```

To run it inside the agent, add `"parenting_agent.rhythm.engine:RhythmPlugin"` to `plugins` in the agent config, with settings under `"rhythm"` (for example `{"channel": "telegram", "lead_min": 20, "summary_at": "07:30", "notes_at": "20:00"}`).
