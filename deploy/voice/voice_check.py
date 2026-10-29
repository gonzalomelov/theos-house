"""Run inside a voice container by deploy/voice.sh: it speaks, converts, and reaches nothing outside its network.

    docker exec -i pa-voice-family python - < deploy/voice/voice_check.py

Exit 0 when every check holds. Prints sizes and seconds only.
"""
import json
import os
import socket
import sys
import time
import urllib.request

ok = True


def check(name, passed, detail=""):
    global ok
    ok = ok and passed
    print(f"{'ok  ' if passed else 'FAIL'} {name} {detail}".rstrip(), flush=True)


def post(path, body, kind):
    request = urllib.request.Request("http://127.0.0.1:8800" + path, data=body, headers={"Content-Type": kind})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), response.headers.get("X-Timings"), round(time.monotonic() - started, 3)


for lang, text in (("es", "Listo, anoté la mamadera de 90 ml a las 15:00."), ("en", "Done, I logged a 90 ml bottle at 3:00.")):
    ogg, timings, seconds = post("/speak", json.dumps({"text": text, "lang": lang}).encode(), "application/json")
    check(f"speaks {lang}", ogg[:4] == b"OggS" and b"OpusHead" in ogg[:200], f"{len(ogg)} bytes OGG Opus in {seconds} s, model {timings} s")
    wav, _, seconds = post("/wav", ogg, "application/octet-stream")
    check(f"converts {lang} back to WAV", wav[:4] == b"RIFF", f"{len(wav)} bytes in {seconds} s")

check("no proxy settings", not any(k.lower().endswith("_proxy") for k in os.environ))
check("weights offline", os.environ.get("HF_HUB_OFFLINE") == "1")
for host, port in (("1.1.1.1", 443), ("huggingface.co", 443), ("host.docker.internal", 22)):
    try:
        socket.create_connection((host, port), timeout=4).close()
        check(f"cannot reach {host}:{port}", False, "REACHABLE")
    except OSError as error:
        check(f"cannot reach {host}:{port}", True, type(error).__name__)
sys.exit(0 if ok else 1)
