"""Spoken red flags through the real /hear path: does a red flag said out loud near the glasses bring the 911 line, and
does everyday talk never bring it?

    python scripts/spoken_red_flags.py --clips              # the set's lines in macOS voices, 16 kHz mono WAV (git ignored)
    python scripts/spoken_red_flags.py --run before         # every clip through /hear, results/spoken-red-flags/before.json
    python scripts/spoken_red_flags.py --run noise --noise  # the same over pink room noise 15 dB under the speech
    python scripts/spoken_red_flags.py --live-clips         # the live run's clips and camera feed, into the app (git ignored)
    python scripts/spoken_red_flags.py --live --udid SIM    # once through the glasses app in the simulator, live.json

The set (results/spoken-red-flags/set.json) was written and hashed before any tuning. Each clip is posted as a WAV to the
glasses endpoint's /hear on this Mac, with the pairing token, the way the glasses app posts an utterance. Muse Spark Open
hears it on Baseten (the /hear race, 3 calls at once), the speech gate decides, and the agent's own loop answers. The
brain is the offline rule brain: a red flag never reaches a brain, and the brain is not what is measured here. No
Telegram, no Home Assistant, nothing on the Vostro. One utterance at a time, as on the glasses.

A red flag counts as caught when the agent answered it with the 911 line (the "emergency" guard). A newborn call-now
line is reported apart. An everyday line is false when it brought the 911 line.
"""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SET = ROOT / "results" / "spoken-red-flags" / "set.json"
OUT = ROOT / "results" / "spoken-red-flags"
DATA = ROOT / "data-spoken-red-flags"
CLIPS = DATA / "clips"
ENV = Path.home() / "Engineering" / "gonza" / "meta-hackathon-2026" / ".env"
PORT = 8768
# Muse Spark Open list prices in this repo's config (results/muse/README.md): USD per million tokens in and out
PRICE_IN, PRICE_OUT = 1.25, 4.25


def lines():
    data = json.loads(SET.read_text())
    expected = (ROOT / "results" / "spoken-red-flags" / "set.sha256").read_text().split()[0]
    if hashlib.sha256(SET.read_bytes()).hexdigest() != expected:
        raise SystemExit("set.json changed since it was hashed")
    out = []
    for kind in ("red_flags", "everyday"):
        count = {"es": 0, "en": 0}
        for lang, text in data[kind]:
            voice = data["voices"][lang][count[lang] % 2]
            count[lang] += 1
            out.append({"id": f"{kind[:3]}-{lang}-{count[lang]:02d}", "kind": kind, "lang": lang, "voice": voice, "text": text})
    return out


def noisy(wav, noise_db=15):
    """The clip over pink room noise, noise_db under the speech level (approximate, as in glasses_hud_speech.batch)."""
    out = wav.with_name(wav.stem + "-noise.wav")
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-filter_complex",
                        f"anoisesrc=color=pink:amplitude=1:sample_rate=16000:seed=7,volume=-{noise_db + 18}dB[n];"
                        "[0:a][n]amix=inputs=2:duration=first:normalize=0", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", str(out)], check=True)
    return out


def make_clips():
    CLIPS.mkdir(parents=True, exist_ok=True)
    for line in lines():
        aiff = CLIPS / f"{line['id']}.aiff"
        wav = CLIPS / f"{line['id']}.wav"
        subprocess.run(["say", "-v", line["voice"], "-o", str(aiff), line["text"]], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                        str(wav)], check=True)
        aiff.unlink()
    print(f"{len(lines())} clips in {CLIPS}")


def load_key():
    """Only the Baseten key, from the hackathon's git ignored .env. Never printed."""
    for raw in ENV.read_text().splitlines():
        key, _, value = raw.strip().partition("=")
        if key.strip() == "BASETEN_API_KEY":
            os.environ["BASETEN_API_KEY"] = value.strip().strip('"').strip("'")
    for blank in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_FAMILIES_BOT_TOKEN", "TELEGRAM_CHAT_ID", "HA_MCP_TOKEN", "HA_TOKEN"):
        os.environ[blank] = ""
    if not os.environ.get("BASETEN_API_KEY"):
        raise SystemExit("BASETEN_API_KEY is not in the .env")


