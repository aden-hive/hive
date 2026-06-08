"""File-backed, lock-coordinated task tracker for the hive agent loop.

See temp/tasks-system-implementation-plan.md for the design. Two list types:

    colony:{colony_id}            -- the queen's spawn-plan template
    session:{agent_id}:{sess_id}  -- per-session working list

Each agent operates on its own session list via the session task tools
(`task_create_batch`, `task_create`, `task_update`, `task_list`,
`task_get`). The colony
template is addressed only by the queen's `colony_template_*` tools and by
the UI/event surface.
"""

from framework.tasks.models import (
    ClaimResult,
    TaskListMeta,
    TaskListRole,
    TaskRecord,
    TaskStatus,
)
from framework.tasks.scoping import (
    colony_task_list_id,
    parse_task_list_id,
    resolve_task_list_id,
    session_task_list_id,
)
from framework.tasks.store import (
    TaskStore,
    get_task_store,
)

__all__ = [
    "ClaimResult",
    "TaskListMeta",
    "TaskListRole",
    "TaskRecord",
    "TaskStatus",
    "TaskStore",
    "colony_task_list_id",
    "get_task_store",
    "parse_task_list_id",
    "resolve_task_list_id",
    "session_task_list_id",
]
