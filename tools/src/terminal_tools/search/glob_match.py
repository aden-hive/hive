"""Match relative file paths after ripgrep has applied ignore rules."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from functools import cache


def path_matcher(pattern: str) -> Callable[[str], bool]:
    """Support shell globs, ** path segments and bounded brace alternatives."""
    patterns = [pattern]
    expanded = []
    while patterns:
        current = patterns.pop()
        brace = re.search(r"\{([^{}]*)\}", current)
        if brace:
            patterns.extend(current[: brace.start()] + part + current[brace.end() :] for part in brace.group(1).split(","))
            if len(patterns) + len(expanded) > 256:
                raise ValueError("glob has more than 256 brace alternatives")
        elif "{" in current or "}" in current:
            raise ValueError("glob has unbalanced braces")
        else:
            expanded.append(tuple(current.removeprefix("./").split("/")))

    def matches(path: str) -> bool:
        parts = tuple(path.split("/"))
        for pattern_parts in expanded:

            @cache
            def match_at(pattern_index: int, path_index: int, pattern_parts: tuple[str, ...] = pattern_parts) -> bool:
                if pattern_index == len(pattern_parts):
                    return path_index == len(parts)
                segment = pattern_parts[pattern_index]
                if segment == "**":
                    # ** spans zero or more whole path components.
                    return match_at(pattern_index + 1, path_index) or (path_index < len(parts) and match_at(pattern_index, path_index + 1))
                return path_index < len(parts) and fnmatch.fnmatchcase(parts[path_index], segment) and match_at(pattern_index + 1, path_index + 1)

            if match_at(0, 0):
                return True
        return False

    return matches
