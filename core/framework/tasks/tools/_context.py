"""Context resolution for task-tool executors.

Tool executors run synchronously inside ``ToolRegistry.get_executor()``;
they need the calling agent's id and task_list_id to know which list to
write to. We pull both from contextvars set by the runner /
ColonyRuntime / orchestrator before each agent's iteration.
"""

from __future__ import annotations

from typing import Any

from framework.loader.tool_registry import _execution_context


def current_context() -> dict[str, Any]:
    return dict(_execution_context.get() or {})


def current_agent_id() -> str | None:
    return current_context().get("agent_id")


def current_task_list_id() -> str | None:
    return current_context().get("task_list_id")


def current_colony_id() -> str | None:
    return current_context().get("colony_id")


def current_picked_up_from() -> tuple[str, int] | None:
    """If this session was spawned for a colony template entry, return it."""
    raw = current_context().get("picked_up_from")
    if not raw:
        return None
    if isinstance(raw, tuple) and len(raw) == 2:
        return raw[0], int(raw[1])
    return None
