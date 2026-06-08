"""Task lifecycle hooks.

Two events:

  * ``task_created``   -- fires after the task file is written but before the
                          tool returns. Hooks may raise ``BlockingHookError``
                          to abort creation; the wrapper deletes the just-
                          created task and returns an error tool_result.

  * ``task_completed`` -- fires when ``task_update`` transitions a task to
                          ``completed``. A blocking error rolls the status
                          back to ``in_progress`` and surfaces the error.

Hooks are registered on a process-global registry so callers (test
fixtures, integrations) can install them without threading through the
agent loop. They run in registration order; any hook may abort by raising
``BlockingHookError``.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


HOOK_TASK_CREATED = "task_created"
HOOK_TASK_COMPLETED = "task_completed"


class BlockingHookError(Exception):
    """Raised by a hook to veto the surrounding tool operation."""


@dataclass
class TaskHookContext:
    event: str
    task_list_id: str
    task: Any  # TaskRecord (avoid import cycle)
    agent_id: str | None = None
    metadata: dict[str, Any] | None = None


HookFn = Callable[[TaskHookContext], Any | Awaitable[Any]]

_HOOK_REGISTRY: dict[str, list[HookFn]] = {
    HOOK_TASK_CREATED: [],
    HOOK_TASK_COMPLETED: [],
}


def register_hook(event: str, fn: HookFn) -> None:
    if event not in _HOOK_REGISTRY:
        raise ValueError(f"Unknown hook event: {event!r}")
    _HOOK_REGISTRY[event].append(fn)


def clear_hooks(event: str | None = None) -> None:
    """Test helper. Clear all hooks (or just one event's)."""
    if event is None:
        for k in _HOOK_REGISTRY:
            _HOOK_REGISTRY[k].clear()
    else:
        _HOOK_REGISTRY.get(event, []).clear()


async def run_task_hooks(
    event: str,
    *,
    task_list_id: str,
    task: Any,
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Run all hooks registered for ``event``.

    Re-raises ``BlockingHookError`` from any hook; the caller is responsible
    for rolling back the operation.
    """
    hooks = list(_HOOK_REGISTRY.get(event, ()))
    if not hooks:
        return
    ctx = TaskHookContext(
        event=event,
        task_list_id=task_list_id,
        task=task,
        agent_id=agent_id,
        metadata=metadata,
    )
    for hook in hooks:
        try:
            result = hook(ctx)
            if inspect.isawaitable(result):
                await result
        except BlockingHookError:
            raise
        except Exception:
            # Non-blocking exceptions are logged but do not abort the operation.
            logger.exception("Non-blocking hook failed for %s", event)
