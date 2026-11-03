"""The Mac's eye for the persistent agent. Frames from the Tapo camera go through SAM 3.1 here, on this Mac's GPU, and only the
verdict reaches the core on the Vostro, as a camera event. A frame stays in memory on this Mac and is never written or sent.

    TAPO_* in the environment; python scripts/eye_listener.py --ssh vostro            the real camera, the real core
    python scripts/eye_listener.py --dry-run --minutes 5                              the real camera, prints what it would send
    python scripts/eye_listener.py --dry-run --image photo.jpg                        one image through the Tapo-sized path

The rule is parenting_agent/dog_watch.py with its settings unchanged: only a dog close to the baby sends an event. --ssh goes
through docker exec on the Vostro, so the core keeps no published port.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parenting_agent import dog_watch, hearing  # noqa: E402
from parenting_agent.bus import Bus  # noqa: E402

INSIDE = "http://127.0.0.1:8780/events"
SEND = ("import sys,urllib.request as u\nr=u.Request(sys.argv[1],data=sys.stdin.buffer.read(),headers={'Content-Type':'application/json'})\n"
        "print(u.build_opener(u.ProxyHandler({})).open(r,timeout=30).status)\n")


def over_ssh(host, container="parenting-core"):
    quoted = "'" + SEND.replace("'", "'\\''") + "'"

    def post(event):
        subprocess.run(["ssh", host, "docker", "exec", "-i", container, "python", "-I", "-S", "-u", "-c", quoted, INSIDE],
                       input=json.dumps(event).encode(), check=True, capture_output=True, timeout=60)
    return post


def camera_frame(url, timeout=20):
    """One frame from the camera's RTSP stream, decoded in memory. The address has the password, so errors never carry it."""
    import cv2
    import numpy as np
    done = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url, "-an", "-frames:v", "1",
                           "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=timeout)
    frame = cv2.imdecode(np.frombuffer(done.stdout, np.uint8), cv2.IMREAD_COLOR) if done.stdout else None
    if frame is None:
        raise ValueError(f"no frame from the camera, ffmpeg exit {done.returncode}")
    return frame


class ToCore:
    """Stands where the watch's alert goes. A close dog becomes one camera event, with the verdict only and no pixels."""

    def __init__(self, post, room="living room"):
        self.post, self.room = post, room

    def __call__(self, measured):
        event = {"type": "camera", "source": "eye", "payload": {"saw": "a dog close to the baby", "room": self.room,
                                                               "touching": bool(measured.get("touching"))}}
        self.post(event)
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh", default="vostro")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--room", default="living room")
    parser.add_argument("--every", type=float, default=dog_watch.DEFAULTS["snapshot_every_s"])
    parser.add_argument("--minutes", type=float, help="stop after this long")
    args = parser.parse_args()
    from parenting_agent.carseat.sam3_masks import Sam3Masks

    def show(event):
        print(time.strftime("%H:%M:%S"), json.dumps(event), flush=True)
    post = show if args.dry_run else over_ssh(args.ssh)
    bus = Bus()
    bus.subscribe(lambda e: show({k: e.get(k) for k in ("verdict", "alerted", "sam_s", "dog_score", "baby_score", "ratio")}), ["dog_watch"])
    cfg = {**dog_watch.DEFAULTS, "room": args.room}
    watch = dog_watch.Watch(cfg, bus, Sam3Masks(cfg["sam3"]), ToCore(post, args.room))
    if args.image:
        import cv2
        watch.look(cv2.imread(args.image), why="image")
        return
    url = hearing.camera_url()
    ends = time.monotonic() + args.minutes * 60 if args.minutes else None
    while ends is None or time.monotonic() < ends:
        try:
            watch.look(camera_frame(url))
        except (ValueError, subprocess.TimeoutExpired) as error:
            show({"camera": type(error).__name__})
        time.sleep(args.every)


if __name__ == "__main__":
    main()
