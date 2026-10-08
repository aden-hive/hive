"""Colony worker-fleet snapshot for the queen at tool-budget checkpoints.

Sister source to :class:`TrackerSnapshotReminderSource` — fires at the
same ``TOOL_BUDGET_CHECKPOINT`` lifecycle point but is queen-only and
shows the live worker fleet (active list + active/total counts) so a
queen that's grinding on her own tool-calls is reminded what the rest
of the colony is doing.

Distinct from :class:`ActiveWorkersReminderSource`, which fires at
``USER_PROMPT_SUBMIT``: this one fires mid-turn when the queen has been
the one burning through tools, not the workers.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.agent_loop.reminders import (
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)

# Bound the per-worker enumeration so a huge fan-out doesn't produce a
# wall of text the queen has to re-parse on every checkpoint. Total
# count is always shown in the lead sentence.
_MAX_LISTED = 8
_TASK_BODY_MAX = 80


class ColonyWorkerSnapshotReminderSource(ReminderSource):
    """Queen-only, in-colony-only fleet snapshot at tool-budget checkpoints.

    The double gate (queen stream AND non-None binding) keeps the source
    silent for: workers, pre-fork queens, and independent-mode queens.
    Without it, the snapshot would either fire on irrelevant agents or
    report zeroes for a queen that legitimately has no colony.
    """

    name = "colony_worker_snapshot"

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.TOOL_BUDGET_CHECKPOINT}

    def applies_to(self, agent_ctx: Any) -> bool:
        if not bool(getattr(agent_ctx, "is_queen_stream", False)):
            return False
        # We check provider presence here, not its current return value —
        # ``applies_to`` runs once at ``bind()`` time, but a queen forks
        # mid-session. The render path re-resolves the binding each turn.
        return getattr(agent_ctx, "colony_binding_provider", None) is not None

    async def render(self, rctx: ReminderContext) -> str | None:
        # Re-check the binding at render time: a queen who hasn't forked
        # yet has the provider wired but it returns None.
        binding = _safe_call(rctx.agent_ctx, "colony_binding_provider")
        if binding is None:
            return None

        stats = _safe_call(rctx.agent_ctx, "colony_stats_provider") or {}
        workers = _safe_call(rctx.agent_ctx, "active_workers_provider") or []
        if not isinstance(stats, dict):
            stats = {}
        if not isinstance(workers, list):
            workers = []
        active = int(stats.get("active", len(workers)))
        total = int(stats.get("total", active))
        if active == 0 and total == 0:
            return None
        return _render_body(workers, active=active, total=total)


def _safe_call(agent_ctx: Any, attr: str):
    provider = getattr(agent_ctx, attr, None)
    if not callable(provider):
        return None
    try:
        return provider()
    except Exception:
        logger.debug("colony_worker_snapshot: %s raised", attr, exc_info=True)
        return None


def _render_body(workers: list[dict], *, active: int, total: int) -> str:
    lines = [f"Colony fleet: {active} active worker(s), {total} total this session."]
    listed = [w for w in workers if isinstance(w, dict)][:_MAX_LISTED]
    if listed:
        lines.append("")
        for w in listed:
            wid = str(w.get("worker_id", "?"))
            status = str(w.get("status", "?"))
            task = str(w.get("task", "")).strip()
            if len(task) > _TASK_BODY_MAX:
                task = task[: _TASK_BODY_MAX - 1].rstrip() + "…"
            lines.append(f"  - {wid} [{status}]: {task}" if task else f"  - {wid} [{status}]")
        if len(workers) > _MAX_LISTED:
            lines.append(f"  ... and {len(workers) - _MAX_LISTED} more")
    lines.append("")
    lines.append(
        "Don't re-dispatch in-flight tasks. If you're tool-busy because "
        "workers are pending, prefer waiting on their WORKER_REPORTs over "
        "running their work yourself."
    )
    return "\n".join(lines)
