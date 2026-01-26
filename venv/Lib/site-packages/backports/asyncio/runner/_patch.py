from contextlib import contextmanager
from typing import Any, TypeVar, Iterator

_T = TypeVar("_T")


@contextmanager
def _patch_object(target: Any, attribute: str, new: _T) -> Iterator[None]:
    """A basic version of unittest.mock patch.object."""
    # https://github.com/python/cpython/blob/3.8/Lib/unittest/mock.py#L1358
    temp_original = getattr(target, attribute)
    # https://github.com/python/cpython/blob/3.8/Lib/unittest/mock.py#L1490
    setattr(target, attribute, new)
    try:
        yield
    finally:
        # https://github.com/python/cpython/blob/3.8/Lib/unittest/mock.py#L1509
        setattr(target, attribute, temp_original)
