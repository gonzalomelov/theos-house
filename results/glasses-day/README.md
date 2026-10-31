# A day on the glasses display, live, Oct 30 2026

Run on Oct 30 2026 at 21:12 to 21:18 Montevideo, during the Meta hackathon. Until now the glasses display showed the changing table and the dog only (`results/glasses-live`). Now everything the agent tells a parent that fits a glance is also a card on that parent's glasses, in their language, and only on the glasses of the parent the Telegram copy went to. The cards and their rules: `apps/glasses/HUD.md`, "Everything that fits a glance".

Result: **11 of 11 scenes passed** in the recorded take. Every expected card reached the right parent's glasses, and no card reached the other parent's. Two rehearsals came before it (10 of 11 each, the next feed reminder missed, fixed below). That is one recorded take, not a rate.

Clip: `~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-day.mp4`, 5 min 48 s, silent, not committed. `hud-day-raw.mp4` next to it is the untouched screen recording. One take in real time, not edited. On screen: "LIVE", "Live: the family agent running on this Mac, glasses and lens simulated by Meta's mock", "A day compressed: the agent's clock jumps between moments. Telegram captured, house dry", and under the lens each scene with the agent's time ("09:54 · Red flag · Gonza's glasses").

`run.json` is that run: every scene, every card each parent's glasses got with its text and times, the Telegram capture, the house dry runs, the SAM 3.1 checks and the app's display log. Screenshots from the clip: `01-morning.png` to `05-red-flag.png`.

## What ran live

| Part | What ran | Where |
|---|---|---|
| The family agent | `config/agent.vostro.json` with every plug-in and its own loop (Telegram, prep, the day engine, the night feed and its rota, the house brain, reminders, the rhythm reminders, the sitter, the family push), plus the glasses channel and the car seat coach | this Mac |
| Brain | Muse Spark Open, `meta-models/muse-spark-open-1026`, 21 calls, 0.13 USD | Baseten |
| Baby log | Baby Buddy, child `test-baby`, standing in for Theo (`baby.born` true for the run). Two night bottles seeded before the day (00:30 and 03:30, entries 216 and 217, tagged e2e) so the rhythm has a recent rhythm. Everything else was written by the agent from the parents' messages | the Vostro, through the SSH tunnel |
| Home Assistant | reads only (weather, house state) through the tunnel. The 4 house writes of the day (nap mode, the Echo announce) were dry runs | the Vostro, reads |
| SAM 3.1 | `sam3_prompts_worker` for the car seat coach, one process, under `/tmp/pa-gpu.lock`, killed at the end. 1.4 to 1.7 s a look | this Mac |
| Display | 29 sends through DAT's Display API on Gonza's glasses, the red flag's two refreshes among them (`MWDATDisplay` 1.0.1), drawn by Meta's `MockDisplayKit` | iOS 27.0 simulator, iPhone 18 Pro |
| Telegram | a capture (`parenting_agent/e2e/harness.py`), 15 messages, fake chat ids. Nothing reached api.telegram.org | this Mac |

## The cards

Gonza's glasses are the app in the simulator (the display log). Ceci's glasses are a second listener on the same endpoint with her own token (her event stream, no display). "Agent to lens" is from the agent publishing the card to the display accepting it (Gonza) or to her stream receiving it (Ceci), same Mac, real clock.

| Agent time | Scene and trigger | Gonza's glasses | Ceci's glasses | Agent to lens |
|---|---|---|---|---|
| 06:00 | Gonza on Telegram: "Le di 80 ml de mamadera." | Respuesta · "Anotado, 80 ml en mamadera." | nothing | 0.02 s |
| 07:31 | The morning message (day engine brief, house brain night, prep lines), one per parent | Buen día, Gonza · "Esta noche te toca a vos." · "Anoche: 3 tomas…" | Buen día, Ceci · "Anoche: 3 tomas…" · "Clima: nublado, 14 a 15 C." | 0.002 s, 0.001 s |
| 08:10 | The rhythm reminder, 20 min before the predicted feed, both by day | Próxima toma · "Cerca de las 08:30 · en 20 min" · "Cada 2 h 45 min más o menos" | the same card | 0.002 s, 0.001 s |
| 08:12 | Ceci on Telegram: the bottle, then "Se durmió." Nap mode on, both by day | Modo siesta · "Siesta desde las 08:10" · "Prueba en seco, no se movió nada" | the same, plus her two answers ("Anotado, 90 ml en mamadera.", "Se durmió anotado.") | 0.003 s |
| 09:28 | Ceci: "Se despertó." Nap mode off | Fin de la siesta · "Se despertó, la casa vuelve a lo normal" | the same, plus her answer | 0.005 s |
| 09:33 | Gonza on his glasses: "¿Cuándo comió por última vez?" | Respuesta · "Fue a las 08:10, 90 ml en mamadera." | nothing | 0.07 s, words to card 3.95 s (Muse) |
| 09:36 | Gonza on Telegram: "¿Quién está de turno esta noche?" (the rota, no brain call) | Esta noche · "De turno: Gonza" | nothing | 0.02 s |
| 09:39 | Ceci on Telegram: "Quedan pocos pañales, agregalos a la lista de compras." | nothing | Lista de compras · "Pañales está listo para la lista de compras." | 0.001 s |
| 09:44 | Gonza on his glasses: "Ayudame a instalar la silla del auto." Muse starts the coach. "Sí." on the glasses answers step 1 | Silla del auto, step by step: "¿Silla atrás, mirando hacia atrás?" (Paso 1 de 8), then steps 2 to 6 each as asked and then "Visto en cámara: bien" (SAM 3.1 on our car seat clip), then "Revisión de la silla terminada · No es un veredicto: consultá a un técnico" | nothing | 0.002 to 0.12 s, words to the first step card 10.7 s (Muse's call, then SAM 3.1 loads before the coach starts) |
| 09:54 | Gonza on Telegram: "Test: está azul y no respira bien." The safety gate's fixed 911 line, no brain call | Llamá al 911 ya · "Puede ser una emergencia" · "Contales lo que ves" · "911 · hace 0:00", with an "Entendido" button. Sticky: resent at 0:15 and 0:30 (14.9 s and 15.1 s apart, under Meta's 20 s dim) | nothing | 0.25 s |
| 09:55 | Gonza on his glasses: "Listo, ya llamé al 911." | the red flag card goes, then Respuesta · "Gracias por avisar, Gonza." | nothing | words to card 4.7 s (Muse) |

