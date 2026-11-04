# Car seat coach

The agent coaches a parent through installing an infant carrier with the car's 3-point seat belt and no base, one step at a time by voice. The head camera checks what a camera can see, with Meta's SAM 3.1 on the Mac's GPU. What a camera cannot see, the agent asks and logs. Built during the Meta hackathon (issue #30).

The coach never says the install is safe. It says which visible checks passed, which failed or were not seen, which hand checks remain, and it always ends by suggesting one check by a certified child passenger safety technician. It gives no medical advice.

## The pieces

| Piece | Code | What it does |
|---|---|---|
| Seat profile | `parenting_agent/carseat/manual.py`, `skills/carseat/joie-i-snug-2.json` | Reads the maker's manual (text only, extracted locally with pdftotext) and keeps the belt install steps, the warnings, the child limits, the handle position for the car and the level line rule |
| Car profile | `skills/carseat/tesla-model-3.json` | Tesla Model 3 rules: never rear facing in front with the airbag on, ISOFIX on the outer rear seats only, the center seat takes a belted seat only |
| Visible checks | `parenting_agent/carseat/checks.py` | From SAM 3.1 masks: lap belt in both side guides, shoulder belt in the rear guide, no twist, level line level, handle upright. Each check says pass, fail or unseen. Unseen is never turned into pass |
| SAM 3.1 masks | `parenting_agent/carseat/sam3_masks.py`, `parenting_agent/sam3_prompts_worker.py` | Text prompts to masks on the Mac's GPU, same weights and setup as the changing table (`docs/sam3-local.md`). Frames go through a local pipe and are never saved |
| Muse second opinion | `parenting_agent/carseat/muse_check.py`, `scripts/carseat_muse_eval.py` | One zoomed still per camera step to Muse Spark Open, neutral question, strict JSON, majority of 3. A pass needs SAM and Muse both. Opt-in |
| Coach | `parenting_agent/carseat/coach.py`, `skills/car-seat.json` | Speaks each step, checks the newest frame taken after the step was spoken, asks the hand checks, speaks the summary |
| Plug-in | `parenting_agent/carseat/plugin.py` | Tools `start_car_seat_coach`, `answer_car_seat_check`, `car_seat_outgrow` for the agent |
| Outgrow watch | `parenting_agent/carseat/outgrow.py`, `simweek/growth.py` | Weight and height from Baby Buddy against the seat's limits, with a heads up 4 weeks before |
| Test clips | `scripts/carseat_render.py` | 3D-rendered clips with exact labels and planted mistakes |
| Scoring | `scripts/carseat_eval.py` | Streams each clip through the coach in real time and scores it, results in `results/carseat/` |

## The steps

The order of a real belt install (a Joie i-Gemm install video, Nov 1, and the i-Snug 2 manual):

1. Harness pinch test, with the doll or baby buckled in and the carrier still facing the parent. Asked. It comes first because the harness is only visible while the baby faces the camera, before the carrier goes in the car facing back.
2. Carrier on a rear seat, facing the back, never in front with the airbag on. Asked.
3. Lap belt through both side guides. Camera, one close-up per guide.
4. Buckle the seat belt until it clicks. Asked.
5. Shoulder belt round the back into the rear guide. Camera, close-up.
6. The belt's route, lap belt on top and shoulder belt around the back, against the seat's manual and the blue guides. Asked, with the parent looking: a "no" gets the fix line, a "listo", and the question again, up to three times.
7. Tighten the lap belt first, then the shoulder belt. Asked.
8. Lap belt flat, no twist. Camera, from the door.
9. Level line on the side of the carrier level with the ground. Camera, with the head held level.
10. Handle upright, position 1, the car position. Camera, needs only the car seat in view.
11. Movement at the belt path under 2.5 cm. Asked, the camera cannot feel it.
12. Summary and one check by a certified technician.

Hand checks are never skipped. An unanswered one stays open in the summary.

**The coach waits for the parent.** A camera step is said, then the coach watches while the parent works and never says a fail in that time. It moves on when the parent says "listo" or "ya" (glasses microphone through the speech gate, or the chat), when the step's check passes on its own, or after a long fallback (`ready_timeout_s`, 180 s), then it judges (`step_timeout_s`, 20 s). Until Nov 1 every step judged within a fixed 8 s, and on a real install video every step timed out before the parent had acted.

