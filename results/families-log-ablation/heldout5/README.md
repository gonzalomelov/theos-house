# heldout5 blind test set (families log ablation)

Stats only. The messages stay unseen by the agent being scored.

- Steps: 45
- Days: 29, 30, 31 (Oct 29 to 31 2026, Montevideo time), times strictly increasing
- English messages: 8
- Expected ops: 21 adds of feeds, diapers, sleeps and baths (10 feeding, 5 diaper, 4 sleep, 2 bath), 2 notes, 8 edits, 1 delete, 13 null
- Tags: 3 "asleep", 3 "next", 2 "q"
- Double sends: 2 (one answered as two entries, one as a single entry)
- Closest similarity to any earlier message: 0.7467 (difflib.SequenceMatcher ratio on lowercased, accent-stripped (NFKD), whitespace-collapsed text, against every message in families-never-wrong heldout/heldout-steps.json, heldout2/steps-oct.json, heldout3/steps.json, heldout4/steps.json and STEPS plus JUDGE_STEPS in scripts/families_never_wrong_run.py; 352 earlier messages)
- Every edit and delete targets an entry the expected log holds at that day and time (checked by script)

sha256 (shasum -a 256 steps.json):

```
8115cf416dd2d898c806d31ad00e28df53e11cd8901e4b528e9634f5fc6d4c52  steps.json
```
