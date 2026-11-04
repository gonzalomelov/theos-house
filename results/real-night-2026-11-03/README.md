# A real night at home, Nov 3 to 4, 2026

The live agent on the Vostro, with a simulated Theo, 22:00 to 07:00. Nothing here is the mock home.

| Measure | Result |
|---|---|
| Agent up | All night, with deploy restarts. No crash restarts, no tracebacks in the logs |
| Events after 22:00 | 14 sensor and plug changes, 3 of its own wakes, all done |
| Messages sent after 22:00 | None reached a phone. Muse tried 2 to Ceci, the parent on duty, and the rehearsal rule kept both |
| Echo, vacuum at night | Never used |
| Light | Came on once before morning, not from the agent. Who did it isn't known |
| Memory | Agent 130 MB, database 25 MB and 13 MB on disk |

## Real plug, by hand

Warmer switched by a Home Assistant service call, as a person would.

- The first change after a restart: no event. A bug, fixed in #265.
- Off and on after the fix: each woke Muse, which recorded the person's choice and wrote to the parent on duty. Both messages were kept from Ceci by the rule.
- The plug's own auto-off: it did turn off 30 minutes later. It reached Muse as if a person had done it, though Muse's note read it as scheduled. Fixed in #267, not seen again on the real plug.

## Real Tapo microphone, Perception Encoder Audio, printing only

8.25 hours in 9 runs, no stall, no memory stop. 6 "a baby crying" detections.

Nobody listened to what caused them, and no audio is kept, so this doesn't say they were false. At most it is 6 in 8.25 hours in a home with no baby. No test crying was played that night. Which camera this login points to is still to be confirmed.

## Real Tapo camera, SAM 3.1, printing only

22 looks in 12 minutes, 2.2 s each, frames in memory only, nothing sent. No alerts. 19 of 22 scored a dog above 0.5 (0.5 to 0.9), with no baby in view, so the rule stayed silent. Whether a dog was really there isn't known. This run proves the path, not the accuracy.

## Not proven

- A silent Telegram message to Gonza at night: none came up. Only tests cover it.
- The feed gap ladder's timer at home: it didn't fire, as the simulated Theo was feeding.
- The dehumidifier check: A note said the plugs were empty, so Muse skipped it. The note was cleared later.
- The warmer's end message on a real plug, and the #267 fix, since no plug test ran after the last deploy.
- Tokens and cost for the night: not captured, because the event stream restarts with the agent.
- One night isn't days.
