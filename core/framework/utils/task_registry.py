"""Tracked ``asyncio.create_task`` — prevents silent task loss.

Bare ``asyncio.create_task(...)`` has two well-known failure modes:

1. **Garbage collection.** The event loop only holds a *weak* reference
   to the task, so if the caller doesn't hold a strong reference the
   task can be collected mid-flight and silently cancelled.
2. **Swallowed exceptions.** If a fire-and-forget task raises, the
   exception is stored on the Task object and only surfaces when the
   task is awaited or garbage-collected. If nothing ever awaits it,
   the exception is logged by asyncio at shutdown (if at all).

``TaskRegistry`` fixes both: it holds a strong reference until the task
finishes, logs any exception the task raised, and removes the reference
on completion so it doesn't leak. It also lets a caller cancel every
tracked task at shutdown time in one call.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class TaskRegistry:
    """Owner for background asyncio tasks.

    Typical use::

        self._tasks = TaskRegistry("agent_loop")
        self._tasks.spawn(self._background_worker(), name="background_worker")
        ...
        await self._tasks.cancel_all()
    """

    def __init__(self, owner: str = "") -> None:
        self._owner = owner
        self._tasks: set[asyncio.Task[Any]] = set()

    def spawn(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """Schedule *coro* as a tracked background task."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.error(
            "Tracked task '%s' (owner=%s) raised an unhandled exception: %s",
            task.get_name(),
            self._owner or "?",
            exc,
            exc_info=exc,
        )

    async def cancel_all(self, *, timeout: float = 5.0) -> None:
        """Cancel every tracked task and wait up to *timeout* for them to finish."""
        if not self._tasks:
            return
        pending = list(self._tasks)
        for t in pending:
            t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(
                "TaskRegistry(%s): %d task(s) did not finish within %.1fs of cancel",
                self._owner or "?",
                sum(1 for t in pending if not t.done()),
                timeout,
            )

    def __len__(self) -> int:
        return len(self._tasks)
