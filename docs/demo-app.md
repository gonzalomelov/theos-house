# Public demo app

A phone-first web chat where a visitor talks to the real agent core about Demo Baby, a simulated baby. Built during the Meta hackathon. Live at https://baby.bygmv.com since Oct 28 2026.

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
| Docker files and the wall check | `deploy/demo/` |
| Deploy, check, rollback, backups | `deploy/public.sh`, `deploy/backup.sh` |

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

The brain is Muse Spark Open on Baseten, with Claude Haiku 5.5 only when a Muse call errors (a `brain_fallback` event). Spend is computed from the tokens each call reports, at the price of the brain that answered: Muse Spark Open $1.25 input and $4.25 output per million tokens (Baseten library page, read Oct 28 2026), Claude Haiku 5.5 $0.10 and $0.50 (Anthropic pricing page, read Oct 28 2026). A call that reports no usage is charged a fallback of 4000 input and 400 output tokens. A local run of 22 brain calls cost $0.006.

## Session records for the real-user scorer

SQLite at `data/demo_sessions.sqlite`, table `sessions(ts TEXT ISO8601 UTC, visitor_id TEXT, channel TEXT, kind TEXT, internal INTEGER)`.

- One row per visitor message the demo takes in: answered, refused, resting or busy. Empty, too long and over-the-limit messages write no row.
- `ts` is UTC like `2026-10-28T18:34:17+00:00`. `channel` is `web`. `kind` is `demo`.
- `visitor_id` is the sha256 of a random first-party cookie `pa_vid`. Never an IP, and no IP is logged anywhere.
- `internal` is 1 when the browser has the internal cookie (visit `/internal/<secret>` once) or the request comes from localhost with no proxy headers. The secret is `PA_DEMO_INTERNAL_SECRET`, and the cookie holds a signature of it, never the secret, so a cookie made by hand does not count and a new secret unmarks every browser. Plain `/internal`, a wrong secret and any other `/internal/...` address answer a 404. With the secret unset or shorter than 32 characters, every `/internal` address is a 404. A request that came through a proxy (`X-Forwarded-For`, `CF-Connecting-IP`, `Forwarded`, `X-Real-IP`) is not treated as localhost.
- No message text is stored. The same file also holds a `spend` table that the scorer ignores.

```bash
python -m parenting_agent.demo.export_sessions          # JSON lines, oldest first
python -m parenting_agent.demo.export_sessions --db other/demo_sessions.sqlite
```

## Run it locally

```bash
python -m parenting_agent.demo --brain-env ~/.parenting-agent.env   # Muse Spark Open, Claude fallback
PA_DEMO_BRAIN=fake python -m parenting_agent.demo                                                  # offline rules
PA_DEMO_BRAIN=claude python -m parenting_agent.demo --brain-env ...                                # Claude Haiku alone, for comparison
```

Then open http://127.0.0.1:8765 on a phone-sized window. Local visits count as internal.

## On the Vostro

Deployed on Oct 28 2026. Three containers in the compose project `pa-demo`: `pa-demo` (only on the internal network `pa-demo-internal`, isolated gateway, no host address), `pa-demo-egress` (tinyproxy, HTTPS to the brain hosts only) and `pa-demo-edge` (socat, published on 127.0.0.1:4820 only). The Cloudflare tunnel sends `baby.bygmv.com` to that port. Base images are pinned by digest and the images are tagged with the git commit.

- Env file `~/apps/pa-demo.env`, mode 600, three names: `BASETEN_API_KEY`, `ANTHROPIC_API_KEY` (the fallback) and `PA_DEMO_INTERNAL_SECRET`. `push-env` makes the secret on the Vostro the first time (32 random bytes, hex) and keeps it on later pushes.
- Data `~/apps/pa-demo-data`, owned by the container user (uid 10001), mode 700.
- Backups: `pa-backup.timer` (systemd user unit) copies every SQLite file of the demo and the families service daily at about 04:40 into `~/backups/parenting-agent-public`, keeps 7 days.
- Mark your own browser as internal before testing: open the address in `~/Engineering/gonza/meta-hackathon-2026/internal-url.txt` once. `sh deploy/public.sh demo internal-url FILE` writes it there (mode 600) without printing it. That file is excluded from git like `invites.txt`. Browsers marked with the old `/internal` address before Oct 28 evening are no longer internal.

```bash
sh deploy/public.sh demo push-env     # BASETEN_API_KEY and ANTHROPIC_API_KEY from the meta-hackathon-2026 .env, the internal secret kept or made
sh deploy/public.sh demo internal-url ~/Engineering/gonza/meta-hackathon-2026/internal-url.txt
WALL_EXTRA_TARGETS="192.0.2.10:80 192.0.2.10:22" sh deploy/public.sh demo deploy
sh deploy/public.sh demo check | status | logs 200 | stop | start
sh deploy/public.sh backup install | run
```

A deploy fails, stops the demo and starts the previous commit again when the health check or the wall check fails. The wall check probes every address of the Vostro on ports 22, 80, 8123 and 8790, the family agent's relay, the router, the Mac and the internet, directly and through the proxy, and checks the env holds no secret but the brain key and the internal secret. On Oct 28 all 103 probes were blocked or refused.
