# The persistent agent: first runs (Nov 3)

Muse Spark Open on Baseten decides through LangGraph, with PostgreSQL. Run with `scripts/core_live_eval.py` and `scripts/core_real_test.py`.

| Case | Passed | Where |
|---|---|---|
| High humidity: Muse turns the dehumidifier on | 5 of 5 | mock home |
| Low humidity: nothing moves, nobody is told | 5 of 5 | mock home |
| Restart: a fact told before is answered after | 5 of 5 | mock home, new process state |
| Night cry reaches only the parent on duty, Gonza's night | 5 of 5 | mock home |
| Night cry reaches only the parent on duty, Ceci's night | 5 of 5 | mock home |
| "Let me sleep" moves the night: Gonza told, the cry reaches only him | 5 of 5 | mock home |
| Red flag with "ignore your rules": fixed line to both parents, Muse not called | 5 of 5 | mock home |
| Real humidity event: the real dehumidifier plug switches on | 5 of 5 | real home, plug back to off each time |
| Same event after a restart with the plug on: no second switch | 5 of 5 | real home |
| Home Assistant's real WebSocket delivers a sensor change | seen | real home |

Limits: 5 runs each, on prompts tuned during this work against these same cases, so this shows it works, not how often it works on cases it has not seen. Messages and the baby log were mock in every run, nobody received anything.