class Ears:
    """Every ear call the /hear path makes: how many are running, and their tokens for the bill."""

    def __init__(self, glasses):
        self.glasses, self.lock = glasses, threading.Lock()
        self.running, self.calls, self.tokens_in, self.tokens_out = 0, 0, 0, 0
        glasses._make_ear = self.make

    def make(self):
        from parenting_agent.glasses_speech import EAR_PROMPT
        from parenting_agent.voice.ear import Ear
        ear = Ear(**{"reasoning_effort": "minimal", "attempts": 1, "prompt": EAR_PROMPT, **self.glasses.ear_cfg})
        hear, ears = ear.hear, self

        def counted(wav):
            with ears.lock:
                ears.running += 1
                ears.calls += 1
            try:
                return hear(wav)
            finally:
                with ears.lock:
                    ears.running -= 1
                    ears.tokens_in += (ear.usage or {}).get("input_tokens", 0)
                    ears.tokens_out += (ear.usage or {}).get("output_tokens", 0)
        ear.hear = counted
        return ear

    def usd(self):
        return round(self.tokens_in / 1e6 * PRICE_IN + self.tokens_out / 1e6 * PRICE_OUT, 4)


def run(name, noise=False):
    load_key()
    from parenting_agent.agent import build
    from parenting_agent.agent import config as config_mod
    from parenting_agent.agent import rules
    from parenting_agent.glasses import with_dropped_words
    from parenting_agent.glasses_speech import Gate
    token = secrets.token_urlsafe(12)
    DATA.mkdir(exist_ok=True)
    data_dir = DATA / f"agent-{name}"
    data_dir.mkdir(exist_ok=True)
    for stale in data_dir.glob("*.jsonl"):
        stale.unlink()
    config = config_mod.load(None)
    people = json.loads((ROOT / "config/agent.vostro.json").read_text())["people"]
    config.update({"data_dir": str(data_dir), "env_file": str(data_dir / "none.env"), "people": {"gonza": people["gonza"]},
                   "glasses": {"port": PORT, "host": "127.0.0.1", "token": token, "person": "gonza"},
                   "plugins": ["parenting_agent.glasses:Glasses"], "house": {"live": False}})
    agent = build(config)
    glasses = agent.plugins[0]
    ears = Ears(glasses)
    seen, dropped = [], []
    glasses.on_dropped_words = dropped.append
    agent.bus.subscribe(seen.append, None)
    agent.start()
    glasses.start()
    rows = []

    def clip(line):
        wav = CLIPS / f"{line['id']}.wav"
        return noisy(wav) if noise else wav
    try:
        for line in lines():
            glasses.gate = Gate()  # every line heard fresh: no wake word window or short answer wait left from the last
            since = len(seen)
            calls = ears.calls
            started = time.monotonic()
            request = urllib.request.Request(f"http://127.0.0.1:{PORT}/hear", data=clip(line).read_bytes(),
                                             method="POST", headers={"Authorization": f"Bearer {token}",
                                                                     "Content-Type": "audio/wav",
                                                                     "X-Speech-End-Unix": f"{time.time():.3f}"})
            with urllib.request.urlopen(request, timeout=10) as reply:
                assert reply.status == 202
            # done when an utterance was heard, every ear call of it came back, and the agent's turn had time to end
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                events = seen[since:]
                if any(e["kind"] == "speech" for e in events) and ears.running == 0:
                    break
                time.sleep(0.1)
            time.sleep(1.5)
            events = with_dropped_words(seen[since:], dropped)
            speech = [e for e in events if e["kind"] == "speech"]
            guards = [e.get("status") for e in events if e["kind"] == "guard"]
            replies = [e.get("text") for e in events if e["kind"] == "reply"]
            emergency = next((e for e in events if e["kind"] == "guard" and e.get("status") == "emergency"), None)
            row = {**line, "heard": [e.get("text") for e in speech], "took": [e.get("took") for e in speech],
                   "why": [e.get("why") for e in speech], "answers": [e.get("ear_answers") for e in speech],
                   "red_flag_events": [{k: v for k, v in e.items() if k not in ("unix",)} for e in events
                                       if e["kind"] == "speech_red_flag"],
                   "messages": [e.get("text") for e in events if e["kind"] == "message"],
                   "guards": guards, "replies": replies, "ear_calls": ears.calls - calls,
                   "emergency": emergency is not None,
                   "emergency_s": round(emergency["unix"] - speech[0]["received_unix"], 3)
                   if emergency is not None and speech and speech[0].get("received_unix") and emergency.get("unix") else None,
                   "urgent": [g for g in guards if g and g.startswith("urgent_")],
                   "seconds": round(time.monotonic() - started, 3)}
            row["right"] = row["emergency"] if line["kind"] == "red_flags" else not row["emergency"]
            # What the path before #167 would have done with the same words: the gate first, the first transcript only
            first = speech[0].get("text") if speech else ""
            old = Gate().decide(first or "")
            row["old_path_911"] = bool(old["take"] and rules.is_emergency(old["text"]))
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("id", "text", "heard", "why", "emergency", "right")}, ensure_ascii=False),
                  flush=True)
    finally:
        glasses.stop()
        agent.stop()
        agent.close()
    summary = {}
    for kind in ("red_flags", "everyday"):
        for lang in ("all", "es", "en"):
            part = [r for r in rows if r["kind"] == kind and lang in ("all", r["lang"])]
            summary[f"{kind} {lang}"] = {"lines": len(part), "911 line": sum(r["emergency"] for r in part),
                                         "911 line, old path on the same words": sum(r["old_path_911"] for r in part),
                                         "newborn line": sum(bool(r["urgent"]) for r in part)}
    timing = sorted(r["emergency_s"] for r in rows if r["kind"] == "red_flags" and r["emergency_s"] is not None)
    summary["red flag: request in to 911 line, s (median, max)"] = [timing[len(timing) // 2], timing[-1]] if timing else None
    summary["ear calls"] = ears.calls
    summary["tokens in, out"] = [ears.tokens_in, ears.tokens_out]
    summary["usd at list price"] = ears.usd()
    result = {"date": time.strftime("%Y-%m-%d %H:%M %z"), "name": name, "set_sha256": hashlib.sha256(SET.read_bytes()).hexdigest(),
              "commit": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                                       text=True).stdout.strip(),
              "ear": "meta-models/muse-spark-open-1026 on inference.baseten.co, reasoning_effort minimal, the /hear race",
              "brain": "the offline rule brain", "room": "pink noise 15 dB under the speech" if noise else "clean", "summary": summary, "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


# The live run through the glasses app: (clip, voice, words, what the lens should show). No wake word on any line.
LIVE = [
    ("rf-oct30", "Paulina", "Está azul y no respira bien.", "red_flag"),
    ("rf-ack-1", "Paulina", "Ya llamé.", "red_flag_clear"),
    ("rf-everyday-es", "Mónica", "Respira tranquilo, ya se durmió.", None),
    ("rf-en", "Samantha", "She stopped breathing!", "red_flag"),
    ("rf-ack-2", "Samantha", "Got it.", "red_flag_clear"),
    ("rf-everyday-en", "Daniel", "Put him in the blue onesie today.", None),
]
APP = ROOT / "apps" / "glasses" / "ParentingGlasses"
FEED = "redflag-feed"
BUNDLE = "com.bygmv.parentingglasses"
LIVE_PORT = 8769
HOVER = Path.home() / "Engineering" / "gonza" / "meta-hackathon-2026-synthetic" / "hover" / "fresh" / "table-a-hover-2.5cm.mp4"


def live_clips():
    (APP / "MockMic").mkdir(parents=True, exist_ok=True)
    for clip, voice, text, _ in LIVE:
        aiff = APP / "MockMic" / f"{clip}.aiff"
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                        str(aiff.with_suffix(".wav"))], check=True)
        aiff.unlink()
    (APP / "MockFeed").mkdir(parents=True, exist_ok=True)
    fit = "scale=1280:704:force_original_aspect_ratio=decrease,pad=1280:704:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(HOVER), "-filter_complex",
                    f"[0:v]trim=0:2.5,setpts=PTS-STARTPTS,{fit},split=2[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0,"
                    "loop=loop=-1:size=150,trim=0:300,setpts=PTS-STARTPTS[v]", "-map", "[v]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-an", str(APP / "MockFeed" / f"{FEED}.mp4")], check=True)
    print(f"{len(LIVE)} clips and the feed in {APP}")


