"""The session task tools: task_create, task_update, task_list, task_get.

All operate on the calling agent's OWN session list — resolved from the
execution context. There is no other kind of task list.

``task_create`` always takes a ``tasks`` array — one entry or many,
created atomically. There is no separate single-task tool.

Concurrency safety:
    task_list, task_get                -> concurrency_safe=True (reads)
    task_create, task_update           -> concurrency_safe=False

Tool names are defined once in ``names.py`` — the single source of truth.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

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
    current_session_id,
)
from framework.tasks.tools.names import (
    TASK_CREATE,
    TASK_GET,
    TASK_LIST,
    TASK_UPDATE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pivot handler — agent-supplied "fork to a new context" behavior
# ---------------------------------------------------------------------------


PivotKind = Literal["new_session", "new_colony"]


@dataclass
class PivotHandler:
    """Per-agent strategy for forking the task plan into a new context.

    The task system itself stays generic — it knows there is a pivot
    field on ``task_create`` and that it calls ``handle`` when the LLM
    sets that field, but knows nothing about sessions or colonies. The
    agent's wiring layer (today: ``queen_orchestrator``) decides which
    field to expose and what the fork actually does.

    Fields:
        field_name: schema key the pivot bool lives under. Drives the
            LLM-facing name ("new_session" for DM queens, "new_colony"
            for colony queens) so the model gets phase-appropriate
            vocabulary.
        field_description: LLM-facing rationale shown in the schema —
            describes when to set the bool true and what happens after.
        handle: called with (goal, handoff, tasks) when the bool is set.
            Returns the dict the executor passes back to the LLM.
    """

    field_name: PivotKind
    field_description: str
    handle: Callable[..., Awaitable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Schemas (Anthropic-style JSONSchema)
# ---------------------------------------------------------------------------


_TASK_STATUS_VALUES = ["pending", "in_progress", "completed", "archived", "deleted"]


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
            "status": {
                "type": "string",
                "enum": _TASK_STATUS_VALUES,
                "description": (
                    "pending / in_progress / completed track work. "
                    "'archived' moves a finished or no-longer-relevant task "
                    "out of the active plan into the user's History "
                    "(preserved, unlike 'deleted' which removes it "
                    "permanently). Archiving is reversible: set an archived "
                    "task back to pending/in_progress/completed to restore "
                    "it to the active plan (use task_list "
                    "include_archived=true to find archived ids)."
                ),
            },
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
    return {
        "type": "object",
        "properties": {
            "include_archived": {
                "type": "boolean",
                "description": (
                    "Include archived tasks (default false). Set true to "
                    "review what you archived — e.g. before restoring one "
                    "by editing its status back to pending/in_progress."
                ),
            },
        },
    }


def _get_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }


def _create_schema(pivot_handler: PivotHandler | None = None) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "goal": {
            "type": "string",
            "description": (
                "One-sentence statement of what this plan is for, in the "
                "user's own terms. Required on the FIRST task_create of a "
                "session — anchors the work so a later batch that drifts "
                "from this can be recognised as a real pivot rather than "
                "absorbed silently. On follow-up task_create calls in the "
                "same session, you MAY omit it (the existing goal is "
                "kept) OR re-state it unchanged. Provide a NEW goal only "
                "when you are also setting the pivot field below — the "
                "new goal then anchors the forked context."
            ),
        },
        "tasks": {
            "type": "array",
            "minItems": 1,
            "description": ("Array of task specs. Each becomes one task with a sequential id. Atomic — all created or none."),
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
        },
    }
    if pivot_handler is not None:
        properties[pivot_handler.field_name] = {
            "type": "boolean",
            "description": pivot_handler.field_description,
        }
        properties["handoff"] = {
            "type": "string",
            "description": (
                f"Required when {pivot_handler.field_name}=true. The new "
                "context inherits NOTHING from this conversation except "
                "what you write here — no transcript, no summary, no "
                "scrollback. So write a COMPLETE, self-contained "
                "handoff: everything the new context needs to know to "
                "carry the task plan through to done.\n\n"
                "Be descriptive and objective — state facts, not "
                "impressions. Cover, as applicable:\n"
                "- The user's actual goal and intent for this work, in "
                "their own terms.\n"
                "- Concrete facts and data established so far: names, "
                "URLs, IDs, file paths, the account/alias to use, "
                "numbers, exact requirements and wording.\n"
                "- Decisions already made, and options already "
                "considered and ruled out (with the reason).\n"
                "- Constraints, preferences, deadlines, and what 'done' "
                "looks like.\n"
                "- Anything already attempted or partially completed "
                "that the new context must not redo.\n\n"
                "The new context cannot look back — if a detail matters "
                "for finishing the task and is not already in a task "
                "subject/description, it MUST be in this handoff. Write "
                "it in full now, while you still have the whole "
                "conversation in view. Ignored when "
                f"{pivot_handler.field_name} is false."
            ),
        }
    return {
        "type": "object",
        "properties": properties,
        "required": ["tasks"],
    }


# ---------------------------------------------------------------------------
# Tool descriptions
# ---------------------------------------------------------------------------

_UPDATE_DESC = (
    "Update ONE task on your own session task list. There is no batch "
    "update tool by design — every `completed` transition is a discrete "
    "progress signal to the user.\n\n"
    "Workflow:\n"
    "- Mark a task `in_progress` BEFORE you start working on it.\n"
    "- Mark it `completed` AS SOON as you finish it — do not let "
    "multiple finished tasks pile up unmarked before flushing them at "
    "the end of the run.\n"
    "- Archive tasks: when the user asks you to refresh/tidy the plan, set "
    "status='archived' on finished or no-longer-relevant tasks to move "
    "them out of the active plan into the user's History. Archived tasks "
    "are preserved and hidden from the default `task_list` — pass "
    "include_archived=true to see them. Archiving is reversible: edit an "
    "archived task's status back to pending/in_progress/completed to pull "
    "it back into the active plan.\n"
    "- Delete tasks: when a task is no longer relevant or was created "
    "in error. Setting status='deleted' **permanently** removes the "
    "task — the id is retired and cannot be reused. Prefer 'archived' "
    "over 'deleted' unless the task was a genuine mistake.\n\n"
    "ONLY mark `completed` when the task is FULLY done. If you hit errors, "
    "blockers, or partial state, keep it `in_progress` and create a new "
    "task describing what's blocking. Never mark completed with caveats; "
    "if it's not done, it's not done.\n\n"
    "Setting status='in_progress' without owner auto-fills your agent_id."
)

_LIST_DESC = (
    "Show your session task list, sorted by id ascending. Internal tasks "
    "(metadata._internal=true), resolved blockers, and archived tasks are "
    "filtered out by default; pass include_archived=true to also see "
    "archived tasks (e.g. to restore one). **Prefer working on tasks in id "
    "order** (lowest first) — earlier tasks usually set up context for "
    "later ones."
)

_GET_DESC = (
    "Read the full record of one task (description, metadata, timestamps) "
    "from your own session task list. Use this to refresh your view of a "
    "task before updating it if you're not sure of current fields."
)

_CREATE_DESC = (
    "Use this tool to create a structured task list for your current "
    "session. The list renders as a live widget in the user's right-rail "
    "panel — it helps the user understand progress on their request and "
    "demonstrates thoroughness.\n\n"
    "**Always takes a `tasks` array — one entry or many, created "
    "atomically (all-or-none).** Replying to 5 posts is ONE `task_create` "
    "with 5 entries. A single one-off mid-run addition is ONE "
    "`task_create` with a 1-entry array.\n\n"
    "**GTM work:** if the plan is about people / leads / accounts / "
    "outreach, include a CLAIM task (dedup leads in the global CRM before "
    "outreach) and a PROMOTE task (write results to the CRM after) — the "
    "shared CRM is a planned deliverable, not an afterthought.\n\n"
    "## When to use this tool\n\n"
    "Use this tool proactively in these scenarios:\n"
    "- **Multi-step requests** — when a request requires 2+ distinct "
    "atomic actions\n"
    "- **Non-trivial work** — anything involving careful planning or "
    "multiple operations (browser automation, file edits, API calls, "
    "fan-out to workers)\n"
    "- **User provides multiple tasks** — a list of things to do "
    "(numbered or comma-separated)\n"
    "- **After receiving REFINING instructions** — if the new request "
    "refines the existing plan (same goal, more detail), capture the "
    "changes as tasks and delete prior ones via `task_update` "
    "status='deleted'. If the new request is OFF-GOAL — different goal "
    "from this list's anchor — DON'T wipe and redo here; use the pivot "
    "field on this same tool instead.\n"
    "- **Mid-run additions** — when you discover unplanned work after "
    "the initial plan is laid out, add it with a 1-entry array\n"
    "- **User explicitly requests a plan or task list**\n\n"
    "## When NOT to use this tool\n\n"
    "Skip this tool when:\n"
    "- There is only a single, straightforward action (one terminal_exec, "
    "one `hive-browser open`, one tracker_query)\n"
    "- The task is trivial and tracking it provides no organizational "
    "benefit\n"
    "- The request is purely conversational or informational (greetings, "
    "questions, opinions)\n"
    "- The user has explicitly asked you not to use it\n\n"
    "## Task fields\n\n"
    "- **subject**: short imperative title (e.g. 'Crawl target URL')\n"
    "- **description**: optional, slightly longer 'what to do' note\n"
    "- **active_form**: present-continuous label shown while in_progress "
    "(e.g. 'Crawling target URL'). If omitted, the spinner shows the "
    "subject\n"
    "- **metadata**: optional KV. Set _internal=true to hide from "
    "`task_list`\n\n"
    "All tasks are created with status `pending`.\n\n"
    "## Tips\n\n"
    "- Subjects should be clear and outcome-focused\n"
    "- **Granularity: one task/batch per atomic action, not one umbrella per "
    'project** — "Scrape 5 LinkedIn profiles" is 5 entries, not 1\n'
    "- Include a final **verification step** for any non-trivial plan "
    "(re-read the diff, query the tracker for gaps, screenshot the "
    "result, run the script end-to-end)\n"
    "- Check `task_list` first to avoid creating duplicate tasks"
)


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


def _resolve_session_id() -> str | None:
    """Pull the calling agent's session_id from execution context."""
    return current_session_id()


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


