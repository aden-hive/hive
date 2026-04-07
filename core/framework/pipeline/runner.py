"""Pipeline runner -- executes registered stages in order."""

from __future__ import annotations

import logging
from typing import Any

from framework.pipeline.stage import (
    PipelineContext,
    PipelineRejectedError,
    PipelineStage,
)

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Executes a list of :class:`PipelineStage` instances in ``order``.

    The runner is the orchestration layer that :class:`AgentRuntime` calls
    on every trigger.  Stages execute in ascending ``order`` (ties broken by
    registration order).  A stage returning ``reject`` short-circuits the
    pipeline and causes the trigger to raise :class:`PipelineRejectedError`.
    """

    def __init__(self, stages: list[PipelineStage] | None = None) -> None:
        self._stages: list[PipelineStage] = sorted(stages or [], key=lambda s: s.order)

    @property
    def stages(self) -> list[PipelineStage]:
        return list(self._stages)

    def add_stage(self, stage: PipelineStage) -> None:
        """Add a stage after construction (for dynamic registration)."""
        self._stages.append(stage)
        self._stages.sort(key=lambda s: s.order)

    async def initialize_all(self) -> None:
        """Call ``initialize`` on every registered stage."""
        for stage in self._stages:
            name = stage.__class__.__name__
            logger.info("[pipeline] Initializing %s (order=%d)", name, stage.order)
            await stage.initialize()
            logger.info("[pipeline] %s initialized", name)
        if self._stages:
            logger.info(
                "[pipeline] Ready: %d stages [%s]",
                len(self._stages),
                " -> ".join(s.__class__.__name__ for s in self._stages),
            )

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        """Run all stages.  Raises ``PipelineRejectedError`` on rejection.

        Returns the (possibly transformed) context.
        """
        if not self._stages:
            return ctx
        import time

        pipeline_start = time.perf_counter()
        logger.info(
            "[pipeline] Running %d stages for entry_point=%s",
            len(self._stages),
            ctx.entry_point_id,
        )
        for stage in self._stages:
            stage_name = stage.__class__.__name__
            t0 = time.perf_counter()
            result = await stage.process(ctx)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if result.action == "reject":
                reason = result.rejection_reason or "(no reason given)"
                logger.warning(
                    "[pipeline] REJECTED by %s (%.1fms): %s",
                    stage_name, elapsed_ms, reason,
                )
                raise PipelineRejectedError(stage_name, reason)
            if result.action == "transform":
                logger.info(
                    "[pipeline] %s TRANSFORMED input (%.1fms)",
                    stage_name, elapsed_ms,
                )
                if result.input_data is not None:
                    ctx.input_data = result.input_data
            else:
                logger.info(
                    "[pipeline] %s passed (%.1fms)",
                    stage_name, elapsed_ms,
                )
        total_ms = (time.perf_counter() - pipeline_start) * 1000
        logger.info("[pipeline] Complete (%.1fms total)", total_ms)
        return ctx

    async def run_post(self, ctx: PipelineContext, result: Any) -> Any:
        """Run all stages' ``post_process`` hooks in order.

        Each stage can transform the result; the final value is returned.
        Exceptions are logged and swallowed -- post-processing must not
        break a successful execution.
        """
        current = result
        for stage in self._stages:
            try:
                current = await stage.post_process(ctx, current)
            except Exception:
                logger.exception(
                    "Pipeline post_process raised in %s; continuing with previous result",
                    stage.__class__.__name__,
                )
        return current
