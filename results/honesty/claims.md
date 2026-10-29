# Honesty pass: every claim the product makes, Oct 28 2026

Done on Oct 28 2026, during the Meta hackathon (Oct 26 12 PM ET to Nov 4 9 PM ET). The bar is the round 1 judges in `meta-hackathon-2026/judges/rounds/r1/`, mainly `safety-honesty-auditor.json`, plus every claim the other six doubted.

Scope: this repo's README.md, docs/*, results/*/README.md, what the agents say (`parenting_agent/agent/rules.py`, `families/texts.py`, `demo/page.html`), and the video draft in `meta-hackathon-2026-synthetic/video-v0/` (`storyboard.md`, `captions.srt`, not a git repo, edited in place). The plan page (`meta-hackathon-2026/docs/planning/plan-page.html`) is the orchestrator's, so its claims are listed with the fix and not edited here.

Verdicts: **true** as written, **fixed** (true once rewritten, rewritten in this PR unless the fix says otherwise), **false** (removed or replaced), **pending** (depends on work in flight tonight, not written as true).

## Dates

The event started Oct 26 2026 at 12 PM ET. This repo's first commit is Oct 26 15:03 Montevideo time (14:03 ET), after the start. Prior work is the prep repo `gonzalomelov/meta-hackathon-2026`: 64 commits from Oct 21 to Oct 25 (`git log --until=2026-10-26`). The judges brief (`judges/README.md:15`) and `results/hover/ablation.json` still say Oct 27, which is wrong.

| Prior work, Oct 21 to 25 | Commit, date | Where it shows up now |
|---|---|---|
| Hand reflex, contact rule, chime then voice after 1.2 s | 32a60bd, 767b8a4, Oct 23 | Ported into `reflex.py` and `alarm.py` in f41acfa, 5 min after this repo was created |
| SAM 3.1 local, then on the Mac GPU | f8a8977 Oct 23, 20dafd4 Oct 24 | `scripts/sam3-setup.sh`, `sam3_worker.py` |
| 21 of 21 hovers read off, one clip | 20dafd4, Oct 24 | Not evidence any more. Replaced by `results/hover/README.md` (Oct 28) |
| iPhone page as head camera over Tailscale | aab2083, a6db9c9, Oct 23 | `sources.py`, `phone.html` |
| PANNs under speech, 18 of 24 at 0 dB, thresholds | 7faf636, Oct 23 | `hearing.py` thresholds, `docs/house-sounds.md` |
| Home Assistant MCP check, actions from live events | 2e8ce66 Oct 21, bf07cc4 Oct 23 | House layer design |
| Generated changing-table clips (Oct 22), bath clip and hover clip (Oct 23) | file dates in `meta-hackathon-2026-synthetic` | Test clips for `results/kr222/table.json`, the bath set and video shots s02, s06, s07, s11 |

## Product and privacy

