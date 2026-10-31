# Only Meta models at runtime: the brain falls back to the fixed rules (Oct 31 2026)

The hackathon rule is that every model the project calls at runtime is a Meta model. Claude Haiku was the logged fallback brain of the family agent, the demo and the families bot. It is gone from all three, from their configs, the deploy env files and the egress allowlists. When a Muse Spark Open call errors, the fixed rules that run the tests answer, and the reply starts by saying the brain is busy.

Run once on the Mac on Oct 31 around 13:15 Montevideo, through the real demo app (`parenting_agent/demo/app.py`) with "le di 90 ml de mamadera":

| Case | Brain calls | Reply | Tag on the page |
|---|---|---|---|
| Muse with the real Baseten key | 2 to `meta-models/muse-spark-open-1026` at inference.baseten.co | "Anotado: mamadera de 90 ml." | Muse Spark Open |
| Muse with a wrong key, so Baseten refuses the call | 2 `brain_fallback` events, each answered by "fixed rules" at "none (local)" | "Mi cerebro está ocupado ahora, así que te respondo con mis reglas fijas simples. Anoté la mamadera de 90 ml de las 13:13." | Fixed rules, Muse was busy, no AI |

The bottle was logged in both cases. No other host was called. Tests: `tests/test_muse_brain.py` (every config, the refusal of any non-Meta provider, the busy line in English and Spanish, no runtime file naming another vendor's API).

Claude stays only in `scripts/eval_brains.py`, outside the package, for the offline comparisons in `results/muse-vs-haiku/` and the families runs, loaded only with `--brain claude`.
