"""Wire task tools into a ToolRegistry.

The four session task tools are registered for every agent that gets a
ToolRegistry.
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
    pivot_handler=None,
) -> None:
    """Register the four session task tools on ``registry``.

    Idempotent: re-registering overwrites the previous executor (which is
    fine — they share the same TaskStore singleton anyway).

    ``pivot_handler`` — passed through to ``build_session_tools``. When
    set (queen only), ``task_create`` gains the handler's pivot field
    (``new_session`` for DM, ``new_colony`` for colony queens) for
    forking the plan into a fresh context.
    """
    from framework.tasks.tools.session_tools import build_session_tools

    pairs = build_session_tools(store=store, pivot_handler=pivot_handler)
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
