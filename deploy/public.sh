#!/bin/sh
# shellcheck disable=SC2016,SC2029  # remote commands are quoted on purpose, they expand on the Vostro
# The public demo (pa-demo, https://baby.bygmv.com) and the families service (pa-families, Telegram) on the Vostro.
# Run from the Mac, in a clean checkout of this repo. Only committed files are deployed.
#
#   sh deploy/public.sh demo|families push-env   copy only the names the service needs to ~/apps/pa-<service>.env (mode 600)
#   sh deploy/public.sh demo|families deploy     build and run HEAD, check health and the wall, roll back on failure
#   sh deploy/public.sh demo|families check      health and the wall, against what runs now
#   sh deploy/public.sh demo|families status     containers, health, deployed commit
#   sh deploy/public.sh demo|families logs [n]   the service's last n log lines (default 100)
#   sh deploy/public.sh demo|families stop|start
#   sh deploy/public.sh backup install           the daily backup of both data folders (deploy/backup.sh, systemd user timer)
#   sh deploy/public.sh backup run               one backup now
#
# WALL_EXTRA_TARGETS: more host:port pairs the service must not reach, on top of every address of the Vostro on
# ports 22, 80, 8123 and 8790. Example: WALL_EXTRA_TARGETS="192.0.2.10:80 192.0.2.10:22"
# Secrets are never printed and never in git. See docs/demo-app.md and docs/families.md.
set -eu
HOST="${VOSTRO_HOST:-vostro}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_ENV="${SOURCE_ENV:-$HOME/.parenting-agent.env}"
SERVICE="${1:-}"
COMMAND="${2:-}"

remote() { ssh "$HOST" "$@"; }
usage() { sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

case "$SERVICE" in
  demo)     UID_IN=10001; REQUIRED_NAMES="ANTHROPIC_API_KEY" ;;
  families) UID_IN=10002; REQUIRED_NAMES="ANTHROPIC_API_KEY TELEGRAM_FAMILIES_BOT_TOKEN PA_FAMILIES_INTERNAL_USERS" ;;
  backup)   ;;
  *)        usage ;;
esac

