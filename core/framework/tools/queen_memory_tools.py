"""Tool for the queen to write to her episodic memory.

The queen can consciously record significant moments during a session — like
writing in a diary. Semantic memory (MEMORY.md) is updated automatically at
session end and is never written by the queen directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.runner.tool_registry import ToolRegistry


def write_to_diary(entry: str) -> str:
    """Write a prose entry to today's episodic memory.

    Use this when something significant just happened: a pipeline went live, the
    user shared an important preference, a goal was achieved or abandoned, or
    you want to record something that should be remembered across sessions.

    Write in first person, as you would in a private diary. Be specific — what
    happened, how the user responded, what it means going forward. One or two
    paragraphs is enough.

    You do not need to include a timestamp or date heading; those are added
    automatically.
    """
    from framework.agents.hive_coder.queen_memory import append_episodic_entry

    append_episodic_entry(entry)
    return "Diary entry recorded."


def register_queen_memory_tools(registry: ToolRegistry) -> None:
    """Register the episodic memory tool into the queen's tool registry."""
    registry.register_function(write_to_diary)
