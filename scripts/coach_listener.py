"""The Mac's side of the car seat coach. The core asks for it with start_car_seat_coach, and the coach runs here, where SAM 3.1
and the camera are. Follows the core's stream, starts the coach for the parent who asked, sends each line back with POST /coach,
and hands that parent's yes, no and listo to the coach. Frames stay on this Mac.

    python scripts/coach_listener.py --core http://127.0.0.1:8780 --source clip.mp4     a local core, a recording as the camera
    python scripts/coach_listener.py --ssh vostro --source phone                         the core on the Vostro, nothing published

--ssh goes through docker exec on the Vostro, so the core keeps no published port. --quiet doesn't speak on this Mac.
"""
import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parenting_agent.bus import Bus  # noqa: E402
from parenting_agent.carseat.coach import Coach, _yes_no, is_ready, load_profiles  # noqa: E402

INSIDE = "http://127.0.0.1:8780"
FOLLOW = ("import sys,urllib.request as u\nfor line in u.build_opener(u.ProxyHandler({})).open(sys.argv[1]):\n"
          "    sys.stdout.write(line.decode());sys.stdout.flush()\n")
SEND = ("import sys,urllib.request as u\nr=u.Request(sys.argv[1],data=sys.stdin.buffer.read(),headers={'Content-Type':'application/json'})\n"
        "print(u.build_opener(u.ProxyHandler({})).open(r,timeout=30).status)\n")


class Direct:
    def __init__(self, url):
        self.url = url

    def follow(self):
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.url + "/stream")

    def post(self, path, body):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30).read()


class OverSsh:
    def __init__(self, host, container="parenting-core"):
        self.base = ["ssh", host, "docker", "exec", "-i", container, "python", "-I", "-S", "-u", "-c"]

    def follow(self):
        return subprocess.Popen([*self.base, _quoted(FOLLOW), INSIDE + "/stream"], stdout=subprocess.PIPE).stdout

    def post(self, path, body):
        subprocess.run([*self.base, _quoted(SEND), INSIDE + path], input=json.dumps(body).encode(), check=True, capture_output=True, timeout=40)


def _quoted(code):
    return "'" + code.replace("'", "'\\''") + "'"


def events(lines):
    for raw in lines:
        line = raw.decode() if isinstance(raw, bytes) else raw
        if line.startswith("data:"):
            try:
                yield json.loads(line[5:].strip())
            except ValueError:
                continue


class Listener:
    def __init__(self, link, source, skill="skills/car-seat.json", speak=False, make_vision=None, make_source=None, report=None):
        self.link, self.source_name, self.speak, self.report = link, source, speak, report
        self.cfg = json.loads((ROOT / skill).read_text())
        self.seat, self.car = load_profiles(self.cfg, str(ROOT))
        self.make_vision, self.make_source = make_vision or self.sam, make_source or self.open_source
        self.coach, self.thread, self.parent = None, None, None
        self.lines, self.results = [], None

    def sam(self):
        from parenting_agent.carseat.sam3_masks import Sam3Masks
        return Sam3Masks(self.cfg.get("sam3"))

    def open_source(self):
        from parenting_agent.sources import open_source
        return open_source(self.source_name)

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, parent, lang):
        if self.running():
            return
        bus = Bus()
        self.parent = parent
        vision, source = self.make_vision(), self.make_source()
        if self.speak:
            from parenting_agent.speaker import Speaker
            bus.subscribe(Speaker(source, lang=lang).on_event, ["voice"])
        bus.subscribe(self.line, ["voice"])
        self.coach = Coach(self.cfg, bus, vision, source, self.seat, self.car, lang=lang)

        def run():
            try:
                self.results = self.coach.run()
            finally:
                source.close()
                vision.close()
                if self.report:
                    Path(self.report).write_text(json.dumps({"parent": parent, "lang": lang, "lines": self.lines, "results": self.results}, ensure_ascii=False, indent=1, default=str))
        self.thread = threading.Thread(target=run, name="car-seat", daemon=True)
        self.thread.start()

    def line(self, event):
        self.lines.append({"text": event.get("text"), "step": event.get("step") or event.get("check")})
        self.link.post("/coach", {"parent": self.parent, "text": event.get("text"), "step": self.lines[-1]["step"]})

    def hear(self, text):
        """A parent's message while the coach runs: a listo for the step they are doing, or a yes or no to its question."""
        coach = self.coach
        if coach.waiting is not None and is_ready(text):
            coach.ready(coach.waiting)
        elif coach.asking is not None and coach.asking not in coach.answers and _yes_no(text) is not None:
            coach.answer(coach.asking, text)

    def handle(self, item):
        kind = item.get("kind")
        if kind == "tool_result" and item.get("tool") == "start_car_seat_coach" and not str(item.get("result", "")).startswith("Refused"):
            arguments = item.get("arguments") or {}
            self.start(arguments.get("parent"), arguments.get("lang") or "es")
        elif kind == "event" and item.get("type") == "message" and self.running() and (item.get("payload") or {}).get("from") == self.parent:
            self.hear(str((item.get("payload") or {}).get("text", "")))

    def follow(self, once=False):
        while True:
            try:
                for item in events(self.link.follow()):
                    self.handle(item)
                    if once and self.results is not None:
                        return
                    if once and self.thread is not None and not self.thread.is_alive():
                        return
            except OSError as failure:
                print("stream lost:", failure, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", default=INSIDE)
    parser.add_argument("--ssh")
    parser.add_argument("--source", default="phone")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--report")
    parser.add_argument("--once", action="store_true", help="stop when one coaching run has ended")
    args = parser.parse_args()
    Listener(OverSsh(args.ssh) if args.ssh else Direct(args.core), args.source, speak=not args.quiet, report=args.report).follow(once=args.once)
