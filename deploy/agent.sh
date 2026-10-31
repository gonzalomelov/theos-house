#!/bin/sh
# shellcheck disable=SC2016,SC2029  # remote commands are quoted on purpose, they expand on the Vostro
# The family's private agent on the Vostro (issue #15). Run from the Mac, in a clean checkout of this repo.
#
#   sh deploy/agent.sh push-env          copy the needed secrets to ~/apps/parenting-agent.env on the Vostro (mode 600)
#   sh deploy/agent.sh deploy            build and run the committed HEAD, check health and the wall, roll back on failure
#   sh deploy/agent.sh update            same as deploy
#   sh deploy/agent.sh check             health, --check, Baby Buddy and Home Assistant reads, the wall
#   sh deploy/agent.sh status            containers, health, deployed commit, last heartbeat
#   sh deploy/agent.sh logs [lines]      the agent's logs (default 100 lines)
#   sh deploy/agent.sh stop | start      stop or start the agent and its two proxies
#   sh deploy/agent.sh rollback          run the image of the previous good deploy again
#
# NO_HA=1 in front of deploy or check sends no request to Home Assistant at all, for when it has banned the relay.
# Secrets are never printed and never in git. See docs/deploy-agent.md.
set -eu
HOST="${VOSTRO_HOST:-vostro}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_ENV="${SOURCE_ENV:-$HOME/.parenting-agent.env}"
SECRET_NAMES="BABYBUDDY_TOKEN HA_MCP_TOKEN TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_CECI_CHAT_ID BASETEN_API_KEY"
REQUIRED_NAMES="BASETEN_API_KEY BABYBUDDY_TOKEN"

remote() { ssh "$HOST" "$@"; }
# shellcheck source=deploy/lock.sh
. "$ROOT/deploy/lock.sh"

