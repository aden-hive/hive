"""Cost guard stage -- reject requests over a pre-flight budget."""

from __future__ import annotations

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage


@register("cost_guard")
class CostGuardStage(PipelineStage):
    """Reject requests whose estimated cost exceeds the per-request budget.

    The cost estimate must be populated in ``ctx.metadata["estimated_cost"]``
    by an earlier stage (or by the caller).  When no estimate is present,
    the stage passes through.
    """

    order = 300

    def __init__(self, max_cost_per_request: float = 1.0) -> None:
        self._budget = max_cost_per_request

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        estimated = ctx.metadata.get("estimated_cost")
        if estimated is None:
            return PipelineResult(action="continue")
        if estimated > self._budget:
            return PipelineResult(
                action="reject",
                rejection_reason=(
                    f"Estimated cost ${estimated:.4f} exceeds budget ${self._budget:.4f}"
                ),
            )
        return PipelineResult(action="continue")
