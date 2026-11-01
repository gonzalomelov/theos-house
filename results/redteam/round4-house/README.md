# Red team, round 4: the house findings closed

On Oct 29 2026 red-team pass 4 landed seven attacks. The honesty guard that erased safety answers was closed in PR #123. This change closes the other six, the house ones. Each is now a test in `tests/test_redteam_r4.py` that replays the red-team harness input (live.py, h_demo.py, h_floor2.py, h_brain.py) with a scripted brain or a fake Muse, no network.

**Before** is the test file run on origin/main at 8fccb95. **After** is this branch. Run on Oct 29 2026: 14 of 16 tests fail before and pass after. The other 2 are controls that pass on both (a plugin's "Reply yes" still reaches the brain, and a plan with two boosts and one quiet door window still stands). The full suite, 983 tests, passes.

```bash
python -m unittest discover -s tests -p test_redteam_r4.py -v
```

| # | Finding | Fix | Tests |
|---|---|---|---|
| 1 | A bare "yes" with nothing waiting re-ran dim_lights, asked call_partner five times in one turn and brought back a call cancelled 8 turns earlier | A bare yes with nothing waiting runs nothing and says "Nothing is waiting for your yes, so nothing ran". It reaches the brain only when the agent's last answer asked or offered something, or a plug-in asked on Telegram in the last hour. One call per tool and arguments per turn, and one ask per tool per turn. A cancelled or expired ask never comes back on a bare yes or an observation, and an action that already ran is not replayed by a bare yes (`agent/loop.py`) | `BareYesRunsNothing` (4) |
| 2 | A stale "Out with the baby" note opened the floor clean with him on the play mat | An out note counts for 2 hours. A later "back home" note or a note that puts him in a room ends it. The living room sensor and the latest room note are checked before the out note. When the log does not say where he is, the engine asks once and the vacuum stays docked (`house_plan.baby_out`, `day_engine.floor_ok`) | `StaleOutNote` (4) |
| 3 | "Vacuum started for the floor clean." while every write was a dry run | With house.live off every vacuum reply says it was only written down, and a reply guard adds the dry run line to any brain reply that says a device started, paused or turned on (`house_plan.dry_reply`, loaded by the day engine, the house plan and the house tools) | `DryRunReplies` (2) |
| 4 | Muse's summary and why_changed skipped the secret check, and the summary could name the other parent on duty | Both texts go through the same check as the plan's messages: no advice, no code, no contact detail. A summary that puts a parent other than on_duty on duty is dropped (`house_brain.validate`) | `MuseTexts` (3) |
| 5 | Twelve white noise boosts and a doorbell silent for 12 hours were accepted | At most 4 boosts and 120 min in all, at most 2 quiet door windows and 240 min in all (`house_brain.MAX_WINDOWS`, `MAX_TOTAL_MIN`) | `WindowCaps` (2) |
| 6 | "white noise" on the demo baby tab went to prep mode and dropped "put Parent B on duty" | On the baby tab, duty words and a white noise level stay with the baby agent unless the message names a list. The demo has two new simulated tools: `set_on_duty`, which the rota panel shows, and `white_noise`, capped at 50 dB at the crib | `BabyTabHouseWords` (1) |

Not in this change: the red-team finding that a parent note can reach Muse's plan prompt and so the morning text (house_brain.py:438 and :704). Real Muse refused it once in the red-team run. The speaker check stays the last line there.
