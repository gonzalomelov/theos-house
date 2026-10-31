"""A compressed day on the glasses display: the real family agent, a mock Meta Ray-Ban Display on Gonza, and the
cards each parent's glasses get.

    python scripts/glasses_hud_day.py --build-feed      # MockFeed/hud-day-feed.mp4, our synthetic car seat clip
    # build and install the app (apps/glasses/README.md), open the Baby Buddy and Home Assistant tunnels, then:
    python scripts/glasses_hud_day.py --udid SIM --out-dir results/glasses-day \\
        --video ~/Engineering/gonza/meta-hackathon-2026-synthetic/video-v5/rec/hud/hud-day.mp4

What runs for real: the family agent of config/agent.vostro.json with every plug-in and its own loop (the day engine,
the night feed and its rota, the house brain, the rhythm reminders, the morning message, the family push), plus the
glasses channel and the car seat coach. Muse Spark Open on Baseten is the brain, Baby Buddy gets the test child's
entries, Home Assistant is read through the tunnel, SAM 3.1 runs on this Mac for the car seat (one process, under
/tmp/pa-gpu.lock, stopped at the end). The display cards go through DAT's Display API in the app.

What is mocked, and why: the glasses and their lens (DAT MockDeviceKit and MockDisplayKit, no hardware here), the
camera picture (our synthetic car seat clip), Ceci's glasses (a second listener on the same endpoint with her own
token, no second simulator), the parents' words (typed by this script on the captured Telegram and on the glasses
endpoint, the same /say path the app uses), the clock (the e2e day's virtual clock jumps between moments of the day,
the glasses endpoint and the app keep real time). Telegram is a capture (parenting_agent/e2e/harness.py), house writes
are refused before they leave the Mac. Nothing touches the Vostro's agent.
"""
import argparse
import datetime
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GLASSES_APP = ROOT / "apps" / "glasses" / "ParentingGlasses"
FEED_NAME = "hud-day-feed"
FEED_OUT = GLASSES_APP / "MockFeed" / f"{FEED_NAME}.mp4"
CLIP = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips/test/test-02-correct.mp4"
BUNDLE = "com.bygmv.parentingglasses"
GPU_LOCK = Path("/tmp/pa-gpu.lock")
PORT = 8766
DATA = ROOT / "data-glasses-day"
REAL_TIME = {"time": time.time, "monotonic": time.monotonic}
# The modules that keep real time while the agent's clock is virtual: the frames, the camera skill and its speaker, so
# their waits are real seconds. The glasses plug-in stamps its cards with time.time taken before the clock froze.
REAL_MODULES = ["parenting_agent.sources", "parenting_agent.carseat", "parenting_agent.speaker",
                "parenting_agent.hud_cards", "http.server", "socketserver", "cv2", "numpy"]


def build_feed(out=FEED_OUT):
    """The car seat clip forwards then backwards, four times, so the loop has no cut: 30 fps HEVC, 1280 x 704."""
    fit = "scale=1280:704:force_original_aspect_ratio=decrease,pad=1280:704:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    graph = (f"[0:v]{fit},split=2[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0,split=4[x0][x1][x2][x3];"
             "[x0][x1][x2][x3]concat=n=4:v=1:a=0[v]")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(CLIP), "-filter_complex", graph, "-map", "[v]", "-c:v", "libx265",
                    "-tag:v", "hvc1", "-preset", "medium", "-crf", "26", "-x265-params", "log-level=error", "-pix_fmt", "yuv420p",
                    "-an", str(out)], check=True)
    return out


def at(day0, hhmm):
    from parenting_agent.e2e.harness import TZ
    h, m = map(int, hhmm.split(":"))
    return datetime.datetime.combine(day0, datetime.time(h, m), TZ)


