# Families: invited parents on Telegram

Invited parents log their own baby on Telegram, through a second bot, each family in its own private log. Built during the Meta hackathon. Issue #40. **Not deployed yet.**

It is a separate service, walled off like the public demo. Other families never reach Gonza's family agent, his Baby Buddy, his Home Assistant or his LAN.

## For parents: your data in 1 minute

- **What is stored.** Your baby's name or nickname and birth date. What you log: feeds, diapers, sleep, baths and notes. Our conversation. Your Telegram chat id, so the bot can answer you. To count real use, one row per message with the time and a scrambled id (a hash of your Telegram id), never the text.
- **Where.** One private file for your family on a small server in Gonza's home in Uruguay. No other family can see it, and it is not mixed with Gonza's own family data.
- **Who else sees the text.** To answer, the conversation text goes to an AI model: Anthropic's Claude for now, Meta's Muse Spark Open later. Neither keeps it or trains on it. Telegram carries the messages, like any Telegram chat.
- **What it never does.** It never gives medical advice. Health questions get a kind refusal and a suggestion to call your pediatrician.
- **How to delete.** Send `/deletemydata`, then `DELETE`. Your family's file, the conversation, the counting rows and both parents' access are removed at once. The other parent gets a message that it happened.

The bot sends the same text when a parent sends `/privacy`.

## The invite flow

1. Gonza makes a code on the server: `docker exec pa-families python -m parenting_agent.families invite --count 3`. Each code is 8 characters, single use, valid 7 days, and only its hash is stored. With `PA_FAMILIES_BOT_USERNAME` set, each line also has a `https://t.me/<bot>?start=<code>` link that opens the bot with the code filled in.
2. The parent taps the link, or sends `/start K7QM3XPA` to the bot.
3. Three questions: the baby's name or nickname, the birth date (`2026-10-12` or `12/10/2026`, never in the future), and whether the other parent should log too. A yes gives a second code for the other parent, who joins the same log with no questions.
4. The parent is logging. In the tests the whole flow is 4 messages.

Without a valid code the bot replies politely that it is a private beta and stores nothing: no row, no file. After 5 wrong codes in a day from the same Telegram account it stops checking codes for that account until the next day (kept in memory only). Group chats get "please message me directly". The beta holds 20 families at most (`PA_FAMILIES_MAX_FAMILIES`) and 4 people per family.

For Gonza's own test accounts: `invite --internal` makes a code whose parent, and the partner they invite, are marked internal. `PA_FAMILIES_INTERNAL_USERS` (Telegram user ids, comma separated) does the same by account.

## What a family can do

| Message | What happens |
|---|---|
| `bottle 120 ml`, `left breast 15 min`, `wet and dirty diaper`, `she fell asleep`, `she woke up`, `bath done` | A log entry in the family's own file, never timed in the future |
| `when did she last eat?`, `how much did she drink today?` | Answered from the family's log through `baby_summary` and `read_baby_log` |
| Health questions | The existing kind refusal, without a brain call |
| `/summary` | Today so far, computed from the log, no brain call |
| `/next` | The next feed from the rhythm engine (`patterns.next_feed`) |
| `/invite` | A code for the other parent |
| `/reminders off`, `/reminders on` | Next feed reminders |
| `/privacy` | The privacy note above |
| `/deletemydata` then `DELETE` | Wipes the family. Anything else cancels, and the confirmation expires after 10 minutes |

The bot speaks first twice: a next feed reminder about 10 minutes before the feed the rhythm engine expects, sent once per feed to every parent, only when the last feed is less than 8 hours old. And a daily summary at 20:00 local time, once a day, only when something was logged that day. Both pass the rhythm engine's `no_advice` check.

## How it is built

| Part | Code |
|---|---|
| Settings, the environment scrub, reading only the brain key and the bot token | `parenting_agent/families/settings.py` |
| Registry, session rows, spend | `parenting_agent/families/store.py` |
| One SQLite file per family: log, conversation, facts | `parenting_agent/families/babylog.py` |
| Invite gate, onboarding, commands, caps, reminders, summaries | `parenting_agent/families/service.py` |
| Telegram long polling and the reminder clock | `parenting_agent/families/bot.py` |
| `run`, `invite`, `check` | `parenting_agent/families/__main__.py` |
| Session export for the scorer | `parenting_agent/families/export_sessions.py` |
| Docker files, not deployed | `deploy/families/` |

Each family gets its own agent with its own bus and its own file, `family-<id>.sqlite` in the data folder, opened by nothing else. The tools are only `log_baby_event`, `read_baby_log`, `baby_summary`, `remember` and `current_time`. There is no Baby Buddy client, no Home Assistant client, no house tool, no channel router and no sitter role in the service. The Telegram adapter is the one from `parenting_agent/channels/telegram.py`, standard library only, so no new package was added.

## Walled off

