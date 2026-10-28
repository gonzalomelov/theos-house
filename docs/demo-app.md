# Public demo app

A phone-first web chat where a visitor talks to the real agent core about Demo Baby, a simulated baby. Built during the Meta hackathon. It runs locally only. It goes public only after Gonza says "OK public".

![The demo at 390x844](../results/demo-app/demo-390x844.png)

## What a visitor can do

- Ask about the baby's day: "when did she last eat?", "how much did she drink today?". Answers come from the log through the same `baby_summary` and `read_baby_log` tools the family agent uses.
- Add entries by text: "bottle 120 ml", "wet and dirty diaper", "she just fell asleep".
- See what the agent says first: the next feed, the night summary and who is next on duty, computed by the daily rhythm engine from the visitor's own log.
- See what the agent would do in the house. House tools are simulated and every action is labelled "Simulated house" in the chat. Calling the partner shows "Waits for your yes" and runs, simulated, only after the visitor says yes.
- Health questions get the same kind refusal as the family agent, without a brain call.

## How it is built

| Part | Code |
|---|---|
| Settings, the environment scrub, reading only the brain key | `parenting_agent/demo/settings.py` |
| Demo Baby's log, the simulated week moved to today, in memory | `parenting_agent/demo/babylog.py` |
| One agent per visitor, spend cap, caps, simulated house tools | `parenting_agent/demo/app.py` |
| Web server and page, standard library only | `parenting_agent/demo/server.py`, `page.html` |
| Session records and the export | `parenting_agent/demo/records.py`, `export_sessions.py` |
| Docker files for the Vostro later, not deployed | `deploy/demo/` |

Each visitor gets their own agent with its own bus, an in-memory memory file and a fresh copy of the simulated week (`simweek.generate`, seed 7), with the last day placed on today and nothing in the future. Visitors never share state. "Fresh demo baby" gives the visitor a new copy. Idle visitors are dropped from memory after 6 hours.

## Walled off

- The demo never loads the family env file. `--brain-env FILE` reads only `ANTHROPIC_API_KEY` or `BASETEN_API_KEY` from it and ignores every other line.
- At start, every variable that could reach the house or holds a secret is removed from the process environment: Home Assistant, Baby Buddy, Telegram, tunnels, tokens and other keys. Only their names are printed.
- The demo has no Baby Buddy client, no Home Assistant client and no channel plug-in. A test checks the demo code imports none of them and that a conversation with the fake brain opens no network connection.
- In Docker (`deploy/demo/compose.yml`) the container sits on an internal network with no gateway and no host address. Its only way out is a proxy that allows HTTPS to `api.anthropic.com` and `inference.baseten.co`. A small relay publishes the port on 127.0.0.1 only. No host networking. `deploy/demo/check-wall.sh` probes Home Assistant and Baby Buddy from inside the container after a deploy.

## Caps

| Cap | Default | Setting |
|---|---|---|
| Messages per visitor | 25 (internal visitors are not capped) | `PA_DEMO_MAX_MESSAGES` |
| Brain spend per UTC day, then "the demo is resting" | $2.00 | `PA_DEMO_DAILY_USD` |
| Messages per day from strangers, a second guard | 1500 | `PA_DEMO_MAX_DAILY_MESSAGES` |
| Message length | 300 characters | `PA_DEMO_MAX_INPUT` |
| Request body | 4 KB of JSON, no uploads, multipart refused | fixed |
| Brain calls at once | 4 | `PA_DEMO_PARALLEL` |

Spend is computed from the tokens each brain call reports, at Claude Haiku 5.5 prices ($0.10 input and $0.50 output per million tokens, Anthropic pricing page read on Oct 28 2026). A call that reports no usage is charged a fallback of 4000 input and 400 output tokens. A local run of 22 brain calls cost $0.006.

## Session records for the real-user scorer

SQLite at `data/demo_sessions.sqlite`, table `sessions(ts TEXT ISO8601 UTC, visitor_id TEXT, channel TEXT, kind TEXT, internal INTEGER)`.

- One row per visitor message the demo takes in: answered, refused, resting or busy. Empty, too long and over-the-limit messages write no row.
- `ts` is UTC like `2026-10-28T18:34:17+00:00`. `channel` is `web`. `kind` is `demo`.
- `visitor_id` is the sha256 of a random first-party cookie `pa_vid`. Never an IP, and no IP is logged anywhere.
- `internal` is 1 when the browser has the cookie `pa_internal=1` (visit `/internal` once) or the request comes from localhost with no proxy headers. A request that came through a proxy (`X-Forwarded-For`, `CF-Connecting-IP`, `Forwarded`, `X-Real-IP`) is not treated as localhost.
- No message text is stored. The same file also holds a `spend` table that the scorer ignores.

```bash
python -m parenting_agent.demo.export_sessions          # JSON lines, oldest first
python -m parenting_agent.demo.export_sessions --db other/demo_sessions.sqlite
```

## Run it locally

```bash
python -m parenting_agent.demo --brain-env ~/.parenting-agent.env   # Claude stand-in
PA_DEMO_BRAIN=fake python -m parenting_agent.demo                                                  # offline rules
PA_DEMO_BRAIN=baseten python -m parenting_agent.demo --brain-env ...                               # Muse Spark Open, when the credits land
```

Then open http://127.0.0.1:8765 on a phone-sized window. Local visits count as internal.

## Before it goes public

- Gonza says "OK public".
- Pin the base images in `deploy/demo/` by digest, create the internal network, deploy on the Vostro, run `check-wall.sh` with the Home Assistant and Baby Buddy addresses.
- Point a hostname at the relay through the Cloudflare tunnel, and set `PA_DEMO_SECURE_COOKIE=1` (the Dockerfile already does).
