"""triton's kernel signatures name types from here, so any name resolves to the same empty type."""


class _AnyType:
    pass


def __getattr__(_name):
    return _AnyType
