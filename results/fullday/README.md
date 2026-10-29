# Simulated full day, 06:10 to 02:30

`python -m parenting_agent.fullday` replays the plan page day through the real agent, Baby Buddy and the clips.

| Brain | Run | Steps | File |
|---|---|---|---|
| **Muse Spark Open** | Oct 29 01:13, with the clips and SAM 3.1, after the lift check (#75) | **7 of 7** | `muse-sam-lift/day.md` |
| **Muse Spark Open** | Oct 29 01:00, with the clips and SAM 3.1, before #75 | 6 of 7, the doorbell failed | `muse-sam/day.md` |
| **Muse Spark Open** (`meta-models/muse-spark-open-1026`) | Oct 28 night, `--no-video` | 4 of the 5 steps that ran passed, 2 clip steps skipped | `day-muse-no-video.md` |
| Claude Haiku 5.5 | Oct 27, with the clips and SAM 3.1 | 7 of 7 | `day.md` |

The Oct 28 Muse run is without the clips: SAM 3.1 needs the Mac GPU and another agent held the GPU lock all night. The one failing step, the question about the last dirty diaper, expects the time of the diaper the changing table step logs, and `--no-video` skips that step. Muse did answer from Baby Buddy with the last dirty diaper in the log.

On the first two Muse runs the doorbell step failed. Muse logged the morning bottle again and did not call reply_to_visitor. Both are fixed in #71, and the third run passed it.

On Oct 29 both runs had the whole day with the clips, SAM 3.1 confirm on and Muse as the brain. The changing table spoke "hand" 3 of 3 and kept the one-hand clip silent, the bath chimed in 0.24 and 0.28 s and spoke in 1.46 and 1.49 s, and the question about the last dirty diaper was answered from Baby Buddy. At 01:00 the doorbell step failed again: Muse answered with the words to say at the door ("One moment please, I'm in the middle of a diaper change with both hands on the baby.") but called no tool, so nothing was announced and it did not offer to reply to the visitor. At 01:13 it announced "one moment please" and asked before replying. Counting only runs after the #71 fix, the doorbell passed 2 of 3 (Oct 28 third run, Oct 29 01:13) and failed once (Oct 29 01:00). It is a brain flake, not fixed here.

Oct 29, both runs: 23 brain calls, p50 1.46 s, p90 2.01 s, $0.090, no fallback (`results/muse/calls-fullday-sam.jsonl`, `calls-fullday-sam-lift.jsonl`).

Muse on the Oct 28 last run: 10 brain calls, p50 1.17 s, p90 1.48 s, $0.038, no fallback (`results/muse/calls-fullday-novideo.jsonl`).
