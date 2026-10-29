# Simulated full day, 06:10 to 02:30

`python -m parenting_agent.fullday` replays the plan page day through the real agent, Baby Buddy and the clips.

| Brain | Run | Steps | File |
|---|---|---|---|
| **Muse Spark Open** (`meta-models/muse-spark-open-1026`) | Oct 28 night, `--no-video` | 4 of the 5 steps that ran passed, 2 clip steps skipped | `day-muse-no-video.md` |
| Claude Haiku 5.5 | Oct 27, with the clips and SAM 3.1 | 7 of 7 | `day.md` |

The Muse run is without the clips: SAM 3.1 needs the Mac GPU and another agent held the GPU lock all night. The one failing step, the question about the last dirty diaper, expects the time of the diaper the changing table step logs, and `--no-video` skips that step. Muse did answer from Baby Buddy with the last dirty diaper in the log.

On the first two Muse runs the doorbell step failed. Muse logged the morning bottle again and did not call reply_to_visitor. Both are fixed in #71, and the third run passed it.

Muse on the last run: 10 brain calls, p50 1.17 s, p90 1.48 s, $0.038, no fallback (`results/muse/calls-fullday-novideo.jsonl`).