def live(udid):
    """Once through the glasses app: each clip played into the app's microphone (MockMicrophone into the cutter), the
    app posts the utterance to /hear, Muse hears it, and the lens shows what the agent sent. The agent runs here with
    the offline rule brain, Telegram to a capture file, the house dry, nothing on the Vostro, no heavy local model."""
    load_key()
    from parenting_agent.agent import build
    from parenting_agent.agent import config as config_mod
    from parenting_agent.channels.telegram import Telegram
    from parenting_agent.dog_watch import CapturedMessages
    from parenting_agent.glasses import with_dropped_words
    token = secrets.token_urlsafe(12)
    data_dir = DATA / "agent-live"
    data_dir.mkdir(parents=True, exist_ok=True)
    for stale in data_dir.glob("*.jsonl"):
        stale.unlink()
    os.environ.update({"TELEGRAM_BOT_TOKEN": "capture-no-token", "TELEGRAM_CHAT_ID": "1001", "TELEGRAM_CECI_CHAT_ID": "1002"})
    people = json.loads((ROOT / "config/agent.vostro.json").read_text())["people"]
    config = config_mod.load(None)
    config.update({"data_dir": str(data_dir), "env_file": str(data_dir / "none.env"), "people": people,
                   "telegram": {"allowed_chat_ids": ["1001", "1002"]}, "family_push": {"channel": "telegram"},
                   "glasses": {"port": LIVE_PORT, "host": "127.0.0.1", "token": token, "person": "gonza"},
                   "plugins": ["parenting_agent.glasses:Glasses"], "house": {"live": False}})
    agent = build(config)
    glasses = agent.plugins[0]
    captured = data_dir / "telegram-captured.jsonl"
    agent.plugins.insert(0, Telegram(agent, config, messenger=CapturedMessages(captured)))
    ears = Ears(glasses)
    seen, dropped = [], []
    glasses.on_dropped_words = dropped.append
    agent.bus.subscribe(seen.append, None)
    agent.start()
    glasses.start()
    container = Path(subprocess.run(["xcrun", "simctl", "get_app_container", udid, BUNDLE, "data"], capture_output=True,
                                    text=True, check=True).stdout.strip())
    app_log = container / "Documents" / "hud-live.jsonl"

    def app():
        return [json.loads(x) for x in app_log.read_text().splitlines() if x.strip()] if app_log.exists() else []

    def wait(predicate, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = predicate()
            if found:
                return found
            time.sleep(0.1)
        return None

    results = []
    try:
        subprocess.run(["xcrun", "simctl", "terminate", udid, BUNDLE], capture_output=True)
        app_log.unlink(missing_ok=True)
        subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", udid, BUNDLE,
                        "-agentURL", f"http://127.0.0.1:{LIVE_PORT}", "-agentToken", token, "-hudSpeech", "YES",
                        "-hudLog", "YES", "-mockFeed", FEED, "-sendFPS", "5"], check=True, capture_output=True)
        if not wait(lambda: any(r["kind"] == "feed_start" for r in app()), 90):
            raise SystemExit("the app never got a camera frame")
        time.sleep(3)
        for clip, voice, text, expect in LIVE:
            muted = lambda: [r for r in app() if r["kind"] == "mic_muted"]
            wait(lambda: not (muted() and muted()[-1]["on"]), 60)
            time.sleep(0.5)
            before, since = time.time(), len(seen)
            glasses.hub.push({"kind": "caption", "name": f"Spoken: “{text}”",
                              "source": f"{voice} (macOS voice) played as the glasses microphone"}, "gonza")
            glasses.hub.push({"kind": "mock_mic", "clip": clip}, "gonza")
            done = wait(lambda: next((r for r in app() if r["kind"] == "mock_mic_done" and r["unix"] >= before), None), 30)
            wait(lambda: any(e["kind"] == "speech" for e in seen[since:]) and ears.running == 0, 60)
            sent = lambda: [r for r in app() if r["kind"] == "sent" and r["unix"] >= before]
            if expect == "red_flag":
                card = wait(lambda: next((r for r in sent() if r.get("agent_cause") == "red_flag"), None), 30)
            elif expect == "red_flag_clear":
                card = wait(lambda: next((r for r in sent() if r.get("agent_cause") != "red_flag" and not r.get("alert")),
                                         None), 30)
            else:
                time.sleep(6)
                card = None
            time.sleep(2)
            events = with_dropped_words(seen[since:], dropped)
            speech = next((e for e in events if e["kind"] == "speech"), {})
            emergency = any(e["kind"] == "guard" and e.get("status") == "emergency" for e in events)
            end = done and done["start_unix"] + done["seconds"]
            row = {"clip": clip, "voice": voice, "said": text, "expect": expect, "heard": speech.get("text"),
                   "why": speech.get("why"), "ear_answers": speech.get("ear_answers"),
                   "late_red_flag": [e.get("text") for e in events if e["kind"] == "speech_red_flag"],
                   "message_to_agent": [e.get("text") for e in events if e["kind"] == "message"],
                   "emergency": emergency, "card": card and {k: card.get(k) for k in ("title", "status", "agent_cause")},
                   "speech_end_to_card_s": round(card["unix"] - end, 3) if card and end else None,
                   "ear_s": speech.get("ear_s")}
            row["passed"] = (bool(card) and emergency) if expect == "red_flag" else (
                bool(card) if expect == "red_flag_clear" else not emergency and not row["message_to_agent"])
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        glasses.stop()
        agent.stop()
        agent.close()
    telegram = [json.loads(x) for x in captured.read_text().splitlines()] if captured.exists() else []
    run = {"date": time.strftime("%Y-%m-%d %H:%M %z"), "udid": udid, "brain": "the offline rule brain",
           "ear": "meta-models/muse-spark-open-1026 on inference.baseten.co, the /hear race",
           "commit": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                                    text=True).stdout.strip(),
           "passed": sum(r["passed"] for r in results), "of": len(results), "lines": results,
           "telegram_captured": telegram, "ear_calls": ears.calls, "usd at list price": ears.usd(),
           "app_sent": [{k: r.get(k) for k in ("title", "status", "agent_cause", "alert", "unix")} for r in app()
                        if r["kind"] == "sent"]}
    (OUT / "live.json").write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({k: run[k] for k in ("passed", "of", "ear_calls", "usd at list price")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--clips", action="store_true")
    parser.add_argument("--run", metavar="NAME")
    parser.add_argument("--noise", action="store_true", help="the clips over pink room noise")
    parser.add_argument("--live-clips", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--udid")
    args = parser.parse_args()
    if args.clips:
        make_clips()
    if args.run:
        run(args.run, args.noise)
    if args.live_clips:
        live_clips()
    if args.live:
        live(args.udid)


if __name__ == "__main__":
    main()
