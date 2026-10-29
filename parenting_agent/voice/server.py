"""The voice service: ffmpeg conversions and MMS-TTS behind a small HTTP API on the internal network.

    python -m parenting_agent.voice.server --host 0.0.0.0 --port 8800 [--preload]

POST /wav     body: any audio            -> 16 kHz mono WAV
POST /speak   JSON {"text", "lang", "format": "ogg" or "wav"} -> the reply as audio, X-Timings header with the
              seconds per sentence
GET  /health  -> {"ok": true, "loaded": [...]}

It has no internet and no secrets. It never logs text or audio, only sizes and seconds.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import audio
from .tts import MmsVoice

MAX_AUDIO = 20 * 1024 * 1024
MAX_TEXT = 1200


def make_handler(voice):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body, kind="application/json", headers=None):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def fail(self, code, error):
            self.reply(code, json.dumps({"error": error}).encode())

        def do_GET(self):
            if self.path == "/health":
                return self.reply(200, json.dumps({"ok": True, "loaded": sorted(voice.loaded)}).encode())
            self.fail(404, "not found")

        def do_POST(self):
            size = int(self.headers.get("Content-Length") or 0)
            if size <= 0 or size > MAX_AUDIO:
                return self.fail(413, "body missing or too large")
            body = self.rfile.read(size)
            try:
                if self.path == "/wav":
                    return self.reply(200, audio.to_wav(body), "audio/wav")
                if self.path == "/speak":
                    request = json.loads(body)
                    text, lang = str(request.get("text") or "")[:MAX_TEXT], request.get("lang") or "en"
                    wav, timings = voice.synth(text, lang)
                    out, kind = (wav, "audio/wav") if request.get("format") == "wav" else (audio.to_ogg_opus(wav), "audio/ogg")
                    return self.reply(200, out, kind, {"X-Timings": json.dumps([t["seconds"] for t in timings])})
            except (audio.AudioError, ValueError) as error:
                return self.fail(422, str(error)[:200])
            self.fail(404, "not found")

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(prog="parenting_agent.voice.server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--preload", action="store_true", help="load both voices before serving")
    args = parser.parse_args(argv)
    voice = MmsVoice()
    if args.preload:
        for lang in voice.models:
            voice.synth("ok.", lang)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(voice))
    print(f"voice: serving on {args.host}:{args.port}, voices {sorted(voice.loaded) or 'load on first use'}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
