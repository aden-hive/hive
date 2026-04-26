"""Pathable parsers module"""

from collections.abc import Hashable
from typing import Sequence

SEPARATOR = "/"


def parse_parts(
    parts: Sequence[Hashable | None], sep: str = SEPARATOR
) -> list[Hashable]:
    """Parse (filter and split) path parts."""
    parsed: list[Hashable] = []
    append = parsed.append

    for part in parts:
        if part is None:
            continue

        # Fast-path: int is common and never needs splitting/decoding.
        if isinstance(part, int):
            append(part)
            continue

        # Fast-path: str is most common.
        if isinstance(part, str):
            if not part or part == ".":
                continue
            if sep in part:
                for split_part in part.split(sep):
                    if split_part and split_part != ".":
                        append(split_part)
                continue
            append(part)
            continue

        # Fast-path: bytes, decode then treat as str.
        if isinstance(part, bytes):
            text = part.decode("ascii")
            if not text or text == ".":
                continue
            if sep in text:
                for split_part in text.split(sep):
                    if split_part and split_part != ".":
                        append(split_part)
                continue
            append(text)
            continue

        # Fallback: Hashable (covers e.g. tuple, custom keys).
        if isinstance(part, Hashable):
            append(part)
            continue

        raise TypeError(f"part must be Hashable or None; got {type(part)!r}")

    return parsed
