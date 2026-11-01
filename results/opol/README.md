# The OPOL helper on recorded clips (issue #144, Nov 1 2026)

One run of `scripts/opol_run.py` through the real glasses `/hear` path on this Mac. Raw numbers in `run.json`.

| Part | Real or mocked |
|---|---|
| The parents' voices | **Stand-ins**: 10 short lines spoken by Meta's MMS-TTS (`facebook/mms-tts-eng`, `facebook/mms-tts-spa`), labelled in `LINES` in the script: 3 English and 1 Spanish line to the baby on Gonza's glasses, 3 Spanish and 1 English on Ceci's, Ceci asking Gonza for a diaper, Gonza asking the agent |
| Theo | **Mocked**: he is not born, so the run's agent has `"baby": {"born": true}` |
| Telegram | **Fake messenger**, nothing sent to anyone |
| Upload with each wearer's own token, Muse Spark Open's ear (the existing /hear race), the gate, the agent's loop, the family push | **Real** |
| Language ID | **Real**: `facebook/mms-lid-126` (rev 53da6e3) in `opol_worker.py`, on the Mac GPU, under `/tmp/pa-gpu.lock` |

## Results

| | |
|---|---|
| Lines right | 10 of 10 |
| Lines to the baby counted in the language spoken | 8 of 8, share 0.999 to 1.0 |
| Talk to the other parent ("Gonza, ¿me alcanzás un pañal?") | left out, opens with his name |
| "Agente, ¿cuánto inglés escuchó Theo hoy?" | answered on the glasses, not counted |
| Kept | day, parent, language, seconds, utterances. No word of any line in the OPOL tables, no WAV in the agent's data folder |

The answer on demand: "Hoy Theo escuchó 23 s en español (Ceci 17 s, Gonza 5 s) y 19 s en inglés (Gonza 15 s, Ceci 4 s)." The next Monday's morning line for Gonza: "Idiomas: la semana pasada Theo te escuchó 15 s en inglés (tu idioma con él) y 5 s en español." The run lowers the floor for a line (`min_minutes`) from 10 to 0.1 so seconds of clips can show one.

Limits: clean synthetic speech, one voice per language, no room noise and no baby sounds, so the 8 of 8 says the path works end to end, not how well the language ID does on real parents in a real room. Speech to another adult that does not open with a name is counted too.

```bash
.venv-hearing/bin/python scripts/opol_run.py --make-clips
sh scripts/opol_setup.sh
mkdir /tmp/pa-gpu.lock && python scripts/opol_run.py; rmdir /tmp/pa-gpu.lock
```
