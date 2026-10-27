# Simulated full day

Issue #17. The day from the plan page, replayed end to end through the real agent, in one command:

```bash
python -m parenting_agent.fullday
```

## The day

| Time | Step | What runs | Passes when |
|---|---|---|---|
| 06:10 | Bottle by voice | "bottle, 120 ml" as a message on the ear channel, through the brain into Baby Buddy | a 120 ml feeding is logged and read back by id |
| 06:40 | Changing table | the changing-table clips streamed in real time through the skill (local reflex, SAM 3.1 confirm on the Mac GPU), then "that was a dirty diaper" | every both-hands-off moment is spoken within 2.5 s, the one-hand clip stays silent, a dirty diaper is logged |
| 09:15 | Doorbell during a change | a doorbell sound event reaches the agent as an observation, with a courier asking to sign | the agent says "one moment" on the speaker and asks the parent before replying to the visitor |
| 13:00 | Unusual nap note | a nap 40 min longer than the simulated week's usual daytime nap | the note says so plainly, passes the no-advice check and is delivered on Telegram |
| 18:30 | Bath | the generated bath clip streamed through the bath skill, the bath logged as a note | the chime comes within 1 s and "hand" within 2.5 s, calling the partner waits for a yes |
| 20:00 | Question | "When was the last dirty diaper?" on Telegram | the answer names the time of the dirty diaper from 06:40 |
| 02:30 | Night feed | the night feed starts (observation), then "night feed, 90 ml bottle" | the lights are dimmed, 90 ml is logged, the next feed and the next parent on duty are told |

## The clock

The day is compressed into the few minutes the run takes. Every Baby Buddy entry is timed at the real moment its step ran, so nothing is in the future, and the report shows both the day's time and the real time. The next feed at 02:30 comes from the simulated week's feed rhythm put on the day's clock, since the compressed day itself has no real gaps. Every entry carries the tag `full-day-sim`, and each run wipes the previous run's entries first.

## Dry run, never faked

| Not built yet | How it shows |
|---|---|
| Home Assistant actions (#9) | `house_dry` events and "Home Assistant dry run" in the report. The token is pending, nothing is switched |
| Telegram, ear and speaker delivery (#3, #8) | replies and reminders carry their intended channel, the report says delivery is logged only |
| House sound detector (#14) | the doorbell is a scripted sound event, marked as such |

## Output

- `results/fullday/day.md`: the timeline table, one row per step, with pass, fail or pending.
- `results/fullday/day.json`: the same with the agent's replies and the evidence per step.
- `results/fullday/kr222/`: `table.json`, `voice-log.json` and `reminder.json` in the schema of `measure-kr222.sh`. Check them with `measure-kr222.sh --fixture results/fullday/kr222`.