**The guides are judged up close.** After "listo" on a guide step the coach says "Acercá el teléfono a la guía azul del lado de la puerta" (then "del otro lado", or "de atrás") and judges only frames where a guide fills at least 0.8% of the view (`closeup_min_share`), for up to 30 s (`closeup_timeout_s`). A guide needs two close frames that agree, a pass and a fail with no third frame is unsure, and one close frame alone is listed as not seen (a single door-distance frame read a false fail in the Nov 1 proof run). From the door SAM 3.1 never found the guides on the real video, so a door view of a guide is never judged.

Every line is in the language of the parent who started the coach: their "lang" in the people block, else Spanish for a request in Spanish, else the family's language (`LINES`, `CAMERA_STEPS`, `SUMMARY` and `NAMES` in `coach.py`, `ask_es` and `technician_es` in `skills/car-seat.json`, `text_es` for the car rule). The same words are spoken (each voice event carries its `lang`, and `say` on the Mac uses a Spanish voice for Spanish), shown on the glasses card and, when the coach was started from Telegram, sent to that parent's chat. The summary is the coach's last line and is kept in the conversation, it is never handed to the brain to say again. The coach refuses "safe", "safely", "seguro" and "segura" in either language. "Cinturón de seguridad" is the seat belt's name and is allowed.

**The camera can't read the belt's route.** The guide checks see a belt in a guide, not which belt: on a still of the commonest mistake (shoulder belt in the side guides, lap belt round the back) SAM 3.1 passed both close-ups. Muse couldn't tell the two apart either, so the route is asked and the summary says "a belt in both side guides", not "the lap belt". Numbers in `results/carseat/routing/README.md`.

## Seat profile from a manual

```bash
python -m parenting_agent.carseat.manual MANUAL.pdf --seat "Joie i-Snug 2" --url URL > skills/carseat/joie-i-snug-2.json
```

The Joie Litetrax travel system ships with the i-Snug 2 carrier in the EU and NZ listings (the Gemm in the US). The manual comes from Joie's own download server, linked from Joie's UK support page for the "litetrax TS w/ i-Snug 2". The PDF stays outside the repo. The profile keeps its URL and SHA-256, and a test checks that the parser rebuilds the committed profile from the real PDF when it is on this machine.

Limits from the manual: 40 to 75 cm, up to 13 kg, up to 12 months. Handle position 1 for the car. The level line must be level with the ground.

## The camera

SAM 3.1 finds the parts by text: `strap` for the belt, `blue clip` for the belt guides, `handle`, `green line` for the level line and `car seat` for the seat itself. The words live in `skills/car-seat.json`, because the guide color and the level indicator differ between seats. The geometry then decides:

- a guide holds the belt when enough of the ring around it is belt and the belt runs between the two side guides
- the two side guides are the pair that lines up across the view, the rear guide is the other one
- a twist shows as the belt narrowing to under 45% of its usual width between the guides
- the level line passes when it is within 8 degrees of level in the image, so the phone must be held level and side on
- a level line more than 30 degrees off is read as not seen, not as a fail: no install is that steep, and on a real install video (Nov 1) SAM 3.1 read a belt edge as the level line at 68 degrees
- the handle passes when it stands within 40 degrees of vertical, with the car seat in view (`car seat` at 0.3 or a guide). Where SAM reads the same pixels as a strap more surely than as a handle, they count as belt
- a guide up close holds the belt when at least 10% of the ring around it is belt (`closeup_coverage_min`)

A miss at the far side guide alone cannot be seen from the door side, because the belt projects onto the guide. That is why the far guide gets its own close-up. The rendered clips are filmed from the door with the install already done, so `scripts/carseat_eval.py` runs them with `"closeup": false, "ready_timeout_s": 0` and the 8 s window they were scored with: every step judged at once, guides judged from the door.

## Test material

No seat has been bought yet and the Tesla arrives on Nov 5, so the tests run on rendered clips. `scripts/carseat_render.py` is a small software renderer in NumPy and OpenCV, no extra packages, no Blender. It draws the rear bench, a carrier, a doll, the guides, the handle, the level line and the belts, and plants one mistake per wrong clip: the belt outside a guide (near side, both side guides, or the rear guide), a twisted belt, a wrong recline (12 to 20 degrees off), or the handle in position 2 or 3. Unseen clips keep the carrier out of view or cover it with a blanket.