Every Telegram copy still went out: 15 messages in the capture, 7 to Gonza's chat and 8 to Ceci's. The agent logged 36 cards (26 for Gonza, 10 for Ceci), each with the parent it was for.

The HUD adds almost nothing: agent to lens is under 0.12 s for every card except the red flag (0.25 s, it plays a chime first). The slow parts are Muse (about 4 s an answer here) and loading SAM 3.1 when the car seat coach starts.

## Built and tested, not in this run

These cards are built and covered by tests (`tests/test_glasses_cards.py`, `apps/glasses/Tests/HUDStateTests.swift`), but no scene of this day triggered them, because each needs a night or a camera scene of its own: the night handover ("Cambio de turno"), tonight's plan, the night feed (awake signal, warmer, light), supplies running low from the day engine's count, the bath watch, the urgent newborn line (fever under 3 months), reminders, the sitter. The dog near the baby and the changing table cards ran live on Oct 30 in `results/glasses-live`.

## Still mocked, and why

| Part | Why |
|---|---|
| The glasses and their lens | No Meta Ray-Ban Display here. DAT MockDeviceKit pairs a simulated one, MockDisplayKit draws what the app sends through the real Display API |
| Ceci's glasses | One simulator, so her glasses are a second listener on the same endpoint with her own token: the routing is real, there is no second display |
| The camera picture | Our synthetic car seat clip (`carseat/clips/test/test-02-correct.mp4`), played forwards and backwards in a loop. No real child |
| The parents' words | Typed by the run's script on the captured Telegram and on the glasses endpoint (the same `/say` path the app uses). The app has no speech recognition yet |
| The clock | The e2e day's virtual clock (`parenting_agent/e2e/clock.py`) jumps between moments of the day. The glasses endpoint, the app, the camera and SAM 3.1 keep real time |
| Telegram and the house | Captured and dry, on purpose: no real messages, no real devices. Nothing ran on the Vostro |
| Audio | The app spoke the coach's lines and chimed for the red flag. The simulator records no sound |

## What is weak

- **The car seat coach speaks English.** The cards are Spanish (`hud_cards.CAR_SEAT`), the coach's spoken steps and the app's line log are its English words.
- **Muse still adds its own car seat words.** With the new standing note ("the coach speaks each step itself") Muse said "Primero, ponela mirando hacia atrás en el asiento trasero", which matches the coach's step 1. In rehearsal 1, before the note, it told Gonza to place a base the Joie i-Snug does not have.
- **The shopping list answer is Muse's**: "Pañales está listo para la lista de compras. ¿Lo agrego?" for a list add that was dry. The card shows what Ceci got on Telegram, word for word.
- **The morning numbers come from the test child**: "el sueño más largo 0.0 h" because the seeded night has feeds and no sleep entries.
- **Hand steps left open.** The run stopped the coach after the five camera steps, so the two hand checks show as open in its summary.

## What we fixed to make it run

- **Icons.** DAT 1.0.1's `IconName` has its own raw values, not its case names, so `IconName(rawValue:)` found nothing and every card before today drew the "i" icon. `DisplayHUD.icons` maps each name to its case, and a test keeps it in step with the Python catalog.
- **The car seat answer.** In rehearsal 1 "sí" went to Muse, which answered in its own words, the step stayed open, and the agent then said nothing was waiting for a yes. A plain yes or no on the coach's channel now answers the step it is asking (`Agent.answer_takers`), and the agent says "Anotado: sí."
- **The next feed reminder.** In both rehearsals it never fired: the test child's history ended 26 h before the day, so the median gap was over a day. Two night bottles are now seeded before the day, and the reminder scene follows the morning without a clock jump that could skip its 20 minute window.

## Run it

```bash
python scripts/glasses_hud_day.py --build-feed      # MockFeed/hud-day-feed.mp4
xcodebuild -project apps/glasses/ParentingGlasses.xcodeproj -scheme ParentingGlasses -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' -derivedDataPath apps/glasses/build build
xcrun simctl install booted apps/glasses/build/Build/Products/Debug-iphonesimulator/ParentingGlasses.app
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro   # Baby Buddy
ssh -f -N -L 127.0.0.1:18123:127.0.0.1:8123 vostro   # Home Assistant reads
python scripts/glasses_hud_day.py --udid SIM --out-dir results/glasses-day --name run \
  --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-day.mp4
```

The script takes the GPU lock, removes the earlier run's test entries of the day, starts the agent, launches the app with `-hudDay YES`, plays the day and frees the lock.
