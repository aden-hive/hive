"""Trigger definitions and missed-fire math for queen-level heartbeats.

A trigger's runtime is managed by ``framework.tools.queen_lifecycle_tools``
(``_start_trigger_timer`` / ``_start_trigger_webhook``); this module
holds the persistent shape and the pure helpers used to reconstruct
what ticks would have fired during a session-closed gap.

The session-load path in ``framework.server.session_manager`` calls
``compute_missed`` on every load and emits ``EventType.MISSED_TRIGGERS``
when the result is non-empty.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# Cap how many missed ticks we enumerate per trigger when reporting to
# the UI. Beyond this the ``count`` stays accurate but the ``ticks``
# list is truncated to keep the SSE payload bounded for very tight
# schedules over a long gap (e.g. */1 cron, multi-week absence).
_MAX_REPORTED_TICKS = 100


@dataclass
class TriggerDefinition:
    """A registered trigger configured on a colony.

    Trigger *definitions* come from the colony's ``triggers.json``.
    Whether a trigger fires depends on **two** things:

    1. ``enabled`` — a per-trigger configuration flag. "Should this
       trigger run when its colony's session is loaded?" Default
       True. Set from advanced settings; not a runtime state.
    2. The colony's session being loaded. Triggers don't fire while
       the session is closed; on next session load,
       ``compute_missed`` reconstructs the gap.

    ``last_fired_at`` and ``next_due_at`` are ISO8601 UTC strings
    persisted across restarts so the missed-trigger handshake can
    reconstruct which ticks would have fired during the closed
    period.
    """

    id: str
    trigger_type: str  # "timer" | "webhook"
    trigger_config: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    task: str = ""
    enabled: bool = False
    last_fired_at: str | None = None
    next_due_at: str | None = None


@dataclass
class MissedTrigger:
    """One trigger's missed-fire summary for the missed-trigger handshake."""

    trigger_id: str
    trigger_type: str
    count: int
    ticks: list[str] = field(default_factory=list)  # ISO8601 UTC, capped
    next_due_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "trigger_type": self.trigger_type,
            "count": self.count,
            "ticks": list(self.ticks),
            "next_due_at": self.next_due_at,
        }


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _missed_for_cron(cron_expr: str, since: datetime, now: datetime) -> tuple[int, list[str], str | None]:
    """Return (count, ticks_iso, next_due_iso) for a cron trigger.

    Counts how many cron matches lie strictly after ``since`` and at-or-
    before ``now``. ``next_due_at`` is the first match strictly after
    ``now`` (i.e. the next future fire).
    """
    try:
        from croniter import croniter
    except ImportError:
        logger.warning("croniter not installed; cannot compute missed cron ticks")
        return 0, [], None

    if not croniter.is_valid(cron_expr):
        return 0, [], None

    ticks: list[str] = []
    count = 0
    it = croniter(cron_expr, since)
    while True:
        nxt = it.get_next(datetime)
        if nxt > now:
            break
        count += 1
        if len(ticks) < _MAX_REPORTED_TICKS:
            ticks.append(nxt.astimezone(UTC).isoformat())

    future = croniter(cron_expr, now).get_next(datetime)
    next_due = future.astimezone(UTC).isoformat()
    return count, ticks, next_due


def _missed_for_interval(interval_minutes: float, since: datetime, now: datetime) -> tuple[int, list[str], str | None]:
    """Return (count, ticks_iso, next_due_iso) for an interval timer.

    Floors ``(now - since) / interval`` for the count. Ticks are the
    successive timestamps walking forward from ``since`` at
    ``interval`` steps, up to (and including) the last one that lies
    at-or-before ``now``.
    """
    if interval_minutes <= 0:
        return 0, [], None

    step = timedelta(minutes=interval_minutes)
    if now <= since:
        return 0, [], (since + step).astimezone(UTC).isoformat()

    elapsed = now - since
    count = int(elapsed / step)
    if count <= 0:
        return 0, [], (since + step).astimezone(UTC).isoformat()

    ticks: list[str] = []
    cursor = since + step
    while cursor <= now and len(ticks) < _MAX_REPORTED_TICKS:
        ticks.append(cursor.astimezone(UTC).isoformat())
        cursor += step

    next_due = (since + step * (count + 1)).astimezone(UTC).isoformat()
    return count, ticks, next_due