def _make_create_executor(store: TaskStore, pivot_handler: PivotHandler | None = None):
    async def execute(inputs: dict) -> dict[str, Any]:
        session_id = _resolve_session_id()
        if not session_id:
            return {"success": False, "error": "No session_id resolved for this agent."}
        agent_id = current_agent_id() or ""
        specs = inputs.get("tasks") or []
        if not isinstance(specs, list) or not specs:
            return {
                "success": False,
                "error": "task_create requires a non-empty `tasks` array.",
            }

        goal_in = inputs.get("goal")
        goal = goal_in.strip() if isinstance(goal_in, str) else None

        # First-call gate: the very first task_create of a session MUST
        # anchor a goal. Without it a later batch can drift the plan
        # without any reference to compare against — defeats the whole
        # pivot-vs-continuation decision.
        existing_meta = await store.get_meta(session_id)
        is_first_create = existing_meta is None or existing_meta.goal is None
        if is_first_create and not goal:
            return {
                "success": False,
                "error": (
                    "task_create on a fresh task list requires a `goal` — "
                    "one sentence describing what this plan is for, in "
                    "the user's terms. The goal anchors the plan so a "
                    "later batch that drifts from it can be recognised "
                    "as a real pivot. Call task_create again with `goal` "
                    "set."
                ),
            }

        # Pivot branch: fork into a new context (session for DM, colony
        # for colony-phase queens) and seed THIS plan there instead of
        # the current list. Only wired for the queen — the handler is
        # None for workers / colony stages, so the schema omits the
        # field for them and this branch is unreachable.
        if pivot_handler is not None and inputs.get(pivot_handler.field_name):
            if not goal:
                return {
                    "success": False,
                    "error": (
                        f"{pivot_handler.field_name}=true requires a "
                        "`goal` — state the new context's goal in one "
                        "sentence, in the user's terms. The new context "
                        "anchors on this."
                    ),
                }
            return await pivot_handler.handle(
                goal=goal,
                handoff=inputs.get("handoff"),
                tasks=specs,
            )

        # Storage layer validates subject; surface its error as a soft
        # tool_result so sibling tools don't cancel. ``goal`` is only
        # written when the caller supplied one (skipped on follow-up
        # calls so the existing anchor isn't accidentally cleared).
        try:
            recs = await store.create_tasks_batch(session_id, specs, goal=goal)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        # Run task_created hooks per task; blocking on any aborts the
        # whole batch (delete every record we just wrote, return error).
        for rec in recs:
            try:
                await run_task_hooks(
                    HOOK_TASK_CREATED,
                    session_id=session_id,
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
                    await store.delete_task(session_id, r.id)
                return {
                    "success": False,
                    "error": (f"Hook blocked task #{rec.id} ({rec.subject!r}); entire batch rolled back: {exc}"),
                }

        for rec in recs:
            await emit_task_created(session_id=session_id, record=rec)

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
            "session_id": session_id,
            "task_ids": ids,
            "message": (f"Created {len(ids)} task(s): {range_label}. Mark #{ids[0]} in_progress before starting it."),
            "tasks": [_serialize_task(r) for r in recs],
        }

    return execute


