# "Let me sleep" said out loud at the Echo (Nov 4)

`scripts/echo_sleep_eval.py`: the Alexa skill's real handler (`alexa-muse-baby/lambda/lambda_function.py`, its real 6 s wait), real `/ask` over HTTP, the real gate and danger screen, real Muse on Baseten, mock home and mock channel. One run at a time. Tuned on, not held-out, not quotable as a held-out number.

What a run checks: the night moves to Gonza, both parents get a message, the Echo's last line is 200 characters or less and speakable, the words run once, the cry at 02:50 reaches Gonza and not Ceci. The words are lower case with no punctuation, as the skill's slot brings them, written by hand. Amazon's ear and the real Echo were not used.

| File | What | Result |
|---|---|---|
| `baseline-es.json`, `baseline-en.json` | origin/main 0a424a0, 10 runs each | 0 of 10, 0 of 10 |
| `tuned-es.json`, `tuned-en.json` | after the fixes, 10 runs each | 10 of 10, 10 of 10 |
| `probes-es.json`, `probes-en.json` | 7 variations, 2 runs each | see below |
| `already-his-es.json`, `already-his-en.json` | the night is already Gonza's on the rota, 3 runs each | 3 of 3, 3 of 3 |

Probes: by day, after 22:00, her name as "cecy" and "sesi", his as "gonzo": all 2 of 2 in both languages. These spellings are guesses, none was seen from Amazon. "no name at all" and "grandma asks" show 0 of 2 in the `passed` field, because those two files came from the script before it knew these two aren't meant to move the night. By their own text: no name, the duty stays and the Echo asks who is speaking, 4 of 4. Grandma, the Echo says the last feed and the duty stays, 4 of 4. The eval's old log raises the feed gap line in "already his night" and in English "grandma asks", which is the log's age in the eval and not the scene.

Seen and not counted: the English "sesi" probe once wrote "Sesi said at the Echo". 2 of the 10 Spanish runs wrote the date in brackets, "(15/12)". Some Spanish messages say "la cocina del Echo".
