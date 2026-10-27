"""Import-only stand-in for triton, which has no CPU or arm64 wheel.

SAM 3 imports triton at module level for GPU kernels (EDT, NMS, connected components) that the
image path on CPU never calls. Calling any of them here raises, so a silent wrong result is impossible.
"""


def _unavailable(*args, **kwargs):
    raise RuntimeError("triton kernels are not available on CPU")


def jit(fn=None, **kwargs):
    return _unavailable if fn is not None else (lambda f: _unavailable)


def autotune(*args, **kwargs):
    return lambda fn: _unavailable


def heuristics(*args, **kwargs):
    return lambda fn: _unavailable


class Config:
    def __init__(self, *args, **kwargs):
        pass


def cdiv(a, b):
    return -(-a // b)
