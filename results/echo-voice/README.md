# The Echo Dot and Assist as a voice channel, tested on the agent side (issue #112)

Run on Oct 29 2026, inside the event. Home Assistant was only read (its config, the Echo entities and the voice event history), never changed. How it works and what needs Gonza: `docs/echo-and-assist.md`.

`scripts/voice_bridge_check.py` plays Home Assistant's part from the real files in `deploy/home-assistant/`: the custom sentences pick out the query, the rest_command payload template is rendered and POSTed over HTTP to a running voice bridge with the bearer token, and the intent_script speech template, or the Echo automation's condition and notify message templates, give what would be said. jinja2 stands in for Home Assistant's template engine, with its `match` test added.

## Fake utterances, rule-based brain (`fake-run.json`)

| Path | Said | Reaches the agent | Spoken back |
|---|---|---|---|
| Assist | "baby agent fed 90 ml" | yes, "fed 90 ml" | "Done, logged." |
| Assist | "Ask the baby agent how much did he drink today?" | yes | "90 ml today over 1 feeds." |
| Assist | "turn on the study light" | no, Assist keeps it | |
| Assist (es) | "agente del bebé tomó 120 ml" | yes, "tomó 120 ml" | "Done, logged." |
| Echo | "baby agent wet diaper" | yes | "Done, logged." on `notify.gonza_s_echo_dot_speak` |
| Echo | "tell the baby agent he fell asleep" | yes | "Done, logged." |
| Echo | "what time is it" | no, Alexa keeps it | |
| Echo | "baby agent yes" (nothing waiting) | yes | "Noted." |
| | a wrong token | refused, HTTP 401 | |

The log after the run held the four entries: feeding 90 ml, feeding 120 ml, wet diaper, sleep start. No network call.

## One real round with Muse Spark Open (`muse-run.json`)

| Path | Said | Spoken back | Seconds |
|---|---|---|---|
| Assist | "baby agent fed 90 ml" | "Logged 90 ml at 12:13." | 2.54 |
| Echo | "baby agent when was the last feed" | "Last feed was at 12:13 today, 90 ml." | 2.74 |
| Assist (es) | "agente del bebé cambié un pañal mojado" | "Pañal mojado registrado a las 12:13." | 3.78 |

6 brain calls, all to inference.baseten.co. The log after: feeding 90 ml, wet diaper. All three answers came back well inside the rest_command timeout of 40 s.

## Unit tests

`tests/test_home_automations.py`, `VoiceBridgeTest` and `WordsTest`: a fake utterance logs a feed and says so, a question is answered from the log, a wrong token reaches nothing, an unknown source is refused, a yes said on the Echo does not run a call that was asked on Telegram, the bridge refuses 0.0.0.0 and a public address, the wake words are stripped in English and Spanish, spoken replies lose markdown and links and stay under 400 characters.

## Not tested, and why

- **The real Echo.** It needs the Home Assistant change (Gonza's yes and his restart). Also, the Echo's voice event had an empty `voice_command` in all 13 changes since Oct 1, so whether it carries the words on this account is unproven. Step 5 of the doc checks it.
- **Assist by voice.** Typed Assist needs no speech engine. Spoken Assist needs one in the pipeline, which was not checked.
- **The bridge in the walled agent on the Vostro.** It needs a relay change to the wall, waiting for Gonza's yes.
