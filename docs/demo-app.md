# Public demo app

A phone-first web chat where a visitor talks to the real agent core about Theo, a simulated baby boy a few weeks old, the same baby as the story. Nothing on the page is a real child. Built during the Meta hackathon. Live at https://baby.bygmv.com since Oct 28 2026.

![The demo at 390x844](../results/demo-app/demo-390x844.png)

## What a visitor can do

- Ask about the baby's day: "when did he last eat?", "how much did he drink today?". Answers come from the log through the same `baby_summary` and `read_baby_log` tools the family agent uses.
- Ask "why is he crying?" (a chip). The answer is the likely reason from the log (hungry, tired or a diaper), the same path as the families bot, with no brain call, and always says it is a guess, never a diagnosis. A missing diaper change counts only once the feed started 10 min ago and the last change is 45 min old, so a bottle logged a moment ago never reads as "probably a diaper". When no reason scores 0.4 or more it says nothing in the log points to a likely reason, gives the facts (last feed, last change, awake time) and lists what to check. The answer is tagged "From the log, no AI". Every answer carries a tag: "Muse Spark Open" when the brain wrote it (or "Claude, fallback"), "Fixed reply, no AI" for the emergency line, a refusal or an entry logged by a rule.
- The simulated day keeps going: an entry of the simulated week joins the log once it is over, and a feed or sleep going on now counts for the next feed, so the panel and the night summary say the same next feed. When a feed is late both say "A feed was expected around 02:57, 68 min ago". Once the visitor logs or changes anything the day is theirs and nothing more is added by itself. On Oct 29, a fresh visitor every 10 minutes of the simulated day saw the next feed late in 10 of 144 loads (the baby is between feeds longer than usual), down from 46 of 288 every 5 minutes before the fix, when a feed going on now was dropped. A red flag ("crying and not breathing") still gets the emergency line, and crying with a health question gets the refusal.
- Add entries by text: "bottle 120 ml", "wet and dirty diaper", "he just fell asleep". Only what the visitor said is kept: "bottle 120 ml just now" has no milk type, no start and no length, at the time of the message. Fix or remove them: "that was 90 ml, fix it", "delete the last one". A value no real entry can have, like 9000 ml, a feed longer than 120 min, a sleep longer than 14 hours or a time in the future, is asked about and never logged.
- See what the agent says first: the next feed, the night summary and who is next on duty, computed by the daily rhythm engine from the visitor's own log. During the night (22:00 to 06:00) the summary is the night in progress ("Tonight so far, since Wed 28 22:00"), in the day it is the night that just ended with both dates. Ask "who is up next tonight?" and the agent answers from the `night_rota` tool, which reads the same wake-ups as the panel, so the two always agree.
- Prep mode, the "Before he arrives" tab: the before-he-arrives tools (docs/before-he-arrives.md) on simulated lists, with a due date 47 days from today so the countdown and the list dates always look current. "Show the hospital bag list", "what is next before he arrives?", "where should the crib go?", "we packed the chargers". A message about the hospital bag, the nursery, the crib, the car seat or the due date goes to prep mode from either tab. Real names in the lists read Parent A and Parent B, house device ids are removed, an appointment with an address is not kept, and copying a list to Home Assistant is not in the demo at all.
- Spanish: with a Spanish browser the page is `es-UY` with voseo chips ("Mamadera 120 ml", "¿Por qué llora?"). The agent's own texts follow each message's language, and the brain is asked to answer in it but nothing checks that, so a brain reply can stay in the language of the turn before. The texts that follow the message: the refusal, the emergency line, the edit reply ("nono eran 70" gets "Corregí la mamadera de las 01:07: 90 ml → 70 ml."), the cry reason and the night summary. The "Before he arrives" tab is in Spanish too: the list titles and the simulated items ("Las cédulas de los dos y el carné de la mutualista"), with dates as dd/mm. For a Spanish message the brain reads the lists in Spanish, and a few Spanish words tick an item ("ya guardamos los cargadores"). An item the visitor added keeps their own words. Parent A and Parent B read Persona A and Persona B.
- A link to the page shows a preview card: Open Graph and Twitter tags with the title "Theo's agent, a simulated baby" and a 1200 x 630 card rendered from `parenting_agent/demo/og.svg` (`rsvg-convert -w 1200 -h 630 og.svg -o og.png`), served at `/og.png`.
- Tonight's house (issue #132): a card that runs the real house brain (`parenting_agent/house_brain.py`, `HouseBrain.ask`: the same prompt, plan schema, clock and safety checks and text guards as on the family server) on the visitor's own simulated log, and says Muse Spark Open's plan in plain words: who is on duty, when the bottle warmer pre-heats (silent, water only), white noise with its 50 dB cap and any boost window, quiet doorbell windows, when the floor clean may run, and Muse's one sentence of why. A routine whose times fail the checks says the fixed rule runs. The card carries "Simulated house, nothing moves": the demo's house brain has no day engine, night feed or device to arm, and the image has no device module. "Let me sleep tonight" ("Dejame dormir esta noche") writes the on-duty parent's note into the visitor's log, re-plans through the same trigger the family server uses (a parent asking to sleep is the one case where Muse may move the night), and lists what changed. When Muse errors, its plan is refused or the demo is resting, the card shows the fixed rules and says why. One plan per visitor for each button, a second tap is free. Each Muse plan call counts as one message against the per-visitor and per-connection limits, writes one session row with the internal marking, and its cost goes into the daily spend cap. The chat agent has a `tonight_house` tool that answers "what will the house do tonight?" from the same plan, and re-plans when a parent says they need to sleep. With the fake brain there is no Muse at all and the card shows the fixed rules.
- See what the agent would do in the house. House tools are simulated and every action is labelled "Simulated house" in the chat. The speakers say only fixed sentences ("Could someone bring a clean diaper and wipes, please?"), never free text, so a code typed in a message is never read aloud. Calling the partner shows "Waits for your yes" and the reply names exactly what waits. A yes runs it, simulated, only when it answers that question within 3 minutes. Any other message cancels it, so a stale "ok" runs nothing.
- Health questions get the kind refusal without a brain call. A health message that reports something to keep, a dose already given or a milestone, is logged as a note in the visitor's words, and only the advice part is refused. The reply is built from the log, never from the brain's words.
- The footer says "Built to refuse medical advice. Red flags get: call 911 now." ("Hecho para no dar consejos médicos. Ante una señal de alarma: llamá al 911 ya."). The refusal is a word list plus the prompt, so the page claims what is built, not "never". Since Oct 29 it says "call 911 now" because the agent never calls anyone itself.
- The demo keeps no facts about a visitor. There is no remember tool, so a real name is never saved as the baby's name.