```bash
python scripts/carseat_render.py --out ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips --set test
python scripts/carseat_eval.py --clips ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips/test
```

Two sets with different seeds. The dev set (8 correct, 12 wrong, 2 unseen) was the only one used to pick the prompts and the thresholds. The test set (12 correct, 12 wrong, 4 unseen) was rendered once and scored once with the thresholds fixed. Clips live outside the repo and are never committed. Public install videos may be used for local accuracy checks only, stored outside the repo, never in the demo.

## Results

Test set, scored once with the thresholds fixed on the dev set (`results/carseat/test.md`, `test.json`):

| Measure | Target | Result |
|---|---|---|
| Wrong installs flagged | at least 9 of 10 | 11 of 12 (outside guide 3 of 3, twisted 3 of 3, recline 3 of 3, handle 2 of 3) |
| False alarms on correct installs | at most 1 | 1 of 12 (the handle read 44 degrees from vertical, the limit is 40) |
| Abstains when it cannot see | yes | 4 of 4 unseen clips, no belt verdicts |
| Result spoken within 2 s of the step being visible | every step | 100 of 116 steps, median 1.69 s, max 4.11 s |
| Spoken texts with "safe" | none | none |
| Hand checks asked and logged | every run | every clip |

The 2 s target is not met for every step. One SAM 3.1 pass with two prompts takes about 1.5 s on the M3 Max, three prompts about 1.8 s. The misses are mostly the first camera step, where the camera pans onto the carrier while a pass on the floor view is still running, so the result comes from the next pass, 2.0 to 2.5 s after the carrier is in view. The handle missed once (test-24, never found) and false-alarmed once (test-01).

Dev set, used to choose the prompts and thresholds (`results/carseat/dev.md`): 12 of 12 flagged, 0 false alarms, 2 of 2 abstained, 86 of 95 steps within 2 s.

These are renders, not a real car. The numbers say the checks work on clean geometry with exact labels. They do not say how SAM 3.1 does on a real belt in a real car, which needs the Tesla run.

## On a real install video (Nov 1)

A public Joie i-Gemm install (a sibling of the i-Snug 2), kept outside the repo and never committed. The baby install runs 8:03 to 9:01. The coach ran one camera step per segment, in Spanish, with SAM 3.1 on the Mac and a simulated "listo" when she finishes each step.

| Step | She does | Simulated "listo" | Coach | Matches |
|---|---|---|---|---|
| Lap belt in both side guides | belt through both hooks 8:28 to 8:35 | 8:35 | asked for both close-ups, 12 frames 8:36 to 9:01 at door distance, not seen | yes: she never came close, and nothing was judged from the door |
| Shoulder belt in the rear guide | round the back into the rear guide 8:43 to 8:50 | 8:50 | asked for the close-up, 5 to 6 frames 8:50 to 9:01, not seen | yes, same |
| No twist | pulls tight 8:50 to 8:54 | 8:54 | 4 to 5 door frames after "listo", not seen | not judged: the guides are not found from the door |
| Level line | angle set at 8:23 | 8:55 | one frame read fail before "listo" and was not said, 4 frames after, not seen | not judged, no wrong call |
| Handle upright | handle up 8:54 to 9:00 | 9:00 | pass on the 9:01 frame | yes |

Her guides are red, so the run was made with `blue clip` (the i-Snug 2) and `red clip`, with the same results. The close-up check itself was set on close-up frames of other seats in the same video (3:12, 3:22, 7:20): a guide with no belt failed on 3 of 4 frames (the 4th not found), a rear guide with the belt passed 2 of 3 frames (so two agreeing frames are needed), a Silver Cross guide with the belt was not found at all (score under 0.2), and a door view at 9:05 passed a guide at 0.4% of the frame until the close-up floor went to 0.8%. These are tuning frames, not a blind test.

## Filming the real take

For Gonza's take with the phone strapped to his head. The coach speaks each step, he does it, then says the word in bold.

