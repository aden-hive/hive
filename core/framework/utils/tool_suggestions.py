"""Helpers for producing actionable errors when an agent calls an unknown tool.

When an LLM hallucinates or misspells a tool name, returning a bare
``Unknown tool`` error usually makes the model repeat the same bad call and
waste a turn.  These helpers suggest the closest registered names so the
model can self-correct on the next turn.  Both the main tool registry and the
reflection agent reuse :func:`format_unknown_tool_error`, so suggestion
behaviour stays consistent across call sites.
"""

from __future__ import annotations

from collections.abc import Iterable
from difflib import get_close_matches

_SUGGESTION_COUNT = 2
_SUGGESTION_CUTOFF = 0.5


def format_unknown_tool_error(name: str, known_tool_names: Iterable[str]) -> str:
    """Build an "Unknown tool" error message, appending close matches when found.

    When no registered tool name is close enough to ``name``, the message has
    no "Did you mean" suffix, preserving the behaviour of existing callers.
    """
    message = f"Unknown tool: {name}"
    matches = get_close_matches(
        str(name),
        list(known_tool_names),
        n=_SUGGESTION_COUNT,
        cutoff=_SUGGESTION_CUTOFF,
    )
    if matches:
        message += f" Did you mean: {', '.join(matches)}?"
    return message
