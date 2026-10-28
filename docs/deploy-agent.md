# The agent on the Vostro, always on

The family's private agent runs 24/7 on the Vostro, next to Baby Buddy and Home Assistant, so it keeps working when the Mac is closed. Deployed on Oct 28 2026 during the hackathon (issue #15). Heavy vision (MediaPipe, SAM 3.1) stays on the Mac.

## How it runs

Three containers in the compose project `parenting-agent` (`deploy/compose.yml`):

| Container | What it is | Networks |
|---|---|---|
| `parenting-agent` | The agent core, `python -m parenting_agent --config config/agent.vostro.json`. Standard library only | `parenting-agent-internal` only |
| `parenting-agent-relay` | nginx, forwards `relay:8790` to Baby Buddy and `relay:8123` to Home Assistant, nothing else | internal, `babybuddy-net`, `home-assistant_default` |
| `parenting-agent-egress` | tinyproxy, HTTPS tunnels only, to `api.anthropic.com`, `inference.baseten.co` and `api.telegram.org` (`deploy/egress/filter`) | internal, its own bridge |

- Images: `python:3.12-slim-bookworm`, `nginxinc/nginx-unprivileged` and `alpine` with tinyproxy, each pinned by digest. The agent and egress images are built on the Vostro and tagged with the git commit.
- Restart `unless-stopped`, read-only root, all capabilities dropped, no new privileges, user 1000, 256 MB, half a CPU, 64 processes.
- Health check: the heartbeat plug-in (`parenting_agent/agent/heartbeat.py`) writes `/data/heartbeat.json` every 30 s while the decide-act loop is alive. Docker marks the container unhealthy when the file is older than 90 s. If the loop thread dies, the plug-in ends the process with exit code 1 so the restart policy brings it back.
- Data: `~/apps/parenting-agent-data` on the Vostro, mounted at `/data`: `memory.sqlite`, `events.jsonl`, `heartbeat.json`.
- Logs: Docker's json-file driver, 10 MB per file, 3 files.
- Plug-ins on the Vostro: the heartbeat and the Telegram channel (#3). No console (no terminal there) and no changing table (vision runs on the Mac).
- No channel router on the Vostro. Replies to a Telegram message go back to Telegram. The router picks the home speaker when the parent is home, and on the Vostro that would be a live house action, so it stays on the Mac until #9.

### Telegram

The agent long-polls the Bot API through the egress proxy, so nothing listens and nothing is on the tunnel. Only the chat ids in `TELEGRAM_CHAT_ID` are answered, other senders are ignored and logged by chat id. The log shows `telegram: polling started` at boot. The read position is kept in `/data/telegram.offset`, so a restart does not answer a message twice.

Telegram allows one poller per bot. While the Vostro agent runs, do not run `python -m parenting_agent` with `config/agent.json` or `scripts/channels_check.py` on the Mac, or the two will steal each other's messages. Stop the Vostro agent first (`sh deploy/agent.sh stop`) and start it again after.

### Why a container and not a systemd service

Docker already runs every other app on the Vostro, starts at boot, and gives the network wall for free: an internal network and two proxies keep the agent away from the LAN, the host and every other container. A systemd service would run on the host network and see all of them.

## The wall

The agent is the private family agent, so it reaches only what it needs:

- Baby Buddy and Home Assistant, through the relay. The relay joins their networks, the agent does not. Baby Buddy and Home Assistant are not changed or restarted.
- The brain and Telegram, through the egress proxy. Every other host is refused.
- Nothing else: not the internet directly, not the host, not the LAN, not Tailscale, not other containers.

The internal network is created with `--internal` and the isolated gateway mode (Docker Engine 28 or newer), so its bridge has no address on the host. Nothing is published on the host, not even on 127.0.0.1, and nothing is on the Cloudflare tunnel. `deploy/wall_check.py` proves it from inside the agent on every deploy and every `check`.

## Secrets

`~/apps/parenting-agent.env` on the Vostro, mode 600, written by `push-env` over ssh from the git-ignored `.env` of meta-hackathon-2026. Only these names travel: `ANTHROPIC_API_KEY`, `BABYBUDDY_TOKEN`, `HA_MCP_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `BASETEN_API_KEY`. Values are never printed. See `deploy/env.example`.

## House actions stay dry

The house layer (`parenting_agent/house.py`) acts only when `HA_TOKEN` is set. The Vostro env file carries the Home Assistant token as `HA_MCP_TOKEN`, so the agent can read Home Assistant and every house action stays dry run. The deploy refuses an env file that sets `HA_TOKEN`. Turning live actions on is issue #9, under the action policy in `docs/home-assistant-inventory.md`.

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

A deploy that fails its health check or its wall check stops the new agent and starts the previous commit again. Rollback switches images only, the compose file stays the last deployed one.

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
| `python -m parenting_agent --check` inside the container | Claude brain, heartbeat plug-in, five tools, Baby Buddy log |
| Read Baby Buddy from inside | child found, 20 entries read |
| Read Home Assistant from inside | HTTP 200, house dry run |
| One question through the brain from inside | "When was the last diaper?" answered from Baby Buddy, brain host api.anthropic.com |
| Wall check | 87 of 87 pass: relay and egress reach their five targets, every other target is blocked |
| Other containers on the Vostro | untouched, same uptime before and after |
| Reboot | not run, it would restart Home Assistant and every other app |
