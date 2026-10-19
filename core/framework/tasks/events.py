"""Bridge from the task store to the EventBus.

The store is intentionally event-free — it's pure storage. The tool
executors (and run_worker) are responsible for emitting the
lifecycle events to the bus after successful mutations.

Events are scoped to a stream_id pulled from the execution context if
available; otherwise they fan out at the global ``primary`` stream so the
UI's broad subscriptions still see them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.tasks.models import TaskRecord

logger = logging.getLogger(__name__)

# Process-global default — set by the runner / orchestrator at bringup.
# Last-writer-wins, so with multiple live colonies/sessions it points at
# whichever booted last. Used only as a fallback now; prefer the resolver.
_DEFAULT_BUS: EventBus | None = None

# Resolver: session_id -> that session's EventBus. Registered at server
# bringup (backed by SessionManager). Task events for session X must land on
# session X's OWN bus — the bus its SSE clients subscribe to — not whatever
# the global default last happened to be. Without this, an SSE-connected task
# panel for an earlier colony silently misses live diffs once a newer colony
# overwrites the default (the snapshot still works, masking it).
_BUS_RESOLVER: Callable[[str], EventBus | None] | None = None


def set_default_event_bus(bus: EventBus | None) -> None:
    global _DEFAULT_BUS
    _DEFAULT_BUS = bus


def set_bus_resolver(resolver: Callable[[str], EventBus | None] | None) -> None:
    global _BUS_RESOLVER
    _BUS_RESOLVER = resolver


def _get_bus(bus: EventBus | None = None, session_id: str | None = None) -> EventBus | None:
    if bus is not None:
        return bus
    if session_id and _BUS_RESOLVER is not None:
        try:
            resolved = _BUS_RESOLVER(session_id)
        except Exception:
            logger.debug("task bus resolver failed for %s", session_id, exc_info=True)
            resolved = None
        if resolved is not None:
            return resolved
    return _DEFAULT_BUS


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
    session_id: str,
    record: TaskRecord,
    stream_id: str = "primary",
    bus: EventBus | None = None,
) -> None:
    b = _get_bus(bus, session_id)
    if b is None:
        return
    try:
        await b.publish(
            AgentEvent(
                type=EventType.TASK_CREATED,
                stream_id=stream_id,
                data={
                    "session_id": session_id,
                    "task": _serialize_record(record),
                },
            )
        )
    except Exception:
        logger.debug("emit_task_created failed", exc_info=True)


async def emit_task_updated(
    *,
    session_id: str,
    record: TaskRecord,
    fields: list[str],
    stream_id: str = "primary",
    bus: EventBus | None = None,
) -> None:
    b = _get_bus(bus, session_id)
    if b is None or not fields:
        return
    try:
        await b.publish(
            AgentEvent(
                type=EventType.TASK_UPDATED,
                stream_id=stream_id,
                data={
                    "session_id": session_id,
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
    session_id: str,
    task_id: int,
    cascade: list[int],
    stream_id: str = "primary",
    bus: EventBus | None = None,
) -> None:
    b = _get_bus(bus, session_id)
    if b is None:
        return
    try:
        await b.publish(
            AgentEvent(
                type=EventType.TASK_DELETED,
                stream_id=stream_id,
                data={
                    "session_id": session_id,
                    "task_id": task_id,
                    "cascade": cascade,
                },
            )
        )
    except Exception:
        logger.debug("emit_task_deleted failed", exc_info=True)
