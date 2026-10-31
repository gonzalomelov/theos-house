"""Writes the tune and held-out sets for the Meta hearing swap (results/sounds/meta-hearing/split.json), before any tuning.

    python scripts/meta_hearing_split.py

Local clips only, file names and labels only, no audio enters git:
- the 48-clip hearing set (meta-hackathon-2026 muse/data/hearing_sources.json, licenses there, audio in
  meta-hackathon-2026-synthetic, which also holds the 31 audio2 clips): its dev split is tune, its test split is held out
- Donate-a-Cry cleaned set (ODbL 1.0, contents DbCL 1.0, 457 cries): grouped by app install, installs ranked by
  sha256(seed + id), the first installs go to tune until it holds at least TUNE_CRIES clips, the rest are held out

Each item is a file, a start and a length in seconds. A clip of 10 s or less is one item. A longer clip with a label
(cry, dog, doorbell, splash) is its first 10 s only, so the label stays true. A longer clip without a label (kitchen,
radio, read speech, a song) is up to 6 items of 10 s spread evenly over it, so false alarms are counted on more room
sound. This file is read by scripts/meta_hearing_eval.py and never changed after it is committed.
"""
import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MEDIA = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic"
SOURCES = Path.home() / "Engineering/gonza/meta-hackathon-2026/muse/data/hearing_sources.json"
CORPUS = Path.home() / "Engineering/gonza/parenting-agent/.models/donateacry/src/donateacry_corpus_cleaned_and_updated_data"
OUT = REPO / "results/sounds/meta-hearing/split.json"
SEED = "meta-hearing-2026-10-31"
TUNE_CRIES = 110
ITEM_S = 10.0
NEGATIVE_ITEMS = 6
LABELS = ("cry", "doorbell", "dog", "splash")
PROMPTS = {
    "cry": ["a baby crying", "an infant crying", "a newborn baby wailing", "a crying baby"],
    "doorbell": ["a doorbell ringing", "a ding dong doorbell chime", "an electronic door chime", "a door buzzer"],
    "dog": ["a dog barking", "a dog bark", "a dog growling and barking"],
    "splash": ["water splashing", "water running from a tap", "water pouring into a bath", "water splashing in a sink"],
}
BACKGROUND = ["people talking", "a quiet room", "kitchen noise", "music playing", "a person coughing",
              "a radio broadcast", "household background noise"]

PROTOCOL = {
    "written": "2026-10-31, before any score was computed on any clip by any listener",
    "audio": "every item is decoded by ffmpeg on a pipe and goes through the Tapo camera channel (8 kHz G.711 A-law and "
             "back, parenting_agent.hearing.from_file camera_channel=True), then scored the way the Ear scores: 2 s "
             "windows every 1 s, and an item fires a label when any window reaches that label's threshold",
    "labels": list(LABELS),
    "truth": "an item's label from its source. hearing-set labels cough, speech and negative are no label at all, so any "
             "label they fire is a false alarm. Every Donate-a-Cry item is a cry",
    "metrics": "per label: hits (items of that label that fire it), misses, false alarms (items of any other truth that "
               "fire it). Cry first, it drives the night feed awake signal",
    "listeners": {
        "before": "PANNs CNN14 as it runs today: hearing.GROUPS and hearing.THRESHOLDS unchanged, not tuned again",
        "meta": "facebook/pe-a-frame-small (Perception Encoder Audio Frame, Apache 2.0), zero shot: per label the "
                "frame logits against the prompts below. Tune chooses on the tune set only, per label: the score "
                "(sigmoid of the best prompt, or the best prompt's logit minus the best background prompt's logit) "
                "and the threshold",
        "signal": "plain signal processing for cry only, no learned model: loudness, voiced share and pitch in the infant "
                  "cry band (250 to 600 Hz), harmonic strength, longest voiced run. Thresholds on a fixed grid, chosen "
                  "on the tune set only",
    },
    "prompts": PROMPTS,
    "background_prompts": BACKGROUND,
    "tuning_rule": "per label, maximize hits minus 3 x false alarms on the tune set. Ties go to the higher threshold. "
                   "The held-out set is scored once, after every choice is written to tune.json",
    "winner_rule": "the runtime listener for a label is the Meta model when its held-out cry hits are at least those of "
                   "the signal listener with no more false alarms. Otherwise the signal listener hears cries and the "
                   "Meta model the other labels, or the signal listener alone if the Meta model fails everywhere",
}


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def items_for(root, file, label, split, length, source, license_):
    truth = label if label in LABELS else "none"
    base = {"root": root, "file": file, "truth": truth, "source_label": label, "split": split, "source": source,
            "license": license_}
    if length <= ITEM_S:
        return [{**base, "start": 0.0, "seconds": round(length, 3)}]
    if truth != "none":
        return [{**base, "start": 0.0, "seconds": ITEM_S}]
    count = min(NEGATIVE_ITEMS, int(length // ITEM_S))
    span = length - ITEM_S
    return [{**base, "start": round(span * i / max(count - 1, 1), 2), "seconds": ITEM_S} for i in range(count)]


def main():
    items = []
    for s in json.loads(SOURCES.read_text()):
        split = {"dev": "tune", "test": "held_out"}[s["split"]]
        items += items_for("hearing", s["file"], s["label"], split, duration(MEDIA / s["file"]), s["id"], s["license"])
    files = sorted(p.relative_to(CORPUS).as_posix() for p in CORPUS.glob("*/*.wav"))
    devices = sorted({Path(f).name[:36] for f in files}, key=lambda d: hashlib.sha256((SEED + d).encode()).hexdigest())
    tune_devices, count = set(), 0
    for device in devices:
        if count >= TUNE_CRIES:
            break
        tune_devices.add(device)
        count += sum(Path(f).name[:36] == device for f in files)
    for f in files:
        split = "tune" if Path(f).name[:36] in tune_devices else "held_out"
        items += items_for("donateacry", f, "cry", split, duration(CORPUS / f), "donateacry:" + Path(f).name[:36],
                           "ODbL 1.0 / DbCL 1.0")
    for i, item in enumerate(items):
        item["id"] = i
    summary = {}
    for item in items:
        key = f"{item['split']} {item['truth']}"
        summary[key] = summary.get(key, 0) + 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"protocol": PROTOCOL, "seed": SEED, "roots": {
        "hearing": "~/Engineering/gonza/meta-hackathon-2026-synthetic",
        "donateacry": "~/Engineering/gonza/parenting-agent/.models/donateacry/src/donateacry_corpus_cleaned_and_updated_data"},
        "counts": dict(sorted(summary.items())), "items": items}, indent=1) + "\n")
    print(json.dumps(dict(sorted(summary.items())), indent=1))


if __name__ == "__main__":
    main()
