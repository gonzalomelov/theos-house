"""How well the MMS-TTS voice can be understood: each reply from results/voice/run.json is spoken with MMS-TTS and
heard back by Muse Spark Open. A reply passes when every number in it (amounts, minutes, clock times) comes back. "a las 4:30" heard as
"a las 4 y media" counts, the same time said another way.
A machine listener, not a person: it says whether the facts survive the voice, not how pleasant it sounds.

    ttsvenv/bin/python scripts/voice_roundtrip.py            # writes results/voice/roundtrip.json
    python scripts/voice_roundtrip.py --rescore              # scores the stored answers again, no model call
    python scripts/voice_roundtrip.py --wavs DIR --out roundtrip-int8.json
                                     # hears DIR/<prefix><id>.wav, spoken elsewhere (the int8 decoder on the Vostro)
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent.agent import config as config_mod  # noqa: E402
from parenting_agent.voice.client import lang_of  # noqa: E402
from parenting_agent.voice.ear import Ear  # noqa: E402

OUT = ROOT / "results" / "voice"


SMALL = {w: str(n) for n, ws in enumerate([("cero", "zero"), ("uno", "una", "one"), ("dos", "two"), ("tres", "three"),
                                            ("cuatro", "four"), ("cinco", "five"), ("seis", "six"), ("siete", "seven"),
                                            ("ocho", "eight"), ("nueve", "nine"), ("diez", "ten"), ("once", "eleven"),
                                            ("doce", "twelve"), ("cien",)]) for w in ws}
SMALL["cien"] = "100"


def facts(text, heard=False):
    """The numbers in a text, with clock times as H:MM. The heard side also reads "4 y media", "las 3" and "315"."""
    text = text.lower()
    if heard:
        text = re.sub(r"\b(\d{1,2}) y media\b", r"\1:30", text)
        text = re.sub(r"\b(\d{1,2}) y cuarto\b", r"\1:15", text)
        text = re.sub(r"\b(\d{1,2}) y (\d{2})\b", r"\1:\2", text)
        text = re.sub(r"\b(?:at|a las|las) (\d)(\d{2})\b", r"at \1:\2", text)
        text = re.sub(r"\b(at|a las|las) (\d{1,2}),? (\d{2})\b", r"\1 \2:\3", text)
        text = re.sub(r"\b(" + "|".join(SMALL) + r")\b", lambda m: SMALL[m.group(1)], text)
    out = [f"{int(h)}:{m}" for h, m in re.findall(r"\b(\d{1,2}):(\d{2})\b", text)]
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)
    text = re.sub(r"\b(?:a las|at) (\d{1,2})\b(?!:)", lambda m: f" {m.group(1)}:00 ", text)
    out += [f"{int(h)}:00" for h in re.findall(r" (\d{1,2}):00 ", text)]
    text = re.sub(r" \d{1,2}:00 ", " ", text)
    return sorted(out + [str(int(n)) for n in re.findall(r"\d+", text)])


def score(rows):
    for row in rows:
        said, back = facts(row["reply"]), facts(row["heard"], heard=True)
        row.update(numbers=said, heard_numbers=back, ok=all(back.count(n) >= said.count(n) for n in set(said)))
    return {"replies": len(rows), "numbers_back": sum(r["ok"] for r in rows),
            "es": sum(r["ok"] for r in rows if r["id"].startswith("es")),
            "en": sum(r["ok"] for r in rows if r["id"].startswith("en")), "listener": Ear().model}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rescore", action="store_true")
    parser.add_argument("--wavs", help="hear these WAVs instead of speaking with MMS-TTS here")
    parser.add_argument("--prefix", default="int8-")
    parser.add_argument("--out", default="roundtrip.json")
    args = parser.parse_args()
    if args.rescore:
        data = json.loads((OUT / args.out).read_text())
        data["summary"] = score(data["rows"])
        (OUT / args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(data["summary"]))
        return
    config_mod.load_env("~/.parenting-agent.env")
    steps = json.loads((OUT / "run.json").read_text())["steps"]
    ear, rows = Ear(), []
    if not args.wavs:
        from parenting_agent.voice.tts import MmsVoice
        voice = MmsVoice()
    for step in steps:
        reply = step["reply"].split("\n", 1)[-1]
        if args.wavs:
            wav = (Path(args.wavs) / f"{args.prefix}{step['id']}.wav").read_bytes()
        else:
            wav, _ = voice.synth(reply, lang_of(reply))
        heard = ear.hear(wav)
        rows.append({"id": step["id"], "reply": reply, "heard": heard})
        print(step["id"], flush=True)
    summary = score(rows)
    (OUT / args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
