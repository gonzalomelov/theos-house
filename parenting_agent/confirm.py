"""Confirm detector: a slower, smarter look that confirms or cancels what the reflex raised.

Providers, chosen by skill config confirm.provider:
- none: no confirmation, the voice hold alone decides.
- sam3_local: Meta's SAM 3.1 from its open weights on this machine (Apple GPU through MPS). Private by
  design: the frame never leaves the house. The model code is loaded lazily through confirm.sam3_module,
  a module exposing build(config) that returns an object with judge(frame_bgr) -> on|off|unsure.
- sam3_hosted: SAM 3.1 through the Meta Model API. Off by default because frames leave the house.

A provider that cannot start (missing weights, no key) raises Unavailable at start, never mid-routine.
"""
import importlib
from concurrent.futures import ThreadPoolExecutor


class Unavailable(Exception):
    pass


class NoConfirm:
    name = "none"

    def judge(self, frame_bgr):
        return "unsure"


class ModuleConfirm:
    """Wraps a confirm implementation that lives in its own module (SAM 3.1 local or hosted)."""

    def __init__(self, name, module, config):
        try:
            impl = importlib.import_module(module)
        except ImportError as error:
            raise Unavailable(f"{name}: cannot import {module}: {error}") from error
        self.name, self.impl = name, impl.build(config)

    def judge(self, frame_bgr):
        return self.impl.judge(frame_bgr)

    def close(self):
        getattr(self.impl, "close", lambda: None)()


def build(config):
    provider = config.get("provider", "none")
    if provider == "none":
        return NoConfirm()
    if provider in ("sam3_local", "sam3_hosted"):
        module = config.get("module")
        if not module:
            raise Unavailable(f"{provider}: confirm.module is not set")
        return ModuleConfirm(provider, module, config)
    raise Unavailable(f"unknown confirm provider {provider}")


class ConfirmStage:
    """Runs one confirm request at a time on a background thread, so the reflex never waits."""

    def __init__(self, detector, bus, alarm):
        self.detector, self.bus, self.alarm = detector, bus, alarm
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None

    def request(self, episode, frame_bgr, stream_s):
        if isinstance(self.detector, NoConfirm) or self.pending:
            return
        self.bus.publish("confirm_request", episode=episode, stream_s=stream_s, provider=self.detector.name)
        self.pending = (episode, stream_s, self.pool.submit(self.detector.judge, frame_bgr))

    def collect(self):
        if not self.pending or not self.pending[2].done():
            return
        episode, stream_s, future = self.pending
        self.pending = None
        try:
            verdict = future.result()
        except Exception as error:  # a failed confirm never silences the alarm
            self.bus.publish("confirm_error", episode=episode, error=str(error)[:200])
            return
        self.bus.publish("confirm", episode=episode, stream_s=stream_s, verdict=verdict)
        self.alarm.on_confirm(episode, verdict, stream_s)

    def close(self):
        self.pool.shutdown(wait=True)
        self.collect()
        getattr(self.detector, "close", lambda: None)()