# The remote half: every command runs on the Vostro with this preamble.
REMOTE_LIB='
set -eu
APP="pa-$SERVICE"
DIR="$HOME/apps/$APP"
DATA="$HOME/apps/$APP-data"
ENV_FILE="$HOME/apps/$APP.env"
CURRENT_FILE="$HOME/apps/$APP.current"
PREVIOUS_FILE="$HOME/apps/$APP.previous"
NETWORK="$APP-internal"
EDGE_PORT=4820
fail() { echo "$1" >&2; exit 1; }
compose() { docker compose --env-file "$ENV_FILE" -f "$DIR/deploy/$SERVICE/compose.yml" "$@"; }
network_is_walled() {
  [ "$(docker network inspect "$NETWORK" --format "{{.Internal}}")" = "true" ] || { echo "$NETWORK is not internal" >&2; return 1; }
  [ "$(docker network inspect "$NETWORK" --format "{{index .Options \"com.docker.network.bridge.gateway_mode_ipv4\"}}")" = "isolated" ] \
    || { echo "$NETWORK has a host address" >&2; return 1; }
  [ "$(docker network inspect "$NETWORK" --format "{{.EnableIPv6}}")" = "false" ] || { echo "$NETWORK has IPv6 on" >&2; return 1; }
}
healthy() {
  for _ in $(seq 1 30); do
    if [ "$SERVICE" = demo ]; then
      [ "$(docker inspect "$APP" --format "{{.State.Health.Status}}" 2>/dev/null)" = "healthy" ] \
        && curl -fsS "http://127.0.0.1:$EDGE_PORT/healthz" >/dev/null 2>&1 && return 0
    else
      [ "$(docker inspect "$APP" --format "{{.State.Running}} {{.RestartCount}}" 2>/dev/null)" = "true 0" ] \
        && docker logs "$APP" 2>&1 | grep -q "families: polling started" && return 0
    fi
    sleep 3
  done
  echo "health: $(docker inspect "$APP" --format "{{.State.Status}} restarts {{.RestartCount}}" 2>&1)" >&2
  docker logs --tail 20 "$APP" >&2 || true
  return 1
}
# Every address of the host a container could try: LAN, Tailscale and each Docker bridge gateway.
host_targets() {
  for ADDR in $(ip -4 -o addr show | awk "{split(\$4, a, \"/\"); if (a[1] != \"127.0.0.1\") print a[1]}"); do
    printf "%s " "$ADDR:22" "$ADDR:80" "$ADDR:8123" "$ADDR:8790"
  done
}
walled() {
  NETWORKS="$(docker inspect "$APP" --format "{{range \$name, \$_ := .NetworkSettings.Networks}}{{\$name}} {{end}}")"
  [ "$NETWORKS" = "$NETWORK " ] || { echo "$APP is on: $NETWORKS" >&2; return 1; }
  [ "$(docker inspect "$APP" --format "{{.HostConfig.NetworkMode}}")" != host ] || { echo "$APP is on the host network" >&2; return 1; }
  [ -z "$(docker port "$APP")$(docker port "$APP-egress")" ] || { echo "a port of $APP or its proxy is published" >&2; return 1; }
  if [ "$SERVICE" = demo ]; then
    [ "$(docker port "$APP-edge")" = "8080/tcp -> 127.0.0.1:$EDGE_PORT" ] || { echo "the edge is published on: $(docker port "$APP-edge")" >&2; return 1; }
  fi
  network_is_walled || return 1
  # shellcheck disable=SC2046,SC2086
  bash "$DIR/deploy/$SERVICE/check-wall.sh" $(host_targets) ${WALL_EXTRA_TARGETS:-}
}
checks() {
  echo "== health"
  healthy || return 1
  echo "healthy"
  if [ "$SERVICE" = families ]; then docker exec "$APP" python -m parenting_agent.families check || return 1; fi
  echo "== the wall"
  walled
}
'

run_remote() { # run_remote <script>, with the preamble
  remote "SERVICE=$SERVICE SHA=${SHA:-} REQUIRED_NAMES='$REQUIRED_NAMES' UID_IN=${UID_IN:-} WALL_EXTRA_TARGETS='${WALL_EXTRA_TARGETS:-}' sh -s" <<REMOTE
$REMOTE_LIB
$1
REMOTE
}

send_code() {
  cd "$ROOT"
  [ -z "$(git status --porcelain)" ] || { echo "working tree is not clean: commit first, only committed files are deployed" >&2; exit 1; }
  SHA="$(git rev-parse --short=12 HEAD)"
  echo "== send commit $SHA to $HOST:~/apps/pa-$SERVICE"
  git archive --format=tar HEAD .dockerignore deploy parenting_agent simweek | remote "
    set -eu
    D=~/apps/pa-$SERVICE
    rm -rf \"\$D.incoming\" && mkdir -p \"\$D.incoming\"
    tar -xf - -C \"\$D.incoming\"
    rm -rf \"\$D.old\"
    [ ! -d \"\$D\" ] || mv \"\$D\" \"\$D.old\"
    mv \"\$D.incoming\" \"\$D\"
    rm -rf \"\$D.old\""
}

push_env() {
  [ -f "$SOURCE_ENV" ] || { echo "no $SOURCE_ENV" >&2; exit 1; }
  if [ "$SERVICE" = demo ]; then
    LINES="$(grep -E '^ANTHROPIC_API_KEY=.+' "$SOURCE_ENV" || true)"
  else
    # Gonza's chat id with the bot is his Telegram user id: his own rows are internal and never count.
    LINES="$(grep -E '^(ANTHROPIC_API_KEY|TELEGRAM_FAMILIES_BOT_TOKEN)=.+' "$SOURCE_ENV" || true)
PA_FAMILIES_BOT_USERNAME=bygmv_parenting_families_bot
$(sed -n 's/^TELEGRAM_CHAT_ID=/PA_FAMILIES_INTERNAL_USERS=/p' "$SOURCE_ENV")"
  fi
  for NAME in $REQUIRED_NAMES; do
    printf '%s\n' "$LINES" | grep -Eq "^$NAME=.+" || { echo "$SOURCE_ENV has no value for $NAME" >&2; exit 1; }
  done
  # Only these lines travel, over ssh, into a file created with mode 600. Nothing is echoed.
  printf '%s\n' "$LINES" | remote "
    set -eu
    umask 077
    F=~/apps/pa-$SERVICE.env
    cat > \"\$F.tmp\"
    chmod 600 \"\$F.tmp\"
    mv \"\$F.tmp\" \"\$F\"
    echo \"wrote \$F, mode \$(stat -c %a \"\$F\"), names: \$(cut -d= -f1 \"\$F\" | tr '\n' ' ')\""
}

deploy() {
  send_code
  run_remote '
[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE: run sh deploy/public.sh $SERVICE push-env"
[ "$(stat -c %a "$ENV_FILE")" = "600" ] || fail "$ENV_FILE must have mode 600"
for NAME in $REQUIRED_NAMES; do grep -Eq "^$NAME=.+" "$ENV_FILE" || fail "$ENV_FILE has no value for $NAME"; done
! grep -Eq "^(HA_|BABYBUDDY|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)" "$ENV_FILE" || fail "$ENV_FILE holds a house or family agent name"

MAJOR="$(docker version --format "{{.Server.Version}}" | cut -d. -f1)"
[ "$MAJOR" -ge 28 ] || fail "Docker Engine 28 or newer is needed for the isolated gateway mode (found $MAJOR)"
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create --internal --ipv6=false \
  -o com.docker.network.bridge.gateway_mode_ipv4=isolated "$NETWORK" >/dev/null
network_is_walled
# The data folder belongs to the user inside the container only.
[ -d "$DATA" ] || sudo -n install -d -m 700 -o "$UID_IN" -g "$UID_IN" "$DATA"

PREVIOUS="$(cat "$CURRENT_FILE" 2>/dev/null || true)"
APP_TAG="$SHA" compose build --quiet
run() { APP_TAG="$1" compose up -d --no-build --force-recreate --remove-orphans; }
run "$SHA"
if checks; then
  if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$SHA" ]; then echo "$PREVIOUS" > "$PREVIOUS_FILE"; fi
  echo "$SHA" > "$CURRENT_FILE"
  echo "deployed $APP $SHA"
else
  echo "commit $SHA failed its health check or its wall check" >&2
  # A service that may be outside the wall does not keep running.
  docker stop "$APP" >/dev/null 2>&1 || true
  if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$SHA" ] && docker image inspect "$APP:$PREVIOUS" >/dev/null 2>&1; then
    echo "rolling back to $PREVIOUS" >&2
    run "$PREVIOUS"
    if checks >/dev/null; then echo "rollback healthy" >&2; else docker stop "$APP" >/dev/null 2>&1 || true; echo "rollback failed too: $APP is stopped" >&2; fi
  fi
  exit 1
fi'
}

backup() {
  cd "$ROOT"
  case "$COMMAND" in
    install)
      [ -z "$(git status --porcelain deploy)" ] || { echo "deploy/ is not clean: commit first" >&2; exit 1; }
      git archive --format=tar HEAD deploy/backup.sh deploy/systemd | remote '
        set -eu
        mkdir -p ~/apps/pa-backup ~/.config/systemd/user
        tar -xf - -C ~/apps/pa-backup --strip-components=1
        cp ~/apps/pa-backup/systemd/pa-backup.service ~/apps/pa-backup/systemd/pa-backup.timer ~/.config/systemd/user/
        systemctl --user daemon-reload
        systemctl --user enable --now pa-backup.timer
        systemctl --user list-timers pa-backup.timer --no-pager | head -2' ;;
    run) remote 'systemctl --user start pa-backup.service && journalctl --user -u pa-backup.service -n 6 --no-pager -o cat' ;;
    *) usage ;;
  esac
}

case "$SERVICE:$COMMAND" in
  backup:*)    backup ;;
  *:push-env)  push_env ;;
  *:deploy)    deploy ;;
  *:check)     run_remote 'checks' ;;
  *:status)    run_remote 'docker ps -a --filter "name=^$APP" --format "{{.Names}}  {{.Status}}  {{.Ports}}"
echo "deployed: $(cat "$CURRENT_FILE" 2>/dev/null || echo none), previous: $(cat "$PREVIOUS_FILE" 2>/dev/null || echo none)"' ;;
  *:logs)      remote "docker logs --tail ${3:-100} pa-$SERVICE" ;;
  *:stop)      run_remote 'compose stop' ;;
  *:start)     run_remote 'compose start' ;;
  *)           usage ;;
esac
