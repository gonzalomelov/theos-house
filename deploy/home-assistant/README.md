# Home Assistant side of the voice bridge

Two ways in, see `docs/echo-and-assist.md`.

## The Echo, live since Oct 31 2026 (no restart needed)

Everything here reloads without a Home Assistant restart: a `shell_command` (already loaded in this house for the LG
TV) and an automation.

| File in this folder | Where it goes in Home Assistant |
|---|---|
| `shell/parenting_agent_ask.py` | `/config/shell/parenting_agent_ask.py` |
| `automations/parenting_agent_echo.yaml` | created through the automation config API, lands in `automations.yaml` |

`configuration.yaml`, under the existing `shell_command:` block (arguments are base64, never shell words):

```yaml
  parenting_agent_ask: python3 /config/shell/parenting_agent_ask.py {{ source | base64_encode }} {{ (person or 'guest') | base64_encode }} {{ text | base64_encode }}
```

`secrets.yaml` (the token is the agent's `/data/voice-bridge-token`, kept across restarts, never printed):

```yaml
parenting_agent_voice_url: "http://parenting-agent-relay:8767/ask"
parenting_agent_voice_token: "<token>"
```

Then `shell_command.reload` and `automation.reload`.

## Assist (not installed)

`packages/parenting_agent_voice.yaml` and `custom_sentences/` are the first design (issue #112): `rest_command` and
`intent_script` are not loaded in this house, so they need a Home Assistant restart. `scripts/voice_bridge_check.py`
still tests them offline.
