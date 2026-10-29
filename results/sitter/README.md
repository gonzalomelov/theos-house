# Sitter handover, real brain

`scripts/sitter_brief_run.py`: the parent says "My mom is watching him tonight from 19:00 to 23:00" and the brain must call `sitter_handover` once, which drafts the brief from the log.

| Brain | Run | Tool | Drafts | Sent to Telegram |
|---|---|---|---|---|
| **Muse Spark Open** (`meta-models/muse-spark-open-1026`) | Oct 28 night (`run.json`) | sitter_handover ran | 1 | no, run without `--send` |
| Claude Haiku 5.5 | Oct 26, prior run in git history | sitter_handover ran | 1 | yes, once to Gonza |

Muse wrote the sitter's name as "mom". The brief now capitalises the name it is given, so it reads "Hi Mom" whatever the brain wrote (#61). 2 brain calls, $0.0065.
