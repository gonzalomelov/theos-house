"""Muse Spark Open's ears against PANNs on the licensed hearing set (issue #14).

    python scripts/sounds_muse_eval.py            # writes results/sounds/muse/run.json
    python scripts/sounds_muse_eval.py --no-muse  # PANNs only, no Baseten spend

1. The audio canary: a synthetic beep clip (not house audio) sent in each audio format Baseten lists, to see whether
   Muse hears audio on this endpoint at all.
2. Each clip of the hearing set (meta-hackathon-2026 hearing_sources.json, licenses there) is decoded in memory
   through the camera's 8 kHz A-law channel, cut to its first clip_s seconds, and scored by PANNs (the local reflex)
   and by Muse Spark Open (one call, strict JSON: what sound, and for a cry a guessed reason with a confidence).
Nothing is written but the labels, scores and Muse's answers. The clips stay outside the repo.
"""
import argparse
import base64
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent import hearing  # noqa: E402
from parenting_agent.agent.brain import BrainError  # noqa: E402
from parenting_agent.agent.config import load_env  # noqa: E402
from parenting_agent.cry_reason import REASONS  # noqa: E402
from parenting_agent.muse_senses import MuseSenses, beeps  # noqa: E402

MEDIA = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic"
SOURCES = Path.home() / "Engineering/gonza/meta-hackathon-2026/muse/data/hearing_sources.json"
SOUNDS = ["baby_crying", "dog_barking", "doorbell", "coughing", "water_splashing", "speech", "other", "silence"]
TRUTH = {"cry": "baby_crying", "dog": "dog_barking", "doorbell": "doorbell", "cough": "coughing",
         "splash": "water_splashing", "negative": "other"}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["heard_sound", "sound", "reason_guess", "confidence"],
          "properties": {"heard_sound": {"type": "boolean"}, "sound": {"type": "string", "enum": SOUNDS},
                         "reason_guess": {"type": "string", "enum": [*REASONS, "not_a_cry", "cannot_tell"]},
                         "confidence": {"type": "number"}}}
SYSTEM = ("You listen to a few seconds of audio from a home camera. If no audio reaches you, set heard_sound false. "
          "You never give medical advice and never name pain or illness.")
TEXT = ("What is the main sound in the attached audio? If it is a baby crying, guess the most likely everyday reason "
        "from the sound alone (hungry, tired, diaper, comfort, or cannot_tell), else not_a_cry. Confidence 0 to 1.")
CANARY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["heard_sound", "beeps"],
                 "properties": {"heard_sound": {"type": "boolean"}, "beeps": {"type": "integer"}}}


def encode(wav, fmt):
    if fmt == "wav":
        return wav
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "wav", "-i", "pipe:0", "-f", fmt, "pipe:1"],
                          input=wav, capture_output=True, check=True).stdout


def canary(senses):
    rows = []
    wav = beeps(3)
    for fmt, mime in (("wav", "audio/wav"), ("mp3", "audio/mpeg"), ("flac", "audio/flac"), ("ogg", "audio/ogg")):
        url = f"data:{mime};base64," + base64.b64encode(encode(wav, fmt)).decode()
        try:
            got = senses.ask("You listen to the attached audio clip. If no audio reaches you, set heard_sound false.",
                             "How many beeps are in the attached audio clip?", CANARY_SCHEMA, audio_url=url)
            rows.append({"format": fmt, "answer": got["answer"], "audio_tokens": got["usage"]["audio_tokens"],
                         "input_tokens": got["usage"]["input_tokens"], "right": got["answer"].get("beeps") == 3
                         and got["answer"].get("heard_sound") is True})
        except BrainError as error:
            rows.append({"format": fmt, "error": str(error)[:200], "right": False})
        print("canary", rows[-1], flush=True)
    return rows


