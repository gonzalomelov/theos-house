# The real home, Nov 4 2026

Read from the live agent's event log on the home server. The log itself stays home, so a judge can't open it. Theo is simulated and these are rehearsal events. Each row is an example, not a rate. Some were repeated later the same day.

| Time | Event id | What came in | What the agent did |
|---|---|---|---|
| 07:30 | 76, 77 | The morning schedule | Sent the morning message to Gonza on WhatsApp |
| 12:12 | 100, 102 | Two WhatsApp voice notes from a parent, one asking when he last ate, one asking the humidity | Heard them and answered on WhatsApp |
| 12:26 | 105 | Question at the kitchen Echo, when he last ate | Answered out loud on the Echo |
| 12:33 | 106 | A recorded cry played aloud near the Tapo camera, labelled by Perception Encoder Audio | One WhatsApp message to the parent on duty |
| 12:41 | 108 | A parent asked at the Echo to sleep tonight | Answered on the Echo, moved the night duty, told both parents |
| 15:26 | 115 | Humidity reading of 76.4% in Theo's room | Muse turned on the dehumidifier's plug |
| 16:26 | 128 | Its own wake, reading 76.5% | Muse turned on the dehumidifier's plug and told Ceci |

At 15:09 a test message cleared an old note and told the agent to follow its usual rule, which came before the 15:26 row. Test messages also came before the 16:26 event. At 15:50 one turned the plug off for filming and left the decision to the next reading. At 16:05 one asked for a humidity check at 16:32, then a decision by its usual rule without asking. The 16:26 wake was the one it had set for itself, and nobody asked for the plug in that wake. The machine starts when its plug does.

Earlier the same day, a person making noise near the camera fired a false cry. That led to the stricter rule in `results/ear-false-alarms/`.

The earlier low-volume microphone test in `results/ear-path/` caught 0 of 10. The test above was louder and is one play, so it shows the path works, not how often.
