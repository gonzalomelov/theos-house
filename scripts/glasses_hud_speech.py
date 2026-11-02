"""Speech on the glasses, live: the parent's spoken words reach the agent through the glasses microphone path, Muse Spark
Open hears them, and the answer is a card on the mock Meta Ray-Ban Display.

    python scripts/glasses_hud_speech.py --clips          # the parents' recorded lines (macOS voices) and the feed
    python scripts/glasses_hud_speech.py --batch          # word accuracy and the gate on a bigger set, no app
    # build and install the app (apps/glasses/README.md), open the Baby Buddy tunnel, then:
    python scripts/glasses_hud_speech.py --udid SIM --out-dir results/glasses-speech \\
        --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-speech.mp4

What runs for real: the app's microphone path (the utterance cutter on the phone, the WAV up to /hear), Muse Spark Open
on Baseten as the ear (the same call that hears Telegram voice notes) and as the brain, the speech gate, the glasses
channel, the changing table skill with MediaPipe on the glasses frames, the car seat coach with SAM 3.1 on this Mac (one
process, under /tmp/pa-gpu.lock), Baby Buddy with the test child, the cards through DAT's Display API.

What is mocked, and why: the microphone input (no glasses here: recorded clips of macOS voices are played into the same
cutter the glasses microphone feeds, in real time, and the run's script only says which clip to play, never its words),
the glasses, camera and lens (DAT MockDeviceKit and MockDisplayKit), the camera picture (our synthetic clips). The
changing table's SAM 3.1 confirm is off in this run, so SAM 3.1 runs once, for the car seat. No Telegram, no Home
Assistant: their variables are blanked. Nothing runs on the Vostro.
"""
import argparse
import concurrent.futures
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

GLASSES = ROOT / "apps" / "glasses" / "ParentingGlasses"
MIC_DIR = GLASSES / "MockMic"
FEED_NAME = "hud-speech-feed"
FEED_OUT = GLASSES / "MockFeed" / f"{FEED_NAME}.mp4"
SYNTH = Path.home() / "Engineering" / "gonza" / "meta-hackathon-2026-synthetic"
HOVER = SYNTH / "hover" / "fresh" / "table-a-hover-2.5cm.mp4"
CARSEAT = SYNTH / "carseat" / "clips" / "test" / "test-02-correct.mp4"
TABLE_S, SEAT_S = 150, 420  # the feed: a hand resting on the baby for the changing table, then the car seat
BUNDLE = "com.bygmv.parentingglasses"
GPU_LOCK = Path("/tmp/pa-gpu.lock")
PORT = 8767  # not the default 8766, so another run on this Mac cannot cross this one
DATA = ROOT / "data-glasses-speech"
BLANKED = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_FAMILIES_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_CECI_CHAT_ID", "HA_MCP_TOKEN",
           "HA_TOKEN", "HA_URL")

# The live run's lines: (clip, voice, words, the card it should bring or None for words not meant for the agent)
LIVE = [
    ("en-changing", "Samantha", "Changing time.", "armed"),
    ("es-baby-talk", "Paulina", "Hola Theo, ¿quién es el bebé más lindo de la casa?", None),
    ("en-done-dirty", "Daniel", "Done, it was dirty.", "logged"),
    ("es-hora-cambio", "Mónica", "Hora del cambio.", "armed"),
    ("es-listo", "Paulina", "Listo, solo pis.", "logged"),
    ("es-question", "Paulina", "Agente, ¿cuándo comió por última vez?", "answer"),
    ("en-question", "Samantha", "Agent, how many diapers has he had today?", "answer"),
    ("es-red-flag", "Mónica", "Agente, el bebé está azul y no respira.", "red_flag"),
    ("es-ya-llame", "Paulina", "Ya llamé.", "red_flag_clear"),
    ("es-car-seat", "Paulina", "Agente, ayudame a instalar la silla del auto.", "car_seat"),
    ("es-si", "Mónica", "Sí.", "car_seat_answer"),
]

