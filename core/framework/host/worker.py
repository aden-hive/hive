"""Worker — a single autonomous clone in a colony.

Each worker is an exact copy of the queen's AgentLoop running independently.
Workers execute a task, report results back to the queen, and terminate.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class WorkerStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class WorkerResult:
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tokens_used: int = 0
    duration_seconds: float = 0.0


@dataclass
class WorkerInfo:
    id: str
    task: str
    status: WorkerStatus
    started_at: float = 0.0
    result: WorkerResult | None = None


class Worker:
    """A single autonomous clone in a colony.

    Wraps an AgentLoop execution with lifecycle management:
    - Starts as PENDING
    - Runs via AgentLoop → RUNNING
    - Completes → COMPLETED/FAILED
    - Can be stopped by the queen → STOPPED
    """

    def __init__(
        self,
        worker_id: str,
        task: str,
        agent_loop: Any,
        context: Any,
        event_bus: Any = None,
        colony_id: str = "",
    ):
        self.id = worker_id
        self.task = task
        self.status = WorkerStatus.PENDING
        self._agent_loop = agent_loop
        self._context = context
        self._event_bus = event_bus
        self._colony_id = colony_id
        self._task_handle: asyncio.Task | None = None
        self._started_at: float = 0.0
        self._result: WorkerResult | None = None
        self._input_queue: asyncio.Queue[str | None] = asyncio.Queue()

    @property
    def info(self) -> WorkerInfo:
        return WorkerInfo(
            id=self.id,
            task=self.task,
            status=self.status,
            started_at=self._started_at,
            result=self._result,
        )

    @property
    def is_active(self) -> bool:
        return self.status in (WorkerStatus.PENDING, WorkerStatus.RUNNING)

    async def run(self) -> WorkerResult:
        self.status = WorkerStatus.RUNNING
        self._started_at = time.monotonic()

        try:
            result = await self._agent_loop.execute(self._context)
            duration = time.monotonic() - self._started_at

            if result.success:
                self.status = WorkerStatus.COMPLETED
                self._result = WorkerResult(
                    output=result.output,
                    tokens_used=result.tokens_used,
                    duration_seconds=duration,
                )
            else:
                self.status = WorkerStatus.FAILED
                self._result = WorkerResult(
                    error=result.error or "Unknown error",
                    tokens_used=result.tokens_used,
                    duration_seconds=duration,
                )

            if self._event_bus:
                from framework.host.event_bus import AgentEvent, EventType

                event_type = (
                    EventType.EXECUTION_COMPLETED if result.success else EventType.EXECUTION_FAILED
                )
                await self._event_bus.publish(
                    AgentEvent(
                        type=event_type,
                        stream_id=self._context.stream_id or self.id,
                        node_id=self.id,
                        execution_id=self._context.execution_id or self.id,
                        data={
                            "worker_id": self.id,
                            "colony_id": self._colony_id,
                            "task": self.task,
                            "success": result.success,
                            "error": result.error,
                            "output_keys": list(result.output.keys()) if result.output else [],
                        },
                    )
                )

            return self._result

        except asyncio.CancelledError:
            self.status = WorkerStatus.STOPPED
            duration = time.monotonic() - self._started_at
            self._result = WorkerResult(
                error="Worker stopped by queen",
                duration_seconds=duration,
            )
            return self._result

        except Exception as exc:
            self.status = WorkerStatus.FAILED
            duration = time.monotonic() - self._started_at
            self._result = WorkerResult(
                error=str(exc),
                duration_seconds=duration,
            )
            logger.error("Worker %s failed: %s", self.id, exc, exc_info=True)
            return self._result

    async def start_background(self) -> None:
        self._task_handle = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task_handle and not self._task_handle.done():
            self._task_handle.cancel()
            try:
                await self._task_handle
            except asyncio.CancelledError:
                pass

    async def inject(self, message: str) -> None:
        await self._input_queue.put(message)