| # | Claim | Where | Verdict | Evidence | Fix |
|---|---|---|---|---|---|
| 1 | "Everything stays in your house." | README.md:3, storyboard s03, captions 9, plan-page.html:95 | false | README Private by design table: the brain call sends conversation text and tool results (baby log lines) to Baseten, or Anthropic on a fallback. Telegram carries messages. Families' logs live on Gonza's server | "Video and audio stay in your house. Only the conversation text goes to the brain." Done in README, storyboard, captions. Plan page: orchestrator |
| 2 | "stays with you all day through your phone, glasses and home speakers" | README.md:3, storyboard s03, captions 5 and 6 | pending (glasses) | Glasses app merged in PR #65 (b571201): the full loop ran in the iOS 27 simulator with DAT's mock Ray-Ban Meta, real glasses not paired (`results/glasses/README.md`). The kitchen Echo announce passed once live (`results/channels/check.json`, Oct 28) | README says the glasses ran only in the simulator. Video: label glasses "simulator, real pairing next" until a run on real glasses exists |
| 2b | Glasses app "sends what the parent says" | README.md glasses section | fixed | `apps/glasses/ParentingGlasses/ContentView.swift`: phrase buttons and a text field, no speech recognition in the app | "sends the parent's phrases (a button or typed text, there is no speech recognition in the app yet)" |
| 3 | "acts in your home" | README.md:3, storyboard s03 | fixed | `house.live` false in every config. Real actions so far: one Echo announce (`results/channels/check.json`), one test list item added and removed (`results/house-plan/live-check.json`). Everything else dry | README status line names the real actions. Video labels the rest simulated (s10, s14) |
| 4 | "Only the brain call" leaves the house | README.md Private by design, docs/architecture.md data flows ("the only flow that does") | false | Same page lists Telegram through Telegram's servers, and the car from Nov 5 | Both rewritten: the brain call, Telegram, and the car from Nov 5 leave. No frame and no audio leaves |
| 5 | Families /privacy: text goes to "Anthropic's API (Claude)" | families/texts.py PRIVACY (EN, ES), docs/families.md:11 and :21 | false since PR #61 | pa-families on the Vostro runs bb919cd, which includes #61, so Muse on Baseten answers (`results/families/three-day-muse.md`, 0 fallbacks) | Rewritten: Muse Spark Open on Baseten first, Claude only when that call fails. Test `test_log_edit.Privacy` checks both names and links. Live after the families redeploy |
| 6 | Baseten keeps nothing | families note (new), README Private by design | fixed with source | https://docs.baseten.co/observability/security: "Baseten does not store model inputs, outputs, or weights by default", synchronous inference only. Our calls are synchronous | Worded as "Baseten's docs say it does not store them by default", with the link. No training claim is made for Baseten, its docs give none |
| 7 | Anthropic "keeps it for a limited time" | families note | fixed | https://privacy.claude.com/en/articles/7996866: API inputs and outputs deleted within 30 days by default, longer for flagged content or a law | "By default Anthropic does not train on API data and deletes it within 30 days", with that link |
| 8 | Demo page: messages "stay in memory only, never on disk, for at most 6 hours" | demo/page.html:66 | fixed | True for the demo server (`docs/demo-app.md`). Not true at the brain host on a Claude fallback (30 days) | Names the brain and says "on this server". Live after the demo redeploy |
| 9 | "Frames never leave the house" | README Meta models and Private by design, docs/sam3-local.md:3, docs/architecture.md | true, with one precision | `confirm.py`, `sam3_masks.py`: frames go over a local pipe. The iPhone page streams to the Mac over Wi-Fi or Tailscale | Architecture now says a Tailscale relay would see only encrypted packets |
| 10 | "never on disk" for audio and frames | README, docs/house-sounds.md | true | `tests/test_sounds.py` checks the Ear opens no file for writing. `results/sounds/run.json` `audio_written: false` | none |
| 11 | "213 of 213 probes against the wall were blocked" under "your baby's video never leaves your home" | storyboard s16, captions 48 | fixed | 103 demo probes (`docs/demo-app.md:98`) plus 110 families probes (`docs/families.md:185`), Oct 28. They test the public containers, not the camera path | "The demo and the families bot are walled off, 213 of 213 probes blocked." |

## Meta models

| # | Claim | Where | Verdict | Evidence | Fix |
|---|---|---|---|---|---|
| 12 | "Muse Spark Open is ready as the brain, and Claude stands in today" | storyboard s04, captions 11 and 12, storyboard line 8 | false since PR #61 (stale, now understated) | `config/agent.json`, `demo/settings.py` DEFAULT_BRAIN baseten. Live Vostro containers run 115dc2e, bb919cd, ed6c488. `results/muse/vostro-family-agent-turn.jsonl`: brain_call to inference.baseten.co, fallback false | "Muse Spark Open, Meta's open model, is the brain, with Claude only as a logged fallback." |
| 13 | "Planned, not built yet: Muse Spark Open live on Baseten (#4)" | README.md built section | false (stale) | PR #61 merged | Moved to the built table, row #4 / #61 / 115dc2e |
| 14 | "Numbers in `results/muse/README.md`" | README.md Meta models | false | That file does not exist on origin/main | Points to the per-call logs in `results/muse/`. A README there is pending from the Muse work |
| 15 | "SAM 3.1 confirms whether a hand really touches, or only hovers" | storyboard s07, captions 19 and 20 | false | `results/hover/README.md` (Oct 28): 0 of 24 rendered 2 to 5 cm hovers caught by any configuration, SAM 3.1 read 0 of 12 table hovers as off | "We tested SAM 3.1 on it. A 2 to 5 cm hover still reads as a touch. Not solved yet." Pending: hover depth work tonight. Change only if what merges shows a measured win |
| 16 | "21 of 21 hovers right" | plan-page.html:261, meta-hackathon-2026 README.md:188 | false as event evidence | Oct 24 run in the prep repo, one clip, forearm far above the baby | Already relabelled in `docs/sam3-local.md` and `results/hover/README.md`. Plan page: remove, or label "prior work, Oct 24" |
| 17 | SAM 3.1 "1.5 to 3 s per frame" | README Meta models, docs/sam3-local.md | true | 1.5 s M3 Max (docs), 2.2 to 3.2 s in `results/hover/ablation.json` | none |
| 18 | "Two Meta models" | storyboard s04 | true | SAM 3.1 local, Muse Spark Open on Baseten, both called in runs tonight | none. `reasoning.py` no longer points at a hosted non-open model |