# The bigger offline set: every line in two voices of its language, clean and over room noise.
BATCH = {
    "es": (("Paulina", "Mónica"), [
        ("Hora del cambio.", True), ("Listo, estaba sucio.", True), ("Listo.", True), ("Sí.", True), ("No.", True),
        ("Ya llamé.", True), ("Entendido.", True), ("Agente, ¿cuándo comió por última vez?", True),
        ("Agente, ¿cuántos pañales lleva hoy?", True), ("Agente, ayudame a instalar la silla del auto.", True),
        ("Hola mi amor, ¿quién es el más lindo?", False), ("Pasame las toallitas, por favor.", False)]),
    "en": (("Samantha", "Daniel"), [
        ("Changing time.", True), ("Done, it was dirty.", True), ("Done.", True), ("Yes.", True), ("No.", True),
        ("I called.", True), ("Got it.", True), ("Agent, when did he last eat?", True),
        ("Agent, how many diapers has he had today?", True), ("Agent, help me install the car seat.", True),
        ("Who's my little guy? Yes you are.", False), ("Can you pass me the wipes?", False)]),
}
# What the agent is waiting for while each batch line is heard: the short answers need their wait, as in the live run.
BATCH_WAITS = {"listo": "finish", "done": "finish", "si": "answer", "yes": "answer", "no": "answer",
               "ya llame": "ack", "entendido": "ack", "i called": "ack", "got it": "ack"}


def say(voice, text, out):
    """A macOS voice reading the line, as a 16 kHz mono 16-bit WAV like the cutter sends."""
    aiff = out.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)],
                   check=True)
    aiff.unlink()
    return out


def speech_bounds(wav):
    """(first, last) second with speech in a clip, from ffmpeg's silence detector at -40 dB."""
    log = subprocess.run(["ffmpeg", "-v", "info", "-i", str(wav), "-af", "silencedetect=noise=-40dB:d=0.1", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    length = float(re.search(r"Duration: (\d+):(\d+):([\d.]+)", log).groups()[2])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    first = ends[0] if starts and starts[0] < 0.05 and ends else 0.0
    last = starts[-1] if starts and (not ends or starts[-1] > ends[-1]) else length
    return round(first, 3), round(last, 3)


def make_clips():
    MIC_DIR.mkdir(parents=True, exist_ok=True)
    clips = {}
    for clip, voice, text, expect in LIVE:
        wav = say(voice, text, MIC_DIR / f"{clip}.wav")
        start, end = speech_bounds(wav)
        clips[clip] = {"voice": voice, "text": text, "expect": expect, "speech_start_s": start, "speech_end_s": end}
    DATA.mkdir(exist_ok=True)
    (DATA / "mic-clips.json").write_text(json.dumps(clips, indent=1, ensure_ascii=False) + "\n")
    return clips


def build_feed(out=FEED_OUT):
    """A hand resting on the baby (the hover clip's first 2.5 s, forwards then backwards) for the changing table, then
    the car seat clip forwards then backwards, 30 fps HEVC, 1280 x 704, no audio track (the microphone is separate)."""
    fit = "scale=1280:704:force_original_aspect_ratio=decrease,pad=1280:704:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    graph = (f"[0:v]trim=0:2.5,setpts=PTS-STARTPTS,{fit},split=2[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0,"
             f"loop=loop=-1:size=150,trim=0:{TABLE_S},setpts=PTS-STARTPTS[t];"
             f"[1:v]{fit},split=2[c][d];[d]reverse[e];[c][e]concat=n=2:v=1:a=0,loop=loop=-1:size=32767,"
             f"trim=0:{SEAT_S},setpts=PTS-STARTPTS[s];[t][s]concat=n=2:v=1:a=0[v]")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(HOVER), "-i", str(CARSEAT), "-filter_complex", graph, "-map", "[v]",
                    "-c:v", "libx265", "-tag:v", "hvc1", "-preset", "medium", "-crf", "28", "-x265-params", "log-level=error",
                    "-pix_fmt", "yuv420p", "-an", str(out)], check=True)
    return out


