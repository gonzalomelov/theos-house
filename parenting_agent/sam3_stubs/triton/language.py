"""Names used in triton kernel signatures, so the modules that define them import on CPU."""


class constexpr:
    pass


def __getattr__(name):
    return constexpr
