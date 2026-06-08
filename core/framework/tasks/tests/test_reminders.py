"""Tests for the periodic task-reminder logic.

The reminder state is a small counter machine; the policy is:
  - Bump on each iteration
  - Reset to zero on any task op tool call (task_create / task_update /
    colony_template_*)
  - When ``turns_since_task_op >= REMINDER_THRESHOLD_TURNS`` AND
    ``turns_since_last_reminder >= REMINDER_COOLDOWN_TURNS`` AND there
    are open tasks, fire a reminder

The build_reminder helper composes the message body — checked for the
key behavioral nudges (granularity + completion discipline).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from framework.tasks import TaskListRole, TaskStore
from framework.tasks.models import TaskStatus
from framework.tasks.reminders import (
    REMINDER_COOLDOWN_TURNS,
    REMINDER_THRESHOLD_TURNS,
    ReminderState,
    build_reminder,
    saw_task_op,
)


def test_state_bumps_each_iteration() -> None:
    s = ReminderState()
    s.on_iteration()
    s.on_iteration()
    assert s.turns_since_task_op == 2
    assert s.turns_since_last_reminder == 2


def test_state_resets_on_task_op() -> None:
    s = ReminderState()
    for _ in range(5):
        s.on_iteration()
    s.on_task_op()
    assert s.turns_since_task_op == 0
    # Reminder cooldown is independent — it tracks reminders, not ops.
    assert s.turns_since_last_reminder == 5


def test_should_remind_below_threshold() -> None:
    s = ReminderState()
    s.turns_since_task_op = REMINDER_THRESHOLD_TURNS - 1
    s.turns_since_last_reminder = REMINDER_COOLDOWN_TURNS
    assert not s.should_remind(has_open_tasks=True)


def test_should_remind_no_tasks() -> None:
    s = ReminderState()
    s.turns_since_task_op = REMINDER_THRESHOLD_TURNS + 5
    s.turns_since_last_reminder = REMINDER_COOLDOWN_TURNS + 5
    assert not s.should_remind(has_open_tasks=False)


def test_should_remind_at_threshold() -> None:
    s = ReminderState()
    s.turns_since_task_op = REMINDER_THRESHOLD_TURNS
    s.turns_since_last_reminder = REMINDER_COOLDOWN_TURNS
    assert s.should_remind(has_open_tasks=True)


def test_cooldown_blocks_back_to_back() -> None:
    s = ReminderState()
    s.turns_since_task_op = REMINDER_THRESHOLD_TURNS + 5
    s.on_reminder_sent()
    assert not s.should_remind(has_open_tasks=True)


def test_saw_task_op_recognizes_mutating_tools() -> None:
    assert saw_task_op(["task_create"])
    assert saw_task_op(["read_file", "task_update"])
    assert saw_task_op(["colony_template_add"])
    # Reads do NOT reset the counter — important: model could read forever
    # without making progress.
    assert not saw_task_op(["task_list", "task_get"])
    assert not saw_task_op([])


@pytest.mark.asyncio
async def test_build_reminder_includes_open_tasks(tmp_path: Path) -> None:
    store = TaskStore(hive_root=tmp_path)
    await store.ensure_task_list("session:a:b", role=TaskListRole.SESSION)
    await store.create_task("session:a:b", subject="step 1")
    rec2 = await store.create_task("session:a:b", subject="step 2")
    await store.create_task("session:a:b", subject="step 3")
    # Mark #2 in_progress so the reminder mentions it.
    await store.update_task("session:a:b", rec2.id, status=TaskStatus.IN_PROGRESS)
    records = await store.list_tasks("session:a:b")

    body = build_reminder(records)

    assert "task_reminder" in body
    assert "step 1" in body
    assert "step 2" in body
    assert "step 3" in body
    # Granularity nudge present.
    assert "umbrella" in body.lower() or "atomic" in body.lower()
    # Completion-discipline nudge present.
    assert "completed" in body.lower()
    # Anti-nag boilerplate remains present.
    assert "NEVER mention this reminder to the user" in body


@pytest.mark.asyncio
async def test_build_reminder_empty_when_no_open(tmp_path: Path) -> None:
    store = TaskStore(hive_root=tmp_path)
    await store.ensure_task_list("session:a:b", role=TaskListRole.SESSION)
    rec = await store.create_task("session:a:b", subject="done already")
    await store.update_task("session:a:b", rec.id, status=TaskStatus.COMPLETED)
    records = await store.list_tasks("session:a:b")

    assert build_reminder(records) == ""