## How it is built

| Part | Code |
|---|---|
| Settings, the environment scrub, reading only the brain key | `parenting_agent/demo/settings.py` |
| Theo's log, the simulated week moved to today, in memory | `parenting_agent/demo/babylog.py` |
| One agent per visitor, spend cap, caps, simulated house tools, the cry reason, the night rota, prep mode, Spanish | `parenting_agent/demo/app.py` |
| Web server and page, standard library only | `parenting_agent/demo/server.py`, `page.html` |
| Tonight's house card, the house brain on the visitor's log | `parenting_agent/demo/tonight.py`, `parenting_agent/house_brain.py`, `parenting_agent/sleep_forecast.py` |
| Session records and the export | `parenting_agent/demo/records.py`, `export_sessions.py` |
| Docker files and the wall check | `deploy/demo/` |
| Deploy, check, rollback, backups | `deploy/public.sh`, `deploy/backup.sh` |

Each visitor gets their own agent with its own bus, an in-memory memory file and a fresh copy of the simulated week (`simweek.generate`, seed 7), with the last day placed on today and nothing in the future. Visitors never share state. "Fresh demo baby" gives the visitor a new copy. Idle visitors are dropped from memory after 6 hours.

## Walled off

- The demo never loads the family env file. `--brain-env FILE` reads only `BASETEN_API_KEY` from it and ignores every other line.
- At start, every variable that could reach the house or holds a secret is removed from the process environment: Home Assistant, Baby Buddy, Telegram, tunnels, tokens and other keys. Only their names are printed.
- The demo has no Baby Buddy client, no Home Assistant client and no channel plug-in. A test checks the demo code imports none of them and that a conversation with the fake brain opens no network connection.
- In Docker (`deploy/demo/compose.yml`) the container sits on an internal network with no gateway and no host address. Its only way out is a proxy that allows HTTPS to `inference.baseten.co` only. A small relay publishes the port on 127.0.0.1 only. No host networking. `deploy/demo/check-wall.sh` probes Home Assistant and Baby Buddy from inside the container after a deploy.

## Caps

