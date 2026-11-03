"""Feeds frames from a source into a camera skill."""
import time


def watch(skill, source, minutes=None, frames_limit=None):
    """Feed the newest frames from source into the skill until time, frame count or the source runs out."""
    deadline = time.monotonic() + minutes * 60 if minutes else None
    seq = 0
    while True:
        if deadline and time.monotonic() >= deadline:
            break
        if frames_limit and skill.frames >= frames_limit:
            break
        got = source.latest(seq)
        if got is None:
            if source.stopped:
                break
            skill.confirm.collect()
            time.sleep(0.002)
            continue
        frame, seq, stream_s = got
        skill.on_frame(frame, stream_s)
