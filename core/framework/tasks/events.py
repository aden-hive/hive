"""Bridge from the task store to the EventBus.

The store is intentionally event-free — it's pure storage. The tool
executors (and run_parallel_workers, and any future colony_template_*
caller) are responsible for emitting the lifecycle events to the bus
after successful mutations.

Events are scoped to a stream_id pulled from the execution context if
available; otherwise they fan out at the global ``primary`` stream so the
UI's broad subscriptions still see them.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.tasks.models import TaskRecord

logger = logging.getLogger(__name__)

# Process-global default — set by the runner / orchestrator at bringup.
_DEFAULT_BUS: EventBus | None = None


def set_default_event_bus(bus: EventBus | None) -> None:
    global _DEFAULT_BUS
    _DEFAULT_BUS = bus


def _get_bus(bus: EventBus | None = None) -> EventBus | None:
    return bus or _DEFAULT_BUS


def _serialize_record(rec: TaskRecord) -> dict[str, Any]:
    return {
        "id": rec.id,
        "subject": rec.subject,
        "description": rec.description,
        "active_form": rec.active_form,
        "owner": rec.owner,
        "status": rec.status.value,
        "blocks": list(rec.blocks),
        "blocked_by": list(rec.blocked_by),
        "metadata": dict(rec.metadata),
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
    }


async def emit_task_created(
    *,
    task_list_id: str,
    record: TaskRecord,
    stream_id: str = "primary",
    bus: EventBus | None = None,
) -> None:
    b = _get_bus(bus)
    if b is None:
        return
    try:
        await b.publish(
            AgentEvent(
                type=EventType.TASK_CREATED,
                stream_id=stream_id,
                data={
                    "task_list_id": task_list_id,
                    "task": _serialize_record(record),
                },
            )
        )
    except Exception:
        logger.debug("emit_task_created failed", exc_info=True)


async def emit_task_updated(
    *,
    task_list_id: str,
    record: TaskRecord,
    fields: list[str],
    stream_id: str = "primary",
    bus: EventBus | None = None,
) -> None:
    b = _get_bus(bus)
    if b is None or not fields:
        return
    try:
        await b.publish(
            AgentEvent(
                type=EventType.TASK_UPDATED,
                stream_id=stream_id,
                data={
                    "task_list_id": task_list_id,
                    "task_id": record.id,
                    "after": _serialize_record(record),
                    "fields": fields,
                },
            )
        )
    except Exception:
        logger.debug("emit_task_updated failed", exc_info=True)


async def emit_task_deleted(
    *,
    task_list_id: str,
    task_id: int,
    cascade: list[int],
    stream_id: str = "primary",
    bus: EventBus | None = None,
) -> None:
    b = _get_bus(bus)
    if b is None:
        return
    try:
        await b.publish(
            AgentEvent(
                type=EventType.TASK_DELETED,
                stream_id=stream_id,
                data={
                    "task_list_id": task_list_id,
                    "task_id": task_id,
                    "cascade": cascade,
                },
            )
        )
    except Exception:
        logger.debug("emit_task_deleted failed", exc_info=True)


async def emit_colony_template_assignment(
    *,
    colony_id: str,
    task_id: int,
    assigned_session: str | None,
    assigned_worker_id: str | None,
    stream_id: str = "primary",
    bus: EventBus | None = None,
) -> None:
    b = _get_bus(bus)
    if b is None:
        return
    try:
        await b.publish(
            AgentEvent(
                type=EventType.COLONY_TEMPLATE_ASSIGNMENT,
                stream_id=stream_id,
                data={
                    "colony_id": colony_id,
                    "task_id": task_id,
                    "assigned_session": assigned_session,
                    "assigned_worker_id": assigned_worker_id,
                },
            )
        )
    except Exception:
        logger.debug("emit_colony_template_assignment failed", exc_info=True)
