#!/bin/sh
# Adds Theo's room sensor to Home Assistant on the Vostro, with no restart. Run from the Mac: sh deploy/home-assistant/install_nursery_climate.sh
# Reads only: Home Assistant asks the board for its readings once a minute. Backs up configuration.yaml first. Prints no token.
set -eu
HOST="${VOSTRO_HOST:-vostro}"
HERE="$(cd "$(dirname "$0")" && pwd)"
scp -q "$HERE/templates/nursery_climate.yaml" "$HOST:Engineering/home-assistant/config/templates/nursery_climate.yaml"
ssh "$HOST" sh -s <<'REMOTE'
set -eu
cd ~/Engineering/home-assistant/config
cp -n configuration.yaml configuration.yaml.bak-nursery || true
grep -q nursery_climate_read configuration.yaml || sed -i '/^shell_command:/a\  # Theo'"'"'s room sensor (parenting-agent repo, deploy/home-assistant).\n  nursery_climate_read: wget -q -T 5 -O - http://192.0.2.10/sensors' configuration.yaml
T=$(grep -E '^HA_MCP_TOKEN=' ~/apps/parenting-agent.env | cut -d= -f2-)
H="Authorization: Bearer $T"
API=http://127.0.0.1:8123/api
CHECK=$(curl -s -m 60 -X POST -H "$H" $API/config/core/check_config)
echo "check: $CHECK"
case "$CHECK" in *'"result":"valid"'*|*'"result": "valid"'*) ;; *) echo "config not valid, nothing reloaded" >&2; exit 1 ;; esac
curl -s -m 15 -o /dev/null -w "shell_command reload %{http_code}\n" -X POST -H "$H" $API/services/shell_command/reload
curl -s -m 15 -o /dev/null -w "template reload %{http_code}\n" -X POST -H "$H" $API/services/template/reload
sleep 8
for e in temperature humidity; do
  curl -s -m 5 -H "$H" $API/states/sensor.nursery_climate_$e | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('entity_id'),d.get('state'),d.get('attributes',{}).get('unit_of_measurement'))"
done
REMOTE