def compute_missed(
    triggers: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[MissedTrigger]:
    """Inspect persisted trigger entries and return missed-fire summaries.

    ``triggers`` is the raw list as read from ``triggers.json`` (each
    entry is the dict shape written by ``_save_trigger_to_agent``).

    Only entries with ``enabled=true`` are considered. Webhook triggers
    are never reported (event-driven, no schedule to reconstruct). A
    trigger with no ``last_fired_at`` (never fired since registration)
    contributes zero missed ticks — we don't retroactively fire for the
    period before it was first set up.

    Pure / side-effect-free.
    """
    if now is None:
        now = datetime.now(tz=UTC)
    else:
        now = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)

    out: list[MissedTrigger] = []
    for entry in triggers:
        if not entry.get("enabled"):
            continue
        ttype = entry.get("trigger_type")
        if ttype != "timer":
            continue  # webhook: skip

        last = _parse_iso(entry.get("last_fired_at"))
        if last is None:
            continue

        cfg = entry.get("trigger_config") or {}
        cron_expr = cfg.get("cron")
        interval = cfg.get("interval_minutes")

        if cron_expr:
            count, ticks, next_due = _missed_for_cron(cron_expr, last, now)
        elif interval:
            try:
                count, ticks, next_due = _missed_for_interval(float(interval), last, now)
            except (TypeError, ValueError):
                continue
        else:
            continue

        if count == 0:
            continue

        out.append(
            MissedTrigger(
                trigger_id=entry.get("id", ""),
                trigger_type=ttype,
                count=count,
                ticks=ticks,
                next_due_at=next_due,
            )
        )

    return out


def build_trigger_view(session: Any) -> list[dict[str, Any]]:
    """Project a session's triggers into a UI-ready list — the authoritative
    answer to "what triggers exist and what's their current status".

    Combines the DURABLE definitions (``available_triggers``, hydrated from the
    colony's ``triggers.json``) with LIVE runtime state: ``enabled`` (the trigger
    is in ``active_trigger_ids``), the next-fire countdown (``trigger_next_fire``),
    and fire stats (``trigger_fire_stats``). This is the single projection behind
    both the REST trigger endpoint and the SSE connect-time rehydration, so the
    UI can render its trigger cards from authoritative state instead of
    reconstructing them from SSE events — which age out of the bounded event
    history on a busy colony (the "only one / none show up" bug).

    Pure / side-effect-free. ``session`` is duck-typed (only attribute reads).
    """
    available = getattr(session, "available_triggers", {}) or {}
    if not available:
        return []
    active_ids = set(getattr(session, "active_trigger_ids", set()) or set())
    fire_times = getattr(session, "trigger_next_fire", {}) or {}
    fire_stats = getattr(session, "trigger_fire_stats", {}) or {}
    now_mono = time.monotonic()
    now_wall = time.time()

    out: list[dict[str, Any]] = []
    for t in available.values():
        config_out = dict(getattr(t, "trigger_config", {}) or {})
        mono = fire_times.get(t.id)
        if mono is not None:
            remaining = max(0.0, mono - now_mono)
            config_out["next_fire_in"] = remaining
            config_out["next_fire_at"] = int((now_wall + remaining) * 1000)
        stats = fire_stats.get(t.id)
        if stats:
            config_out["fire_count"] = stats.get("fire_count", 0)
            if stats.get("last_fired_at") is not None:
                config_out["last_fired_at"] = stats["last_fired_at"]
        out.append(
            {
                "trigger_id": t.id,
                "trigger_type": t.trigger_type,
                "trigger_config": config_out,
                "name": getattr(t, "description", None) or t.id,
                "task": getattr(t, "task", "") or "",
                "enabled": t.id in active_ids,
                "last_fired_at": getattr(t, "last_fired_at", None),
                "next_due_at": getattr(t, "next_due_at", None),
            }
        )
    return out