def panns_label(listener, samples):
    best = {}
    for start in range(0, max(samples.size - hearing.WINDOW, 0) + 1, hearing.STEP):
        window = samples[start:start + hearing.WINDOW]
        if window.size < hearing.WINDOW:
            window = hearing.np.pad(window, (0, hearing.WINDOW - window.size))
        for label, score in listener.score(window).get("scores", {}).items():
            best[label] = max(best.get(label, 0.0), score)
    fired = {k: v / t for k, v in best.items() for kk, t in hearing.THRESHOLDS.items() if k == kk and v >= t}
    return (max(fired, key=fired.get) if fired else "none"), {k: round(v, 4) for k, v in best.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip-s", type=float, default=5.0)
    ap.add_argument("--no-muse", action="store_true")
    args = ap.parse_args()
    load_env("~/.parenting-agent.env")
    sources = [s for s in json.loads(SOURCES.read_text()) if (MEDIA / s["file"]).is_file() and s["label"] in TRUTH]
    listener = hearing.PannsListener({"model_dir": str(Path.home() / "Engineering/gonza/parenting-agent/.models/panns")})
    senses = None if args.no_muse else MuseSenses({"max_tokens": 4000})
    canary_rows = canary(senses) if senses else []
    rows = []
    for source in sources:
        samples = hearing.from_file(MEDIA / source["file"], seconds=args.clip_s)
        panns, scores = panns_label(listener, samples)
        row = {"id": source["id"], "split": source["split"], "truth": TRUTH[source["label"]], "license": source["license"],
               "panns": {"cry": "baby_crying", "dog": "dog_barking", "doorbell": "doorbell", "splash": "water_splashing"}.get(panns, "other"),
               "panns_scores": scores}
        if senses:
            from parenting_agent.muse_senses import wav_bytes, wav_data_url
            try:
                got = senses.ask(SYSTEM, TEXT, SCHEMA, audio_url=wav_data_url(wav_bytes(samples)))
                row["muse"] = {**got["answer"], "seconds": got["seconds"], "usd": got["usd"],
                               "audio_tokens": got["usage"]["audio_tokens"], "input_tokens": got["usage"]["input_tokens"]}
            except BrainError as error:
                row["muse"] = {"error": str(error)[:200]}
        del samples
        rows.append(row)
        print(row["id"], row["truth"], "panns", row["panns"], "muse", {k: row.get("muse", {}).get(k) for k in ("heard_sound", "sound", "reason_guess")}, flush=True)
    listener.close()
    # PANNs only knows cry, dog, doorbell and splash. A cough or other sound is right when PANNs stays quiet.
    panns_right = sum(r["panns"] == (r["truth"] if r["truth"] in ("baby_crying", "dog_barking", "doorbell", "water_splashing") else "other") for r in rows)
    muse_rows = [r for r in rows if "muse" in r and "error" not in r["muse"]]
    secs = [r["muse"]["seconds"] for r in muse_rows]
    summary = {"clips": len(rows), "clip_s": args.clip_s, "camera_channel": "8 kHz A-law",
               "panns_right": panns_right,
               "muse_model": senses.cfg["model"] if senses else None, "muse_host": senses.destination if senses else None,
               "muse_answered": len(muse_rows),
               "muse_heard_sound": sum(r["muse"].get("heard_sound") is True for r in muse_rows),
               "muse_audio_tokens": sum(r["muse"].get("audio_tokens", 0) for r in muse_rows),
               "muse_sound_right": sum(r["muse"].get("sound") == r["truth"] for r in muse_rows),
               "muse_cries_heard_as_cries": sum(r["truth"] == "baby_crying" and r["muse"].get("sound") == "baby_crying" for r in muse_rows),
               "cries": sum(r["truth"] == "baby_crying" for r in rows),
               "canary_right": [c["format"] for c in canary_rows if c["right"]],
               "latency_s": {"median": statistics.median(secs), "max": max(secs)} if secs else None,
               "usd": round(senses.spent_usd, 4) if senses else 0.0}
    out = ROOT / "results" / "sounds" / "muse"
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps({"summary": summary, "canary": canary_rows, "clips": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
