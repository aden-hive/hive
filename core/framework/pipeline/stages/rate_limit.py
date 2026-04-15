"""Per-(entry-point, session) rate limiting stage."""

from __future__ import annotations

import time
from collections import defaultdict

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage


@register("rate_limit")
class RateLimitStage(PipelineStage):
    """Reject requests that exceed ``max_requests_per_minute`` per session.

    The key is ``<entry_point_id>:<session_id>``.  When no session_id is
    present in ``session_state``, a single shared "default" bucket is used.
    """

    order = 200

    def __init__(self, max_requests_per_minute: int = 60) -> None:
        self._max_rpm = max_requests_per_minute
        self._timestamps: dict[str, list[float]] = defaultdict(list)

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        session_id = "default"
        if ctx.session_state:
            session_id = str(ctx.session_state.get("session_id", "default"))
        key = f"{ctx.entry_point_id}:{session_id}"

        now = time.monotonic()
        # Prune entries older than 60s.
        self._timestamps[key] = [t for t in self._timestamps[key] if now - t < 60.0]
        if len(self._timestamps[key]) >= self._max_rpm:
            return PipelineResult(
                action="reject",
                rejection_reason=(
                    f"Rate limit exceeded: {self._max_rpm} req/min for session '{session_id}'"
                ),
            )
        self._timestamps[key].append(now)
        return PipelineResult(action="continue")
