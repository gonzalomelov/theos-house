#!/bin/sh
# Puts the read-only nursery MCP server on the Vostro at https://nursery-mcp.home.example/mcp. Run from the Mac:
#   sh deploy/nursery-mcp/install.sh
# Makes the key once (NURSERY_MCP_KEY in meta-hackathon-2026/.env), never prints it, and copies it to the clipboard for
# Muse's connector settings. Uses sudo on the Vostro for the service and the Cloudflare route.
set -eu
HOST="${VOSTRO_HOST:-vostro}"
NAME=nursery-mcp.home.example
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HOME/.parenting-agent.env"
grep -q '^NURSERY_MCP_KEY=' "$ENV_FILE" || printf 'NURSERY_MCP_KEY=%s\n' "$(openssl rand -hex 32)" >> "$ENV_FILE"
KEY=$(grep '^NURSERY_MCP_KEY=' "$ENV_FILE" | cut -d= -f2-)
ssh "$HOST" 'mkdir -p ~/apps/nursery-mcp'
scp -q "$HERE/server.py" "$HOST:apps/nursery-mcp/server.py"
# The key goes over stdin inside the script, so it is never on a command line.
{ printf 'KEY=%s\nNAME=%s\n' "$KEY" "$NAME"; cat <<'REMOTE'
set -eu
HA=$(grep -E '^HA_MCP_TOKEN=' ~/apps/parenting-agent.env | cut -d= -f2-)
umask 077
printf 'NURSERY_MCP_KEY=%s\nHA_TOKEN=%s\n' "$KEY" "$HA" > ~/apps/nursery-mcp/env
sudo tee /etc/systemd/system/nursery-mcp.service >/dev/null <<UNIT
[Unit]
Description=Read-only nursery MCP server for Muse
After=network-online.target

[Service]
User=$(id -un)
EnvironmentFile=$HOME/apps/nursery-mcp/env
ExecStart=/usr/bin/python3 $HOME/apps/nursery-mcp/server.py
Restart=always
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now nursery-mcp
sudo systemctl restart nursery-mcp
sleep 2
CFG=/etc/cloudflared/config.yml
if ! sudo grep -q "$NAME" "$CFG"; then
  sudo cp -n "$CFG" "$CFG.bak-nursery" || true
  sudo sed -i "0,/^  - hostname:/s||  - hostname: $NAME\n    service: http://127.0.0.1:8933\n  - hostname:|" "$CFG"
  TUNNEL=$(sudo awk '/^tunnel:/{print $2}' "$CFG")
  cloudflared tunnel route dns "$TUNNEL" "$NAME" || sudo cloudflared tunnel route dns "$TUNNEL" "$NAME"
  sudo systemctl restart cloudflared
fi
curl -s -m 5 -o /dev/null -w "local without key: %{http_code} (want 401)\n" -X POST http://127.0.0.1:8933/mcp -d '{}'
REMOTE
} | ssh "$HOST" sh -s
sleep 6
BODY='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"nursery_climate"}}'
curl -s -m 15 -o /dev/null -w "public without key: %{http_code} (want 401)\n" -X POST "https://$NAME/mcp" -d "$BODY" || true
curl -s -m 15 -H "Authorization: Bearer $KEY" -X POST "https://$NAME/mcp" -d "$BODY" | cut -c1-300; echo
printf '%s' "$KEY" | pbcopy
echo "Key copied to the clipboard. URL: https://$NAME/mcp"
