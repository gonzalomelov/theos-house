#!/bin/sh
# shellcheck disable=SC2016,SC2029  # remote commands are quoted on purpose, they expand on the Vostro
# The voice service on the Vostro (issue #58). Run from the Mac, in a clean checkout of this repo.
#
#   sh deploy/voice.sh deploy     build the committed HEAD (ffmpeg, torch CPU, MMS-TTS weights baked in), run both
#                                 containers, wait for health, check the wall and speak one sentence in each language
#   sh deploy/voice.sh check      the same checks against what runs now
#   sh deploy/voice.sh status     containers and the deployed commit
#   sh deploy/voice.sh logs       the last log lines of both containers
#
# Deploy the voice service before the agent and the families bot that use it. See docs/voice.md.
set -eu
HOST="${VOSTRO_HOST:-vostro}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
remote() { ssh "$HOST" "$@"; }
# shellcheck source=deploy/lock.sh
. "$ROOT/deploy/lock.sh"

REMOTE_LIB='
set -eu
DIR="$HOME/apps/pa-voice"
CURRENT_FILE="$HOME/apps/pa-voice.current"
BUILDER=pa-lowprio
fail() { echo "$1" >&2; exit 1; }
compose() { docker compose -f "$DIR/deploy/voice/compose.yml" "$@"; }
healthy() {
  for _ in $(seq 1 60); do
    A="$(docker inspect pa-voice-family --format "{{.State.Health.Status}}" 2>/dev/null || true)"
    B="$(docker inspect pa-voice-families --format "{{.State.Health.Status}}" 2>/dev/null || true)"
    [ "$A" = healthy ] && [ "$B" = healthy ] && return 0
    sleep 5
  done
  echo "health: family $A, families $B" >&2
  return 1
}
checks() {
  for C in pa-voice-family pa-voice-families; do
    echo "== $C"
    NETS="$(docker inspect "$C" --format "{{range \$name, \$_ := .NetworkSettings.Networks}}{{\$name}} {{end}}")"
    case "$C" in
      pa-voice-family) [ "$NETS" = "parenting-agent-internal " ] || { echo "$C is on: $NETS" >&2; return 1; } ;;
      *) [ "$NETS" = "pa-families-internal " ] || { echo "$C is on: $NETS" >&2; return 1; } ;;
    esac
    [ -z "$(docker port "$C")" ] || { echo "$C publishes a port" >&2; return 1; }
    [ "$(docker network inspect "${NETS% }" --format "{{.Internal}}")" = "true" ] || { echo "${NETS% } is not internal" >&2; return 1; }
    docker exec -i "$C" python - < "$DIR/deploy/voice/voice_check.py" || return 1
  done
}
'

send_code() {
  cd "$ROOT"
  [ -z "$(git status --porcelain)" ] || { echo "working tree is not clean: commit first, only committed files are deployed" >&2; exit 1; }
  SHA="$(git rev-parse --short=12 HEAD)"
  echo "== send commit $SHA to $HOST:~/apps/pa-voice"
  git archive --format=tar HEAD .dockerignore deploy parenting_agent | remote '
    set -eu
    rm -rf ~/apps/pa-voice.incoming && mkdir -p ~/apps/pa-voice.incoming
    tar -xf - -C ~/apps/pa-voice.incoming
    rm -rf ~/apps/pa-voice && mv ~/apps/pa-voice.incoming ~/apps/pa-voice'
}

case "${1:-}" in
  deploy|update)
    deploy_lock "voice deploy $(git -C "$ROOT" rev-parse --short=12 HEAD)"
    send_code
    remote "SHA=$SHA sh -s" <<REMOTE
$REMOTE_LIB
for NET in parenting-agent-internal pa-families-internal; do
  docker network inspect "\$NET" >/dev/null 2>&1 || fail "\$NET does not exist: deploy the agent and the families bot first"
done
PREVIOUS="\$(cat "\$CURRENT_FILE" 2>/dev/null || true)"
# The torch build is heavy. It runs in its own BuildKit container held to cores 1 to 3 with a quarter of the normal
# CPU weight and 3 GB, so core 0 stays free and the live agents win every contention (Oct 29, a pa-voice build loaded
# the 4 core Vostro). A nice on the client would do nothing: the build runs inside the BuildKit daemon.
docker buildx inspect "\$BUILDER" >/dev/null 2>&1 || docker buildx create --name "\$BUILDER" --driver docker-container \
  --driver-opt image=moby/buildkit:v0.32.2 --driver-opt cpuset-cpus=1-3 --driver-opt cpu-shares=256 \
  --driver-opt memory=3g >/dev/null
APP_TAG="\$SHA" compose build --builder "\$BUILDER" --quiet
APP_TAG="\$SHA" compose up -d --no-build --force-recreate --remove-orphans
if ! { healthy && checks; }; then
  docker logs --tail 30 pa-voice-family >&2 || true
  compose stop
  # The voice that ran before comes back if it is still inside the wall. The same commit is started again too.
  if [ -n "\$PREVIOUS" ] && docker image inspect "pa-voice:\$PREVIOUS" >/dev/null 2>&1; then
    echo "starting \$PREVIOUS again" >&2
    APP_TAG="\$PREVIOUS" compose up -d --no-build --force-recreate --remove-orphans
    healthy || true
    if checks >/dev/null; then echo "\$PREVIOUS is back, inside the wall" >&2; else compose stop; echo "\$PREVIOUS failed its checks: stopped" >&2; fi
  fi
  fail "commit \$SHA failed its health check or its wall check"
fi
echo "\$SHA" > "\$CURRENT_FILE"
echo "deployed \$SHA"
REMOTE
    ;;
  check) remote sh -s <<REMOTE
$REMOTE_LIB
checks
REMOTE
    ;;
  status) remote sh -s <<REMOTE
$REMOTE_LIB
docker ps -a --filter name=pa-voice --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"
echo "deployed: \$(cat "\$CURRENT_FILE" 2>/dev/null || echo none)"
REMOTE
    ;;
  logs) remote "docker logs --tail '${2:-50}' pa-voice-family; docker logs --tail '${2:-50}' pa-voice-families" ;;
  *) sed -n '3,11p' "$0"; exit 2 ;;
esac