1. Carrier in his hands outside the car, doll buckled in, carrier facing him. The coach opens and asks the pinch test. He pinches the strap at the collarbone with the camera looking at it and says **"no"** (no slack).
2. He puts the carrier on the rear seat facing back and says **"sí"**.
3. He threads the lap belt through both blue side guides and says **"listo"**. The coach says "Acercá el teléfono a la guía azul del lado de la puerta": he leans in until the guide fills about a palm's width of the view (30 to 50 cm) and holds still 6 to 8 s, until the coach answers. Then "del otro lado": he leans over to the far guide and holds the same way.
4. He buckles until it clicks and says **"sí"**.
5. He takes the shoulder belt round the back into the rear blue guide and says **"listo"**. At "Acercá el teléfono a la guía azul de atrás" he leans to the head end and holds 6 to 8 s.
6. The coach asks him to look at the belt's route against the manual. Belt wrong on purpose: he says **"no, lo tengo al revés"**, fixes it, says **"listo, ya está"**, and to the second question **"sí, ahora sí"**. The camera doesn't judge this step.
7. He tightens the lap belt first, then the shoulder belt, and says **"sí"**.
8. Back at the door, head level, the lap belt across the carrier in view: **"listo"**.
9. Side of the carrier with the level line in view, head level: **"listo"**.
10. Handle up to position 1, the carrier in view: **"listo"**.
11. He shakes the carrier at the belt path and says **"sí, menos de dos centímetros"**, never "se mueve poco": said about Theo that's a red flag, and the core's gate sends the 911 line to both parents. The coach ends with the summary and the technician line.

Good light, no hand covering the guide in the close-ups, one step at a time. A step he does not finish ends on its own after 3 minutes.

### The phone on the head as the glasses

The companion app reads only the glasses camera (DAT), it has no iPhone camera mode. So for the take the iPhone is the head camera and microphone through Continuity Camera, and `scripts/carseat_glasses_take.py` on the Mac plays the glasses app's part: frames to the glasses endpoint's `/frame`, his utterances cut on the Mac (the app's cutter) to `/hear`, the coach's lines spoken in MMS-TTS on the Mac, the lens card drawn on the recorded clip. Behind the endpoint it is the agent as it runs: Muse's ear and the speech gate, the coach with SAM 3.1 (one process, `/tmp/pa-gpu.lock`), house dry, Telegram and Home Assistant blanked. "Agente, ayudame a instalar la silla del auto" starts the coach without the brain choosing the tool (it did not in 2 of 4 speech runs on Oct 30), and while the coach runs "listo", "ya", "sí" and "no" need no "agente".

Checklist for the take:

1. Mac on the front seat or the car roof, on power, volume up (or AirPods paired to the Mac), Wi-Fi and Bluetooth on, same Apple ID as the iPhone. No other SAM 3.1 run on the Mac (`ls /tmp/pa-gpu.lock` says no such file).
2. iPhone locked, strapped to the forehead, back camera facing forward, landscape. Check the Mac sees it: `ffmpeg -f avfoundation -list_devices true -i ""` lists "iPhone Camera" and "iPhone Microphone". The first run asks to give the terminal camera and microphone access, allow both (System Settings, Privacy and Security).
3. In the repo: `.venv/bin/python scripts/carseat_glasses_take.py --camera "iPhone Camera" --mic "iPhone Microphone" --out ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat-take/take1.mp4`. Wait for the line "live: say ...", about 20 s.
4. Doll buckled in, carrier facing him, say **"Agente, ayudame a instalar la silla del auto"**. About 15 s later (SAM 3.1 loads) the coach opens. Then follow the ten steps above, waiting for each line to end before answering. Say two or three words, not one: "listo, ya está", "sí, hizo clic", "no, no sobra nada". Muse's ear misses single words more often (in the proof run's MMS voice "Sí." came back as "The" and "Listo." as "Y esto"). If the coach does not answer within about 10 s, say it again.
5. After the summary ("Esto no es un veredicto...") press Ctrl-C. The clip and a `.json` report land next to `--out`, never in the repo.

### Proof run on the install video (Nov 1)

`scripts/carseat_glasses_take.py --video` on the public Joie i-Gemm install (8:00 to 9:02, kept outside the repo, never committed): the feed plays the part of the video that matches the coach's step, and an MMS-TTS voice says the parent's words through `/hear` when she finishes, after the coach's line ends. Muse's ear, the speech gate, the coach, SAM 3.1 and the cards ran for real, the brain was not needed (0 calls). The clip with the lens card and both voices is local: `meta-hackathon-2026-synthetic/carseat-yt-test/coach-glasses-take.mp4`, 7 min 42 s, with its `.json` report.