def _make_update_executor(store: TaskStore):
    async def execute(inputs: dict) -> dict[str, Any]:
        session_id = _resolve_session_id()
        if not session_id:
            return {"success": False, "error": "No session_id resolved for this agent."}
        agent_id = current_agent_id() or ""
        task_id = int(inputs["id"])

        # One read up front — reused by the completion hook below. Archived
        # tasks are editable: setting a non-archived status un-archives one
        # (the store strips the archived_* markers), which is how the agent
        # pulls something back out of history.
        current = await store.get_task(session_id, task_id)

        status_in = inputs.get("status")
        # 'deleted' is a synthetic status — handle it as a separate path.
        if status_in == "deleted":
            deleted, cascade = await store.delete_task(session_id, task_id)
            if not deleted:
                return {
                    "success": False,
                    "session_id": session_id,
                    "task_id": task_id,
                    "message": f"Task #{task_id} not found (already deleted?)",
                }
            await emit_task_deleted(session_id=session_id, task_id=task_id, cascade=cascade)
            return {
                "success": True,
                "session_id": session_id,
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
            if current is None:
                return {
                    "success": False,
                    "session_id": session_id,
                    "task_id": task_id,
                    "message": f"Task #{task_id} not found.",
                }
            if current.status != TaskStatus.COMPLETED:
                preview = current.model_copy(update={"status": TaskStatus.COMPLETED})
                try:
                    await run_task_hooks(
                        HOOK_TASK_COMPLETED,
                        session_id=session_id,
                        task=preview,
                        agent_id=agent_id,
                    )
                except BlockingHookError as exc:
                    logger.warning("task_completed hook blocked #%s: %s", task_id, exc)
                    return {
                        "success": False,
                        "session_id": session_id,
                        "task_id": task_id,
                        "message": f"Hook blocked completion of #{task_id}: {exc}",
                        "task": _serialize_task(current),
                    }

        # Hook passed (or wasn't applicable) — proceed with the write.
        new, fields = await store.update_task(
            session_id,
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
                "session_id": session_id,
                "task_id": task_id,
                "message": f"Task #{task_id} not found.",
            }

        if fields:
            await emit_task_updated(session_id=session_id, record=new, fields=fields)

        # Layer 4: tool-result steering. When a task just completed,
        # peek at remaining work and append a focused next-step nudge.
        # For hive's solo (non-claim) model, point at the lowest-id
        # pending task or signal "all done".
        message = f"Task #{task_id} updated. Fields changed: {', '.join(fields) or '(none)'}."
        if status_enum == TaskStatus.COMPLETED and "status" in fields:
            others = await store.list_tasks(session_id)
            completed_ids = {r.id for r in others if r.status == TaskStatus.COMPLETED}
            next_pending = next(
                (r for r in others if r.status == TaskStatus.PENDING and not [b for b in r.blocked_by if b not in completed_ids]),
                None,
            )
            in_progress = [r for r in others if r.status == TaskStatus.IN_PROGRESS]
            if in_progress:
                names = ", ".join(f"#{r.id}" for r in in_progress[:3])
                message += f" Still in progress: {names}."
            elif next_pending is not None:
                message += f' Next pending: #{next_pending.id} — "{next_pending.subject}". Mark it in_progress before starting.'
            else:
                # "All complete" is the moment the queen is most likely
                # to consider a follow-up request as continuation when it
                # is actually a pivot. Remind her of the anchor so she
                # judges the next user turn against the right yardstick.
                meta = await store.get_meta(session_id)
                if meta is not None and meta.goal:
                    message += (
                        f" All tasks complete (goal: {meta.goal}). Wrap up: "
                        "report results to the user and stop. If the user "
                        "follows up with work that doesn't fit this goal, "
                        "treat it as a pivot, not a continuation."
                    )
                else:
                    message += " All tasks complete. Wrap up: report results to the user and stop."

        return {
            "success": True,
            "session_id": session_id,
            "task_id": task_id,
            "fields": fields,
            "message": message,
            "task": _serialize_task(new),
        }

    return execute


def _make_list_executor(store: TaskStore):
    async def execute(inputs: dict) -> dict[str, Any]:
        session_id = _resolve_session_id()
        if not session_id:
            return {"success": False, "error": "No session_id resolved for this agent."}
        # Archived tasks are tucked into history — hidden from the default
        # listing so the working plan stays clean, but shown when the agent
        # asks (include_archived=true) so it can review or restore them.
        # Filtering here (not in store.list_tasks) keeps the REST snapshot
        # serving archived tasks to the panel's History view.
        include_archived = bool(inputs.get("include_archived"))
        records = await store.list_tasks(session_id)
        if not include_archived:
            records = [r for r in records if r.status is not TaskStatus.ARCHIVED]
        meta = await store.get_meta(session_id)
        goal = meta.goal if meta is not None else None
        # Filter resolved blockers from the rendering so a completed
        # blocker disappears from blocked_by.
        completed_ids = {r.id for r in records if r.status == TaskStatus.COMPLETED}
        rendered: list[str] = []
        # Lead with the stored goal so a queen scanning task_list before
        # deciding whether a new batch is a pivot has the anchor in view.
        if goal:
            rendered.append(f"Goal: {goal}")
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
            "session_id": session_id,
            "count": len(records),
            "goal": goal,
            "lines": rendered,
            "tasks": [_serialize_task(r) for r in records],
        }

    return execute


