"""SAM 3 imports triton when it loads, and triton has no arm64 or CPU wheel. Its image path here never runs a triton kernel,
so this package only has to import. Every kernel built through it refuses to run, so nothing can silently compute a wrong result."""


def _refuse(*_, **__):
    raise RuntimeError("this is the import-only triton stand-in, it has no kernels")


def _decorator(*args, **_):
    if len(args) == 1 and callable(args[0]):  # @triton.jit
        return _refuse
    return lambda _kernel: _refuse  # @triton.jit(...), @triton.autotune(...), @triton.heuristics(...)


jit = autotune = heuristics = _decorator


class Config:
    """A tuning choice, only ever passed to autotune."""

    def __init__(self, *_, **__):
        pass


def cdiv(top, bottom):
    """Ceiling division."""
    whole, rest = divmod(top, bottom)
    return whole + bool(rest)
