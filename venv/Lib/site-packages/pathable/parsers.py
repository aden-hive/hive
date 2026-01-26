"""Pathable parsers module"""
from typing import Any
from typing import Hashable
from typing import List
from typing import Union

from pathable.types import PartType

SEPARATOR = "/"


def parse_parts(parts: List[PartType], sep: str = SEPARATOR) -> List[Hashable]:
    """Parse (filter and split) path parts."""
    parsed: List[Hashable] = []
    it = reversed(parts)
    for part in it:
        if isinstance(part, int):
            parsed.append(part)
            continue
        if not part:
            continue
        if sep in part:
            for x in reversed(part.split(sep)):
                if x and x != ".":
                    parsed.append(x)
        else:
            if part and part != ".":
                parsed.append(part)
    parsed.reverse()
    return parsed


def parse_args(args: List[Any], sep: str = SEPARATOR) -> List[Hashable]:
    """Canonicalize path constructor arguments."""
    parts: List[PartType] = []
    for a in args:
        if hasattr(a, "parts"):
            parts += a.parts
        else:
            if isinstance(a, bytes):
                a = a.decode("ascii")
            if isinstance(a, str):
                parts.append(a)
            elif isinstance(a, int):
                parts.append(a)
            else:
                raise TypeError(
                    "argument should be a text object or a Path "
                    "object returning text, binary not %r" % type(a)
                )
    return parse_parts(parts, sep)
