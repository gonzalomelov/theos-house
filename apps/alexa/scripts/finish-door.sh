#!/bin/sh
# Last step of the door, after the Cloudflare service token "alexa-muse-baby-lambda" exists (dashboard only: the
# automation API token cannot create service tokens).
#
#   sh scripts/finish-door.sh <service token id> <file with CF_ACCESS_CLIENT_ID=... and CF_ACCESS_CLIENT_SECRET=...>
#
# Creates the policy "Alexa Lambda baby voice service auth" (non_identity, that token only), puts it on the Access app
# baby-voice-origin, writes both values into the Lambda's env and checks the door answers. Prints no secret.
set -eu
TOKEN_ID="$1"; CREDS="$2"
ACCOUNT=00000000000000000000000000000000
APP=00000000-0000-0000-0000-000000000000
export AWS_REGION=us-east-1
umask 077
set -a; . "$HOME/.config/cloudflare/bygmv-automation.env"; . "$CREDS"; set +a
API="https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/access"
AUTH="Authorization: Bearer $CLOUDFLARE_ACCESS_TOKEN"

POLICY=$(curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" "$API/policies" \
  -d "{\"name\":\"Alexa Lambda baby voice service auth\",\"decision\":\"non_identity\",\"include\":[{\"service_token\":{\"token_id\":\"$TOKEN_ID\"}}]}" | jq -r .result.id)
[ -n "$POLICY" ] && [ "$POLICY" != null ] || { echo "policy not created" >&2; exit 1; }
curl -s -X PUT -H "$AUTH" -H "Content-Type: application/json" "$API/apps/$APP" \
  -d "{\"name\":\"baby-voice-origin\",\"type\":\"self_hosted\",\"domain\":\"baby-voice.home.example\",\"session_duration\":\"24h\",\"app_launcher_visible\":false,\"policies\":[{\"id\":\"$POLICY\",\"precedence\":1}]}" \
  | jq -c '{success, errors, policies: [.result.policies[]?.name]}'

ENV=$(mktemp)
aws lambda get-function-configuration --function-name alexaMuseBabyAgent --query Environment --output json \
  | jq --arg i "$CF_ACCESS_CLIENT_ID" --arg s "$CF_ACCESS_CLIENT_SECRET" '.Variables.CF_ACCESS_CLIENT_ID=$i | .Variables.CF_ACCESS_CLIENT_SECRET=$s' > "$ENV"
aws lambda update-function-configuration --function-name alexaMuseBabyAgent --environment "file://$ENV" --query LastUpdateStatus --output text
rm -f "$ENV"

sleep 10
echo "door with the service token, no bearer (want 401 from the bridge):"
curl -s -o /dev/null -w "%{http_code}\n" -A alexa-muse-baby/1.0 -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" https://baby-voice.home.example/health
echo "door without the service token (want 302 or 403):"
curl -s -o /dev/null -w "%{http_code}\n" -A alexa-muse-baby/1.0 https://baby-voice.home.example/health
