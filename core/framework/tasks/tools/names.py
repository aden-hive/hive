"""Canonical session task-tool names — the single source of truth.

The four identifiers below are stamped onto the ``Tool`` objects in
``session_tools.py``. ``TASK_WRITE_TOOLS`` is also imported by the
reminder system (``framework.tasks.reminders.is_task_turn``) so its
"did this turn record task progress" check uses the same names rather
than a private copy. Kept dependency-free so importers stay cheap.
"""

from __future__ import annotations

TASK_CREATE = "task_create"
TASK_UPDATE = "task_update"
TASK_LIST = "task_list"
TASK_GET = "task_get"

# Mutating task ops — they change task state (concurrency_safe=False).
TASK_WRITE_TOOLS: frozenset[str] = frozenset({TASK_CREATE, TASK_UPDATE})
# Every task tool, reads included. The reminder system treats any touch of
# the task system (even a read-only task_list / task_get) as a sign the
# agent hasn't lost track — see ``framework.tasks.reminders.on_turn``.
ALL_TASK_TOOLS: frozenset[str] = frozenset({TASK_CREATE, TASK_UPDATE, TASK_LIST, TASK_GET})
