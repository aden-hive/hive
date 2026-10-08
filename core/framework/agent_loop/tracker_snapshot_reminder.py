"""Tracker-state snapshot reminders, driven by the colony's own cadence.

Two sibling sources surface the colony's tracker tables — table name +
row count — plus a one-line nudge to persist progress before context
pruning drops in-memory state. Both fire at
:attr:`ReminderPoint.POST_TOOL_USE` and own their own timing; neither
rides the tool-budget checkpoint anymore.

  * :class:`TrackerSnapshotReminderSource` — **queen only, colony only.**
    Driven by the queen's tool activity: fires the first time after a few
    tool turns, then on a cooldown. Its primary job is to nudge the queen
    to *create* a tracker table in the first place, so it fires even when
    no table exists yet (a soft "set one up" suggestion); once tables
    exist it surfaces them instead. The cooldown is shorter while the
    tracker is empty (``QUEEN_COOLDOWN_NO_TABLE``) than once a table
    exists (``QUEEN_COOLDOWN_WITH_TABLE``).
  * :class:`WorkerTrackerSnapshotReminderSource` — **worker only, colony
    only.** Workers browse constantly, so a browser gate is meaningless
    for them; instead they get a tool-call cadence — one reminder every
    ``WORKER_CADENCE_TOOL_CALLS`` tool calls. This is the worker's own
    independent counter, not the shared tool-budget checkpoint.

For both sources, using any tracker tool resets the cooldown — there's no
point nudging an agent that's already working the tracker.

Both self-skip outside a colony: ``colony_binding_provider`` resolves to
``None`` for an independent / pre-fork queen, and the binding is also
what carries the tracker DB path to snapshot.

All state is in-memory per ``AgentLoop`` — these are advisory and a
restart resetting the counters is harmless.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any

from framework.agent_loop.reminders import (
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)

# Render-path bounds. The source runs inline at each fire, so cap both
# rows enumerated and wall-clock time spent. WAL-mode SQLite is
# microseconds per COUNT(*), but a corrupted / very large DB shouldn't
# stall a reminder.
_MAX_TABLES = 10
_QUERY_BUDGET_SECONDS = 0.05

# Prefix shared by every tracker tool (tracker_upsert, tracker_sql,
# tracker_query, tracker_register_writable — see framework.tools.tracker_tools).
# A turn that uses one means the agent just touched the tracker, so the
# reminder's cooldown is reset: no need to nudge someone already on it.
_TRACKER_TOOL_PREFIX = "tracker_"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Queen path: tool turns before the first reminder, then the minimum turns
# between successive reminders. The cooldown is shorter while no tracker
# table exists (keep nudging the queen to create one) and longer once one
# does (just keep it fresh).
QUEEN_FIRST_FIRE_TURNS = _env_int("HIVE_TRACKER_QUEEN_FIRST_FIRE", 3)
QUEEN_COOLDOWN_NO_TABLE = _env_int("HIVE_TRACKER_QUEEN_COOLDOWN_NO_TABLE", 10)
QUEEN_COOLDOWN_WITH_TABLE = _env_int("HIVE_TRACKER_QUEEN_COOLDOWN_WITH_TABLE", 20)
# Worker path: tool calls between successive reminders (no browser gate,
# since workers browse as their normal work). Counted independently of the
# shared tool-budget checkpoint; 20 mirrors the worker's default budget.
WORKER_CADENCE_TOOL_CALLS = _env_int("HIVE_TRACKER_WORKER_TOOL_CALLS", 20)


def _used_tracker_tool(tool_names: list[str]) -> bool:
    """True if the turn used any tracker tool — triggers a cooldown reset."""
    return any(n.startswith(_TRACKER_TOOL_PREFIX) for n in tool_names)


class TrackerSnapshotReminderSource(ReminderSource):
    """Queen-only, in-colony tracker nudge, driven by tool activity.

    Fires at :attr:`ReminderPoint.POST_TOOL_USE` after the queen's first
    few tool turns, then on a cooldown between reminders.

    Its main purpose is to gently steer the queen toward setting up a
    tracker table, so unlike the worker source it fires even when the
    tracker is empty — the empty case *is* the message. The cooldown is
    shorter while no table exists (:data:`QUEEN_COOLDOWN_NO_TABLE`) and
    longer once one does (:data:`QUEEN_COOLDOWN_WITH_TABLE`). Using any
    tracker tool resets the cooldown — no point nudging a queen who's
    already working the tracker.
    """

    name = "tracker_snapshot"

    def __init__(
        self,
        *,
        first_fire_turns: int = QUEEN_FIRST_FIRE_TURNS,
        cooldown_no_table: int = QUEEN_COOLDOWN_NO_TABLE,
        cooldown_with_table: int = QUEEN_COOLDOWN_WITH_TABLE,
    ) -> None:
        self._first_fire_turns = first_fire_turns
        self._cooldown_no_table = cooldown_no_table
        self._cooldown_with_table = cooldown_with_table
        # Count of turns that used any tool — gates the first fire.
        self._tool_turns = 0
        # Turns since the last reminder (or last tracker-tool use) — gates
        # the steady-state cooldown.
        self._turns_since_last_reminder = 0
        # Whether the first fire has happened yet.
        self._has_fired = False

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.POST_TOOL_USE}

    def applies_to(self, agent_ctx: Any) -> bool:
        # Queen only. Binding presence is rechecked per render because a
        # queen forks into a colony mid-session — the provider is wired
        # once, but its return value (and the tracker DB) appears later.
        if not bool(getattr(agent_ctx, "is_queen_stream", False)):
            return False
        return getattr(agent_ctx, "colony_binding_provider", None) is not None

    def observe_turn(self, tool_names: list[str]) -> None:
        # A tracker-tool turn resets the cooldown: the queen just touched
        # the tracker, so hold off on nudging.
        if _used_tracker_tool(tool_names):
            self._turns_since_last_reminder = 0
            return
        self._turns_since_last_reminder += 1
        if tool_names:
            self._tool_turns += 1

    async def render(self, rctx: ReminderContext) -> str | None:
        # Cheap pre-checks before opening the DB. Before the first fire,
        # wait for a few tool turns; after, wait at least the shorter
        # (no-table) cooldown — the exact threshold depends on whether a
        # table exists, decided below once we've read the DB.
        if not self._has_fired:
            if self._tool_turns < self._first_fire_turns:
                return None
        elif self._turns_since_last_reminder < self._cooldown_no_table:
            return None
        binding = _resolve_binding(rctx.agent_ctx)
        if binding is None:
            return None
        # Fire even when there are no tables yet — the reminder's main job
        # is to nudge the queen to *create* a tracker table. The cooldown is
        # shorter until one exists, longer afterwards.
        rows = _snapshot_tables(binding.tracker_db)
        if self._has_fired:
            cooldown = self._cooldown_with_table if rows else self._cooldown_no_table
            if self._turns_since_last_reminder < cooldown:
                return None
        self._has_fired = True
        self._turns_since_last_reminder = 0
        return _render_queen_body(rows)


class WorkerTrackerSnapshotReminderSource(ReminderSource):
    """Worker-only, in-colony tracker snapshot on a tool-call cadence.

    Fires at :attr:`ReminderPoint.POST_TOOL_USE` once every
    :data:`WORKER_CADENCE_TOOL_CALLS` tool calls. No browser gate — a
    worker's browser calls are its normal work, not a special signal. The
    counter is the source's own, independent of the shared tool-budget
    checkpoint, and is reset whenever the worker uses a tracker tool.
    """

    name = "worker_tracker_snapshot"

    def __init__(self, *, cadence_tool_calls: int = WORKER_CADENCE_TOOL_CALLS) -> None:
        self._cadence_tool_calls = cadence_tool_calls
        self._tool_calls_since_last_reminder = 0

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.POST_TOOL_USE}

    def applies_to(self, agent_ctx: Any) -> bool:
        # Workers only (the queen has her own tool-activity source).
        if bool(getattr(agent_ctx, "is_queen_stream", False)):
            return False
        return getattr(agent_ctx, "colony_binding_provider", None) is not None

    def observe_turn(self, tool_names: list[str]) -> None:
        # A tracker-tool turn resets the cadence: the worker just persisted,
        # so hold off on nudging.
        if _used_tracker_tool(tool_names):
            self._tool_calls_since_last_reminder = 0
            return
        self._tool_calls_since_last_reminder += len(tool_names)

    async def render(self, rctx: ReminderContext) -> str | None:
        if self._tool_calls_since_last_reminder < self._cadence_tool_calls:
            return None
        binding = _resolve_binding(rctx.agent_ctx)
        if binding is None:
            return None
        rows = _snapshot_tables(binding.tracker_db)
        if not rows:
            # Don't consume the cadence until there's something to show.
            # Workers upsert into the queen's tables; they don't create the
            # schema, so an empty tracker isn't theirs to act on.
            return None
        self._tool_calls_since_last_reminder = 0
        return _render_worker_body(rows)


def _resolve_binding(agent_ctx: Any):
    provider = getattr(agent_ctx, "colony_binding_provider", None)
    if not callable(provider):
        return None
    try:
        return provider()
    except Exception:
        logger.debug("tracker_snapshot: binding provider raised", exc_info=True)
        return None


def _snapshot_tables(db_path) -> list[tuple[str, int]]:
    """Return ``[(table_name, row_count), ...]`` for non-framework tables.

    Time-budgeted: stops enumerating once ``_QUERY_BUDGET_SECONDS`` elapses
    or ``_MAX_TABLES`` are collected. Read-only open via the ``mode=ro``
    URI so a corrupt write never lands here. Returns ``[]`` on any sqlite
    error rather than raising — a stale or busy DB must never break a
    reminder.
    """
    started = time.monotonic()
    try:
        # mode=ro requires the file to exist; that's intentional. A queen
        # who hasn't called ensure_tracker_db yet has nothing to snapshot.
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return []
    try:
        names = [
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\' ORDER BY name").fetchall()
        ]
        out: list[tuple[str, int]] = []
        for name in names[:_MAX_TABLES]:
            if time.monotonic() - started > _QUERY_BUDGET_SECONDS:
                break
            try:
                # Identifier whitelist: only [A-Za-z0-9_] table names get
                # counted. sqlite_master can in theory return quoted names
                # with punctuation; skip those defensively rather than
                # interpolate into a query.
                if not name.replace("_", "").isalnum():
                    continue
                (n,) = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
                out.append((name, int(n)))
            except sqlite3.Error:
                continue
        return out
    finally:
        try:
            con.close()
        except sqlite3.Error:
            pass


def _render_queen_body(rows: list[tuple[str, int]]) -> str:
    """Soft nudge for the queen — primarily, to set up a tracker table.

    With no tables yet, gently suggest creating one. Once tables exist,
    surface them and softly suggest saving anything not captured. Tone is
    deliberately light: this is advisory, not a directive.
    """
    if not rows:
        return (
            "It looks like there's no tracker table yet. If this is turning "
            "into multi-step work, it might help to set one up so progress "
            "sticks around — older tool results that aren't saved to the "
            "tracker can be dropped when the context is trimmed."
        )
    lines = ["Tracker state right now:"]
    for name, count in rows:
        lines.append(f"  - {name}: {count:,} row{'' if count == 1 else 's'}")
    lines.append("")
    lines.append(
        "If anything you've gathered since isn't in the tracker yet, it "
        "might be worth saving — older tool results that aren't in the "
        "tracker can be dropped when the context is trimmed."
    )
    return "\n".join(lines)


def _render_worker_body(rows: list[tuple[str, int]]) -> str:
    lines = ["Tracker state right now:"]
    for name, count in rows:
        lines.append(f"  - {name}: {count:,} row{'' if count == 1 else 's'}")
    lines.append("")
    lines.append(
        "Before you continue, persist your progress so far via "
        "tracker_upsert. Older tool results that are not in the tracker can be lost. "
        "If you get stuck and can't finish the job, "
        "it is okay to report early and explain why you failed."
    )
    return "\n".join(lines)
