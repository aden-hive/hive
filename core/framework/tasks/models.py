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


class TaskListRole(StrEnum):
    """Distinguishes a colony template from a session-scoped working list.

    Used for sanity-checking which write paths are allowed (e.g. the four
    session tools must never touch a ``template`` list).
    """

    TEMPLATE = "template"  # colony:{colony_id}
    SESSION = "session"  # session:{agent_id}:{session_id}


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
    """Per-list metadata. Embedded in ``TaskListDocument``."""

    task_list_id: str
    role: TaskListRole
    creator_agent_id: str | None = None
    created_at: float = Field(default_factory=time.time)
    last_seen_session_ids: list[str] = Field(default_factory=list)
    schema_version: int = 1


class TaskListDocument(BaseModel):
    """Whole task list as a single JSON document on disk.

    Lives at ``{task_list_path(list_id)}/tasks.json``; the list-lock
    sentinel is its sibling ``tasks.json.lock``.
    """

    meta: TaskListMeta
    highwatermark: int = 0
    tasks: list[TaskRecord] = Field(default_factory=list)


# Tagged union for claim_task_with_busy_check.  Used by run_parallel_workers
# when stamping ``assigned_session`` on a colony template entry — the only
# place a "claim" actually happens under the hive model.
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
