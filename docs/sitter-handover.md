# Sitter handover (issue #16)

One message briefs a grandparent or a sitter. Built during the Meta hackathon, Oct 28 2026.

## What it does

A parent says "my mom is watching him tonight from 19:00 to 23:00". The brain calls `sitter_handover` and the agent writes a short handover in plain words from the log and the rhythm:

| Part | Where it comes from |
|---|---|
| Last feed, how much, today's feeds and bottle ml | The baby log |
| Next feed expected | The daily rhythm's next-feed estimate |
| Asleep now, usual evening sleep | The log: the median first sleep inside the window's hours on earlier days |
| Last diaper, last dirty one | The log |
| Anything unusual today | Notes logged today, and the rhythm's unusual-day note for yesterday |
| Where things are, how to reach us, the pediatrician's number | The family notes file, its `handover` block only |

The draft goes to the parent first, on the parent's channel (Telegram). Nothing goes to the sitter on the agent's word.

## Safety

- No medical advice, no dosage, no treatment. Every line of the brief passes the rhythm's `no_advice()`, the cry reason's `no_medical()` and a dosage guard. A line in the family notes that mentions medicine or a dose is left out, and the parent is told to pass it on in person.
- The only health text is a fixed footer: call the parents first, then the pediatrician, and the emergency number.
- `send_handover_to_sitter` is never on the allowed list. If a config puts it there, the plug-in takes it off. Each send waits for the parent's yes, one send per yes.
- In this build there is no sitter adapter. The send path runs only with a fake messenger in the tests. Sending to a real third party needs Gonza's explicit OK each time.

## Guest role

During the window the sitter is a guest with five tools: `log_feed`, `log_diaper`, `baby_summary`, `handover_brief` and `current_time`. Anything else is refused by name, never queued for a yes, so a guest can never approve a parent's pending action. Outside the window nothing runs. A health question never reaches the brain: the guest gets a fixed answer that points to the parents and the pediatrician, and the question goes into the parents' summary.

When the window ends the parents get a short summary on their channel: what the sitter logged, how many questions, any health questions, any refused tools.

## Family notes

The parents keep `data/family-notes.json` (git-ignored, on the machine that runs the agent). `config/family-notes.example.json` shows the shape with placeholder numbers and is used when the real file is missing. Only `baby_name`, `pronoun` and the `handover` block are read.

## Run

```bash
.venv/bin/python -m unittest tests.test_sitter -v             # numbers against the log, guest role, window end, no medical content
.venv/bin/python scripts/sitter_brief_run.py                  # the real brain on the simulated week, prints the draft
.venv/bin/python scripts/sitter_brief_run.py --send           # also one Telegram message to the parent's chat, prefixed "Test:"
```

The run script sends with one Bot API `sendMessage` call and never polls, so it does not compete with the always-on agent. Results in `results/sitter/run.json`.

To run it inside the agent, add `"parenting_agent.sitter:SitterHandover"` to `plugins` and `"sitter_handover"` to `allowed_tools`, with settings under `"sitter"` (for example `{"family_notes": "data/family-notes.json", "parent_channel": "telegram"}`).