def _make_get_executor(store: TaskStore):
    async def execute(inputs: dict) -> dict[str, Any]:
        session_id = _resolve_session_id()
        if not session_id:
            return {"success": False, "error": "No session_id resolved for this agent."}
        task_id = int(inputs["id"])
        rec = await store.get_task(session_id, task_id)
        if rec is None:
            return {
                "success": False,
                "session_id": session_id,
                "task_id": task_id,
                "message": f"Task #{task_id} not found.",
            }
        return {
            "success": True,
            "session_id": session_id,
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
    *,
    pivot_handler: PivotHandler | None = None,
) -> list[tuple[Tool, Any]]:
    """Build (Tool, executor) pairs for the session task tools.

    ``pivot_handler`` — when provided (queen only), exposes the pivot
    field (``new_session`` for DM queens, ``new_colony`` for colony
    queens) on ``task_create``. The handler's ``handle(goal, handoff,
    tasks)`` is invoked when the bool is set; it forks into the new
    context and seeds the plan there. Workers / colony stages pass None,
    so the field is absent from their schema and this branch is
    unreachable.
    """
    s = store or get_task_store()
    return [
        (
            Tool(
                name=TASK_CREATE,
                description=_CREATE_DESC,
                parameters=_create_schema(pivot_handler=pivot_handler),
                concurrency_safe=False,
            ),
            _make_create_executor(s, pivot_handler),
        ),
        (
            Tool(
                name=TASK_UPDATE,
                description=_UPDATE_DESC,
                parameters=_update_schema(),
                concurrency_safe=False,
            ),
            _make_update_executor(s),
        ),
        (
            Tool(
                name=TASK_LIST,
                description=_LIST_DESC,
                parameters=_list_schema(),
                concurrency_safe=True,
            ),
            _make_list_executor(s),
        ),
        (
            Tool(
                name=TASK_GET,
                description=_GET_DESC,
                parameters=_get_schema(),
                concurrency_safe=True,
            ),
            _make_get_executor(s),
        ),
    ]