# The day: (scene, the agent's time, what happens, what each parent's glasses should get)
# "tg" is a Telegram message from that parent, "glasses" words on Gonza's glasses, "until" moves the clock until the
# cards come or the time limit, "stop_coach" ends the car seat coach after its first camera steps.
def scenes(day0):
    return [
        {"name": "Early feed", "at": at(day0, "06:00"), "do": [("tg", "gonza", "Le di 80 ml de mamadera.")],
         "cards": {}, "note": "The feed the rhythm reminder will count from. No card: Gonza wrote it himself."},
        {"name": "Morning message", "at": at(day0, "07:20"), "until": at(day0, "08:10"), "do": [],
         "cards": {"gonza": ["morning"], "ceci": ["morning"]},
         "note": "The day engine's brief, the house brain's night and the prep lines, one message per parent."},
        {"name": "Next feed reminder", "at": None, "until": at(day0, "10:30"), "do": [],
         "cards": {"gonza": ["next_feed"], "ceci": ["next_feed"]},
         "note": "The rhythm plug-in, 20 minutes before the feed it predicts, to both parents by day."},
        {"name": "Nap mode on", "at": None, "until_min": 15,
         "do": [("tg", "ceci", "Le di 90 ml de mamadera."), ("tg", "ceci", "Se durmió.")],
         "cards": {"gonza": ["nap"], "ceci": ["nap"]},
         "note": "Ceci logs the feed and the nap on Telegram, the day engine turns nap mode on (house writes dry)."},
        {"name": "Nap mode off", "at": None, "advance_min": 75, "until_min": 15, "do": [("tg", "ceci", "Se despertó.")],
         "cards": {"gonza": ["nap"], "ceci": ["nap"]}, "note": "He woke up: nap mode off."},
        {"name": "Voice question", "at": None, "advance_min": 5, "do": [("glasses", "gonza", "¿Cuándo comió por última vez?")],
         "cards": {"gonza": ["answer"], "ceci": []}, "note": "Asked on Gonza's glasses, answered on his glasses only."},
        {"name": "Who is on duty tonight", "at": None, "advance_min": 3,
         "do": [("tg", "gonza", "¿Quién está de turno esta noche?")], "cards": {"gonza": ["on_duty"], "ceci": []},
         "note": "Asked on Telegram, the night rota answers, the card reaches the glasses of the parent who asked."},
        {"name": "Shopping list", "at": None, "advance_min": 3,
         "do": [("tg", "ceci", "Quedan pocos pañales, agregalos a la lista de compras.")],
         "cards": {"gonza": [], "ceci": ["shopping"]}, "note": "Ceci asks, Ceci's glasses get it (the list write is dry)."},
        {"name": "Car seat coach", "at": None, "advance_min": 5,
         "do": [("glasses", "gonza", "Ayudame a instalar la silla del auto."), ("wait_card", "gonza", "car_seat", 90),
                ("glasses", "gonza", "Sí."), ("wait_steps", "gonza", 5, 150),
                ("stop_coach",)],
         "cards": {"gonza": ["car_seat"], "ceci": []},
         "note": "Muse starts the coach, step 1 is asked, Gonza answers on the glasses, SAM 3.1 checks the next steps."},
        {"name": "Red flag", "at": None, "advance_min": 10, "do": [("tg", "gonza", "Test: está azul y no respira bien.")],
         "cards": {"gonza": ["red_flag"], "ceci": []}, "hold_s": 40,
         "note": "The safety gate's fixed 911 line, no brain call. The card stays above everything and never dims."},
        {"name": "Red flag acknowledged", "at": None, "advance_min": 1, "do": [("glasses", "gonza", "Listo, ya llamé al 911.")],
         "cards": {}, "note": "Gonza says it on the glasses: the red flag card goes."},
    ]


class Listener:
    """A wearer's event stream, read like the app reads it. For Ceci it stands in for her glasses."""

    def __init__(self, url, token):
        self.url, self.token, self.seen = url, token, []
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        request = urllib.request.Request(self.url + "events", headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=3600) as response:
                for raw in response:
                    line = raw.decode().strip()
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        event["received_unix"] = round(REAL_TIME["time"](), 3)
                        self.seen.append(event)
        except OSError:
            pass


