# Talk to the agent through the Echo Dot and Assist (issue #112)

## Live since Oct 31: the Echo, read only for a guest (issue #170)

Grandma at the kitchen Echo asks "¿Cuándo comió Theo por última vez?" and the Echo says the answer Muse Spark Open read
from the baby log. One live run: `results/echo-voice/live-2026-10-31/README.md`.

```
words for the Echo (its voice event, or the parenting_agent_echo_ask event with text and person)
  -> automation "Parenting agent: answer on the Echo": starts with "baby agent" or "agente del bebé"?
  -> shell_command.parenting_agent_ask (python3 /config/shell/parenting_agent_ask.py, arguments base64)
  -> http://parenting-agent-relay:8767/ask, bearer token -> the voice bridge inside the walled family agent
  -> a parent: a message to the agent, as below. A guest: VoiceGuest, Muse with the log's read tools only
  -> the reply -> notify.gonza_s_echo_dot_speak says it on the Echo
```

- **Who is a guest.** A person tag that names a parent in the `people` block is a parent. A name in
  `voice_bridge.guests` (abuela, grandma, guest, ...) is a guest. Anyone else is a guest too on the Vostro
  (`unknown_speaker: guest`), because the Echo does not say who spoke.
- **What a guest gets.** Red flags get the 911 line, newborn signs the call-now line, health questions "call the
  parents, then the pediatrician", safe sleep the AAP line, all with no brain call. Anything else goes to Muse with
  three tools: `read_baby_log`, `baby_summary`, `current_time`. No log writes, no house tools, no memory, and a guest's
  "yes" never runs a call waiting for a parent. A reply that claims a write is replaced by "only the parents can", and
  a last feed answer without the log's time is replaced by the log's own line. Every answer is a `voice_guest` event.
- **No Home Assistant restart.** `rest_command` and `intent_script` are not loaded in this house, `shell_command` is
  (the LG TV uses it) and reloads, and automations reload. Files and steps: `deploy/home-assistant/README.md`.
- **The wall.** The relay listens on 8767 for Home Assistant and forwards `/ask` and `/health` only to the agent. The
  wall check proves the relay path answers (401 with no token) and any other path gets the relay's 404. The deploy
  check connects from inside Home Assistant: the relay answers, the agent itself does not.
- **The token** is the agent's `/data/voice-bridge-token`, kept across restarts, copied once into Home Assistant's
  `secrets.yaml` (mode 600). Never printed.

What needs Gonza: a question said out loud does not reach Home Assistant yet. The Echo's voice event has carried no
words since Oct 1 (its `voice_command` is empty). In the Alexa app, More, Alexa Privacy, Manage Your Alexa Data, choose
to save voice recordings, then say "Alexa, agente del bebé, ¿cuándo comió Theo por última vez?" once. That the setting
is the cause is not verified.

## The first design, Oct 29

Built Oct 29 2026, inside the event. Today the agent can only announce on the kitchen Echo. This adds the way back: the parent says "baby agent, fed 90 ml" and the agent logs it and answers out loud.

## Why this route

Searched for the safe existing way, with no third-party skill store and nothing unvetted:

| Option | Verdict |
|---|---|
| A custom Alexa skill | Needs an Amazon developer account and an AWS Lambda or a public endpoint. New accounts and a new public URL, so no |
| Alexa smart home through Home Assistant Cloud, then Alexa routines | Needs a Nabu Casa subscription (an account and a payment), and a routine phrase is fixed, it cannot carry "fed 90 ml". No |
| Alexa Media Player from HACS (its last_called sensor) | Not core, not vetted, so no |
| Extended OpenAI Conversation from HACS | Not core, so no |
| **Core Alexa Devices integration, its voice event entity** | Already installed and working in this Home Assistant (2026.10.2). `event.gonza_s_echo_dot_voice_event` carries `voice_command` and `voice_reply` for each thing the Echo hears, pushed, not polled. **Used** |
| **Core Assist: custom sentences, intent_script, rest_command** | All core Home Assistant, YAML only. **Used** |

## How it works

