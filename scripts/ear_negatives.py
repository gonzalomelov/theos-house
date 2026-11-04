"""The negative set for the Ear's false alarm work: human noise and room noise, built from what is on this Mac, and the frozen split.

    python scripts/ear_negatives.py     # renders into OUT (not in git), writes results/ear-false-alarms/split.json

Real people: 10 coughs, one person reading aloud, a 1944 radio broadcast, a 1918 song, all Wikimedia Commons with their licences in
hearing_sources.json. Everything else human is the Mac's `say`, which is a synthetic voice and not a person close to a microphone: it
stands in for speech, shouting, laughing, singing, humming, sighing, groaning and a bad imitation of a cry, in English and Spanish.
Voices and phrases never appear on both sides of the split. Nothing here was scored when the split was written.
"""
import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HEARING = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic"
OUT = HEARING / "ear-negatives"
CHUNK_S = 20

EN = {"tune": ["Samantha", "Daniel", "Grandpa (English (US))", "Sandy (English (US))"],
      "held_out": ["Karen", "Moira", "Reed (English (US))", "Shelley (English (UK))"]}
ES = {"tune": ["Paulina", "Eddy (Spanish (Mexico))"], "held_out": ["Flo (Spanish (Spain))", "Rocko (Spanish (Spain))"]}
NOVELTY = {"tune": ["Bahh", "Cellos", "Good News"], "held_out": ["Wobble", "Bad News", "Bells", "Trinoids"]}
PHRASES = {
    "speech": {"tune": ("Did you see where I left the keys, I thought they were on the table next to the window.",
                        "A ver, pasame el cargador que se me queda sin batería el teléfono, gracias."),
               "held_out": ("Okay, I will call them tomorrow morning and ask about the delivery, it should be fine.",
                            "Che, mirá que hoy llueve toda la tarde, llevate el paraguas por las dudas.")},
    "shout": {"tune": ("Hey! Hey! Stop it! Come back here right now!", "¡Ey! ¡Vení para acá! ¡Te dije que no!"),
              "held_out": ("No! No! Watch out! Get off of there!", "¡Pará! ¡Pará! ¡Cuidado! ¡Salí de ahí!")},
    "laugh": {"tune": ("ha ha ha ha ha ha, ha ha ha, hee hee hee hee", "ja ja ja ja ja, ja ja, jajajaja"),
              "held_out": ("heh heh heh, ah ha ha ha ha, oh ho ho ho", "jo jo jo, ji ji ji ji, ja ja ja ja")},
    "sing": {"tune": ("la la la la la, la la la, doo doo doo doo", "la la la, tralala, la la la la"),
             "held_out": ("na na na na, hey hey, na na na na na", "lara lara lara, la la, lara la")},
    "hum": {"tune": ("mmmmmmm, hmmmm hmmm hmmmm, mmmmmmmmm", "mmmm, mmmmm, hmmmm"),
            "held_out": ("hmm hmm hmmmmm, nnnnnn, mmmmm hmmm", "hmmmm, nnnnn, mmmm mmm")},
    "sigh": {"tune": ("aaaaaahhhhh, oh dear, hhhhhhhh, oh my", "aaaah, uuuuf, ay, qué cansancio"),
             "held_out": ("ohhhhh, phew, hhhhhhh, oh boy", "ayyyy, uuuuf, ay ay ay, bueno")},
    "groan": {"tune": ("ow ow ow! ouch! ow that hurt, aaaargh", "ay ay ay, me duele, aaay"),
              "held_out": ("ugh, ooooh no, aaah, that really hurts", "aaaay, ay, uuuurgh, no puede ser")},
    "cry_imitation": {"tune": ("waaah waaah waaah waaaaah, wah wah wah", "uaaa uaaa uaaaaa, uaaa"),
                      "held_out": ("wuh wuh waaaaaah, nyaaaa nyaaaa, waaaah", "ngaaa ngaaa, uuaaaa, ngaaaa")},
}
# Commons clips by side. Long ones are cut into CHUNK_S pieces so a false alarm is counted per piece and per hour.
HUMAN_REAL = {"tune": [("speech_real", "audio2/raw/Radio Oranje 22-nov.-1944 AIRCHECK RADIO ORANJE.wav"),
                       ("sing_real", 'audio2/raw/"Cry-Baby" (1918), by Tom Brown & Ernie Erdman.opus')],
              "held_out": [("speech_real", "audio2/raw/The beginning of wikipedia Read aloud.wav")]}
ROOM = {"tune": ["audio2/raw/Kitchen tidy up.ogg", "audio2/raw/Electric kettle and a gastherme.ogg", "audio2/raw/Cooker hood.ogg"],
        "held_out": ["audio2/raw/Ambient Kitchen Sounds.wav", "audio2/raw/Kitchen sounds recorded while cooking.ogg",
                     "audio2/raw/Dishwasher end droning hissing humming.ogg"]}
WIKITTS = "audio2/raw/WikiTTS Canada Wikipedia article.oga"  # 300 s of a synthetic reader, for held-out speech
SIDES = {"dev": "tune", "test": "held_out"}
HOT = "volume=24dB"  # a voice next to the microphone: the level clips, as an overdriven camera input does
QUIET = "volume=-30dB"  # the room from across the room: the camera's real level was about -70 dBFS on Nov 3


def ffmpeg(*args):
    subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-y", "-v", "error", *args], check=True)


