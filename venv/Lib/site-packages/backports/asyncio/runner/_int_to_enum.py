"""Backported implementation of _int_to_enum from 3.11 compatible down to Python 3.8."""

import signal
from enum import IntEnum
from typing import TypeVar, Union, Type

_T = TypeVar("_T")
_E = TypeVar("_E", bound=IntEnum)

_orig_int_to_enum = signal._int_to_enum  # type: ignore[attr-defined]


# See https://github.com/python/cpython/blob/3.11/Lib/signal.py
def _patched_int_to_enum(value: Union[int, _T], enum_klass: Type[_E]) -> Union[_E, _T]:
    """Convert a possible numeric value to an IntEnum member.
    If it's not a known member, return the value itself.
    """
    if not isinstance(value, int):
        return value
    return _orig_int_to_enum(value, enum_klass)  # type: ignore[no-any-return]
