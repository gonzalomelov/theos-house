#!/bin/sh
# shellcheck disable=SC2029  # remote commands are quoted on purpose, they expand on the Vostro
# The persistent agent on the Vostro, next to the old one. Run from the Mac, in a clean checkout.
#
#   sh deploy/core.sh deploy      build and run the committed HEAD, then report health and the wall
#   sh deploy/core.sh status      containers and deployed commit
#   sh deploy/core.sh logs [n]    its logs
#   sh deploy/core.sh stop        stop it, the old agent is not touched
#
# PA_ALLOWED_DEVICES, PA_WATCH_DELTA and PA_HOME_ID in front of deploy are passed on. Secrets are never printed and never in git.
# CUTOVER=1 in front of deploy makes Telegram, the Echo and the baby log real (deploy/core/compose.cutover.yml). It refuses while the
# old agent runs, since only one process can poll the bot. Without it the core can't message anyone.
set -eu
HOST="${VOSTRO_HOST:-vostro}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE='
set -eu
DIR="$HOME/apps/parenting-core"
ENV_FILE="$HOME/apps/parenting-core.env"
compose() { docker compose --env-file "$ENV_FILE" -f "$DIR/deploy/core/compose.yml" ${CUTOVER:+-f "$DIR/deploy/core/compose.cutover.yml"} "$@"; }
'

deploy() {
  cd "$ROOT"
  [ -z "$(git status --porcelain)" ] || { echo "working tree is not clean: commit first" >&2; exit 1; }
  SHA="$(git rev-parse --short=12 HEAD)"
  git archive --format=tar HEAD .dockerignore deploy parenting_agent config requirements-core.txt | ssh "$HOST" \
    'set -eu; rm -rf ~/apps/parenting-core.incoming ~/apps/parenting-core; mkdir -p ~/apps/parenting-core.incoming; tar -xf - -C ~/apps/parenting-core.incoming; mv ~/apps/parenting-core.incoming ~/apps/parenting-core'
  ssh "$HOST" "SHA=$SHA CUTOVER='${CUTOVER:-}' PA_ALLOWED_DEVICES='${PA_ALLOWED_DEVICES:-none}' PA_WATCH_DELTA='${PA_WATCH_DELTA:-}' PA_HOME_ID='${PA_HOME_ID:-alongside}' sh -s" <<REMOTE_END
$REMOTE
umask 077
[ -z "\$CUTOVER" ] || [ "\$(docker inspect parenting-agent --format '{{.State.Running}}' 2>/dev/null)" != true ] || { echo "the old agent is running: stop it first" >&2; exit 1; }
# Only these two come from the old agent's env file: no Telegram token in here. The database password is made once.
OLD="\$HOME/apps/parenting-agent.env"
PASS="\$(grep -E '^POSTGRES_PASSWORD=' "\$ENV_FILE" 2>/dev/null || echo "POSTGRES_PASSWORD=\$(od -An -tx1 -N24 /dev/urandom | tr -d ' \n')")"
{ grep -E '^(HA_MCP_TOKEN|BASETEN_API_KEY)=' "\$OLD"; echo "\$PASS"
  if [ -n "\$CUTOVER" ]; then
    grep -E '^(BABYBUDDY_TOKEN|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|TELEGRAM_CECI_CHAT_ID)=' "\$OLD"
    echo "PARENTING_AGENT_VOICE_TOKEN=\$(cat "\$HOME/apps/parenting-agent-data/voice-bridge-token")"
  fi; } > "\$ENV_FILE.tmp"
mv "\$ENV_FILE.tmp" "\$ENV_FILE"
export APP_TAG="\$SHA"
compose build --quiet
compose up -d --no-build --force-recreate --remove-orphans
for _ in \$(seq 1 40); do
  [ "\$(docker inspect parenting-core --format '{{.State.Health.Status}}')" = healthy ] && break
  sleep 3
done
echo "health: \$(docker inspect parenting-core --format '{{.State.Health.Status}}')"
echo "networks: \$(docker inspect parenting-core --format '{{range \$name, \$_ := .NetworkSettings.Networks}}{{\$name}} {{end}}')"
echo "ports: [\$(docker port parenting-core)\$(docker port parenting-core-db)]"
echo "telegram names in the container: \$(docker exec parenting-core sh -c 'env | grep -c TELEGRAM || true')"
echo "\$SHA" > "\$HOME/apps/parenting-core.current"
echo "deployed \$SHA"
REMOTE_END
}

case "${1:-}" in
  deploy) deploy ;;
  status) ssh "$HOST" 'docker ps -a --filter name=parenting-core --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"; echo "deployed: $(cat ~/apps/parenting-core.current 2>/dev/null || echo none)"' ;;
  logs) ssh "$HOST" "docker logs --tail '${2:-100}' parenting-core" ;;
  stop) ssh "$HOST" sh -s <<REMOTE_END
$REMOTE
compose stop
REMOTE_END
  ;;
  *) sed -n 2,10p "$0"; exit 2 ;;
esac