- The service never loads the family env file. `--keys-env FILE` reads only `ANTHROPIC_API_KEY`, `BASETEN_API_KEY` and `TELEGRAM_FAMILIES_BOT_TOKEN`.
- At start, every variable that could reach the house or holds another secret is removed from the environment, including Gonza's own `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Only their names are printed.
- It refuses to start when the families token equals the family bot's token, or when `getMe` says the token belongs to `@home_agent_example_bot`.
- In Docker (`deploy/families/compose.yml`) the container sits only on an internal network with no gateway and no host address. Its one way out is a proxy that allows HTTPS to `api.anthropic.com`, `inference.baseten.co` and `api.telegram.org`. Nothing is published and nothing is on the Cloudflare tunnel, the bot long-polls. It never joins `babybuddy-net`, `home-assistant_default` or `parenting-agent-internal`. No host networking.
- `deploy/families/check-wall.sh` proves it from inside after a deploy.

## Caps

| Cap | Default | Setting |
|---|---|---|
| Messages per family per UTC day, then "back tomorrow" | 150 | `PA_FAMILIES_MAX_MESSAGES` |
| Brain spend per family per UTC day | $0.50 | `PA_FAMILIES_FAMILY_USD` |
| Brain spend for the whole service per UTC day | $3.00 | `PA_FAMILIES_DAILY_USD` |
| Message length | 500 characters | `PA_FAMILIES_MAX_INPUT` |
| Families | 20 | `PA_FAMILIES_MAX_FAMILIES` |
| Wrong invite codes per account per day | 5 | `PA_FAMILIES_MAX_BAD_CODES` |

Over a spend cap the service does not go silent: the free rule-based brain takes over, so "bottle 120 ml" and "when did she last eat?" keep working until the next day. Spend is priced like the demo (Claude Haiku 5.5, $0.10 and $0.50 per million tokens). A local run of onboarding, 4 messages through Claude, a refusal and a summary cost $0.002.

## Session records for the real-user scorer

`families.sqlite` in the data folder, table `sessions(ts TEXT ISO8601 UTC, visitor_id TEXT, channel TEXT, kind TEXT, internal INTEGER, family_id TEXT)`.

- One row per message a joined parent sends, including the onboarding answers. Strangers, too long messages and messages over the family cap write no row.
- `visitor_id` is the sha256 of the Telegram user id. `channel` is `telegram`, `kind` is `family`, `family_id` is a random 16 hex id.
- `internal` is 1 for Gonza's test accounts (see the invite flow).
- No message text is stored in this file.

```bash
python -m parenting_agent.families.export_sessions                 # JSON lines, oldest first, with family_id
python -m parenting_agent.families.export_sessions --db other/families.sqlite
```

The demo export prints the same columns without `family_id`, and also prints `family_id` if a table has it. `measure-kr222.sh` reads one stream, so on the Vostro both exports are chained:

```bash
KR222_EXPORT_CMD='ssh vostro "docker exec pa-demo python -m parenting_agent.demo.export_sessions; docker exec pa-families python -m parenting_agent.families.export_sessions"' \
  your-scorer.sh
```

Checked on Oct 28 with a simulated export: 3 parents on 3 days, 1 parent on 2 days and 1 internal parent scored "parents 2/3", the internal rows were not counted, and the chained demo and families exports scored together. The scorer's default command names the container `parenting-demo` while `deploy/demo/compose.yml` names it `pa-demo`, so set `KR222_EXPORT_CMD` as above until the scorer is updated.

## Deploy, when Gonza says go

Not done in issue #40. Run from the Mac in a clean checkout of main.

1. Create the second bot with @BotFather (Gonza's assistant does this). Keep the token only in the env file below. Send `/setjoingroups` to BotFather and pick Disable, so the bot cannot be added to groups.
2. Write `~/apps/pa-families.env` on the Vostro, mode 600, with only these names: `ANTHROPIC_API_KEY`, `TELEGRAM_FAMILIES_BOT_TOKEN`, `PA_FAMILIES_BOT_USERNAME`, `PA_FAMILIES_INTERNAL_USERS`. Never print the values. See `deploy/families/env.example`.
3. Pin the three base images in `deploy/families/` by digest.
4. `mkdir -m 700 ~/apps/pa-families-data` and create the network:
   `docker network create --internal --ipv6=false -o com.docker.network.bridge.gateway_mode_ipv4=isolated pa-families-internal`
5. `docker compose --env-file ~/apps/pa-families.env -f deploy/families/compose.yml up -d --build`
6. `deploy/families/check-wall.sh <HA host:port> <Baby Buddy host:port> <Vostro LAN ip>:22`. Every target must say blocked and the proxy must refuse everything but the brain and Telegram.
7. `docker exec pa-families python -m parenting_agent.families check`
8. One internal run: `invite --internal`, onboard from Gonza's phone, log a bottle, ask a question, `/deletemydata`.
9. Gonza makes the invites and sends them himself.

Logs: `docker logs pa-families` shows counts and error types only, never message text or tokens. Stop: `docker compose -f deploy/families/compose.yml down`. The data stays in `~/apps/pa-families-data`.