| What | Result |
|---|---|
| "Agente, ayudame a instalar la silla del auto" | heard in 3.5 s, coach started without the brain, first card "Paso 1 de 10" |
| Spoken answers and done words, no "agente" | 9 of 9 heard on the first try, ear 3.5 to 4.7 s each |
| Cards | one per step in order, the short reply ("Anotado: sí.") before the next step's card, close-up cards name the guide |
| Camera checks | handle passed on its own before "listo". Both side guides and the rear guide: no close frames, not seen. No twist and level line: not seen. Nothing passed or failed wrongly |
| End card | "Revisión de la silla terminada / No es un veredicto: consultá a un técnico", summary spoken with the technician line |

Two fixes came from rehearsals of this run: a bare "Sí.", "Listo." or "Ya." in MMS-TTS's voice was misheard by Muse's ear ("The", "Y esto", nothing), two to four words were heard right, so the mocked parent says "Sí, hizo clic" or "Listo, ya está" and the checklist asks for the same. And one door-distance frame of her red guide filling 0.86% of the view read as a fail on the rear guide while the belt was in it, so one close frame alone is now not seen. Her guides are red and the run used the i-Snug 2's `blue clip`.

## Muse Spark Open as a second pair of eyes

Built Oct 29 2026. With `"car_seat": {"muse": {"enabled": true, "samples": 3}}` in the agent config, the coach also sends one still frame per camera step to Muse Spark Open on Baseten (`parenting_agent/carseat/muse_check.py`). The frame is zoomed on the middle of the view and comes with one neutral question for that step and a strict JSON schema, for example "is the handle raised or lowered", three times in parallel, majority wins. Every schema holds `movement_under_1_inch`, which only accepts `cannot_judge`: a still cannot show movement, so the parent is asked.

Second-opinion rule: a check passes only when SAM 3.1 and Muse both say pass. Both fail, or one fails and the other cannot see, is a fail. A pass against a fail or against "cannot see" is "unsure": the coach says its two checks disagree, does not count it as passed and asks for a check by hand. If Muse cannot be reached, SAM's verdict stands and is marked single. Muse votes on the handle and the level line only. On belt routing and twist it stayed near chance and passed covered views, so it is not asked there.

On the 28 test renders, scored once (`results/carseat/muse/README.md`): Muse alone got the handle right 25 of 28 times and the level line 18 of 28, with no wrong install passed, but it passed 4 checks on covered or floor views. With the rule, 12 of 12 wrong installs were not passed (SAM alone 11 of 12, Muse caught the folded handle SAM never found), no false alarm (SAM alone 1), no unseen view passed, and 5 of 12 correct installs ended with a hand check instead of a pass. A Muse step takes a median 8.1 s and $0.011, so it answers well after the 2 s target.

**Privacy.** With Muse on, frames leave the Mac: one zoomed still per voting step, made in memory, sent to inference.baseten.co in `samples` parallel calls (3 by default, a majority vote), never saved by us. These calls run on the free hackathon credits, and Meta said content sent on those credits may be used to train future Meta models, so it is not promised to stay private. Each call is a `carseat_muse` event with its host. With Muse off (the default), frames stay on the Mac as before.

## Outgrow watch

```bash
python -m simweek.growth load --anchor 2026-10-27   # three weights and heights in the simulated week, tagged
```

`car_seat_outgrow` reads weight and height from Baby Buddy and fits the recent pace. Early weeks grow fastest, so the straight line reaches a limit sooner than real growth will and the heads up comes early, never late.

On the simulated week in Baby Buddy (`results/carseat/outgrow-simweek.json`): Test Baby is at 4.38 kg and 54.8 cm, the height limit (75 cm) comes first, in about 21 weeks, around Mar 26 2027. No heads up yet.

## What is still open

- A real run in the Tesla with the real seat (after Nov 5 and after the seat is bought), the first close-ups on the i-Snug 2's own guides.
- The no twist check still needs both side guides from the door, which SAM 3.1 did not find on the real video.
- The before-each-trip check (harness snug, coat off on cold days) and the recall check from the issue scope.
- Check the car rules against the printed Tesla manual. Tesla's site refused automated downloads.
