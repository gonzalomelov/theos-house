"""Train and test the local cry reason head on Donate-a-Cry, in three steps that never mix (issue #161).

    python scripts/cry_reason_train.py features   # every clip through the camera channel and PANNs, embeddings cached
    python scripts/cry_reason_train.py tune       # train split only: grouped cross validation, fit, write the head
    python scripts/cry_reason_train.py test       # once: the held-out test, the decision rule, results/cry-reason/eval.json

The split and the protocol were committed before this script existed (results/cry-reason/split.json). Embeddings are
numbers, not audio, and are cached in .models/cry-reason (git ignored). Audio is decoded on a pipe into memory.
Runs PANNs in the hearing worker (the SAM 3.1 venv's torch, CPU).
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from parenting_agent import hearing  # noqa: E402
from parenting_agent.cry_sound import CLASSES, HEAD, Head  # noqa: E402

CORPUS = Path.home() / "Engineering/gonza/parenting-agent/.models/donateacry/src/donateacry_corpus_cleaned_and_updated_data"
CACHE = Path.home() / "Engineering/gonza/parenting-agent/.models/cry-reason/embeddings.npz"
SPLIT = REPO / "results/cry-reason/split.json"
TUNE = REPO / "results/cry-reason/tune.json"
EVAL = REPO / "results/cry-reason/eval.json"
GRID = [{"l2": l2, "balanced": bal} for l2 in (0.01, 0.1, 1.0, 10.0) for bal in (True, False)]
FOLDS = 5


def split():
    return json.loads(SPLIT.read_text())


def features():
    clips = split()["clips"]
    listener = hearing.PannsListener({})
    rows = []
    try:
        for i, clip in enumerate(clips):
            samples = hearing.from_file(CORPUS / clip["file"], camera_channel=True)
            rows.append(listener.embed(samples))
            if i % 50 == 0:
                print(f"{i}/{len(clips)}", flush=True)
    finally:
        listener.close()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, x=np.stack(rows), files=np.array([c["file"] for c in clips]))
    print(f"wrote {len(rows)} embeddings")


def load(which):
    data = np.load(CACHE)
    index = {f: i for i, f in enumerate(data["files"])}
    clips = [c for c in split()["clips"] if c["split"] == which]
    x = data["x"][[index[c["file"]] for c in clips]]
    y = np.array([CLASSES.index(c["label"]) for c in clips])
    return x, y, [c["device"] for c in clips]


def recalls(y, pred):
    return {c: (float(np.mean(pred[y == k] == k)) if np.any(y == k) else None) for k, c in enumerate(CLASSES)}


def balanced(y, pred):
    values = [v for v in recalls(y, pred).values() if v is not None]
    return float(np.mean(values))


def folds(devices):
    unique = sorted(set(devices), key=lambda d: hashlib.sha256(("fold" + d).encode()).hexdigest())
    fold_of = {d: i % FOLDS for i, d in enumerate(unique)}
    return np.array([fold_of[d] for d in devices])


def tune():
    x, y, devices = load("train")
    fold = folds(devices)
    rows = []
    for setting in GRID:
        pred = np.zeros_like(y)
        for f in range(FOLDS):
            head = Head.fit(x[fold != f], y[fold != f], **setting)
            pred[fold == f] = head.probs(x[fold == f]).argmax(axis=1)
        rows.append({**setting, "cv_balanced_accuracy": round(balanced(y, pred), 3),
                     "cv_accuracy": round(float(np.mean(pred == y)), 3),
                     "cv_recall": {c: (round(v, 3) if v is not None else None) for c, v in recalls(y, pred).items()}})
        print(json.dumps(rows[-1]), flush=True)
    best = max(rows, key=lambda r: (r["cv_balanced_accuracy"], -r["l2"]))
    head = Head.fit(x, y, l2=best["l2"], balanced=best["balanced"])
    meta = {"trained": datetime.date.today().isoformat(), "embedding": "PANNs Cnn14_16k mAP 0.438, mean over 2 s windows",
            "data": "Donate-a-Cry cleaned set (github.com/gveres/donateacry-corpus), ODbL 1.0, contents DbCL 1.0, "
                    "train split of results/cry-reason/split.json",
            "setting": {"l2": best["l2"], "balanced": best["balanced"]}, "speak": []}
    HEAD.parent.mkdir(exist_ok=True)
    HEAD.write_text(json.dumps(head.to_json(meta)) + "\n")
    TUNE.write_text(json.dumps({"train_clips": int(len(y)), "train_devices": len(set(devices)), "folds": FOLDS,
                                "grid": rows, "chosen": best}, indent=1) + "\n")
    print("chosen", json.dumps(best))


def auc(score, positive):
    pos, neg = score[positive], score[~positive]
    if not pos.size or not neg.size:
        return None
    greater = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(greater / (pos.size * neg.size))


def test():
    x, y, devices = load("test")
    head = Head.load()
    p = head.probs(x)
    pred = p.argmax(axis=1)
    rng = np.random.default_rng(161)
    unique = sorted(set(devices))
    by_device = {d: np.array([i for i, dv in enumerate(devices) if dv == d]) for d in unique}
    boot = []
    for _ in range(2000):
        idx = np.concatenate([by_device[unique[i]] for i in rng.integers(0, len(unique), len(unique))])
        boot.append(balanced(y[idx], pred[idx]))
    low, high = (float(v) for v in np.percentile(boot, [2.5, 97.5]))
    per_class = {}
    for k, c in enumerate(CLASSES):
        predicted = int(np.sum(pred == k))
        per_class[c] = {"clips": int(np.sum(y == k)), "recall": round(float(np.mean(pred[y == k] == k)), 3) if np.any(y == k) else None,
                        "predicted": predicted,
                        "precision": round(float(np.mean(y[pred == k] == k)), 3) if predicted else None}
    bal = balanced(y, pred)
    gate = low > 0.20
    speak = [c for c, r in per_class.items() if gate and r["predicted"] >= 3 and (r["precision"] or 0) >= 0.5]
    confusion = [[int(np.sum((y == a) & (pred == b))) for b in range(len(CLASSES))] for a in range(len(CLASSES))]
    result = {
        "run": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "test_clips": int(len(y)), "test_devices": len(unique),
        "balanced_accuracy": round(bal, 3), "balanced_accuracy_95": [round(low, 3), round(high, 3)],
        "chance_and_always_hungry_balanced_accuracy": 0.2,
        "accuracy": round(float(np.mean(pred == y)), 3),
        "always_hungry_accuracy": round(float(np.mean(y == 0)), 3),
        "hungry_vs_not_auc": round(auc(p[:, 0], y == 0), 3),
        "per_class": per_class, "confusion": {"rows_true_cols_predicted": list(CLASSES), "counts": confusion},
        "decision_rule": split()["protocol"]["decision_rule"],
        "gate_passed": gate, "speak": speak,
    }
    EVAL.write_text(json.dumps(result, indent=1) + "\n")
    data = json.loads(HEAD.read_text())
    data["meta"]["speak"] = speak
    data["meta"]["test"] = {k: result[k] for k in ("balanced_accuracy", "balanced_accuracy_95", "accuracy",
                                                   "always_hungry_accuracy", "gate_passed")}
    HEAD.write_text(json.dumps(data) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("decision_rule",)}, indent=1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["features", "tune", "test"])
    {"features": features, "tune": tune, "test": test}[parser.parse_args().step]()


if __name__ == "__main__":
    main()
