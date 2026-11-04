# Tonight's house on baby.bygmv.com (issue #132)

Live check on Oct 30 2026 at 00:14 Montevideo, after deploying ebbab9b (PRs #133 and #134). A headless browser at 375 x 812, marked internal first, so its rows count as internal. A fresh visitor, the simulated week as the demo builds it.

| File | What it shows |
|---|---|
| `live-375-0-card.png` | The page before any tap. Under the night summary, the "Tonight's house" card with its "SIMULATED HOUSE, NOTHING MOVES" badge and the "See Muse's plan for tonight" button. The panel says Parent B is next on duty |
| `live-375-1-tonight.png`, `live-1-tonight.txt` | Muse's plan, checked by plain code, 5.4 s. On duty: Parent B, from the night rota. Bottle warmer pre-heats at 01:33, 03:46 and 05:39, silent, water only. White noise on for every sleep with the 50 dB cap. Doorbell a silent push during every sleep. Floor clean may run 07:00 to 07:57. Muse's why in one sentence. A "Let me sleep tonight" button |
| `live-375-2-let-me-sleep.png`, `live-2-let-me-sleep.txt` | After "Let me sleep tonight", 4.9 s. A "What changed" box: on duty Parent B to Parent A, floor clean 07:00-07:57 to 07:42-08:40. Muse's why: it changed the parent on duty because Parent B asked to sleep at 00:14. The warmer times stayed the same |
| `live-375-3-panel.png` | The top of the page after the re-plan: "Next night on duty: Parent A", and the night summary says "Next on duty: Parent A, a parent asked." |

What was checked:
- Both plans came from Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten) through `HouseBrain.ask`. Two plan calls in this run.
- The page is 375 px wide with no sideways scroll (scrollWidth 375). The chat thread keeps 150 px and the page scrolls to the input.
- The session rows on the Vostro for both live visitors have internal 1: this run wrote two rows, one per plan call, and the first visitor on 569c930 wrote three (two plan calls and one chat message).
- "What will the house do tonight?" in the chat answered with the cached plan, tagged "Muse Spark Open, house plan", with no new call (checked on the first deploy, 569c930).
- Deploy: `sh deploy/public.sh demo deploy` from a clean worktree, both times "env ok", "wall holds".

Not checked live: the fixed-rules fallback (Muse did not fail tonight, the tests cover it), the Spanish card (the tests cover it), a real phone.

Earlier on the same night, on the first deploy (569c930), the panel still said Parent B after the re-plan and the chat answered with the first plan. PR #134 fixed both, and this run is after that fix. The first screenshots were lost when their worktree was removed, so these are from a second fresh visitor.

Nothing moves: the demo's house brain has no day engine, night feed or device to arm, and the demo image has no device module (`tests/test_demo_house.py`).
