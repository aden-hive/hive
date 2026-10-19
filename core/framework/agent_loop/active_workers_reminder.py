"""Active-workers reminder for the colony queen.

A :class:`ReminderSource` that re-surfaces in-flight parallel work to the
queen each time the user re-engages. Without it, a queen pulled into a
side conversation can easily forget that workers are still running —
leading to duplicate dispatch, premature summarization, or contradictory
instructions.

Fires at :attr:`ReminderPoint.USER_PROMPT_SUBMIT`, queen-only, only when
``agent_ctx.active_workers_provider`` returns at least one worker. Each
user turn while workers are live re-shows the list; once the batch
drains the reminder stops firing on its own.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from framework.agent_loop.reminders import (
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Cap on how many workers we enumerate by name in the reminder body. A
# huge fan-out (50+ workers) would otherwise produce a wall of text the
# queen has to re-parse on every user turn. The full count is always
# shown in the lead sentence.
ACTIVE_WORKERS_SNAPSHOT_MAX = _env_int("HIVE_ACTIVE_WORKERS_SNAPSHOT_MAX", 8)
# Truncate per-worker task descriptions. The runtime already truncates
# to 100 chars in ``ColonyRuntime.get_active_streams``; tighter here keeps
# the reminder scannable.
TASK_BODY_MAX = _env_int("HIVE_ACTIVE_WORKERS_TASK_MAX", 80)


class ActiveWorkersReminderSource(ReminderSource):
    """Remind the queen of in-flight parallel work on each user re-engage.

    Stateless: the precondition (live workers exist) is the sole gate, so
    the reminder fires on every user turn it applies and goes silent the
    turn after the batch drains. No cooldown or per-session cap — the
    reminder's lifetime is naturally bounded by the batch.
    """

    name = "active_workers"

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.USER_PROMPT_SUBMIT}

    def applies_to(self, agent_ctx: Any) -> bool:
        """Queens only. Worker presence is rechecked at render time."""
        return bool(getattr(agent_ctx, "is_queen_stream", False))

    async def render(self, rctx: ReminderContext) -> str | None:
        workers = _list_active_workers(rctx.agent_ctx)
        if not workers:
            return None
        return _render_body(workers)


def _list_active_workers(agent_ctx: Any) -> list[dict]:
    """Snapshot live workers via the queen ctx's provider. ``[]`` on any failure.

    The provider is wired by the queen orchestrator to
    ``session.colony.get_active_streams``; treat anything that isn't a
    callable as "no workers" so non-queen contexts and pre-fork queens
    are silently skipped.
    """
    provider = getattr(agent_ctx, "active_workers_provider", None)
    if not callable(provider):
        return []
    try:
        result = provider() or []
    except Exception:
        logger.debug(
            "active_workers: provider raised; treating as no active workers",
            exc_info=True,
        )
        return []
    return [w for w in result if isinstance(w, dict)]


def _render_body(workers: list[dict]) -> str:
    """The system-reminder body. Lead with count, list up to the cap, then
    a one-line behavioral nudge so the queen knows what to do with the
    information."""
    count = len(workers)
    plural = "" if count == 1 else "s"
    lines = [
        f"You have {count} parallel worker{plural} still running from earlier "
        f"fan-out (run_playbook or run_worker). Their reports arrive as "
        f"WORKER_REPORT messages as each finishes — don't re-dispatch the "
        f"same tasks or summarize the batch yet.",
        "",
    ]
    for w in workers[:ACTIVE_WORKERS_SNAPSHOT_MAX]:
        wid = str(w.get("worker_id", "?"))
        status = str(w.get("status", "?"))
        task = str(w.get("task", "")).strip()
        if len(task) > TASK_BODY_MAX:
            task = task[: TASK_BODY_MAX - 1].rstrip() + "…"
        lines.append(f"  - {wid} [{status}]: {task}" if task else f"  - {wid} [{status}]")
    if count > ACTIVE_WORKERS_SNAPSHOT_MAX:
        lines.append(f"  ... and {count - ACTIVE_WORKERS_SNAPSHOT_MAX} more")
    lines.append("")
    lines.append("If the user's message asks about progress, prefer get_worker_status over re-running tools yourself.")
    return "\n".join(lines)