def post_say(url, token, text):
    body = json.dumps({"text": text}).encode()
    request = urllib.request.Request(url + "say", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status


def rows(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


class Day:
    def __init__(self, args):
        self.args = args
        self.day0 = datetime.date.fromisoformat(args.day)
        self.out = Path(args.out_dir)
        self.turns = 0
        self.log = []

    def config(self, child):
        config = json.loads((ROOT / "config/agent.vostro.json").read_text())
        config["data_dir"] = str(DATA)
        config["env_file"] = "/nonexistent"
        config["baby"] = {"born": True, "name": "Theo"}  # the test child stands in for Theo, so the day's routines run
        config["baby_log"] = {**config["baby_log"], "child": child["slug"]}
        config["rhythm"] = {**config.get("rhythm", {}), "child": child["first_name"]}
        config["house"] = {**config.get("house", {}), "live": False, "live_actions": [], "ha_url": "http://127.0.0.1:18123"}
        config["plugins"] = [p for p in config["plugins"] if not p.endswith("Heartbeat")] + [
            "parenting_agent.glasses:Glasses", "parenting_agent.carseat.plugin:CarSeatCoach"]
        config["glasses"] = {"port": PORT, "host": "127.0.0.1", "wearers": ["gonza", "ceci"]}
        config["car_seat"] = {"skill": "skills/car-seat.json", "source": "glasses", "channel": "glasses"}
        config["allowed_tools"] = config["allowed_tools"] + ["start_car_seat_coach", "answer_car_seat_check", "car_seat_outgrow"]
        return config

    def seed(self, bb, child):
        """Two night bottles before the day starts (00:30 and 03:30), tagged e2e so the next run removes them: the rhythm
        reminder needs a recent rhythm, and the test child's history ends days before (its last gap is over 24 h)."""
        out = []
        for hhmm in ("00:30", "03:30"):
            end = at(self.day0, hhmm)
            body = {"child": child["id"], "start": (end - datetime.timedelta(minutes=15)).isoformat(), "end": end.isoformat(),
                    "type": "formula", "method": "bottle", "amount": 90.0, "tags": ["e2e"]}
            out.append({"id": bb.call("POST", "/api/feedings/", body)["id"], "end": hhmm, "amount_ml": 90})
        return out

    def on_event(self, event):
        if event["kind"] == "turn":
            self.turns += 1

    def app_log(self):
        return rows(self.container / "Documents" / "hud-live.jsonl") if self.container else []

    def cards_of(self, person, since_unix):
        """Agent cards that reached a parent's glasses after a moment (real time): the display's accepted sends for
        Gonza (the app's log), the event stream for Ceci (no display, a listener)."""
        if person == "gonza":
            return [{"topic": r["agent_cause"], "title": r["title"], "status": r["status"], "detail": r.get("detail"),
                     "meta": r.get("meta"), "alert": r.get("alert"), "agent_unix": r["agent_unix"], "shown_unix": r["unix"]}
                    for r in self.app_log() if r["kind"] == "sent" and r.get("agent_unix") and r["unix"] >= since_unix]
        return [{**e["card"], "agent_unix": e.get("agent_unix"), "shown_unix": e["received_unix"]}
                for e in self.ceci.seen if e["kind"] == "card" and e["received_unix"] >= since_unix]

    def topics(self, person, since_unix):
        return [c["topic"] for c in self.cards_of(person, since_unix)]

    def got(self, scene, since_unix):
        return all(all(t in self.topics(p, since_unix) for t in want) for p, want in scene["cards"].items())

    def wait_turns(self, before, timeout=300):
        end = REAL_TIME["monotonic"]() + timeout
        while self.turns < before and REAL_TIME["monotonic"]() < end:
            time.sleep(0.05)

    def step(self, minutes=1):
        for _ in range(minutes):
            self.clock.advance(60)
            self.transport.new_step()
            self.clock.quiet()

    def caption(self, scene):
        hhmm = self.clock.now().strftime("%H:%M")
        self.hub.push({"kind": "caption", "name": f"{hhmm} · {scene['name']}", "source": scene["note"]}, "gonza")

    def act(self, action):
        what = action[0]
        if what == "tg":
            _, person, text = action
            before = self.turns + 1
            self.messenger.incoming(person, text)
            self.channel.poll_once(timeout=0)
            self.wait_turns(before)
        elif what == "glasses":
            _, person, text = action
            before = self.turns + 1
            post_say(self.hub.url, self.tokens[person], text)
            self.wait_turns(before)
        elif what == "wait_card":
            _, person, topic, timeout = action
            end = REAL_TIME["monotonic"]() + timeout
            while REAL_TIME["monotonic"]() < end and topic not in self.topics(person, self.scene_unix):
                time.sleep(0.25)
        elif what == "wait_steps":
            _, person, steps, timeout = action
            end = REAL_TIME["monotonic"]() + timeout
            while REAL_TIME["monotonic"]() < end:
                cards = [e for e in self.agent.bus.history if e["kind"] == "glasses_card" and e["topic"] == "car_seat"]
                if len({e["cause"] for e in cards}) >= steps:
                    break
                time.sleep(0.25)
            time.sleep(3)
        elif what == "stop_coach":
            coach = next(p for p in self.agent.plugins if getattr(p, "name", "") == "car-seat")
            if coach.coach is not None:
                coach.coach.stop()
        return {"at": self.clock.now().isoformat(timespec="seconds"), "unix": round(REAL_TIME["time"](), 3),
                "action": list(action)}

    def run_scene(self, scene):
        if scene.get("at") is not None:
            while self.clock.now() < scene["at"]:
                self.step()
        elif scene.get("advance_min"):
            self.step(scene["advance_min"])
        self.scene_unix = REAL_TIME["time"]()
        self.caption(scene)
        done = [self.act(action) for action in scene["do"]]
        limit = scene.get("until") or (self.clock.now() + datetime.timedelta(minutes=scene.get("until_min", 0)))
        end = REAL_TIME["monotonic"]() + 120
        while not self.got(scene, self.scene_unix) and REAL_TIME["monotonic"]() < end:
            if self.clock.now() < limit:
                self.step()
            else:
                time.sleep(0.25)
        time.sleep(scene.get("hold_s", 7))  # a glance on the video
        result = {"scene": scene["name"], "agent_time": self.clock.now().isoformat(timespec="minutes"), "note": scene["note"],
                  "actions": done, "expected": scene["cards"],
                  "cards": {p: self.cards_of(p, self.scene_unix) for p in ("gonza", "ceci")}}
        result["topics"] = {p: self.topics(p, self.scene_unix) for p in ("gonza", "ceci")}
        result["passed"] = self.got(scene, self.scene_unix) and all(
            not self.topics(p, self.scene_unix) or want or p == "gonza" and scene["name"] == "Red flag acknowledged"
            for p, want in scene["cards"].items())
        print(json.dumps({k: result[k] for k in ("scene", "agent_time", "topics", "passed")}, ensure_ascii=False), flush=True)
        return result

    def execute(self):
        import freezegun
        freezegun.configure(extend_ignore_list=REAL_MODULES)
        import parenting_agent.glasses  # noqa: F401 imported before the clock freezes: real time in the endpoint
        import parenting_agent.carseat.coach  # noqa: F401
        from parenting_agent.agent import build
        from parenting_agent.channels import telegram as telegram_mod
        from parenting_agent.e2e import clock as clock_mod
        from parenting_agent.e2e import harness
        from parenting_agent.voice import client as voice_client

        harness.load_env()
        self.tokens = {p: secrets.token_urlsafe(12) for p in ("gonza", "ceci")}
        for person, token in self.tokens.items():
            os.environ[f"PARENTING_AGENT_GLASSES_TOKEN_{person.upper()}"] = token
        DATA.mkdir(exist_ok=True)
        for stale in DATA.iterdir():
            if stale.is_file():
                stale.unlink()
        bb = harness.BabyBuddy(os.environ["BABYBUDDY_URL"], os.environ["BABYBUDDY_TOKEN"])
        child = bb.child(harness.SHARED_CHILD)
        baseline = json.loads(harness.BASELINE.read_text())
        start = at(self.day0, "06:00") - datetime.timedelta(minutes=5)
        end = at(self.day0, "16:00")
        removed = bb.cleanup(child["id"], at(self.day0, "00:00"), end, baseline)
        seeded = self.seed(bb, child)
        config = self.config(child)

        self.transport = harness.Transport(os.environ["BABYBUDDY_URL"])
        self.transport.install()
        self.clock = clock_mod.VirtualClock(start, harness.TZ)
        self.messenger = harness.CaptureMessenger(self.clock)
        telegram_mod.TelegramMessenger = lambda token, api=None: self.messenger
        voice_client.RemoteVoice = harness.LocalEarVoice
        self.container = None
        self.agent = agent = build(config)
        agent.bus.subscribe(self.on_event)
        self.channel = next(p for p in agent.plugins if p.name == "telegram")
        self.channel.run = lambda: None
        glasses = next(p for p in agent.plugins if p.name == "glasses")
        self.hub = glasses.hub
        loops = []
        for plugin in agent.plugins:
            if plugin.name in ("telegram", "glasses", "car-seat") or not hasattr(plugin, "stopped"):
                continue
            plugin.stopped = self.clock.event(plugin.name)
            loops.append(plugin.name)
        agent.start()
        for plugin in agent.plugins:
            plugin.start()
        agent.bus.publish("agent_started", brain=agent.brain.name, destination=agent.brain.destination, run="glasses-day")
        self.clock.quiet()
        self.ceci = Listener(self.hub.url, self.tokens["ceci"])
        recorder, video_start = None, {}
        raw = Path(os.path.expanduser(self.args.video)).with_name(Path(self.args.video).stem + "-raw.mp4") if self.args.video else None
        results = []
        try:
            udid = self.args.udid
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
                            video_start["unix"] = REAL_TIME["time"]()
                threading.Thread(target=started, daemon=True).start()
                time.sleep(1.5)
            subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", udid, BUNDLE,
                            "-agentURL", f"http://127.0.0.1:{PORT}", "-agentToken", self.tokens["gonza"], "-hudDay", "YES",
                            "-hudLog", "YES", "-mockFeed", FEED_NAME, "-sendFPS", "5"], check=True, capture_output=True)
            deadline = REAL_TIME["monotonic"]() + 90
            while not any(r["kind"] == "feed_start" for r in self.app_log()):
                if REAL_TIME["monotonic"]() > deadline:
                    raise SystemExit("the app never got a camera frame")
                time.sleep(0.5)
            time.sleep(2)
            for scene in scenes(self.day0):
                results.append(self.run_scene(scene))
        finally:
            if recorder:
                recorder.send_signal(signal.SIGINT)
                recorder.wait(timeout=60)
            for plugin in agent.plugins:
                plugin.stop()
            coach = next((p for p in agent.plugins if getattr(p, "name", "") == "car-seat"), None)
            vision = getattr(getattr(coach, "coach", None), "vision", None)
            if vision is not None and getattr(vision, "process", None) is not None:
                vision.process.kill()  # the one SAM 3.1 process, stopped
            agent.stop()
            agent.close()
            self.clock.stop()
            self.transport.uninstall()
        events = rows(DATA / "events.jsonl")
        brains = [e for e in events if e["kind"] == "brain_call"]
        run = {"date": time.strftime("%Y-%m-%d %H:%M %z"), "day": self.args.day, "child": child["slug"],
               "removed_before_run": removed, "seeded": seeded, "loops": loops, "scenes": results,
               "passed": sum(r["passed"] for r in results), "of": len(results),
               "glasses_cards": [e for e in events if e["kind"] == "glasses_card"],
               "telegram_captured": self.messenger.sent, "chats": harness.CHATS,
               "refused": self.transport.refused, "brain_usd": round(self.transport.usd, 4),
               "brain_calls": dict(self.transport.calls),
               "brain_models": sorted({f"{b.get('model')} on {b.get('destination')}" for b in brains}),
               "house": [e for e in events if e["kind"].startswith("house")][:60],
               "sam3": [e for e in events if e["kind"] in ("carseat_frame", "carseat_check")][:80],
               "app_log": self.app_log(), "ceci_events": [e for e in self.ceci.seen if e["kind"] != "hello"]}
        if raw and raw.exists() and video_start:
            video = Path(os.path.expanduser(self.args.video))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-c:v", "libx264", "-crf", "26", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(video)], check=True)
            run["video"] = {"file": str(video), "bytes": video.stat().st_size, "start_unix": video_start["unix"]}
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f"{self.args.name}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str) + "\n")
        print(json.dumps({"passed": run["passed"], "of": run["of"], "brain_usd": run["brain_usd"]}))
        return run


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--build-feed", action="store_true")
    parser.add_argument("--udid")
    parser.add_argument("--day", default="2026-10-30", help="the day, in the past: Baby Buddy refuses future times")
    parser.add_argument("--out-dir", default="results/glasses-day")
    parser.add_argument("--name", default="run")
    parser.add_argument("--video")
    args = parser.parse_args()
    if args.build_feed:
        print(build_feed())
        return
    if not args.udid:
        parser.error("--udid is needed for a run")
    try:
        GPU_LOCK.mkdir()
    except FileExistsError:
        raise SystemExit("the GPU lock is taken, try again later")
    try:
        Day(args).execute()
    finally:
        GPU_LOCK.rmdir()


if __name__ == "__main__":
    main()