def load_env():
    from parenting_agent.e2e import harness
    harness.load_env()
    for key in BLANKED:
        os.environ[key] = ""


def batch(out_dir, noise_db=15, sequential=False):
    """The same ear (Muse on Baseten, raced as /hear races it) and gate on a bigger set: 24 lines in 2 voices, clean and
    over room noise at noise_db dB SNR, plus noise and silence with no speech. No app here, so this checks the hearing
    and the gate, not the cutter. sequential: one call at a time, 3 attempts, the voice notes' way."""
    from parenting_agent.glasses_speech import EAR_PROMPT, Gate, plain, race, word_errors
    from parenting_agent.voice.ear import Ear
    load_env()
    work = DATA / "batch"
    work.mkdir(parents=True, exist_ok=True)
    jobs = []
    for lang, (voices, lines) in BATCH.items():
        for voice in voices:
            for n, (text, for_agent) in enumerate(lines):
                clean = say(voice, text, work / f"{lang}-{voice.lower()}-{n:02d}.wav")
                noisy = clean.with_name(clean.stem + "-noise.wav")
                # pink noise at a fixed level under the speech's mean level (ebur128 would be finer, this is enough)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clean), "-filter_complex",
                                f"anoisesrc=color=pink:amplitude=1:sample_rate=16000,volume=-{noise_db + 18}dB[n];"
                                "[0:a][n]amix=inputs=2:duration=first:normalize=0", "-ac", "1", "-ar", "16000",
                                "-c:a", "pcm_s16le", str(noisy)], check=True)
                for wav, room in ((clean, "clean"), (noisy, "noise")):
                    jobs.append({"lang": lang, "voice": voice, "text": text, "for_agent": for_agent, "room": room, "wav": wav})
    for n, (source, seconds) in enumerate([("anoisesrc=color=pink:amplitude=0.05", 2), ("anoisesrc=color=pink:amplitude=0.05", 4),
                                           ("anoisesrc=color=brown:amplitude=0.1", 3), ("anullsrc=r=16000", 2)]):
        wav = work / f"no-speech-{n}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source if source.startswith("anullsrc") else f"{source}:sample_rate=16000", "-t", str(seconds),
                        "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
        jobs.append({"lang": "none", "voice": "none", "text": "", "for_agent": False, "room": "no speech", "wav": wav})

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=24)

    def hear(job):
        started, calls = time.monotonic(), None
        try:
            if sequential:
                ear = Ear(reasoning_effort="minimal")
                heard, calls = ear.hear(job["wav"].read_bytes()), None
                calls = ear.tries
            else:
                heard, info = race(lambda: Ear(reasoning_effort="minimal", attempts=1, prompt=EAR_PROMPT),
                                   job["wav"].read_bytes(), pool=pool)
                calls = info["calls"]
            error = None
        except Exception as failure:
            heard, error = "", str(failure)[:200]
        seconds = round(time.monotonic() - started, 3)
        gate = Gate()
        said = plain(job["text"]).split()
        wait = (BATCH_WAITS.get(" ".join(said[:2])) or BATCH_WAITS.get(said[0])) if said else "finish, answer, ack"
        for kind in (wait or "").split(", "):
            if kind:
                gate.wait("parent", kind)  # no speech: the hardest case, while the agent waits for every short answer
        decision = gate.decide(heard, "parent")
        errors, words = word_errors(job["text"], heard)
        return {**{k: v for k, v in job.items() if k != "wav"}, "clip": job["wav"].name, "heard": heard, "error": error,
                "ear_s": seconds, "calls": calls, "word_errors": errors, "words": words, "waiting_for": wait,
                "took": decision["take"], "why": decision["why"], "gate_right": decision["take"] == job["for_agent"]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=1 if not sequential else 4) as lines:  # one utterance at a time, as on the glasses
        rows = list(lines.map(hear, jobs))
    summary = {}
    for key in ("all", "es", "en", "clean", "noise"):
        part = [r for r in rows if r["room"] != "no speech" and (key == "all" or key in (r["lang"], r["room"]))]
        errors, words = sum(r["word_errors"] for r in part), sum(r["words"] for r in part)
        seconds = sorted(r["ear_s"] for r in part)
        summary[key] = {"utterances": len(part), "word_accuracy": round(1 - errors / words, 3), "word_errors": errors,
                        "words": words, "exact": sum(r["word_errors"] == 0 for r in part),
                        "gate_right": sum(r["gate_right"] for r in part), "ear_failures": sum(bool(r["error"]) for r in part),
                        "ear_s_median": seconds[len(seconds) // 2], "ear_s_max": seconds[-1]}
    silent = [r for r in rows if r["room"] == "no speech"]
    summary["no speech"] = {"clips": len(silent), "taken": sum(r["took"] for r in silent), "heard": [r["heard"] for r in silent]}
    result = {"date": time.strftime("%Y-%m-%d %H:%M %z"), "ear": "meta-models/muse-spark-open-1026 on inference.baseten.co, "
              "reasoning_effort minimal, " + ("one call at a time, 3 attempts" if sequential else "3 calls at once, first transcript wins, 2 rounds"),
              "noise": f"pink noise {noise_db} dB under the speech level (approximate)",
              "summary": summary, "rows": rows}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / ("batch-sequential.json" if sequential else "batch.json")).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=1))
    return result


