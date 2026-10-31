"""Writes the held-out split and the evaluation protocol for the local cry reason model, before any training (issue #161).

The Donate-a-Cry corpus (ODbL 1.0, contents DbCL 1.0, github.com/gveres/donateacry-corpus) is split by the app
install that uploaded each clip, so no baby's phone is in both train and test. Run once, commit the output, then
train. Re-running gives the same file.

    python scripts/cry_reason_split.py [--corpus .models/donateacry/src/donateacry_corpus_cleaned_and_updated_data]
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path.home() / "Engineering/gonza/parenting-agent/.models/donateacry/src/donateacry_corpus_cleaned_and_updated_data"
CLASSES = ("hungry", "tired", "discomfort", "burping", "belly_pain")
SEED = "cry-reason-161"
OUT = REPO / "results/cry-reason/split.json"

PROTOCOL = {
    "written": "2026-10-30, before any feature was extracted or any model was trained",
    "corpus": "Donate-a-Cry cleaned set, github.com/gveres/donateacry-corpus commit 6baf5ac, ODbL 1.0 / DbCL 1.0",
    "classes": list(CLASSES),
    "split": "grouped by app install id (first 36 characters of the file name). Rarest class first, devices are ranked "
             "by sha256(seed + id) and go to test until at least a quarter of that class's clips are in test, skipping a "
             "device that would put more than half of the class in test. A device keeps the side it got first. Test "
             "is never read while choosing features or settings.",
    "tuning": "only on train, with cross validation grouped by device",
    "audio": "every clip goes through the Tapo camera channel (8 kHz G.711 A-law and back) before features, as at home",
    "primary_metric": "balanced accuracy on test (mean of per-class recall over the 5 classes). Chance and the "
                      "always-hungry baseline are both 0.20",
    "secondary_metrics": ["plain accuracy next to the always-hungry baseline", "per-class recall and precision with counts",
                          "hungry vs not hungry ROC AUC", "95% interval by bootstrap over test devices, 2000 resamples"],
    "decision_rule": "The sound guess enters what the parent is told only if the lower end of the 95% interval of test "
                     "balanced accuracy is above 0.20, and then only for the classes whose test precision is at least "
                     "0.5 with at least 3 test clips predicted. Otherwise the model still runs on every cry and its "
                     "guess is logged as an event, and the parent hears the log-based reason alone.",
}


def device(name):
    return name[:36].lower()


def ranked(ids):
    return sorted(ids, key=lambda d: hashlib.sha256((SEED + d).encode()).hexdigest())


def build(corpus):
    clips = []
    for cls in CLASSES:
        for path in sorted((corpus / cls).iterdir()):
            if path.suffix.lower() in (".wav", ".caf", ".3gp", ".m4a"):
                clips.append({"file": f"{cls}/{path.name}", "label": cls, "device": device(path.name)})
    by_device = defaultdict(set)
    for clip in clips:
        by_device[clip["device"]].add(clip["label"])
    per = defaultdict(lambda: defaultdict(int))
    for clip in clips:
        per[clip["label"]][clip["device"]] += 1
    test, train = set(), set()
    for cls in sorted(CLASSES, key=lambda c: sum(per[c].values())):
        total = sum(per[cls].values())
        held = sum(n for d, n in per[cls].items() if d in test)
        for d in ranked(list(per[cls])):
            if held >= total / 4:
                break
            if d in test or d in train:
                continue
            if held + per[cls][d] > total / 2:
                continue
            test.add(d)
            held += per[cls][d]
        train |= set(per[cls]) - test
    for clip in clips:
        clip["split"] = "test" if clip["device"] in test else "train"
    counts = {s: {c: sum(1 for x in clips if x["split"] == s and x["label"] == c) for c in CLASSES} for s in ("train", "test")}
    return {"protocol": PROTOCOL, "counts": counts, "devices": {"train": len(by_device) - len(test), "test": len(test)},
            "clips": clips}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(CORPUS))
    args = parser.parse_args()
    split = build(Path(args.corpus).expanduser())
    OUT.write_text(json.dumps(split, indent=1) + "\n")
    print(json.dumps({"counts": split["counts"], "devices": split["devices"]}))


if __name__ == "__main__":
    main()
