"""Helpers the glasses tests share."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import cv2
import numpy as np


def jpeg(shape=(360, 640, 3)):
    ok, data = cv2.imencode(".jpg", np.zeros(shape, np.uint8))
    return data.tobytes()


def call(hub, path, body=None, token=None, kind="image/jpeg"):
    headers = {"Content-Type": kind}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(hub.url + path, data=body, method="POST" if body is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class Events:
    """Reads the app's event stream in a thread, like the iPhone app does."""

    def __init__(self, hub):
        request = urllib.request.Request(hub.url + "events", headers={"Authorization": f"Bearer {hub.token}"})
        self.response = urllib.request.urlopen(request, timeout=10)
        self.seen = []
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            for raw in self.response:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    self.seen.append(json.loads(line[6:]))
        except (OSError, ValueError):
            pass

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(predicate(e) for e in self.seen):
                return True
            time.sleep(0.02)
        return False
