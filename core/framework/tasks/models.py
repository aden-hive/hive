"""Data models for the task tracker.

The schema follows the UI-facing task-record shape with one notable
difference: ids are integers (Python is cleaner that way) and rendered
as ``#N`` only in user-facing strings.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    # Set by the sweep job (TaskStore.sweep_idle_tasks) when an in_progress
    # task hasn't been touched within IDLE_TASK_THRESHOLD_SECONDS — typically
    # the queen marked the task started, asked the user a question, and the
    # user moved on without responding. Distinguishes "we gave up on this"
    # from "it actually finished." Queens MAY transition abandoned →
    # in_progress on resume by calling task_update again.
    ABANDONED = "abandoned"
    # Set by the agent via task_update(status="archived") when it tidies
    # the plan (the user's "Update plan"): a finished or no-longer-relevant
    # task is moved out of the active plan into the user's History. Hidden
    # from the default task_list (pass include_archived=true to see it) but
    # NOT gone — the agent can still task_get it and edit it, and setting a
    # live status again restores it (the archived_* markers are stripped).
    # Distinct from `deleted`, which is permanent id retirement.
    ARCHIVED = "archived"


# An in_progress task whose `updated_at` is older than this is treated as
# abandoned by `TaskStore.sweep_idle_tasks`. The frontend mirrors this
# threshold for its purely-visual demote (so the rail stays accurate
# between sweeps); the server is the authority. 30 minutes is conservative —
# adjust if a slow LLM provider produces legitimate single turns longer than
# this and false-positive abandonments become common.
IDLE_TASK_THRESHOLD_SECONDS: float = 30 * 60


def is_task_idle(record: TaskRecord, *, now: float | None = None) -> bool:
    """True when an `in_progress` task has been silent past the threshold.

    Pure function on the record — no I/O. Used by the sweep job and by
    callers that want to filter without persisting.
    """
    if record.status is not TaskStatus.IN_PROGRESS:
        return False
    current = now if now is not None else time.time()
    return current - (record.updated_at or 0.0) > IDLE_TASK_THRESHOLD_SECONDS


class TaskRecord(BaseModel):
    """One unit of work tracked by an agent."""

    id: int  # monotonic, never reused — see store.py
    subject: str
    description: str = ""
    active_form: str | None = None  # present-continuous label, surfaces in UI
    owner: str | None = None  # agent_id of the owning agent
    status: TaskStatus = TaskStatus.PENDING
    blocks: list[int] = Field(default_factory=list)
    blocked_by: list[int] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class TaskListMeta(BaseModel):
    """Per-list metadata. Embedded in ``TaskListDocument``.

    The list's identity comes from its on-disk path (its parent session
    folder). The session_id is not stored here — it's already encoded in
    the path.
    """

    # Always "session" — colony template lists were removed. Kept as a field
    # so the REST snapshot and persisted docs carry a stable shape.
    role: str = "session"
    creator_agent_id: str | None = None
    # The user-facing goal this task list serves. Set by the queen on the
    # first task_create of a session and used as the divergence anchor: a
    # later task_create whose goal differs meaningfully is the trigger for
    # a pivot (new_session in DM phase, new_colony in colony phase).
    goal: str | None = None
    created_at: float = Field(default_factory=time.time)
    schema_version: int = 1


class TaskListDocument(BaseModel):
    """Whole task list as a single JSON document on disk.

    Lives at ``{session_storage_dir(session_id)}/tasks.json``.
    """

    meta: TaskListMeta
    highwatermark: int = 0
    tasks: list[TaskRecord] = Field(default_factory=list)


# Tagged union for claim_task_with_busy_check — an atomic owner-claim under
# the list lock. Generic task-store infrastructure, not tied to any one caller.
@dataclass
class ClaimOk:
    kind: Literal["ok"]
    record: TaskRecord


@dataclass
class ClaimNotFound:
    kind: Literal["not_found"]


@dataclass
class ClaimAlreadyOwned:
    kind: Literal["already_owned"]
    by: str


@dataclass
class ClaimAlreadyCompleted:
    kind: Literal["already_completed"]


@dataclass
class ClaimBlocked:
    kind: Literal["blocked"]
    by: list[int]


ClaimResult = ClaimOk | ClaimNotFound | ClaimAlreadyOwned | ClaimAlreadyCompleted | ClaimBlocked
