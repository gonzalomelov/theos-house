# The judge simulator

The real agent core (`parenting_agent/core`) with Muse Spark Open deciding live, on a simulated home. A judge sends the same events the real home sends, with the real entity ids, and watches the house, both phones, the raw event, Muse's tool calls and its memory. The moments from the video are only shortcuts that dispatch those events: nothing holds an outcome, so a second press can go differently. The one recorded input is the car seat video, labelled as a recording.

## Run it locally

Needs `requirements-core.txt`, PostgreSQL and `BASETEN_API_KEY`.

```
python3 scripts/simulator_media.py SOURCE.mp4 data-sim/media/carseat.mp4
PA_DB_URL=postgresql://agent@127.0.0.1:55432/sim PA_SIM_MEDIA=data-sim/media python -m parenting_agent.simulator --port 8781
```

Open http://127.0.0.1:8781. `python3 scripts/simulator_live_eval.py` plays the story against real Muse, checks what it chose, and checks that one event gives different choices in different homes.

## What is real

| Part | Here |
|---|---|
| The agent, LangGraph, PostgreSQL, the safety gate | Real, the same code as at home |
| Every decision and message | Live, by Muse Spark Open on Baseten |
| Home Assistant | The mock MCP server, same tools |
| Phones, Echo | A mock outbox shown on the page |
| Theo, sounds, sensors | Events sent down the same path as real ones |
| Car seat coach | A recording from Meta's glasses kit simulator with a rendered car seat. Muse decides to start it |

## Walls

- One private home per visitor: mock server, outbox, baby log, thread and facts. The session ends after 20 idle minutes or on Start over, and its rows and files are deleted.
- `python -m parenting_agent.simulator` removes every Home Assistant, Telegram and Baby Buddy setting and forces `PA_WORLD=mock` before loading anything.
- The page gets a session cookie only. It never sees a key, and a failure's text stays on the server.
- Limits: 12 sessions at once, 3 per visitor address, 40 moments per session, 280 characters per message.
- On the Vostro, `deploy/simulator/compose.yml` has no route to the home. `deploy/simulator/check-wall.sh` proves it after a deploy.
