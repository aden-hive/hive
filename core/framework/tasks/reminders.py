"""Periodic task-reminder injection.

After enough silent turns since the last task tool call, inject a
reminder summarizing the current open tasks. Catches the failure mode
where the agent has silently absorbed multiple finished steps into one
in_progress task and stopped using the task tools.

The reminder counter lives on the AgentLoop instance; this module owns
the policy (threshold, cooldown, message text) and the integration
helper. Wiring lives in :mod:`framework.tasks.integrations.agent_loop`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass

from framework.tasks.models import TaskRecord, TaskStatus

logger = logging.getLogger(__name__)


REMINDER_THRESHOLD_TURNS = int(os.environ.get("HIVE_TASK_REMINDER_TURNS", "8"))
REMINDER_COOLDOWN_TURNS = int(os.environ.get("HIVE_TASK_REMINDER_COOLDOWN", "8"))

# Names that count as "task ops" — calling any of these resets the silence
# counter. Keep narrow: only mutating ops re-establish discipline. task_list
# / task_get are read-only and shouldn't reset the counter (the agent could
# read forever without making progress).
TASK_OP_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "task_create",
        "task_update",
        "colony_template_add",
        "colony_template_update",
        "colony_template_remove",
    }
)


@dataclass
class ReminderState:
    """Per-loop counter — caller bumps it each iteration."""

    turns_since_task_op: int = 0
    turns_since_last_reminder: int = 0

    def on_iteration(self) -> None:
        self.turns_since_task_op += 1
        self.turns_since_last_reminder += 1

    def on_task_op(self) -> None:
        self.turns_since_task_op = 0

    def on_reminder_sent(self) -> None:
        self.turns_since_last_reminder = 0

    def should_remind(self, has_open_tasks: bool) -> bool:
        return (
            has_open_tasks
            and self.turns_since_task_op >= REMINDER_THRESHOLD_TURNS
            and self.turns_since_last_reminder >= REMINDER_COOLDOWN_TURNS
        )


def saw_task_op(tool_names: Iterable[str]) -> bool:
    """True if any of the names is a counter-resetting task op."""
    return any(name in TASK_OP_TOOL_NAMES for name in tool_names)


def build_reminder(records: list[TaskRecord]) -> str:
    """Compose the reminder body — pending/in-progress focus."""
    open_ = [r for r in records if r.status != TaskStatus.COMPLETED]
    if not open_:
        return ""
    in_progress = [r for r in open_ if r.status == TaskStatus.IN_PROGRESS]
    head = (
        "[task_reminder] The task tools haven't been used in several "
        "turns. If you're working on tasks that would benefit from "
        "tracked progress:"
    )
    bullets = [
        "  - Mark the in_progress task `completed` THE MOMENT it's done — "
        "before starting the next step. Don't batch completions.",
        "  - If you've finished work that wasn't on the list, add a "
        "task_create + task_update completed pair so the panel reflects it.",
        "  - If you're umbrella-tracking ('reply to all posts' as one task), break it into one task per atomic action.",
    ]
    if in_progress:
        bullets.append(
            "  - Currently in_progress (consider whether they're really "
            "still active): " + ", ".join(f'#{r.id} "{r.subject}"' for r in in_progress[:5])
        )
    listing = ["", "Open tasks:"]
    for r in open_[:10]:
        listing.append(f"  #{r.id} [{r.status.value}] {r.subject}")
    if len(open_) > 10:
        listing.append(f"  ... and {len(open_) - 10} more")
    listing.append("\nOnly act on this if relevant to the current work. NEVER mention this reminder to the user.")
    return "\n".join([head, *bullets, *listing])