# The remote half: every command runs on the Vostro with this preamble.
REMOTE_LIB='
set -eu
APP=parenting-agent
DIR="$HOME/apps/parenting-agent"
ENV_FILE="$HOME/apps/parenting-agent.env"
CURRENT_FILE="$HOME/apps/parenting-agent.current"
PREVIOUS_FILE="$HOME/apps/parenting-agent.previous"
NETWORK=parenting-agent-internal
fail() { echo "$1" >&2; exit 1; }
compose() { docker compose --env-file "$ENV_FILE" -f "$DIR/deploy/compose.yml" "$@"; }
network_is_walled() {
  [ "$(docker network inspect "$NETWORK" --format "{{.Internal}}")" = "true" ] || { echo "$NETWORK is not internal" >&2; return 1; }
  [ "$(docker network inspect "$NETWORK" --format "{{index .Options \"com.docker.network.bridge.gateway_mode_ipv4\"}}")" = "isolated" ] \
    || { echo "$NETWORK has a host address" >&2; return 1; }
  [ "$(docker network inspect "$NETWORK" --format "{{.EnableIPv6}}")" = "false" ] || { echo "$NETWORK has IPv6 on" >&2; return 1; }
}
healthy() {
  for _ in $(seq 1 30); do
    [ "$(docker inspect "$APP" --format "{{.State.Health.Status}}" 2>/dev/null)" = "healthy" ] && return 0
    sleep 3
  done
  echo "health: $(docker inspect "$APP" --format "{{.State.Status}} {{.State.Health.Status}}" 2>&1)" >&2
  return 1
}
# Every address of the host a container could try: LAN, Tailscale and each Docker bridge gateway.
host_addresses() {
  ip -4 -o addr show | awk "{split(\$4, a, \"/\"); if (a[1] != \"127.0.0.1\") print a[1]}" | tr "\n" " "
}
# restore <commit>: run that image again after a failed deploy or rollback. It keeps running when it is inside the
# wall, healthy or not yet, so a failure never leaves the family without the agent that ran before. Only an agent
# that fails the wall is stopped. The same commit as the failed one is started again too (a redeploy of HEAD).
restore() {
  if [ -z "$1" ]; then echo "no earlier deploy recorded: the agent stays stopped" >&2; return 1; fi
  docker image inspect "$APP:$1" >/dev/null 2>&1 || { echo "image $APP:$1 is gone: the agent stays stopped" >&2; return 1; }
  echo "starting $1 again" >&2
  APP_TAG="$1" compose up -d --no-build --force-recreate --remove-orphans
  HEALTH=healthy
  healthy || HEALTH="running, not healthy yet"
  if walled >/dev/null; then echo "$1 is back: $HEALTH, inside the wall" >&2; return 0; fi
  docker stop "$APP" >/dev/null 2>&1 || true
  echo "$1 failed the wall check: the agent is stopped" >&2
  return 1
}
walled() {
  NETWORKS="$(docker inspect "$APP" --format "{{range \$name, \$_ := .NetworkSettings.Networks}}{{\$name}} {{end}}")"
  [ "$NETWORKS" = "$NETWORK " ] || { echo "$APP is on: $NETWORKS" >&2; return 1; }
  [ -z "$(docker port "$APP")$(docker port "$APP-relay")$(docker port "$APP-egress")" ] || { echo "a port is published" >&2; return 1; }
  network_is_walled || return 1
  # shellcheck disable=SC2046
  docker exec -i "$APP" python - $(host_addresses) < "$DIR/deploy/wall_check.py" || return 1
  door_walled
}
# The door of the Alexa skill (issue #177): published on loopback only, on the door network only, two paths through it, and
# from inside it no Home Assistant, Baby Buddy, agent or LAN. Requests carry no token, and none can reach Home
# Assistant: the relay refuses the door network on 8123 before anything is forwarded.
door_walled() {
  echo "== the door of the Alexa skill"
  [ "$(docker port "$APP-door")" = "8080/tcp -> 127.0.0.1:4830" ] || { echo "WRONG the door is published on: $(docker port "$APP-door")" >&2; return 1; }
  DOOR_NETS="$(docker inspect "$APP-door" --format "{{range \$name, \$_ := .NetworkSettings.Networks}}{{\$name}} {{end}}")"
  [ "$DOOR_NETS" = "parenting-agent_door " ] || { echo "WRONG the door is on: $DOOR_NETS" >&2; return 1; }
  echo "PASS  published on 127.0.0.1:4830 only, on parenting-agent_door only"
  python3 - door < "$DIR/deploy/wall_check.py" || return 1
  BAD=0
  TARGETS="homeassistant:8123 babybuddy:8000 home-assistant-mcp-server:8086 parenting-agent:8767 parenting-agent-egress:8888 192.0.2.10:80"
  for ADDR in $(host_addresses); do TARGETS="$TARGETS $ADDR:22 $ADDR:8123 $ADDR:8790"; done
  for TARGET in $TARGETS; do
    if docker exec "$APP-door" nc -z -w 3 "${TARGET%:*}" "${TARGET##*:}" 2>/dev/null; then
      echo "WRONG the door reaches $TARGET" >&2; BAD=1
    else
      echo "PASS  the door cannot reach $TARGET"
    fi
  done
  for PORT in 8123 8790; do
    if docker exec "$APP-door" wget -S -q -O /dev/null -T 4 "http://$APP-relay:$PORT/" 2>&1 | grep -q " 403 "; then
      echo "PASS  the relay refuses the door on $PORT"
    else
      echo "WRONG the relay answers the door on $PORT" >&2; BAD=1
    fi
  done
  [ "$BAD" = 0 ] && echo "door holds"
  return "$BAD"
}
# One Home Assistant request before any other. Home Assistant bans an IP after a few failed logins,
# so a rejected token (probe exit 3) stops the check here instead of trying again.
ha_token_ok() {
  if [ "${NO_HA:-0}" = 1 ]; then echo "== Home Assistant skipped (NO_HA=1): no request is sent"; return 0; fi
  echo "== Home Assistant token, one request from inside the container"
  RC=0
  docker exec -i "$APP" python - token < "$DIR/deploy/probe.py" || RC=$?
  [ "$RC" != 3 ] && return 0
  echo "Home Assistant rejected HA_MCP_TOKEN (401 or 403). Stopping before any other Home Assistant call to avoid an IP ban." >&2
  echo "Fix HA_MCP_TOKEN in the source .env, run sh deploy/agent.sh push-env, then deploy or check again." >&2
  return 1
}
checks() {
  ha_token_ok || fail "deploy check aborted: Home Assistant token rejected"
  echo "== health: $(docker inspect "$APP" --format "{{.State.Health.Status}}")"
  echo "== python -m parenting_agent --check (inside the container)"
  docker exec "$APP" python -m parenting_agent --check --config config/agent.vostro.json || return 1
  echo "== Baby Buddy and Home Assistant, read from inside the container"
  docker exec -i -e PA_NO_HA="${NO_HA:-0}" "$APP" python - < "$DIR/deploy/probe.py" || return 1
  echo "== the wall"
  walled || return 1
  ha_way_in
}
# Home Assistant reaches the agent only through the relay, on the voice bridge port. Two TCP connects from inside
# Home Assistant, no HTTP request, so nothing there can count as a failed login.
ha_way_in() {
  if [ "${NO_HA:-0}" = 1 ]; then return 0; fi
  echo "== the way in for Home Assistant, from inside the homeassistant container"
  docker exec homeassistant python3 -c "import socket; socket.create_connection((\"$APP-relay\", 8767), timeout=4)" \
    || { echo "WRONG Home Assistant cannot reach the voice bridge through the relay" >&2; return 1; }
  echo "PASS  relay:8767 reached"
  if docker exec homeassistant python3 -c "import socket; socket.create_connection((\"$APP\", 8767), timeout=4)" 2>/dev/null; then
    echo "WRONG Home Assistant reaches the agent directly" >&2; return 1
  fi
  echo "PASS  the agent itself blocked"
}
'

send_code() {
  cd "$ROOT"
  [ -z "$(git status --porcelain)" ] || { echo "working tree is not clean: commit first, only committed files are deployed" >&2; exit 1; }
  SHA="$(git rev-parse --short=12 HEAD)"
  echo "== send commit $SHA to $HOST:~/apps/parenting-agent"
  git archive --format=tar HEAD .dockerignore deploy parenting_agent config | remote '
    set -eu
    rm -rf ~/apps/parenting-agent.incoming && mkdir -p ~/apps/parenting-agent.incoming
    tar -xf - -C ~/apps/parenting-agent.incoming
    rm -rf ~/apps/parenting-agent.old
    [ ! -d ~/apps/parenting-agent ] || mv ~/apps/parenting-agent ~/apps/parenting-agent.old
    mv ~/apps/parenting-agent.incoming ~/apps/parenting-agent
    rm -rf ~/apps/parenting-agent.old'
}

push_env() {
  [ -f "$SOURCE_ENV" ] || { echo "no $SOURCE_ENV" >&2; exit 1; }
  for NAME in $REQUIRED_NAMES; do
    grep -Eq "^$NAME=.+" "$SOURCE_ENV" || { echo "$SOURCE_ENV has no value for $NAME" >&2; exit 1; }
  done
  PATTERN="^($(echo "$SECRET_NAMES" | tr ' ' '|'))="
  # Only the named lines travel, over ssh, into a file created with mode 600. Nothing is echoed.
  grep -E "$PATTERN" "$SOURCE_ENV" | remote '
    set -eu
    umask 077
    cat > ~/apps/parenting-agent.env.tmp
    chmod 600 ~/apps/parenting-agent.env.tmp
    mv ~/apps/parenting-agent.env.tmp ~/apps/parenting-agent.env
    echo "wrote ~/apps/parenting-agent.env, mode $(stat -c %a ~/apps/parenting-agent.env), names: $(cut -d= -f1 ~/apps/parenting-agent.env | tr "\n" " ")"'
}

deploy() {
  deploy_lock "agent deploy $(git -C "$ROOT" rev-parse --short=12 HEAD)"
  send_code
  remote "SHA=$SHA REQUIRED_NAMES='$REQUIRED_NAMES' NO_HA=${NO_HA:-0} sh -s" <<REMOTE
$REMOTE_LIB
[ -f "\$ENV_FILE" ] || fail "missing \$ENV_FILE: run sh deploy/agent.sh push-env"
[ "\$(stat -c %a "\$ENV_FILE")" = "600" ] || fail "\$ENV_FILE must have mode 600"
for NAME in \$REQUIRED_NAMES; do grep -Eq "^\$NAME=.+" "\$ENV_FILE" || fail "\$ENV_FILE has no value for \$NAME"; done
# HA_TOKEN would turn every house.py action live. The only live writes are house.live_actions in the config (Oct 30).
! grep -Eq "^HA_TOKEN=" "\$ENV_FILE" || fail "\$ENV_FILE sets HA_TOKEN: live house actions are not part of this deploy"

MAJOR="\$(docker version --format "{{.Server.Version}}" | cut -d. -f1)"
[ "\$MAJOR" -ge 28 ] || fail "Docker Engine 28 or newer is needed for the isolated gateway mode (found \$MAJOR)"
docker network inspect "\$NETWORK" >/dev/null 2>&1 || docker network create --internal --ipv6=false \
  -o com.docker.network.bridge.gateway_mode_ipv4=isolated "\$NETWORK" >/dev/null
network_is_walled
mkdir -p "\$HOME/apps/parenting-agent-data"

PREVIOUS="\$(cat "\$CURRENT_FILE" 2>/dev/null || true)"
APP_TAG="\$SHA" compose build --quiet
run() { APP_TAG="\$1" compose up -d --no-build --force-recreate --remove-orphans; }
run "\$SHA"
# A rejected token is the same for every image, so a rollback would not help: stop the agent and abort.
ha_token_ok || { docker stop "\$APP" >/dev/null 2>&1 || true; fail "deploy aborted: Home Assistant token rejected, the agent is stopped"; }
if healthy && checks; then
  if [ -n "\$PREVIOUS" ] && [ "\$PREVIOUS" != "\$SHA" ]; then echo "\$PREVIOUS" > "\$PREVIOUS_FILE"; fi
  echo "\$SHA" > "\$CURRENT_FILE"
  echo "deployed \$SHA"
else
  echo "commit \$SHA failed its health check or its wall check" >&2
  docker logs --tail 30 "\$APP" >&2 || true
  # An agent that may be outside the wall does not keep running.
  docker stop "\$APP" >/dev/null 2>&1 || true
  restore "\$PREVIOUS"
  exit 1
fi
REMOTE
}

rollback() {
  deploy_lock "agent rollback"
  remote sh -s <<REMOTE
$REMOTE_LIB
PREVIOUS="\$(cat "\$PREVIOUS_FILE" 2>/dev/null || true)"
CURRENT="\$(cat "\$CURRENT_FILE" 2>/dev/null || true)"
[ -n "\$PREVIOUS" ] || fail "no previous deploy recorded"
docker image inspect "\$APP:\$PREVIOUS" >/dev/null 2>&1 || fail "image \$APP:\$PREVIOUS is gone"
echo "== roll back from \$CURRENT to \$PREVIOUS (images only, the compose file stays the deployed one)"
APP_TAG="\$PREVIOUS" compose up -d --no-build --force-recreate --remove-orphans
if ! { healthy && walled >/dev/null; }; then
  echo "\$PREVIOUS is not healthy or not walled" >&2
  docker stop "\$APP" >/dev/null 2>&1 || true
  restore "\$CURRENT" || true
  fail "rollback failed: \$CURRENT runs again if it passed the wall check"
fi
echo "\$PREVIOUS" > "\$CURRENT_FILE"
echo "\$CURRENT" > "\$PREVIOUS_FILE"
echo "rolled back to \$PREVIOUS"
REMOTE
}

case "${1:-}" in
  push-env) push_env ;;
  deploy|update) deploy ;;
  rollback) rollback ;;
  check) remote "NO_HA=${NO_HA:-0} sh -s" <<REMOTE
$REMOTE_LIB
checks
REMOTE
  ;;
  status) remote sh -s <<REMOTE
$REMOTE_LIB
docker ps -a --filter name=parenting-agent --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"
echo "deployed: \$(cat "\$CURRENT_FILE" 2>/dev/null || echo none)  previous: \$(cat "\$PREVIOUS_FILE" 2>/dev/null || echo none)"
echo "heartbeat: \$(cat "\$HOME/apps/parenting-agent-data/heartbeat.json" 2>/dev/null || echo none)"
REMOTE
  ;;
  logs) remote "docker logs --tail '${2:-100}' parenting-agent" ;;
  stop) deploy_lock "agent stop"; remote sh -s <<REMOTE
$REMOTE_LIB
compose stop
REMOTE
  ;;
  start) deploy_lock "agent start"; remote sh -s <<REMOTE
$REMOTE_LIB
APP_TAG="\$(cat "\$CURRENT_FILE")" compose up -d --no-build
healthy && echo "healthy"
REMOTE
  ;;
  *) sed -n 2,14p "$0"; exit 2 ;;
esac