## Logging and voice

| # | Claim | Where | Verdict | Evidence | Fix |
|---|---|---|---|---|---|
| 19 | "A bottle, logged by voice" | storyboard s05, captions 13 | pending | No speech to text on origin/main at ed6c488. `results/kr222/voice-log.json` utterances are typed. Voice notes are in flight on `feat/voice-notes`, not merged | "A bottle, logged from one typed line." Becomes "by voice" only after voice notes merge and a real voice note is recorded |
| 20 | "Your voice notes 10 of 10 logged right" | plan-page.html:255 | false as worded | `results/kr222/voice-log.json`, Oct 28, Muse brain: typed notes | Plan page: "typed notes 10 of 10" until voice notes merge |
| 21 | "Bottle by voice", "dirty diaper said aloud" | README full day, docs/full-day.md:13 | fixed | `results/fullday/day.json` input "voice: bottle, 120 ml" is a typed message on the ear channel | Rewritten as typed. README also says the recorded day is Oct 27 with the Claude brain |
| 22 | "voice log" script name | README, `scripts/voice_log_run.py` | fixed | a usage goal calls the check "voice log" | README says the notes are typed text |
| 23 | "Notes arrive as text for now, the channels issue adds speech to text" | README Baby log | fixed | Telegram adapter is text only (`channels/telegram.py`) | "Voice notes on Telegram are being built and are not merged yet." |
| 24 | "every note logged once", "0 false logged" on 150 notes | docs/families.md:93 | true | Oct 28 run, `tests/test_no_false_logged.py` | none |
| 25 | families 3 day run "29, 28 and 27 of 29" | docs/families.md:108 | fixed | `results/families/three-day-after*.md`, Claude Haiku 5.5, Oct 28 | Now says it was Claude, before Muse, and points to the Muse run (29 of 29, `three-day-muse.md`) |

## Skills and numbers