def render(source, name, af=None, loop_to=None, start=None, seconds=None):
    """A mono 16 kHz file, optionally looped to loop_to seconds, optionally with a level filter."""
    path = OUT / f"{name}.wav"
    args = []
    if loop_to:
        args += ["-stream_loop", "-1"]
    if start is not None:
        args += ["-ss", str(start)]
    args += ["-i", str(source), "-vn", "-ac", "1", "-ar", "16000"]
    if af:
        args += ["-af", af]
    if loop_to or seconds:
        args += ["-t", str(loop_to or seconds)]
    ffmpeg(*args, str(path))
    return path.name


def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True, check=True).stdout)


def spoken(voice, text, tag):
    aiff = OUT / f"_{tag}.aiff"
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    return aiff


def items():
    OUT.mkdir(exist_ok=True)
    rows = []
    def add(name, side, kind, variant, source, origin):
        rows.append({"id": len(rows), "file": name, "split": side, "kind": kind, "variant": variant, "source": source, "origin": origin})
    for side in ("tune", "held_out"):
        for kind, (en, es) in {k: v[side] for k, v in PHRASES.items()}.items():
            for voice, text in [(v, en) for v in EN[side]] + [(v, es) for v in ES[side]]:
                tag = hashlib.sha1(f"{voice}{text}".encode()).hexdigest()[:10]
                aiff = spoken(voice, text, tag)
                base = f"say-{kind}-{tag}"
                up = "asetrate=22050*1.5,aresample=16000" if kind == "cry_imitation" else None  # a voice pushed up to baby pitch
                add(render(aiff, base, up, loop_to=12), side, kind, "plain", voice, "say")
                add(render(aiff, base + "-hot", ",".join(f for f in (up, HOT) if f), loop_to=12), side, kind, "hot", voice, "say")
                aiff.unlink()
        for voice in NOVELTY[side]:
            text = "la la la la, waaah waaah, mmmm hmmm, la la la"
            tag = hashlib.sha1(voice.encode()).hexdigest()[:10]
            aiff = spoken(voice, text, tag)
            add(render(aiff, f"say-novelty-{tag}", loop_to=12), side, "novelty_voice", "plain", voice, "say")
            add(render(aiff, f"say-novelty-{tag}-hot", HOT, loop_to=12), side, "novelty_voice", "hot", voice, "say")
            aiff.unlink()
        for kind, rel in HUMAN_REAL[side]:
            source = HEARING / rel
            stem = hashlib.sha1(rel.encode()).hexdigest()[:10]
            for n, start in enumerate(range(0, int(duration(source)) - 4, CHUNK_S)):
                add(render(source, f"real-{stem}-{n}", start=start, seconds=CHUNK_S), side, kind, "plain", rel, "commons")
                add(render(source, f"real-{stem}-{n}-hot", HOT, start=start, seconds=CHUNK_S), side, kind, "hot", rel, "commons")
        for rel in ROOM[side]:
            source = HEARING / rel
            stem = hashlib.sha1(rel.encode()).hexdigest()[:10]
            for n, start in enumerate(range(0, int(duration(source)) - 4, CHUNK_S)):
                add(render(source, f"room-{stem}-{n}", start=start, seconds=CHUNK_S), side, "room", "plain", rel, "commons")
                add(render(source, f"room-{stem}-{n}-quiet", QUIET, start=start, seconds=CHUNK_S), side, "room", "quiet", rel, "commons")
    for n, start in enumerate(range(0, 300, CHUNK_S)):
        stem = hashlib.sha1(WIKITTS.encode()).hexdigest()[:10]
        add(render(HEARING / WIKITTS, f"wikitts-{stem}-{n}", start=start, seconds=CHUNK_S), "held_out", "speech_wikitts", "plain", WIKITTS, "commons")
        add(render(HEARING / WIKITTS, f"wikitts-{stem}-{n}-hot", HOT, start=start, seconds=CHUNK_S), "held_out", "speech_wikitts", "hot", WIKITTS, "commons")
    for entry in json.loads((HEARING / "hearing_sources.json").read_text()):
        side = SIDES[entry["split"]] if entry["label"] in ("cough", "dog", "doorbell", "splash") else None
        if side is None:
            continue
        source = HEARING / entry["file"]
        name = f"set-{entry['id']}"
        if entry["label"] == "cough":
            add(render(source, name + "-hot", HOT, start=0, seconds=min(CHUNK_S, duration(source))), side, "cough", "hot", entry["id"], "commons")
            add(render(source, name + "-fit", loop_to=12), side, "cough", "fit", entry["id"], "commons")
        add(render(source, name, start=0, seconds=min(CHUNK_S, duration(source))), side, entry["label"], "plain", entry["id"], "commons")
    return rows


def main():
    rows = items()
    protocol = {
        "written": "2026-11-04, before any score was computed on any of these items or any new rule",
        "cries": "the cries keep the Oct 31 split of results/sounds/meta-hearing/split.json, the held-out 348 are not looked at until the rule is committed",
        "negatives": "every item here is not a cry. Sides share no voice, no phrase and no source recording",
        "tuning_rule": "maximize cries sent minus 3 x negative items sent on the tune side, the Oct 31 rule. Ties go to the stricter rule",
        "metric": "an item counts as sent when the listener's own sink posts at least once, through the Tapo channel and the real Ear",
        "limits": "most human items are the Mac's say, not a person. hot is a level boost and clipping, not the sound of a mouth at a microphone",
    }
    (REPO / "results/ear-false-alarms").mkdir(exist_ok=True)
    (REPO / "results/ear-false-alarms/split.json").write_text(json.dumps({"protocol": protocol, "root": str(OUT).replace(str(Path.home()), "~"), "items": rows}, indent=0, ensure_ascii=False) + "\n")
    print(len(rows))


if __name__ == "__main__":
    main()
