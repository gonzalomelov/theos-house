"""Try the ears and the voice by hand.

    python -m parenting_agent.voice hear note.ogg              # what Muse hears in a voice note
    python -m parenting_agent.voice say "Listo, anoté 90 ml"    # speak on the default output (Mac speakers, AirPods)
    python -m parenting_agent.voice say "Done" --out reply.ogg  # write a Telegram voice note instead
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ..agent import config as config_mod
from . import audio
from .client import lang_of
from .ear import Ear


def main(argv=None):
    parser = argparse.ArgumentParser(prog="parenting_agent.voice")
    parser.add_argument("action", choices=["hear", "say"])
    parser.add_argument("value")
    parser.add_argument("--lang", choices=["es", "en"])
    parser.add_argument("--out")
    parser.add_argument("--env-file", default="~/.parenting-agent.env")
    args = parser.parse_args(argv)
    if args.action == "hear":
        config_mod.load_env(args.env_file)
        ear = Ear()
        print(ear.hear(audio.to_wav(Path(args.value).read_bytes())))
        print(f"({ear.seconds} s, {ear.model})", file=sys.stderr)
        return 0
    from .tts import MmsVoice
    wav, timings = MmsVoice().synth(args.value, args.lang or lang_of(args.value))
    for t in timings:
        print(f"{t['seconds']:.3f} s for {t['audio_s']:.2f} s of speech", file=sys.stderr)
    if args.out:
        Path(args.out).write_bytes(audio.to_ogg_opus(wav) if args.out.endswith(".ogg") else wav)
        return 0
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out:
        out.write(wav)
    try:
        subprocess.run(["afplay" if sys.platform == "darwin" else "aplay", out.name], check=False)
    finally:
        os.unlink(out.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
