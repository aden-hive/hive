"""Wire task tools into a ToolRegistry.

The four session task tools are registered for every agent that gets a
ToolRegistry. The colony template tools are queen-only and registered
separately by ``register_colony_template_tools``.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.loader.tool_registry import ToolRegistry
from framework.tasks.store import TaskStore

logger = logging.getLogger(__name__)


def _wrap_async_executor(async_executor):
    """Adapt an async executor to ToolRegistry's sync executor protocol.

    ToolRegistry's executor expects ``Callable[[dict], Any]`` where Any may
    be a coroutine; the registry awaits it. We just pass the coroutine
    through.
    """

    def executor(inputs: dict) -> Any:
        return async_executor(inputs)

    return executor


def register_task_tools(
    registry: ToolRegistry,
    *,
    store: TaskStore | None = None,
) -> None:
    """Register the four session task tools on ``registry``.

    Idempotent: re-registering overwrites the previous executor (which is
    fine — they share the same TaskStore singleton anyway).
    """
    from framework.tasks.tools.session_tools import build_session_tools

    pairs = build_session_tools(store=store)
    for tool, async_executor in pairs:
        registry.register(tool.name, tool, _wrap_async_executor(async_executor))
        # Also stamp into the concurrency-safe set if appropriate so the
        # parallel batch dispatcher knows it can fan reads out.
        if tool.concurrency_safe and tool.name not in ToolRegistry.CONCURRENCY_SAFE_TOOLS:
            # CONCURRENCY_SAFE_TOOLS is a frozenset; attribute is a frozenset
            # at the class level, so we instead set the attribute on the Tool
            # object itself (already done) and trust the dispatcher to read it.
            pass
    logger.debug("Registered task tools on %s", registry)


def register_colony_template_tools(
    registry: ToolRegistry,
    *,
    colony_id: str,
    store: TaskStore | None = None,
) -> None:
    """Register the queen-only colony_template_* tools on ``registry``.

    Should only be called for the queen of a colony — workers and queen-DM
    do not get these tools.
    """
    from framework.tasks.tools.colony_tools import build_colony_template_tools

    pairs = build_colony_template_tools(colony_id=colony_id, store=store)
    for tool, async_executor in pairs:
        registry.register(tool.name, tool, _wrap_async_executor(async_executor))
    logger.debug("Registered colony_template_* tools (colony_id=%s)", colony_id)
