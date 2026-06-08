"""The four session task tools: task_create, task_update, task_list, task_get.

All four operate on the calling agent's OWN session list. They never touch
the colony template — the queen has separate ``colony_template_*`` tools
for that (see ``colony_tools.py``).

Concurrency safety:
    task_list, task_get      -> concurrency_safe=True (pure reads)
    task_create, task_update -> concurrency_safe=False (writes serialize)
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
from framework.tasks.hooks import (
    HOOK_TASK_COMPLETED,
    HOOK_TASK_CREATED,
    BlockingHookError,
    run_task_hooks,
)
from framework.tasks.models import TaskRecord, TaskStatus
from framework.tasks.store import (
    _UNSET_SENTINEL as _UNSET,  # re-export for clarity
    TaskStore,
    get_task_store,
)
from framework.tasks.tools._context import (
    current_agent_id,
    current_task_list_id,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas (Anthropic-style JSONSchema)
# ---------------------------------------------------------------------------


_TASK_STATUS_VALUES = ["pending", "in_progress", "completed", "deleted"]


def _create_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Imperative title (e.g., 'Crawl target URLs').",
            },
            "description": {
                "type": "string",
                "description": "Brief description of what to do.",
            },
            "active_form": {
                "type": "string",
                "description": "Present-continuous label shown while in_progress (e.g., 'Crawling target URLs').",
            },
            "metadata": {
                "type": "object",
                "description": "Arbitrary key/value metadata. Use _internal=true to hide from task_list.",
            },
        },
        "required": ["subject"],
    }


def _update_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "Task id (the #N from task_list)."},
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "active_form": {"type": "string"},
            "owner": {
                "type": ["string", "null"],
                "description": "Agent id of the owner. Null clears ownership.",
            },
            "status": {"type": "string", "enum": _TASK_STATUS_VALUES},
            "add_blocks": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Add task ids that this task blocks (bidirectional).",
            },
            "add_blocked_by": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Add task ids that block this task (bidirectional).",
            },
            "metadata_patch": {
                "type": "object",
                "description": "Merge into metadata. Null values delete keys.",
            },
        },
        "required": ["id"],
    }


def _list_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


def _get_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }


def _create_batch_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "minItems": 1,
                "description": (
                    "Array of task specs. Each becomes one task with a sequential id. Atomic — all created or none."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {
                            "type": "string",
                            "description": "Imperative title (e.g. 'Crawl target URL').",
                        },
                        "description": {"type": "string"},
                        "active_form": {
                            "type": "string",
                            "description": ("Present-continuous label shown while in_progress."),
                        },
                        "metadata": {"type": "object"},
                    },
                    "required": ["subject"],
                },
            }
        },
        "required": ["tasks"],
    }


# ---------------------------------------------------------------------------
# Tool descriptions
# ---------------------------------------------------------------------------

_CREATE_DESC = (
    "Create ONE task on your own session task list. Use this for one-off "
    "mid-run additions when you discover unplanned work after the initial "
    "plan is laid out.\n\n"
    "**After receiving new instructions, immediately capture the user's "
    "requirements as tasks** — and delete (via `task_update` with "
    "status='deleted') any prior tasks that no longer apply.\n\n"
    "**For laying out a multi-step plan upfront, use `task_create_batch` "
    "instead** — one tool call with all the steps is cheaper and atomic.\n\n"
    "Fields:\n"
    "- subject: short imperative title (e.g. 'Crawl target URL').\n"
    "- description: optional, slightly longer 'what to do' note.\n"
    "- active_form: present-continuous label shown while in_progress (e.g. "
    "'Crawling target URL'). If omitted, the spinner shows the subject.\n"
    "- metadata: optional KV. Set _internal=true to hide from task_list."
)

_UPDATE_DESC = (
    "Update ONE task on your own session task list. There is no batch "
    "update tool by design — every `completed` transition is a discrete "
    "progress signal to the user.\n\n"
    "Workflow:\n"
    "- Mark a task `in_progress` BEFORE you start working on it.\n"
    "- Mark it `completed` AS SOON as you finish it — do not let "
    "multiple finished tasks pile up unmarked before flushing them at "
    "the end of the run.\n"
    "- Delete tasks: when a task is no longer relevant or was created "
    "in error. Setting status='deleted' **permanently** removes the "
    "task — the id is retired and cannot be reused.\n\n"
    "ONLY mark `completed` when the task is FULLY done. If you hit errors, "
    "blockers, or partial state, keep it `in_progress` and create a new "
    "task describing what's blocking. Never mark completed with caveats; "
    "if it's not done, it's not done.\n\n"
    "Setting status='in_progress' without owner auto-fills your agent_id."
)

_LIST_DESC = (
    "Show your session task list, sorted by id ascending. Internal tasks "
    "(metadata._internal=true) and resolved blockers are filtered out. "
    "**Prefer working on tasks in id order** (lowest first) — earlier "
    "tasks usually set up context for later ones."
)

_GET_DESC = (
    "Read the full record of one task (description, metadata, timestamps) "
    "from your own session task list. Use this to refresh your view of a "
    "task before updating it if you're not sure of current fields."
)

_CREATE_BATCH_DESC = (
    "Create N tasks at once on your own session task list. **Use this "
    "FIRST when laying out a multi-step plan upfront** — replying to 5 "
    "posts is one `task_create_batch` with 5 entries, not 5 separate "
    "`task_create` calls. Atomic: all-or-none. Use single `task_create` "
    "for one-off mid-run additions when you discover unplanned work, "
    "not for the initial plan."
)


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


def _resolve_list_id() -> str | None:
    """Pull the calling agent's session task_list_id from execution context."""
    return current_task_list_id()


