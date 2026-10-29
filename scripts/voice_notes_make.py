"""Makes the synthetic voice-note test set: macOS say voices, converted to OGG Opus like a Telegram voice note.

Every file is synthetic (a text-to-speech voice reading a scripted line), no family audio. macOS has no
rioplatense voice, so the Spanish lines are rioplatense wording read by the Mexican (Paulina) and Spain (Mónica)
voices.

    python scripts/voice_notes_make.py      # writes results/voice/notes/*.ogg and notes.json
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent.voice import audio  # noqa: E402

OUT = ROOT / "results" / "voice" / "notes"

# (id, voice, clock time the note is sent, text). The checks live in voice_notes_run.py.
NOTES = [
    ("es01", "Paulina", "03:20", "Le di noventa mililitros de mamadera a las tres."),
    ("es02", "Mónica", "03:45", "Le cambié el pañal, estaba mojado."),
    ("es03", "Paulina", "04:10", "Recién hizo caca, pañal sucio."),
    ("es04", "Mónica", "04:50", "Se durmió a las cuatro y media."),
    ("es05", "Paulina", "06:15", "Se despertó recién."),
    ("es06", "Mónica", "06:40", "Le di la teta del lado izquierdo, diez minutos."),
    ("es07", "Paulina", "07:30", "Tomó una mamadera de ciento veinte."),
    ("es08", "Mónica", "07:55", "¿Cuánto tomó de mamadera hoy?"),
    ("es09", "Paulina", "08:05", "Perdón, la última mamadera fue de cien, no de ciento veinte."),
    ("es10", "Mónica", "08:40", "Pañal mojado y con caca."),
    ("en01", "Samantha", "02:20", "Gave her a sixty milliliter bottle at two."),
    ("en02", "Daniel", "02:45", "Changed a wet diaper."),
    ("en03", "Samantha", "03:10", "She just pooped, dirty diaper."),
    ("en04", "Daniel", "03:40", "She fell asleep at three fifteen."),
    ("en05", "Samantha", "05:30", "She just woke up."),
    ("en06", "Daniel", "05:50", "Breastfed on the right side for twelve minutes."),
    ("en07", "Samantha", "06:30", "Bottle, one hundred fifty milliliters."),
    ("en08", "Daniel", "06:55", "How much did she drink from bottles today?"),
    ("en09", "Samantha", "07:05", "Sorry, that last bottle was one hundred thirty, not one hundred fifty."),
    ("en10", "Daniel", "07:40", "Wet and dirty diaper."),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for note_id, voice, _, text in NOTES:
            aiff = Path(tmp) / f"{note_id}.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
            (OUT / f"{note_id}.ogg").write_bytes(audio.to_ogg_opus(aiff.read_bytes()))
    (OUT / "notes.json").write_text(json.dumps(
        [{"id": i, "voice": v, "sent_at": at, "text": t, "synthetic": True, "made_with": f"macOS say -v {v}"}
         for i, v, at, t in NOTES], ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {len(NOTES)} synthetic voice notes to {OUT}")


if __name__ == "__main__":
    main()
