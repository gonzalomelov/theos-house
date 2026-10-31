# Grandma asks the Echo, live once (issue #170)

Run on Oct 31 2026 at 11:11 Montevideo, inside the event, on the real house: the family agent on the Vostro, the real
Home Assistant, the kitchen Echo Dot, Baby Buddy with the test baby's log, Muse Spark Open on Baseten. One question,
at the Echo's normal volume (0.2, not changed).

## What happened

Home Assistant got the words as if said to the Echo: the `parenting_agent_echo_ask` event with "agente del bebé,
¿cuándo comió Theo por última vez?" and the person tag "abuela". Nobody spoke to the Echo, see below.

| Time after the question | What | File |
|---|---|---|
| 0.0 s | The automation "Parenting agent: answer on the Echo" starts, the wake words match | `ha-automation-trace.json` |
| 0.0 s | `shell_command.parenting_agent_ask` asks the voice bridge through the relay | `ha-automation-trace.json` |
| 1.5 s | Muse call 1 returns (1.17 s): it asks for `baby_summary` (the only tools it had were the three read tools) | `agent-events.jsonl` |
| 4.0 s | Muse call 2 returns (1.21 s): "Theo comió por última vez hoy a las 10:55." Role guest, no guard needed | `agent-events.jsonl` |
| 4.1 s | `notify.send_message` to `notify.gonza_s_echo_dot_speak` with that sentence, accepted | `ha-automation-trace.json`, `ha-echo-states.json` |

The log's newest feed was 10:55 that day, 90 ml (an e2e test entry on the test baby), so the answer matches the log.
Two Muse calls, USD 0.0042 in all, both to inference.baseten.co, no fallback. Nothing was written to the log, no house
action ran, `house.live` stays false.

## What is not proven

- **That the Echo was heard.** Home Assistant accepted the speak call and logged it. The Echo's media player stays
  `idle` during a speak, so there is no state that shows the sound, and nobody listened for it.
- **A question said out loud.** The Echo's voice event (`event.gonza_s_echo_dot_voice_event`) has not changed since
  Oct 29 and its `voice_command` is empty, so a spoken "Alexa, agente del bebé, ..." does not reach Home Assistant
  today. The likely cause, not verified, is the Alexa app's voice recording setting. When it works, Alexa first gives
  her own reply, then the Echo says the agent's answer.
- **Who speaks.** The Echo does not name the speaker, so on the Vostro anyone at the Echo is a read-only guest.

## Before the live run

The same question through `shell_command.parenting_agent_ask` alone, without the Echo, at 11:09: the same answer in
5.2 s round trip. Tests: 12 new in `tests/test_home_automations.py` (the guest role, the safety lines with no brain
call, a refused write tool, a wrong time from the brain replaced by the log, the token kept across a restart, Home
Assistant's script against a real bridge). Full suite: 1304 tests, all pass, 4 skipped.
