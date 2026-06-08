"""Queen-only colony template tools.

These tools manipulate a colony's task template — the queen's spawn plan.
They are gated to the queen of a colony at registration time
(``register_colony_template_tools(colony_id=...)``).

Workers never see these tools. The four session tools (`task_create`,
`task_update`, `task_list`, `task_get`) operate exclusively on the
caller's session list — never the colony template.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.llm.provider import Tool
from framework.tasks.events import (
    emit_task_created,
    emit_task_deleted,
    emit_task_updated,
)
from framework.tasks.models import TaskRecord, TaskStatus
from framework.tasks.scoping import colony_task_list_id
from framework.tasks.store import _UNSET_SENTINEL, TaskStore, get_task_store
from framework.tasks.tools.session_tools import _serialize_task

logger = logging.getLogger(__name__)


def _add_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "active_form": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["subject"],
    }


def _update_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "active_form": {"type": "string"},
            "owner": {"type": ["string", "null"]},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
            },
            "metadata_patch": {"type": "object"},
        },
        "required": ["id"],
    }


def _remove_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }


def _list_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


_ADD_DESC = (
    "Append a task to your colony's spawn-plan template. Templates are read "
    "by `run_parallel_workers` and the UI; workers do not pull from the "
    "template after spawn. Use this to plan colony work before spawning."
)

_UPDATE_DESC = (
    "Update a template entry on your colony's spawn-plan template (e.g., "
    "stamp completion when a worker reports back, adjust subject/description). "
    "Only the queen can call this."
)

_REMOVE_DESC = (
    "Remove a template entry from your colony's spawn-plan template. The "
    "id is reserved (high-water-mark preserved) — never reused."
)

_LIST_DESC = (
    "List all entries on your colony's spawn-plan template. Each entry "
    "includes any `metadata.assigned_session` stamp that ties the entry to "
    "a spawned worker."
)


def _make_add_executor(store: TaskStore, list_id: str):
    async def execute(inputs: dict) -> dict[str, Any]:
        rec: TaskRecord = await store.create_task(
            list_id,
            subject=inputs["subject"],
            description=inputs.get("description", ""),
            active_form=inputs.get("active_form"),
            metadata=inputs.get("metadata") or {},
        )
        await emit_task_created(task_list_id=list_id, record=rec)
        return {
            "success": True,
            "task_list_id": list_id,
            "task_id": rec.id,
            "message": f"Template entry #{rec.id} added: {rec.subject}",
            "task": _serialize_task(rec),
        }

    return execute


def _make_update_executor(store: TaskStore, list_id: str):
    async def execute(inputs: dict) -> dict[str, Any]:
        task_id = int(inputs["id"])
        status_in = inputs.get("status")
        status_enum = TaskStatus(status_in) if status_in else None
        owner_in = inputs.get("owner", _UNSET_SENTINEL)
        new, fields = await store.update_task(
            list_id,
            task_id,
            subject=inputs.get("subject"),
            description=inputs.get("description"),
            active_form=inputs.get("active_form"),
            owner=owner_in,
            status=status_enum,
            metadata_patch=inputs.get("metadata_patch"),
        )
        if new is None:
            return {
                "success": False,
                "task_list_id": list_id,
                "task_id": task_id,
                "message": f"Template entry #{task_id} not found.",
            }
        if fields:
            await emit_task_updated(task_list_id=list_id, record=new, fields=fields)
        return {
            "success": True,
            "task_list_id": list_id,
            "task_id": task_id,
            "fields": fields,
            "message": f"Template entry #{task_id} updated. Fields: {', '.join(fields) or '(none)'}.",
            "task": _serialize_task(new),
        }

    return execute


def _make_remove_executor(store: TaskStore, list_id: str):
    async def execute(inputs: dict) -> dict[str, Any]:
        task_id = int(inputs["id"])
        deleted, cascade = await store.delete_task(list_id, task_id)
        if not deleted:
            return {
                "success": False,
                "task_list_id": list_id,
                "task_id": task_id,
                "message": f"Template entry #{task_id} not found.",
            }
        await emit_task_deleted(task_list_id=list_id, task_id=task_id, cascade=cascade)
        return {
            "success": True,
            "task_list_id": list_id,
            "task_id": task_id,
            "deleted": True,
            "cascade": cascade,
            "message": f"Template entry #{task_id} removed.",
        }

    return execute


def _make_list_executor(store: TaskStore, list_id: str):
    async def execute(inputs: dict) -> dict[str, Any]:
        records = await store.list_tasks(list_id)
        return {
            "success": True,
            "task_list_id": list_id,
            "count": len(records),
            "tasks": [_serialize_task(r) for r in records],
        }

    return execute


def build_colony_template_tools(
    *,
    colony_id: str,
    store: TaskStore | None = None,
) -> list[tuple[Tool, Any]]:
    s = store or get_task_store()
    list_id = colony_task_list_id(colony_id)
    return [
        (
            Tool(
                name="colony_template_add",
                description=_ADD_DESC,
                parameters=_add_schema(),
                concurrency_safe=False,
            ),
            _make_add_executor(s, list_id),
        ),
        (
            Tool(
                name="colony_template_update",
                description=_UPDATE_DESC,
                parameters=_update_schema(),
                concurrency_safe=False,
            ),
            _make_update_executor(s, list_id),
        ),
        (
            Tool(
                name="colony_template_remove",
                description=_REMOVE_DESC,
                parameters=_remove_schema(),
                concurrency_safe=False,
            ),
            _make_remove_executor(s, list_id),
        ),
        (
            Tool(
                name="colony_template_list",
                description=_LIST_DESC,
                parameters=_list_schema(),
                concurrency_safe=True,
            ),
            _make_list_executor(s, list_id),
        ),
    ]