```
Echo hears "Alexa, baby agent fed 90 ml"
  -> Alexa Devices updates event.gonza_s_echo_dot_voice_event (voice_command)
  -> automation: starts with "baby agent"? -> rest_command.parenting_agent_ask
Assist hears or reads "baby agent fed 90 ml"
  -> custom sentence ParentingAgentAsk {query} -> intent_script -> rest_command.parenting_agent_ask
rest_command -> POST /ask on the voice bridge (bearer token) -> a "message" on the agent's "voice" channel
agent answers -> the bridge returns the reply -> Assist says it, or notify.gonza_s_echo_dot_speak says it on the Echo
```

- Agent side: `parenting_agent/voice_bridge.py`, plug-in `parenting_agent.voice_bridge:VoiceBridge`, settings under `voice_bridge` (`host`, `port` 8767, `timeout_s` 35).
- Home Assistant side: `deploy/home-assistant/packages/parenting_agent_voice.yaml` and `deploy/home-assistant/custom_sentences/{en,es}/parenting_agent.yaml`.
- Only phrases that start with "baby agent" (or "agente del bebé") reach the agent. "Turn on the study light" stays with Assist, "what time is it" stays with Alexa.
- The message is on the `voice` channel with chat id `echo:<person>` or `assist:<person>`. A "baby agent yes" runs only a call the agent asked on that same voice chat, never one asked on Telegram (tested).
- The token lives in `data/voice-bridge-token` (mode 600) and is never printed. The bridge refuses to listen on every interface or a public address.

## What leaves the house

The Echo route sends what the parent says to Amazon, as every Alexa command already does, and the agent's spoken answer goes to Amazon to be said on the Echo, as the announcements already do. So the answer's facts (a time, an amount) reach Amazon. Assist with a local speech engine keeps everything in the house. The brain call to Muse on Baseten is the same as for a typed message.

## What needs Gonza

1. **Say yes to the Home Assistant change.** It is persistent configuration and an automation, which the house policy keeps for his yes.
2. **Copy the files** into the Home Assistant config folder on the Vostro: `packages/parenting_agent_voice.yaml` into `<config>/packages/`, the two `custom_sentences` folders into `<config>/custom_sentences/`. In `configuration.yaml` add:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. **Add two secrets** to `<config>/secrets.yaml`: `parenting_agent_voice_url: "http://<bridge address>:8767/ask"` and `parenting_agent_voice_auth: "Bearer <the token in the agent's data/voice-bridge-token>"`.
4. **Check and restart Home Assistant himself**: Developer tools, YAML, Check configuration, then Restart. Agents never restart it.
5. **Check the Echo's voice event.** Say "Alexa, what time is it", then open Developer tools, States, `event.gonza_s_echo_dot_voice_event`. `voice_command` should read the words. On Oct 29 its history since Oct 1 had 13 changes, all with an empty `voice_command`. If it stays empty, the likely cause (not verified) is the Alexa app's voice recording setting: Alexa app, More, Alexa Privacy, Manage Your Alexa Data, and choose to save recordings, since the integration reads the voice history. Then try again.
6. **Assist by voice** needs a speech engine in the pipeline (Settings, Voice assistants). Typed Assist in the Home Assistant app works with none. For voice without a new account, the local Whisper add-on. Home Assistant Cloud would need a Nabu Casa subscription.

Alexa answers first with her own reply (something like "Sorry, I don't know that one"), then the Echo says the agent's answer. No Alexa routine can silence that without a skill.

## Where the bridge runs

- On the Mac, for a test: add the plug-in to a local config with `"voice_bridge": {"host": "<Mac Tailscale 100.x address>"}` and point the secret URL there.
- On the Vostro, in the walled family agent: the agent has no address Home Assistant can reach, by design. It needs one more server block in the relay (`deploy/relay/nginx.conf`) on the Home Assistant network, forwarding port 8767 to the agent's bridge only, the bridge listening on the agent's internal network address, and `deploy/wall_check.py` taught that one inbound path. That is a change to the wall, so it is not done here. It waits for Gonza's yes with step 1.

## Tested

See `results/echo-voice/README.md`.
