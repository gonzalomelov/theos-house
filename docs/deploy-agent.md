# The agent on the Vostro, always on

The family's private agent runs 24/7 on the Vostro, next to Baby Buddy and Home Assistant, so it keeps working when the Mac is closed. Deployed on Oct 28 2026 during the hackathon (issue #15). Heavy vision (SAM 3.1) stays on the Mac.

## How it runs

Three containers in the compose project `parenting-agent` (`deploy/compose.yml`):

| Container | What it is | Networks |
|---|---|---|
| `parenting-agent` | The agent core, `python -m parenting_agent --config config/agent.vostro.json`. Standard library only | `parenting-agent-internal` only |
| `parenting-agent-relay` | nginx, forwards `relay:8790` to Baby Buddy and `relay:8123` to Home Assistant, nothing else | internal, `babybuddy-net`, `home-assistant_default` |
| `parenting-agent-egress` | tinyproxy, HTTPS tunnels only, to `inference.baseten.co` and `api.telegram.org` (`deploy/egress/filter`) | internal, its own bridge |

- Images: `python:3.12-slim-bookworm`, `nginxinc/nginx-unprivileged` and `alpine` with tinyproxy, each pinned by digest. The agent and egress images are built on the Vostro and tagged with the git commit.
- Restart `unless-stopped`, read-only root, all capabilities dropped, no new privileges, user 1000, 256 MB, half a CPU, 64 processes.
- Health check: the heartbeat plug-in (`parenting_agent/agent/heartbeat.py`) writes `/data/heartbeat.json` every 30 s while the decide-act loop is alive. Docker marks the container unhealthy when the file is older than 90 s. The check reads the file with the standard library only (`python -I -S`), because importing `parenting_agent` took 5.5 s inside the 0.5 CPU container on Oct 29, over the 5 s timeout, and the container showed unhealthy while the agent ran. If the loop thread dies, the plug-in ends the process with exit code 1 so the restart policy brings it back.
- Data: `~/apps/parenting-agent-data` on the Vostro, mounted at `/data`: `memory.sqlite`, `events.jsonl`, `heartbeat.json`, `reminders.json` (open reminders).
- Logs: Docker's json-file driver, 10 MB per file, 3 files.
- Plug-ins on the Vostro: the heartbeat, the Telegram channel (#3), the prep mode with the morning nudge (#56, `docs/before-he-arrives.md`), the day engine, the night feed, the house brain, reminders, the next feed reminders (`rhythm.engine:RhythmPlugin`, since Oct 30), the sitter brief (`sitter:SitterHandover`, since Oct 30) and the family push and the voice bridge (the Echo, read only for a guest, since Oct 31). No console (no terminal there) and no changing table (vision runs on the Mac).
- Before the birth, `"baby": {"born": false}` keeps every routine that reads the baby log silent (`parenting_agent/baby_phase.py`): the log is the test child "Test Baby". At birth set it to true and point `baby_log.child` and `rhythm.child` at Theo. `results/e2e-day/` runs a full day with it set to true.
- Door: `day_engine.door_sensors` is empty, so a camera's person detection doesn't count as someone at the door.
- No channel router on the Vostro. Replies to a Telegram message go back to the chat that asked. Pushes the agent starts on its own go through the family push (`parenting_agent/channels/push.py`) to Gonza's or Ceci's chat, or both, by the table in `docs/before-he-arrives.md`. The router picks the home speaker when the parent is home, and on the Vostro that would be a live house action, so it stays on the Mac until #9.

### Telegram

The agent long-polls the Bot API through the egress proxy, so nothing listens and nothing is on the tunnel. Only the chat ids in `TELEGRAM_CHAT_ID` are answered, other senders are ignored and logged by chat id. The log shows `telegram: polling started` at boot. The read position is kept in `/data/telegram.offset`, so a restart does not answer a message twice.

Telegram allows one poller per bot. While the Vostro agent runs, do not run `python -m parenting_agent` with `config/agent.json` or `scripts/channels_check.py` on the Mac, or the two will steal each other's messages. Stop the Vostro agent first (`sh deploy/agent.sh stop`) and start it again after.

### Why a container and not a systemd service

Docker already runs every other app on the Vostro, starts at boot, and gives the network wall for free: an internal network and two proxies keep the agent away from the LAN, the host and every other container. A systemd service would run on the host network and see all of them.

### Voice notes

A voice note on Telegram is heard by Muse Spark Open and answered in text and as a voice note (issue #58, `docs/voice.md`). ffmpeg and MMS-TTS run in the voice service, `pa-voice-family`, a separate container on `parenting-agent-internal` with the weights baked in and no secret (`deploy/voice/`, `sh deploy/voice.sh deploy`). The agent image stays standard library only. The agent reaches it at `http://pa-voice-family:8800` without the proxy. Hearing is the Muse call through the egress proxy, like the brain. So a voice note leaves the house as audio, to Muse Spark Open on Baseten, once and never saved by us. These calls run on the free hackathon credits, and Meta said content sent on those credits may be used to train future Meta models, so it is not promised to stay private. Video and house audio stay in the house.

## The wall

The agent is the private family agent, so it reaches only what it needs:

- Baby Buddy and Home Assistant, through the relay. The relay joins their networks, the agent does not. Baby Buddy and Home Assistant are not changed or restarted.
- The brain and Telegram, through the egress proxy. Every other host is refused.
- Nothing else: not the internet directly, not the host, not the LAN, not Tailscale, not other containers.
- One way in, since Oct 31: Home Assistant asks the voice bridge at `parenting-agent-relay:8767`, which forwards `/ask` and `/health` to the agent and nothing else (the Echo path, `docs/echo-and-assist.md`). The bridge listens on the agent's internal address and checks a bearer token.
- A second way in, since Oct 31 (issue #177): the Alexa skill "baby agent". Cloudflare Access checks the skill's service token at `baby-voice.home.example`, cloudflared checks the Access token again and hands the request to the door, `parenting-agent-door` on `127.0.0.1:4830`. The door forwards `/ask` and `/health` to `parenting-agent-relay:8767` and nothing else. It sits on its own network (`192.0.2.0/29`) with the relay only, and the relay refuses that network on its Home Assistant and Baby Buddy ports. The skill has its own bearer token, `data/voice-skill-token`, separate from Home Assistant's.

The internal network is created with `--internal` and the isolated gateway mode (Docker Engine 28 or newer), so its bridge has no address on the host. Nothing of the agent, the relay or the egress proxy is published on the host. Only the door is, on 127.0.0.1:4830, for the Cloudflare tunnel. `deploy/wall_check.py` proves it from inside the agent on every deploy and every `check`, and its door mode (`python3 - door`) proves from the Vostro that only the bridge's two paths pass the door. `agent.sh` also checks from inside the door that it reaches no Home Assistant, Baby Buddy, agent or LAN address, and that the relay refuses it on 8123 and 8790.

## Secrets

`~/apps/parenting-agent.env` on the Vostro, mode 600, written by `push-env` over ssh from the git-ignored `.env` of meta-hackathon-2026. Only these names travel: `BABYBUDDY_TOKEN`, `HA_MCP_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_CECI_CHAT_ID` (optional, Ceci's chat), `BASETEN_API_KEY`. Values are never printed. See `deploy/env.example`.

## House actions: three live, the rest dry

The house layer (`parenting_agent/house.py`) acts only when `HA_TOKEN` is set. The Vostro env file carries the Home Assistant token as `HA_MCP_TOKEN`, so the agent can read Home Assistant. The deploy refuses an env file that sets `HA_TOKEN`. Since Oct 30 `config/agent.vostro.json` lists three live actions in `house.live_actions`: the night feed's study light, nap mode's vacuum pause and return to base, and adding an item to the shopping list when a supply runs low or a parent asks (`parenting_agent/house_live.py`, the table in `docs/house-policy.md`). Every other house action stays a dry run. These need Home Assistant reachable, so deploy without `NO_HA` for them to write.

## Home Assistant bans after failed logins

Home Assistant on the Vostro has `ip_ban_enabled`, so a few requests with a wrong token ban the sender's IP. On Oct 28 between 15:31 and 15:45 it banned the relay (192.0.2.10) after four 401s from `deploy/probe.py`, run by `agent.sh` checks while the env file did not yet hold the right `HA_MCP_TOKEN`. Docker can later hand a banned IP to another container, so a failed login must not repeat.

- Every Home Assistant client goes through `HomeAssistant` in `parenting_agent/house.py`. After the first 401 or 403 it logs `Home Assistant rejected the token, not retrying to avoid an IP ban` and makes no other call for the rest of the process.
- `agent.sh` checks the token with one request (`probe.py token`) before any other Home Assistant call. On 401 or 403 it aborts the check. On a deploy it also stops the new agent, because a rollback would use the same token.

To clear a ban (Gonza does this):

1. Open a shell in Home Assistant: `docker exec -it homeassistant sh`
2. Back up the ban list: `cp /config/ip_bans.yaml /config/ip_bans.yaml.bak`
3. Empty it: `: > /config/ip_bans.yaml`
4. Restart Home Assistant: `docker restart homeassistant`

Fix the token first (`push-env`), or the next check bans the relay again.

## Commands

Run from the Mac, in a clean checkout. Only committed files are deployed.

```bash
sh deploy/agent.sh push-env    # copy the secrets, mode 600
sh deploy/agent.sh deploy      # build and run HEAD, health check, --check, Baby Buddy and Home Assistant reads, wall check
sh deploy/agent.sh update      # same as deploy, after a merge
sh deploy/agent.sh check       # the same checks against what runs now
sh deploy/agent.sh status      # containers, deployed commit, last heartbeat
sh deploy/agent.sh logs 200    # last 200 log lines
sh deploy/agent.sh stop        # stop the agent and its two proxies
sh deploy/agent.sh start       # start them again
sh deploy/agent.sh rollback    # run the image of the previous good deploy
```

When Home Assistant has banned the relay's address, `NO_HA=1 sh deploy/agent.sh deploy` (or `check`) sends no request to Home Assistant at all and checks everything else. The wall check reaches Home Assistant with a TCP connect only, since a tokenless HTTP request counts as a failed login there (Oct 28, the relay was banned after two of them).

A deploy that fails its health check or its wall check stops the new agent and starts the commit that ran before it again, even when that is the same commit (a redeploy of HEAD). That agent keeps running when it is inside the wall, healthy or not yet, so a failed deploy never leaves the family without an agent. Only an agent that fails the wall check is stopped. Before Oct 29 a failed redeploy of the same commit stopped the agent and never started it again. `rollback` works the same way: if the previous image fails, the current one starts again. Rollback switches images only, the compose file stays the last deployed one. `public.sh` (pa-demo and pa-families) and `voice.sh` restore the same way.

### One deploy at a time

On Oct 29 two agents deployed at once and both rolled back. Every deploy now takes one lock on the Vostro, the directory `~/apps/.pa-deploy.lock.d` (`deploy/lock.sh`). `agent.sh` deploy, update, rollback, stop and start, `public.sh demo|families` deploy, stop and start, and `voice.sh` deploy all take it before they send code. A deploy that finds it held prints who holds it and waits up to 10 minutes (`PA_DEPLOY_LOCK_WAIT`, in seconds), then stops without changing anything. The lock is released when the script exits, also on failure or Ctrl-C, and only by the deploy that took it.

To hold it by hand, for example while working on the Vostro: `ssh vostro 'mkdir ~/apps/.pa-deploy.lock.d'`, and `ssh vostro 'rmdir ~/apps/.pa-deploy.lock.d'` when done. A killed deploy no longer blocks the next one forever. Each deploy writes `owner.pid` (PID, host, start time) into the lock. When the lock is older than 30 minutes and its PID no longer runs on the same host, the next deploy takes it over and prints `TAKING OVER` with the old owner. A lock with no `owner.pid`, like one made by hand, is never taken over. If a deploy from another host lost its connection and no deploy runs, clear it with `ssh vostro 'rm -rf ~/apps/.pa-deploy.lock.d'`.

### The voice build stays out of the way

The pa-voice image installs torch, which loaded all 4 cores of the Vostro. `voice.sh` builds it in its own BuildKit container, `pa-lowprio` (docker-container driver, `moby/buildkit:v0.32.2`), held to cores 1 to 3, a quarter of the normal CPU weight and 3 GB of memory. Core 0 stays free and the live agents win every contention. A `nice` on the Mac or on the `docker compose` client would do nothing, because the build runs inside the BuildKit daemon. The builder is created on the first voice deploy and keeps its own cache.

## Restarts

| Event | What happens |
|---|---|
| The agent process crashes or is killed (`kill -9`, out of memory) | Docker starts it again within seconds |
| The decide-act loop dies but the process lives | The heartbeat plug-in exits the process, then Docker restarts it |
| The Vostro reboots | Docker starts at boot and starts the agent, like Baby Buddy |
| `docker stop` or `docker kill` | Treated by Docker as an operator stop: it stays stopped until `start`. Same for every container on the Vostro |

## Checked on Oct 28

| Check | Result |
|---|---|
| Health check | healthy |
| `kill -9` of the agent process from the host | running and healthy again 2 s later, restart count 1 |
| `docker restart` | healthy again after 11 s |
| `python -m parenting_agent --check` inside the container | Muse Spark Open brain with the fixed rules as fallback, heartbeat plug-in, five tools, Baby Buddy log |
| Read Baby Buddy from inside | child found, 20 entries read |
| Read Home Assistant from inside | HTTP 200, house dry run |
| One question through the brain from inside | "When was the last diaper?" answered from Baby Buddy, brain host inference.baseten.co (Oct 28 that was api.anthropic.com, before Muse) |
| Wall check | 87 of 87 pass: relay and egress reach their five targets, every other target is blocked |
| Other containers on the Vostro | untouched, same uptime before and after |
| Reboot | not run, it would restart Home Assistant and every other app |