| # | Claim | Where | Verdict | Evidence | Fix |
|---|---|---|---|---|---|
| 26 | "The camera watches your hands, not the baby" | storyboard s06, captions 15 and 16 | false | `docs/sam3-local.md`: SAM 3.1 finds the hands and the baby by text. The reflex needs a baby box | "It checks whether your hands are on the baby." |
| 27 | "it says hand in your ear" | storyboard s06, s08, captions 16 and 22 | fixed | The ear is the Mac speaker today (`channels/router.py`, README) | "out loud". The glasses or earpiece only once built |
| 28 | Changing table "15 of 15", max 1.68 s | storyboard s06 source, plan page | true | `results/kr222/table.json`, Oct 27, generated clips from Oct 22 (prior work) | Storyboard says the clips predate the event. Frame s06-02 shows two hands under "1 hand on" and must be replaced |
| 29 | Bath "a chime in under a third of a second, and hand before one second. 10 of 10" | storyboard s11, captions 32 and 33 | false as worded | `results/bath/bath.json` (Oct 28, Claude brain): max chime 0.606 s, max voice 1.886 s over 10 baths. 0.284 and 0.908 were one full-day run | "A chime within 0.61 seconds, and hand within 1.9 seconds. 10 of 10 bath runs." `docs/bath.md` now quotes the same and names the brain |
| 30 | "A local hand detector raises the alarm in under a second" | README How it works | true | bath.json chime within 1 s 10 of 10, max 0.606 s | none |
| 31 | "93 percent of new parents make at least one mistake with the car seat" | storyboard s02, captions 3, plan-page.html:364, frame shots.py:25 | false as worded | Traced to a 2014 AAP conference abstract, 267 families at OHSU (https://www.golocalpdx.com/health/ohsu-study-finds-widespread-misuse-of-carseats-among-oregon-families), mostly harness errors (69 percent loose harness). Not "new parents" in general | Replaced by the peer reviewed paper: Hoffman, Gallardo, Carlson, "Unsafe from the Start", J Pediatr 2016, vol 171, pp 48-54, doi:10.1016/j.jpeds.2015.11.047 (https://ohsu.elsevierpure.com/en/publications/unsafe-from-the-start-serious-misuse-of-car-safety-seats-at-newbo): 291 newborns at one Oregon hospital, 95 percent misused, serious misuse 91 percent, positioning 86 percent, installation 77 percent. Caption: "In one Oregon hospital, 91 percent of newborns left with a serious car seat error." Citation on screen. The coach checks the install, not harness positioning |
| 32 | "Nothing on the market checks a belt install with a camera" | plan-page.html:364 | false (unsourced) | No search recorded | Plan page: cut |
| 33 | "11 of 12 wrong installs caught" | storyboard s13, captions 40, README, docs/car-seat-coach.md | fixed | `results/carseat/test.md`: 3D renders with planted mistakes | "11 of 12 planted mistakes caught, on rendered clips." The docs already said rendered |
| 34 | "It never says safe" | README car seat, storyboard s13, docs/car-seat-coach.md:5 | fixed (scoped) | `carseat/coach.py` FORBIDDEN blocks the word in the coach's own lines. `results/carseat/test.md`: no spoken text with "safe". Brain replies about car seats are not filtered | README now says it is a filter on the coach's own lines. Open: filter the brain's car seat replies too |
| 35 | Car rules "from the Tesla Model 3 manual" | README car seat | fixed | `skills/carseat/tesla-model-3.json` note: Tesla's site refused downloads, rules come from its published child seat pages | README says so, and that the printed manual check is open |
| 36 | "Cry reason 9 of 10", "Probably hungry, last feed almost three hours ago" | storyboard s09, captions 25, docs/house-sounds.md | fixed | `results/sounds/cry-eval.json`: 9 of 10 and 166 of 184 on the simulated week, built from the same rhythm assumptions as the reasoner. `results/sounds/run.json`: 2 h 51 min | Caption adds "Tested on a simulated week". House sounds doc says it checks the logic, not real cries. Pronoun fixed to "he" to match the quoted line. The public demo refuses this question, so do not invite viewers to try it there |
| 37 | PANNs "18 of 24 events heard under speech" | docs/house-sounds.md:49 | fixed | meta-hackathon-2026 `results/muse_hearing.json`, Oct 23 | Labelled prior work, not re-measured |
| 38 | White noise "under the 50 dB cap" | README house plan, docs/house-plan.md:16 | fixed | `docs/house-sounds.md:41`: placeholder calibration, 70 dB at full level, never measured | README: the cap is in code, the calibration is a placeholder, no dB number is measured |
| 39 | "The lights dim" at 02:30 | storyboard s14, captions 41 | fixed | `house.live` false, demo house is simulated | "The lights dim, simulated" |
| 40 | Touch versus hover not solved | README, docs/sam3-local.md, docs/bath.md, docs/architecture.md | true | `results/hover/README.md` | Date in `results/hover/README.md` fixed to Oct 26 12 PM ET. `ablation.json` still says Oct 27, left for the hover depth work that rewrites it |

## Safety and what the agents say

| # | Claim | Where | Verdict | Evidence | Fix |
|---|---|---|---|---|---|
| 41 | "It never gives medical advice" | README.md:7, storyboard s18, captions 53, families WELCOME, demo footer | fixed (scoped) | `results/honesty/gate_check.json`, run tonight: red flags take the emergency fast path 8 of 8 in English and 6 of 6 in Spanish. Of 10 other risky questions the gate catches 3. Yellow skin, tummy sleep, water, car seat sleep, pillow in the crib, 4 days without stool and rice cereal go to the brain, so "never" rests on the prompt there | README says how it is enforced and where the prompt is the last line. Open: add those 7 to the gate. The short "never medical advice" in the agent's own replies stays, it is the agent's rule, not a measured claim |
| 42 | REFUSAL and NO_ADVICE name emergency services | rules.py | true | rules.py:116 to 124, 911 for Uruguay | none |
| 43 | Families: red flags answered "at once, without a brain call" | docs/families.md:58 | true | gate_check.json, `tests/test_log_edit.py` | none |
| 44 | Families: "remind you of the next feed and send a short summary each evening" | families WELCOME | true | `docs/families.md:71`, service reminder clock | none |
| 45 | Demo: "Calling the partner shows Waits for your yes" and "a stale ok runs nothing" | docs/demo-app.md:12 | true | `tests/test_redteam_r1.py` StaleApproval, 29 of 29 after (`results/redteam/README.md`) | none |
| 46 | "Anything outside the allowed list waits for a parent's yes" | README How it works | true since PR #63 | The red teamer's stale yes is closed, `results/redteam/README.md` | none |
| 47 | "It speaks first" | README Daily rhythm | true with a note | Rhythm reminders are computed from the log outside the brain loop (`results/redteam/README.md`, still open). The family agent sends them, the demo panel is computed on page load | none, the README does not claim the brain decides |
| 48 | "Sitter: nothing is sent until you approve it" | storyboard s12, docs/sitter-handover.md | true | `results/sitter/run.json` (Muse brain, `sent: false`), `send_handover_to_sitter` never on the allowed list | none |

## Stale or missing

| # | Claim | Where | Verdict | Evidence | Fix |
|---|---|---|---|---|---|
| 49 | "Everything in this repo was written during the event" | README built section | fixed | Code written here from Oct 26, but reflex, alarm, SAM 3.1 setup, phone page and PANNs thresholds were designed Oct 21 to 25 | New "Prior work (Oct 21 to 25 2026)" section in the README |
| 50 | Event dates "Oct 26 to Nov 4" or "Oct 27 to Nov 4" | README, results/hover/README.md, storyboard line 53 | fixed | Event start Oct 26 12 PM ET | All say Oct 26 12 PM ET to Nov 4 9 PM ET. `judges/README.md:15` and `ablation.json` still say Oct 27 |
| 51 | Demo "Local only until Gonza says OK public" | README public demo, built table | false (stale) | `docs/demo-app.md:3`, live since Oct 28 | Rewritten as live at baby.bygmv.com |
| 52 | "Every number here came from a real run during the hackathon" | storyboard s17, captions 49 | pending | True for every number in the rewritten captions. The scoreboard frame comes from the plan page, which still has 21 of 21 hovers and "voice notes" | Caption keeps the line, minus "real". True once the plan page fixes 16 and 20 |
| 53 | "Built during the hackathon" on every frame | storyboard line 7 | fixed | s02, s06 and s07 use clips generated Oct 22 and 23 | Storyboard asks for "clip made before the event" on those shots |
| 54 | Live tests run "with Claude" | README Tests | fixed | The live brain is the configured one, Muse by default | "with the configured live brain" |
| 55 | Code comments calling Claude the stand-in | `agent/brain.py:5`, `demo/app.py:4` | fixed | PR #61 | Comments now say logged fallback |

## What changed outside this repo

`~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v0/` is not a git repo. Edited in place on Oct 28:

- `captions.srt`: 19 cue texts rewritten (cues 3, 9, 11, 12, 13, 15, 16, 19, 20, 22, 24, 26, 32, 33, 40, 41, 47, 48, 49), timings unchanged. The narration audio still says the old lines.
- `storyboard.md`: header notes on prior-work clips, the Muse switch and the honesty pass, captions and sources for s02 to s09, s11, s13, s14, s16, s17, and the final checklist line.
- Not changed: `shots.py`, the rendered frames, the narration and `video-v0.mp4`. They need `python3 build.py` before any cut is shown.