def rows(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def gpu_lock(wait_s=1800):
    deadline = time.monotonic() + wait_s
    while True:
        try:
            GPU_LOCK.mkdir()
            return
        except FileExistsError:
            if time.monotonic() > deadline:
                raise SystemExit("the GPU lock stayed taken")
            print("GPU lock taken, waiting 60 s", flush=True)
            time.sleep(60)


class Run:
    def __init__(self, args):
        self.args = args
        self.clips = json.loads((DATA / "mic-clips.json").read_text())

    def config(self):
        config = json.loads((ROOT / "config/agent.glasses-live.json").read_text())
        people = json.loads((ROOT / "config/agent.vostro.json").read_text())["people"]
        skill = json.loads((ROOT / "skills/changing-table.json").read_text())
        skill["confirm"] = {"provider": "none"}  # SAM 3.1 runs once in this run, for the car seat
        DATA.mkdir(exist_ok=True)
        (DATA / "changing-table.json").write_text(json.dumps(skill, indent=1) + "\n")
        config.update({
            "data_dir": str(DATA), "people": {"gonza": people["gonza"]},
            "plugins": ["parenting_agent.glasses:Glasses", "parenting_agent.changing_table:ChangingTable",
                        "parenting_agent.carseat.plugin:CarSeatCoach"],
            "glasses": {"port": PORT, "host": "127.0.0.1", "person": "gonza"},
            "changing_table": {**config["changing_table"], "skill": str(DATA / "changing-table.json"), "preload_confirm": False,
                               "keep_confirm": False},
            "car_seat": {"skill": "skills/car-seat.json", "source": f"glasses:{PORT}", "channel": "glasses"},
            "allowed_tools": config["allowed_tools"] + ["start_car_seat_coach", "answer_car_seat_check", "car_seat_outgrow"],
            "house": {"live": False},
        })
        config["changing_table"]["source"] = f"glasses:{PORT}"
        for drop in ("camera_skills", "dog_watch_glasses"):
            config.pop(drop, None)
        return config

    def app_log(self):
        return rows(self.container / "Documents" / "hud-live.jsonl")

    def feed_s(self):
        start = next((r["unix"] for r in self.app_log() if r["kind"] == "feed_start"), None)
        return None if start is None else time.time() - start

    def wait(self, predicate, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = predicate()
            if found:
                return found
            time.sleep(0.1)
        return None

    def muted(self):
        rows_ = [r for r in self.app_log() if r["kind"] == "mic_muted"]
        return bool(rows_ and rows_[-1]["on"])

    def speech_after(self, unix):
        from parenting_agent.glasses import with_dropped_words
        return [e for e in with_dropped_words(self.agent.bus.history, self.dropped)
                if e["kind"] == "speech" and e.get("received_unix", 0) >= unix]

    def sent_after(self, unix):
        return [r for r in self.app_log() if r["kind"] == "sent" and r["unix"] >= unix]

    def outcome(self, expect, since):
        """The app's display send that answers the line, or None."""
        sent = self.sent_after(since)
        match = {
            "armed": lambda r: r["cause"] == "armed",
            "logged": lambda r: r["cause"] == "logged",
            "answer": lambda r: r["agent_cause"] == "answer",
            "red_flag": lambda r: r["agent_cause"] == "red_flag",
            "car_seat": lambda r: r["agent_cause"] == "car_seat",
            "car_seat_answer": lambda r: r["agent_cause"] == "car_seat" and r["unix"] > since,
            "red_flag_clear": lambda r: r["agent_cause"] != "red_flag" and not r.get("alert"),
        }[expect]
        return next((r for r in sent if match(r)), None)

    def line(self, clip, hold_s=6.0, timeout=60):
        """Plays one clip into the app's microphone and follows it to the card."""
        info = self.clips[clip]
        # The app mutes its microphone while it speaks (so the agent never hears itself): a parent waits for it to finish
        self.wait(lambda: not self.muted(), 60)
        time.sleep(0.5)
        before = time.time()
        turns = self.agent.bus.count("turn")
        self.hub.push({"kind": "caption", "name": f"Spoken: “{info['text']}”",
                       "source": f"{info['voice']} (macOS voice) played as the glasses microphone"}, "gonza")
        self.hub.push({"kind": "mock_mic", "clip": clip}, "gonza")
        played = self.wait(lambda: next((r for r in self.app_log() if r["kind"] == "mock_mic" and r["unix"] >= before), None), 10)
        heard = self.wait(lambda: self.speech_after(before), timeout)
        result = {"clip": clip, **info, "played": played}
        if not heard:
            return {**result, "heard": None, "passed": False}
        heard = heard[0]
        result["heard"] = {k: heard.get(k) for k in ("text", "took", "why", "ear_s", "speech_end_unix", "speech_s",
                                                     "received_unix", "heard_unix", "error")}
        from parenting_agent.glasses_speech import word_errors
        result["word_errors"], result["words"] = word_errors(info["text"], heard.get("text") or "")
        done = next((r for r in self.app_log() if r["kind"] == "mock_mic_done" and r["unix"] >= before), None)
        true_end = done and round(done["start_unix"] + info["speech_end_s"], 3)
        result["speech_end_unix"] = true_end
        result["cutter_end_unix"] = heard.get("speech_end_unix")
        if info["expect"] is None:
            time.sleep(hold_s)
            result["passed"] = not heard["took"] and self.agent.bus.count("turn") == turns
            result["messages_to_agent"] = self.agent.bus.count("turn") - turns
            return result
        card = self.wait(lambda: self.outcome(info["expect"], before), timeout)
        result["card"] = card and {k: card.get(k) for k in ("title", "status", "detail", "meta", "cause", "agent_cause", "unix")}
        base = true_end or heard.get("speech_end_unix")
        if card and base:
            result["latency"] = {"speech_end_to_card_s": round(card["unix"] - base, 3),
                                 "speech_end_to_cutter_end_s": round(heard["speech_end_unix"] - base, 3) if heard.get("speech_end_unix") else None,
                                 "endpoint_and_upload_s": round(heard["received_unix"] - heard["speech_end_unix"], 3) if heard.get("speech_end_unix") else None,
                                 "ear_s": heard.get("ear_s"),
                                 "heard_to_card_s": round(card["unix"] - heard["heard_unix"], 3)}
        result["passed"] = bool(heard["took"] and card)
        # the parent waits for the agent's answer before speaking again: its turn ends, then the app speaks it
        self.wait(lambda: self.agent.bus.count("turn") > turns, timeout)
        time.sleep(1.0)
        time.sleep(hold_s)
        return result

    def execute(self):
        load_env()
        from parenting_agent.agent import build
        token = secrets.token_urlsafe(12)
        os.environ["PARENTING_AGENT_GLASSES_TOKEN"] = token
        DATA.mkdir(exist_ok=True)
        for stale in DATA.glob("*.jsonl"):
            stale.unlink()
        self.agent = agent = build(self.config())
        glasses = next(p for p in agent.plugins if p.name == "glasses")
        self.hub = glasses.hub
        self.dropped = []
        glasses.on_dropped_words = self.dropped.append
        agent.start()
        for plugin in agent.plugins:
            plugin.start()
        agent.bus.publish("agent_started", brain=agent.brain.name, destination=agent.brain.destination, run="glasses-speech")
        udid = self.args.udid
        recorder, video_start, results = None, {}, []
        raw = Path(os.path.expanduser(self.args.video)).with_name(Path(self.args.video).stem + "-raw.mp4") if self.args.video else None
        try:
            subprocess.run(["xcrun", "simctl", "terminate", udid, BUNDLE], capture_output=True)
            self.container = Path(subprocess.run(["xcrun", "simctl", "get_app_container", udid, BUNDLE, "data"],
                                                 capture_output=True, text=True, check=True).stdout.strip())
            (self.container / "Documents" / "hud-live.jsonl").unlink(missing_ok=True)
            if raw:
                raw.parent.mkdir(parents=True, exist_ok=True)
                recorder = subprocess.Popen(["xcrun", "simctl", "io", udid, "recordVideo", "--codec", "h264", "--force", str(raw)],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

                def started():
                    for line in recorder.stderr:
                        if "Recording started" in line and "unix" not in video_start:
                            video_start["unix"] = time.time()
                threading.Thread(target=started, daemon=True).start()
                time.sleep(1.5)
            subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", udid, BUNDLE,
                            "-agentURL", f"http://127.0.0.1:{PORT}", "-agentToken", token, "-hudSpeech", "YES",
                            "-hudLog", "YES", "-mockFeed", FEED_NAME, "-sendFPS", "5", "-recordSpeech", "YES"],
                           check=True, capture_output=True)
            if not self.wait(lambda: any(r["kind"] == "feed_start" for r in self.app_log()), 90):
                raise SystemExit("the app never got a camera frame")
            time.sleep(3)
            for clip, *_ in LIVE:
                if clip == "es-car-seat":
                    # the car seat clip starts TABLE_S s into the feed: wait for it before asking for the coach
                    self.wait(lambda: (self.feed_s() or 0) > TABLE_S + 3, TABLE_S + 60)
                result = self.line(clip, timeout=120 if clip == "es-car-seat" else 60)
                if clip == "es-car-seat" and result.get("card"):
                    time.sleep(2)
                results.append(result)
                print(json.dumps({k: result.get(k) for k in ("clip", "passed", "heard", "latency")}, ensure_ascii=False,
                                 default=str), flush=True)
            # the coach goes on to SAM 3.1's camera steps after the "sí": a few of them on the car seat clip, then stop
            self.wait(lambda: len({e["cause"] for e in agent.bus.history if e["kind"] == "glasses_card"
                                   and e["topic"] == "car_seat"}) >= 4, 90)
            time.sleep(4)
        finally:
            if recorder:
                recorder.send_signal(signal.SIGINT)
                recorder.wait(timeout=60)
            coach = next((p for p in agent.plugins if getattr(p, "name", "") == "car-seat"), None)
            if coach is not None and coach.coach is not None:
                coach.coach.stop()
            vision = getattr(getattr(coach, "coach", None), "vision", None)
            for plugin in agent.plugins:
                plugin.stop()
            if vision is not None and getattr(vision, "process", None) is not None:
                vision.process.kill()  # the one SAM 3.1 process, stopped
            agent.stop()
            agent.close()
        return self.report(results, raw, video_start)

    def report(self, results, raw, video_start):
        import glasses_hero_run as hero
        from parenting_agent.glasses import with_dropped_words
        events = rows(DATA / "events.jsonl")
        app = self.app_log()
        out = Path(self.args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        heard = [r for r in results if r.get("heard")]
        errors, words = sum(r.get("word_errors", 0) for r in heard), sum(r.get("words", 0) for r in heard)
        lat = sorted(r["latency"]["speech_end_to_card_s"] for r in results if r.get("latency"))
        brains = hero.brain_calls(events)
        run = {"date": time.strftime("%Y-%m-%d %H:%M %z"), "port": PORT, "lines": results,
               "passed": sum(bool(r.get("passed")) for r in results), "of": len(results),
               "word_accuracy": round(1 - errors / words, 3) if words else None, "word_errors": errors, "words": words,
               "speech_end_to_card_s": lat,
               "brain_models": sorted({f"{b.get('model')} on {b.get('destination')}" for b in brains}),
               "brain_calls": len(brains),
               "speech_events": [e for e in with_dropped_words(events, self.dropped) if e["kind"] == "speech"],
               "conversation": [{"unix": e.get("unix"), "who": "parent" if e["kind"] == "message" else "agent", "text": e["text"]}
                                for e in events if e["kind"] in ("message", "reply")],
               "glasses_cards": [e for e in events if e["kind"] == "glasses_card"],
               "baby_log": [{k: e.get(k) for k in ("kind", "id", "time", "wet", "solid", "entry")} for e in events
                            if e["kind"] in ("change_read_back", "tracked", "track_error")],
               "sam3": [e for e in events if e["kind"] in ("carseat_frame", "carseat_check")][:40],
               "house": [e for e in events if e["kind"].startswith("house")],
               "app_log": app}
        if raw and raw.exists() and video_start:
            speech_dir = out / f"{self.args.name}-speech"
            spoken = hero.pull_speech(self.args.udid, speech_dir)
            clips = hero.audio_clips(spoken, speech_dir, video_start["unix"], speech_dir / hero.TONE)
            # the parent's voice: each clip at the moment the app started feeding it to the microphone
            for row in app:
                if row["kind"] == "mock_mic_done":
                    clips.append((MIC_DIR / f"{row['clip']}.wav", round(row["start_unix"] - video_start["unix"], 3), None))
            clips.sort(key=lambda c: c[1])
            video = Path(os.path.expanduser(self.args.video))
            hero.mux(raw, [c for c in clips if c[1] >= 0], video, crf=26)
            run["video"] = {"file": str(video), "bytes": video.stat().st_size, "raw": str(raw), "start_unix": video_start["unix"]}
        (out / f"{self.args.name}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str) + "\n")
        print(json.dumps({k: run[k] for k in ("passed", "of", "word_accuracy", "speech_end_to_card_s", "brain_calls")}))
        return run


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--clips", action="store_true", help="make the recorded lines and the mock camera feed")
    parser.add_argument("--batch", action="store_true", help="word accuracy and the gate on the bigger set")
    parser.add_argument("--udid")
    parser.add_argument("--out-dir", default="results/glasses-speech")
    parser.add_argument("--name", default="run")
    parser.add_argument("--video")
    args = parser.parse_args()
    if args.clips:
        print(json.dumps(make_clips(), indent=1, ensure_ascii=False))
        print(build_feed())
        return
    if args.batch:
        batch(args.out_dir)
        return
    if not args.udid:
        parser.error("--udid is needed for a run")
    gpu_lock()
    try:
        Run(args).execute()
    finally:
        GPU_LOCK.rmdir()


if __name__ == "__main__":
    main()