def _serialize_task(t: TaskRecord) -> dict[str, Any]:
    return {
        "id": t.id,
        "subject": t.subject,
        "description": t.description,
        "active_form": t.active_form,
        "owner": t.owner,
        "status": t.status.value,
        "blocks": list(t.blocks),
        "blocked_by": list(t.blocked_by),
        "metadata": dict(t.metadata),
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _make_create_executor(store: TaskStore):
    async def execute(inputs: dict) -> dict[str, Any]:
        list_id = _resolve_list_id()
        if not list_id:
            return {"success": False, "error": "No task_list_id resolved for this agent."}
        agent_id = current_agent_id() or ""
        kwargs = {
            "subject": inputs["subject"],
            "description": inputs.get("description", ""),
            "active_form": inputs.get("active_form"),
            "metadata": inputs.get("metadata") or {},
        }
        rec = await store.create_task(list_id, **kwargs)
        # task_created hooks may block creation -> rollback by deleting.
        try:
            await run_task_hooks(
                HOOK_TASK_CREATED,
                task_list_id=list_id,
                task=rec,
                agent_id=agent_id,
            )
        except BlockingHookError as exc:
            logger.warning("task_created hook blocked task #%s: %s", rec.id, exc)
            await store.delete_task(list_id, rec.id)
            return {"success": False, "error": f"Hook blocked task creation: {exc}"}
        await emit_task_created(task_list_id=list_id, record=rec)
        return {
            "success": True,
            "task_list_id": list_id,
            "task_id": rec.id,
            "message": f"Task #{rec.id} created successfully: {rec.subject}",
            "task": _serialize_task(rec),
        }

    return execute


def _make_create_batch_executor(store: TaskStore):
    async def execute(inputs: dict) -> dict[str, Any]:
        list_id = _resolve_list_id()
        if not list_id:
            return {"success": False, "error": "No task_list_id resolved for this agent."}
        agent_id = current_agent_id() or ""
        specs = inputs.get("tasks") or []
        if not isinstance(specs, list) or not specs:
            return {
                "success": False,
                "error": "task_create_batch requires a non-empty `tasks` array.",
            }
        # Storage layer validates subject; surface its error as a soft
        # tool_result so sibling tools don't cancel.
        try:
            recs = await store.create_tasks_batch(list_id, specs)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        # Run task_created hooks per task; blocking on any aborts the
        # whole batch (delete every record we just wrote, return error).
        for rec in recs:
            try:
                await run_task_hooks(
                    HOOK_TASK_CREATED,
                    task_list_id=list_id,
                    task=rec,
                    agent_id=agent_id,
                )
            except BlockingHookError as exc:
                logger.warning(
                    "task_created hook blocked batch on task #%s: %s",
                    rec.id,
                    exc,
                )
                for r in recs:
                    await store.delete_task(list_id, r.id)
                return {
                    "success": False,
                    "error": (f"Hook blocked task #{rec.id} ({rec.subject!r}); entire batch rolled back: {exc}"),
                }

        for rec in recs:
            await emit_task_created(task_list_id=list_id, record=rec)

        ids = [r.id for r in recs]
        # Compact summary message — don't flood the conversation with
        # one line per created task.
        if len(ids) == 1:
            range_label = f"#{ids[0]}"
        elif ids == list(range(ids[0], ids[-1] + 1)):
            range_label = f"#{ids[0]}-#{ids[-1]}"
        else:
            range_label = ", ".join(f"#{i}" for i in ids)
        return {
            "success": True,
            "task_list_id": list_id,
            "task_ids": ids,
            "message": (f"Created {len(ids)} task(s): {range_label}. Mark #{ids[0]} in_progress before starting it."),
            "tasks": [_serialize_task(r) for r in recs],
        }

    return execute


def _make_update_executor(store: TaskStore):
    async def execute(inputs: dict) -> dict[str, Any]:
        list_id = _resolve_list_id()
        if not list_id:
            return {"success": False, "error": "No task_list_id resolved for this agent."}
        agent_id = current_agent_id() or ""
        task_id = int(inputs["id"])

        status_in = inputs.get("status")
        # 'deleted' is a synthetic status — handle it as a separate path.
        if status_in == "deleted":
            deleted, cascade = await store.delete_task(list_id, task_id)
            if not deleted:
                return {
                    "success": False,
                    "task_list_id": list_id,
                    "task_id": task_id,
                    "message": f"Task #{task_id} not found (already deleted?)",
                }
            await emit_task_deleted(task_list_id=list_id, task_id=task_id, cascade=cascade)
            return {
                "success": True,
                "task_list_id": list_id,
                "task_id": task_id,
                "deleted": True,
                "cascade": cascade,
                "message": f"Task #{task_id} deleted.",
            }

        # Auto-owner on in_progress.
        owner_in = inputs.get("owner", _OwnerSentinel)
        status_enum = TaskStatus(status_in) if status_in else None
        if status_enum == TaskStatus.IN_PROGRESS and owner_in is _OwnerSentinel and agent_id:
            owner_in = agent_id

        # task_completed hook — fires BEFORE the write (Claude Code's
        # veto-before-write semantics). If the hook blocks, nothing
        # touches disk and no SSE event fires. The hook receives a
        # preview record with the intended new status so it can inspect
        # what's about to land.
        if status_enum == TaskStatus.COMPLETED:
            current = await store.get_task(list_id, task_id)
            if current is None:
                return {
                    "success": False,
                    "task_list_id": list_id,
                    "task_id": task_id,
                    "message": f"Task #{task_id} not found.",
                }
            if current.status != TaskStatus.COMPLETED:
                preview = current.model_copy(update={"status": TaskStatus.COMPLETED})
                try:
                    await run_task_hooks(
                        HOOK_TASK_COMPLETED,
                        task_list_id=list_id,
                        task=preview,
                        agent_id=agent_id,
                    )
                except BlockingHookError as exc:
                    logger.warning("task_completed hook blocked #%s: %s", task_id, exc)
                    return {
                        "success": False,
                        "task_list_id": list_id,
                        "task_id": task_id,
                        "message": f"Hook blocked completion of #{task_id}: {exc}",
                        "task": _serialize_task(current),
                    }

        # Hook passed (or wasn't applicable) — proceed with the write.
        new, fields = await store.update_task(
            list_id,
            task_id,
            subject=inputs.get("subject"),
            description=inputs.get("description"),
            active_form=inputs.get("active_form"),
            owner=owner_in if owner_in is not _OwnerSentinel else _UNSET,
            status=status_enum,
            add_blocks=inputs.get("add_blocks"),
            add_blocked_by=inputs.get("add_blocked_by"),
            metadata_patch=inputs.get("metadata_patch"),
        )
        if new is None:
            # "Task not found" is not an error — keep is_error=False semantics.
            return {
                "success": False,
                "task_list_id": list_id,
                "task_id": task_id,
                "message": f"Task #{task_id} not found.",
            }

        if fields:
            await emit_task_updated(task_list_id=list_id, record=new, fields=fields)

        # Layer 4: tool-result steering. When a task just completed,
        # peek at remaining work and append a focused next-step nudge.
        # For hive's solo (non-claim) model, point at the lowest-id
        # pending task or signal "all done".
        message = f"Task #{task_id} updated. Fields changed: {', '.join(fields) or '(none)'}."
        if status_enum == TaskStatus.COMPLETED and "status" in fields:
            others = await store.list_tasks(list_id)
            completed_ids = {r.id for r in others if r.status == TaskStatus.COMPLETED}
            next_pending = next(
                (
                    r
                    for r in others
                    if r.status == TaskStatus.PENDING and not [b for b in r.blocked_by if b not in completed_ids]
                ),
                None,
            )
            in_progress = [r for r in others if r.status == TaskStatus.IN_PROGRESS]
            if in_progress:
                names = ", ".join(f"#{r.id}" for r in in_progress[:3])
                message += f" Still in progress: {names}."
            elif next_pending is not None:
                message += (
                    f' Next pending: #{next_pending.id} — "{next_pending.subject}". '
                    f"Mark it in_progress before starting."
                )
            else:
                message += " All tasks complete. Wrap up: report results to the user and stop."

        return {
            "success": True,
            "task_list_id": list_id,
            "task_id": task_id,
            "fields": fields,
            "message": message,
            "task": _serialize_task(new),
        }

    return execute


def _make_list_executor(store: TaskStore):
    async def execute(inputs: dict) -> dict[str, Any]:
        list_id = _resolve_list_id()
        if not list_id:
            return {"success": False, "error": "No task_list_id resolved for this agent."}
        records = await store.list_tasks(list_id)
        # Filter resolved blockers from the rendering so a completed
        # blocker disappears from blocked_by.
        completed_ids = {r.id for r in records if r.status == TaskStatus.COMPLETED}
        rendered: list[str] = []
        for r in records:
            unresolved_blockers = [b for b in r.blocked_by if b not in completed_ids]
            line_parts = [f"#{r.id}", f"[{r.status.value}]", r.subject]
            if r.owner:
                line_parts.append(f"({r.owner})")
            if unresolved_blockers:
                line_parts.append(f"[blocked by {', '.join(f'#{b}' for b in unresolved_blockers)}]")
            rendered.append(" ".join(line_parts))
        return {
            "success": True,
            "task_list_id": list_id,
            "count": len(records),
            "lines": rendered,
            "tasks": [_serialize_task(r) for r in records],
        }

    return execute


def _make_get_executor(store: TaskStore):
    async def execute(inputs: dict) -> dict[str, Any]:
        list_id = _resolve_list_id()
        if not list_id:
            return {"success": False, "error": "No task_list_id resolved for this agent."}
        task_id = int(inputs["id"])
        rec = await store.get_task(list_id, task_id)
        if rec is None:
            return {
                "success": False,
                "task_list_id": list_id,
                "task_id": task_id,
                "message": f"Task #{task_id} not found.",
            }
        return {
            "success": True,
            "task_list_id": list_id,
            "task_id": task_id,
            "task": _serialize_task(rec),
        }

    return execute


# Sentinels so we can distinguish "owner not provided" from "owner=null".
class _OwnerSentinel:  # noqa: N801 — internal sentinel class
    pass


# ---------------------------------------------------------------------------
# Public registration
# ---------------------------------------------------------------------------


def build_session_tools(
    store: TaskStore | None = None,
) -> list[tuple[Tool, Any]]:
    """Build (Tool, executor) pairs for the session task tools."""
    s = store or get_task_store()
    return [
        (
            Tool(
                name="task_create_batch",
                description=_CREATE_BATCH_DESC,
                parameters=_create_batch_schema(),
                concurrency_safe=False,
            ),
            _make_create_batch_executor(s),
        ),
        (
            Tool(
                name="task_create",
                description=_CREATE_DESC,
                parameters=_create_schema(),
                concurrency_safe=False,
            ),
            _make_create_executor(s),
        ),
        (
            Tool(
                name="task_update",
                description=_UPDATE_DESC,
                parameters=_update_schema(),
                concurrency_safe=False,
            ),
            _make_update_executor(s),
        ),
        (
            Tool(
                name="task_list",
                description=_LIST_DESC,
                parameters=_list_schema(),
                concurrency_safe=True,
            ),
            _make_list_executor(s),
        ),
        (
            Tool(
                name="task_get",
                description=_GET_DESC,
                parameters=_get_schema(),
                concurrency_safe=True,
            ),
            _make_get_executor(s),
        ),
    ]
