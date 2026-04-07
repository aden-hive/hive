"""Pipeline stage base class and request/response types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


class PipelineRejectedError(Exception):
    """Raised by ``AgentRuntime.trigger`` when a stage rejects the request."""

    def __init__(self, stage_name: str, reason: str) -> None:
        super().__init__(f"Pipeline rejected by {stage_name}: {reason}")
        self.stage_name = stage_name
        self.reason = reason


@dataclass
class PipelineContext:
    """Carries request data through the pipeline.

    Stages can mutate ``metadata`` to pass information downstream -- e.g. a
    cost-estimation stage might write ``metadata["estimated_cost"]`` so a
    budget-guard stage later in the chain can reject requests over budget.
    """

    entry_point_id: str
    input_data: dict[str, Any]
    correlation_id: str | None = None
    session_state: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Outcome of a stage's ``process`` call."""

    action: Literal["continue", "reject", "transform"] = "continue"
    input_data: dict[str, Any] | None = None
    rejection_reason: str | None = None


class PipelineStage(ABC):
    """Base class for all middleware stages.

    Subclasses implement :meth:`process`.  The class attribute ``order``
    controls stage ordering (lower runs first; 100 is the default).
    Stages may also implement :meth:`initialize` for one-time setup and
    :meth:`post_process` to decorate the execution result.
    """

    order: int = 100

    async def initialize(self) -> None:
        """Called once when the runtime starts."""
        return None

    @abstractmethod
    async def process(self, ctx: PipelineContext) -> PipelineResult:
        """Process the incoming request.

        Return a :class:`PipelineResult` with action ``continue``, ``reject``,
        or ``transform``.
        """

    async def post_process(self, ctx: PipelineContext, result: Any) -> Any:
        """Optional post-execution hook. Default: pass-through."""
        return result
