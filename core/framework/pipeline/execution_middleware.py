"""Execution-level middleware protocol.

Unlike :class:`PipelineStage` (which gates ``AgentHost.trigger()`` at the
request level), execution middleware runs at the start of **every** execution
attempt inside ``ExecutionManager._run_execution()`` -- including resurrection
retries.

Use this for concerns that must re-evaluate per attempt:
- Cost tracking (charge per attempt, not per trigger)
- Tool scoping (different tools on retry)
- Checkpoint config overrides
- Per-execution logging/tracing setup
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    """Context passed to execution middleware."""

    execution_id: str
    stream_id: str
    run_id: str
    input_data: dict[str, Any]
    session_state: dict[str, Any] | None = None
    attempt: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionMiddleware(ABC):
    """Base class for per-execution middleware."""

    @abstractmethod
    async def on_execution_start(self, ctx: ExecutionContext) -> ExecutionContext:
        """Called before each execution attempt (including resurrections).

        Modify and return *ctx* to transform execution parameters.
        Raise to abort the execution.
        """
