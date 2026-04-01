"""Deprecated — queen memory tools replaced by reflection agent + recall selector.

The write_to_diary and recall_diary tools are no longer registered.
Memory is now handled automatically:
  - Save: reflection_agent.py extracts learnings after each turn
  - Recall: recall_selector.py picks relevant memories before each turn

This file is kept only for import compatibility during migration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.runner.tool_registry import ToolRegistry


def register_queen_memory_tools(registry: ToolRegistry) -> None:  # noqa: ARG001
    """No-op — memory tools replaced by automatic reflection + recall."""
    pass