| Cap | Default | Setting |
|---|---|---|
| Messages per visitor | 25 (internal visitors are not capped) | `PA_DEMO_MAX_MESSAGES` |
| Messages per connection per day, whatever the cookie | 100 | `PA_DEMO_MAX_CLIENT_MESSAGES` |
| New demo babies per connection per hour (first message or reset) | 10 | `PA_DEMO_MAX_CLIENT_VISITORS` |
| Visitors in memory, then "the demo is full" | 1000 | `PA_DEMO_MAX_VISITORS` |
| A visitor quiet for less than this is never evicted to make room | 10 min | `PA_DEMO_PROTECT_S` |
| Brain spend per UTC day, then "the demo is resting" | $2.00 | `PA_DEMO_DAILY_USD` |
| Messages per day from strangers, a second guard | 1500 | `PA_DEMO_MAX_DAILY_MESSAGES` |
| Message length | 300 characters | `PA_DEMO_MAX_INPUT` |
| Request body | 4 KB of JSON, no uploads, multipart refused | fixed |
| Brain calls at once | 4 | `PA_DEMO_PARALLEL` |

A connection is the address in `CF-Connecting-IP`, which Cloudflare sets on every request through the tunnel and a visitor cannot change (`PA_DEMO_CLIENT_HEADER`, the socket address when unset). An IPv6 address counts by its /64. It is held only as an HMAC under a key made at start, in memory, never stored or logged, and a restart forgets it. Page loads (`GET /api/state`) never create a visitor: a browser with no demo yet sees a fresh copy built once a minute, so cookie-less requests cannot fill the demo or push anyone out (issue #60).

The brain is Muse Spark Open on Baseten, the only model. When a Muse call errors the fixed rules answer, the reply starts by saying the brain is busy, the page tags it "Fixed rules, Muse was busy, no AI", and a `brain_fallback` event counts it. No other vendor's model runs in the demo. Spend is computed from the tokens each call reports: Muse Spark Open $1.25 input and $4.25 output per million tokens (Baseten library page, read Oct 28 2026). What a visitor types goes to Muse on Baseten on the free hackathon credits, and Meta said content on those credits may be used to train future Meta models, which the page says. A call that reports no usage is charged a fallback of 4000 input and 400 output tokens. A local run of 22 brain calls cost $0.006.

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
python -m parenting_agent.demo --brain-env ~/.parenting-agent.env   # Muse Spark Open, the fixed rules when it errors
PA_DEMO_BRAIN=fake python -m parenting_agent.demo                                                  # offline rules
```

Then open http://127.0.0.1:8765 on a phone-sized window. Local visits count as internal.

## On the Vostro

Deployed on Oct 28 2026. Three containers in the compose project `pa-demo`: `pa-demo` (only on the internal network `pa-demo-internal`, isolated gateway, no host address), `pa-demo-egress` (tinyproxy, HTTPS to the brain hosts only) and `pa-demo-edge` (socat, published on 127.0.0.1:4820 only). The Cloudflare tunnel sends `baby.bygmv.com` to that port. Base images are pinned by digest and the images are tagged with the git commit.

- Env file `~/apps/pa-demo.env`, mode 600, two names: `BASETEN_API_KEY` and `PA_DEMO_INTERNAL_SECRET`. `push-env` makes the secret on the Vostro the first time (32 random bytes, hex) and keeps it on later pushes.
- Data `~/apps/pa-demo-data`, owned by the container user (uid 10001), mode 700.
- Backups: `pa-backup.timer` (systemd user unit) copies every SQLite file of the demo and the families service daily at about 04:40 into `~/backups/parenting-agent-public`, keeps 7 days.
- Mark your own browser as internal before testing: open the address in `~/Engineering/gonza/meta-hackathon-2026/internal-url.txt` once. `sh deploy/public.sh demo internal-url FILE` writes it there (mode 600) without printing it. That file is excluded from git like `invites.txt`. Browsers marked with the old `/internal` address before Oct 28 evening are no longer internal.

```bash
sh deploy/public.sh demo push-env     # BASETEN_API_KEY from the meta-hackathon-2026 .env, the internal secret kept or made
sh deploy/public.sh demo internal-url ~/Engineering/gonza/meta-hackathon-2026/internal-url.txt
WALL_EXTRA_TARGETS="192.0.2.10:80 192.0.2.10:22" sh deploy/public.sh demo deploy
sh deploy/public.sh demo check | status | logs 200 | stop | start
sh deploy/public.sh backup install | run
```

A deploy fails, stops the demo and starts the previous commit again when the health check or the wall check fails. The wall check probes every address of the Vostro on ports 22, 80, 8123 and 8790, the family agent's relay, the router, the Mac and the internet, directly and through the proxy, and checks the env holds no secret but the brain key and the internal secret. On Oct 28 all 103 probes were blocked or refused.

## Red team, round 1 (issue #60)

Red-team pass 1 landed 8 attacks on Oct 28. Each is now a test in `tests/test_redteam_r1.py` that replays it, failed on main before the fix and passes after. See `results/redteam/README.md`.
