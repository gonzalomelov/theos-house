"""The Mac's ear for the persistent agent. The camera's microphone goes through Perception Encoder Audio here, on this Mac's GPU, and
only the label reaches the core on the Vostro, as a sound event. The audio stays in memory on this Mac, as parenting_agent/hearing.py
says, and nothing writes it to disk.

    TAPO_* in the environment, TAPO_PORT for a relay (554 without it)
    python scripts/ear_listener.py --ssh vostro                                            the real microphone, the real core
    python scripts/ear_listener.py --dry-run                                               the real microphone, prints what it would send
    python scripts/ear_listener.py --dry-run --file clip.wav                               a recording, through the Tapo channel

--ssh goes through docker exec on the Vostro, so the core keeps no published port. Run it with .venv-hearing/bin/python.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent import hearing  # noqa: E402

INSIDE = "http://127.0.0.1:8780/events"
SEND = ("import sys,urllib.request as u\nr=u.Request(sys.argv[1],data=sys.stdin.buffer.read(),headers={'Content-Type':'application/json'})\n"
        "print(u.build_opener(u.ProxyHandler({})).open(r,timeout=30).status)\n")
KIND = {"cry": "a baby crying", "dog": "a dog barking", "doorbell": "the doorbell"}


def over_ssh(host, container="parenting-core"):
    quoted = "'" + SEND.replace("'", "'\\''") + "'"
    def post(event):
        subprocess.run(["ssh", host, "docker", "exec", "-i", container, "python", "-I", "-S", "-u", "-c", quoted, INSIDE],
                       input=json.dumps(event).encode(), check=True, capture_output=True, timeout=60)
    return post


class ToCore:
    """Stands where the Ear's bus goes. Sound events become one core event per label per cooldown, carrying no audio and no numbers about it."""

    def __init__(self, post, room="living room", labels=("cry",), cooldown_s=120, clock=time.monotonic):
        self.post, self.room, self.labels, self.cooldown_s, self.clock = post, room, set(labels), cooldown_s, clock
        self.last = {}

    def publish(self, topic, **fields):
        label = fields.get("label")
        if topic != "sound" or label not in self.labels:
            return None
        now = self.clock()
        if label in self.last and now - self.last[label] < self.cooldown_s:
            return None
        self.last[label] = now
        event = {"type": "sound", "source": "ear", "payload": {"kind": KIND[label], "room": self.room}}
        self.post(event)
        return event


def listener_config(device):
    return {"device": device, "cry_rule": hearing.CRY_RULE}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh", default="vostro")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file")
    parser.add_argument("--room", default="living room")
    parser.add_argument("--labels", default="cry")
    parser.add_argument("--cooldown", type=int, default=120)
    parser.add_argument("--report-after", type=int, default=8, help="a cry still going after this many seconds is reported")
    parser.add_argument("--minutes", type=float, help="stop after this long, and print what was heard")
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()
    def show(event):
        print(time.strftime("%H:%M:%S"), json.dumps(event), flush=True)
    real = None if args.dry_run else over_ssh(args.ssh)
    def post(event):
        show(event)
        if real:
            real(event)
    sink = ToCore(post, args.room, args.labels.split(","), args.cooldown)
    listener = hearing.default_listener(listener_config(args.device))
    settings = {"cry_report_s": args.report_after}
    if args.file:
        hearing.play(hearing.Ear(listener, sink, settings, args.room), hearing.from_file(args.file))
        return
    end = time.monotonic() + args.minutes * 60 if args.minutes else None
    if end is not None:  # a stalled camera never yields a chunk, so the check in the loop alone can't end a timed run
        signal.signal(signal.SIGALRM, lambda *_: os._exit(4))
        signal.alarm(int(args.minutes * 60) + 60)
    seconds, loud = 0, 0
    while end is None or time.monotonic() < end:
        try:
            ear = hearing.Ear(listener, sink, settings, args.room)
            for chunk in hearing.camera_seconds(hearing.camera_url()):
                ear.feed(chunk)
                seconds += 1
                loud += bool(hearing.dbfs(chunk) > -50)
                if end is not None and time.monotonic() >= end:
                    break
        except (ConnectionError, OSError, KeyError) as error:
            print("ear:", hearing.mask(str(error))[:300], file=sys.stderr, flush=True)
            time.sleep(10)
    print(json.dumps({"seconds": seconds, "seconds_with_sound": loud}), flush=True)


if __name__ == "__main__":
    main()
