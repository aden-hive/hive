"""Task-system reminders — a :class:`ReminderSource` for the framework hub.

Two payloads, two cadences:

  * **Snapshot** — the current task list, so the model always sees fresh
    task state. Cheap; re-shown only when the list changed since the
    model last saw it, or on a slow heartbeat.
  * **Drift nudge** — prose steering. Rate-limited; fires when the agent
    has open tasks but stopped updating them, or has gone many turns
    without ever creating a task.

Policy (thresholds, cooldown, message text, counters) lives here.
:class:`TaskReminderSource` adapts that policy to the five framework
:class:`~framework.agent_loop.reminders.ReminderPoint`\\ s; the hub owns
the ``<system-reminder>`` wrapper and where each block is placed.

The counter (:class:`ReminderState`) is persisted to ``reminder_state.json``
beside the session's task list, so drift counts and the per-session nudge
cap survive a session restart rather than silently resetting.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from framework.agent_loop.reminders import ReminderContext, ReminderPoint, ReminderSource
from framework.tasks.models import TaskRecord, TaskStatus
from framework.tasks.tools.names import ALL_TASK_TOOLS, TASK_CREATE, TASK_WRITE_TOOLS
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)

# The reminder counter is persisted beside the session's task list so it
# survives a session restart — see _load_state / _save_state.
STATE_FILENAME = "reminder_state.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Turns since the last task write (with open tasks) before a "stale
# tracking" nudge.
REMINDER_THRESHOLD_TURNS = _env_int("HIVE_TASK_REMINDER_TURNS", 10)
# Turns before nagging an agent that never created a single task. Lower
# than the stale threshold — catching "never started" early is worth more
# than catching "stopped updating".
UNTRACKED_TURNS = _env_int("HIVE_TASK_UNTRACKED_TURNS", 5)
# Turns between drift nudges at the normal cadence.
REMINDER_COOLDOWN_TURNS = _env_int("HIVE_TASK_REMINDER_COOLDOWN", 10)
# Soft cap (not a hard stop): after this many nudges without the agent
# re-engaging, every turn gate is stretched by DRIFT_BACKOFF_FACTOR — so a
# model that keeps ignoring nudges is nagged at a slower cadence rather than
# silenced outright. A task write (re-engagement) resets the count, so the
# back-off only kicks in on *consecutive ignored* nudges. This replaces the
# old hard cap that could permanently silence a long-running session.
DRIFT_SOFT_CAP = _env_int("HIVE_TASK_REMINDER_SOFT_CAP", 2)
DRIFT_BACKOFF_FACTOR = _env_int("HIVE_TASK_REMINDER_BACKOFF", 2)
# No reminder of any kind in the first few turns of a session.
REMINDER_WARMUP_TURNS = _env_int("HIVE_TASK_REMINDER_WARMUP", 4)
# Re-show the snapshot even when the list is unchanged, every N turns.
SNAPSHOT_HEARTBEAT_TURNS = _env_int("HIVE_TASK_SNAPSHOT_HEARTBEAT", 12)
# Safety valve on snapshot volume (each one persists in the transcript).
MAX_SNAPSHOTS = _env_int("HIVE_TASK_SNAPSHOT_MAX", 40)
# Cap on lines in the snapshot listing.
SNAPSHOT_MAX_ITEMS = _env_int("HIVE_TASK_SNAPSHOT_ITEMS", 12)
# Completed tasks accumulate on a long-running plan and clutter the active
# list. Once MORE than this many are still sitting on the plan (not yet
# archived), nudge the agent to archive the finished work so the plan shows
# only current + upcoming tasks. Mirrors the user-facing "Clear done" button.
COMPLETED_CLEANUP_THRESHOLD = _env_int("HIVE_TASK_COMPLETED_CLEANUP", 20)


def is_task_turn(tool_names: Iterable[str]) -> bool:
    """True when the turn recorded task progress — i.e. it called a
    mutating task tool (task_create / task_update).

    This is the *write* signal: it sets ``task_tool_ever_used`` and always
    resets the staleness counter. Read-only task tools (task_list /
    task_get) also reset the counter once tracking has begun, but through
    the separate ``touched_tasks`` path in ``ReminderState.on_turn`` — they
    do not count as progress here. Tool names come from the shared taxonomy
    in ``framework.tasks.tools.names``.
    """
    return any(n in TASK_WRITE_TOOLS for n in tool_names)


def fingerprint_tasks(records: list[TaskRecord]) -> str:
    """Stable short hash of the task list's user-visible state.

    Changes whenever a task is added, removed, renamed, or changes status
    — which is exactly when the model should be re-shown the snapshot.
    """
    parts = [f"{r.id}:{r.status.value}:{r.subject}" for r in sorted(records, key=lambda r: r.id)]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:12]


@dataclass
class ReminderState:
    """Per-loop reminder bookkeeping. Lives on the AgentLoop instance.

    ``on_turn`` is the single per-turn mutation point — call it exactly
    once per outer turn. The decision helpers (``drift_trigger`` /
    ``snapshot_due``) are pure reads; ``note_*`` record what was injected.
    """

    turns_total: int = 0
    # Turns since the last task write. Until the agent ever writes a task
    # this just counts up from 0, so the same field backs both the
    # "untracked" and "stale" triggers.
    turns_since_task_op: int = 0
    task_tool_ever_used: bool = False
    # Start high so the cooldown never blocks the first reminder.
    turns_since_last_reminder: int = 1_000_000
    drift_reminders_sent: int = 0
    turns_since_snapshot: int = 1_000_000
    snapshots_sent: int = 0
    last_snapshot_fingerprint: str | None = None

    def on_turn(self, *, is_task_turn: bool, touched_tasks: bool = False) -> None:
        """Advance per-turn counters. Call once per outer turn.

        Resetting the staleness counter is about *engagement*, not just
        writes. ``is_task_turn`` is the write signal: it sets
        ``task_tool_ever_used`` and always resets the counter. A read
        (task_list / task_get) arrives via ``touched_tasks`` and also
        resets — but only once tracking has begun, so before the first
        write a read does NOT reset, which keeps the "untracked" nudge
        (you've worked but created zero tasks) firing. Every other turn
        (work or pure conversation) advances the counter.
        """
        self.turns_total += 1
        self.turns_since_last_reminder += 1
        self.turns_since_snapshot += 1
        if is_task_turn:
            self.task_tool_ever_used = True
            self.turns_since_task_op = 0
            # Re-engaging lifts the soft-cap back-off — the cap counts
            # *consecutive ignored* nudges, not lifetime ones.
            self.drift_reminders_sent = 0
        elif touched_tasks and self.task_tool_ever_used:
            self.turns_since_task_op = 0
        else:
            self.turns_since_task_op += 1

    def drift_trigger(self, open_task_count: int, completed_task_count: int = 0) -> str | None:
        """Return the drift-nudge kind (``untracked`` / ``stale`` /
        ``all_done`` / ``too_many_completed``) or None.

        Honors warm-up, cooldown, and the soft-cap back-off. Past the soft
        cap every turn gate (cooldown + the untracked/stale thresholds) is
        multiplied by ``DRIFT_BACKOFF_FACTOR`` so an unresponsive agent is
        nagged at a slower cadence instead of being silenced — and a task
        write resets ``drift_reminders_sent``, lifting the back-off.

        ``all_done`` is the "list fully worked" case: tracking has begun but
        every task is complete. Unlike ``stale`` it is not staleness-gated —
        the moment there is no open task left, nudge the agent to create the
        next one (or confirm the goal is done) rather than drifting on with
        an empty list. Subject only to warm-up + cooldown like the others.

        ``too_many_completed`` is the "clean up the pile" case: more than
        ``COMPLETED_CLEANUP_THRESHOLD`` completed tasks are still on the
        active plan. Like ``all_done`` it is not staleness-gated — a busy
        agent keeps completing tasks without drifting — so it is checked
        first (a cluttered plan is worth clearing before any other nudge)
        and subject only to warm-up + cooldown.
        """
        if self.turns_total < REMINDER_WARMUP_TURNS:
            return None
        backoff = DRIFT_BACKOFF_FACTOR if self.drift_reminders_sent >= DRIFT_SOFT_CAP else 1
        if self.turns_since_last_reminder < REMINDER_COOLDOWN_TURNS * backoff:
            return None
        if completed_task_count > COMPLETED_CLEANUP_THRESHOLD:
            return "too_many_completed"
        if not self.task_tool_ever_used and self.turns_since_task_op >= UNTRACKED_TURNS * backoff:
            return "untracked"
        # Not on the completing write turn: when the last task is marked
        # complete, observe_turn() has just reset turns_since_task_op to 0,
        # so the >= 1 gate skips that turn — mirroring how a write
        # implicitly suppresses stale/untracked. The nudge lands on the next
        # turn instead, so finishing the list isn't nagged in the same breath.
        if self.task_tool_ever_used and open_task_count == 0 and self.turns_since_task_op >= 1:
            return "all_done"
        if open_task_count > 0 and self.turns_since_task_op >= REMINDER_THRESHOLD_TURNS * backoff:
            return "stale"
        return None

    def snapshot_due(self, fingerprint: str, *, has_tasks: bool, ignore_fingerprint: bool = False) -> bool:
        """True when the tool-result tail should carry a task snapshot.

        ``ignore_fingerprint`` drops the "list changed" trigger and leaves
        only the slow heartbeat — used when the change was self-induced
        (the agent's own task_update this turn), so re-dumping the list it
        just edited adds nothing it doesn't already know.
        """
        if not has_tasks:
            return False
        if self.turns_total < REMINDER_WARMUP_TURNS:
            return False
        if self.snapshots_sent >= MAX_SNAPSHOTS:
            return False
        if not ignore_fingerprint and fingerprint != self.last_snapshot_fingerprint:
            return True
        return self.turns_since_snapshot >= SNAPSHOT_HEARTBEAT_TURNS

    def note_drift_sent(self) -> None:
        self.turns_since_last_reminder = 0
        self.drift_reminders_sent += 1

    def note_snapshot_shown(self, fingerprint: str) -> None:
        self.turns_since_snapshot = 0
        self.snapshots_sent += 1
        self.last_snapshot_fingerprint = fingerprint

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ReminderState:
        """Rebuild from a persisted dict, tolerating added/removed fields."""
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


def _snapshot_lines(records: list[TaskRecord], *, goal: str | None = None) -> list[str]:
    """The ``#1. [pending] subject`` listing, ordered by id and capped.

    Prepends ``Goal: <goal>`` when one is stored so the queen seeing this
    snapshot mid-turn (at USER_PROMPT_SUBMIT, POST_TOOL_USE, etc.) has
    the pivot anchor in view without having to call ``task_list``.
    """
    if not records:
        return []
    ordered = sorted(records, key=lambda r: r.id)
    lines: list[str] = []
    if goal:
        lines.append(f"Goal: {goal}")
        lines.append("")
    lines.extend(["Here are the existing tasks:", ""])
    for r in ordered[:SNAPSHOT_MAX_ITEMS]:
        lines.append(f"#{r.id}. [{r.status.value}] {r.subject}")
    if len(ordered) > SNAPSHOT_MAX_ITEMS:
        lines.append(f"... and {len(ordered) - SNAPSHOT_MAX_ITEMS} more")
    return lines


def _drift_lines(kind: str, records: list[TaskRecord]) -> list[str]:
    """The prose steering for a drift nudge."""
    if kind == "untracked":
        return [
            "[task_reminder] You've done several steps of real work but "
            "haven't created any tasks. If this is multi-step work, track "
            "it: create tasks with task_create and keep "
            "their status current (in_progress when you start, completed "
            "the moment a step is done). One task per atomic action/batch — don't "
            "umbrella-track.",
        ]
    if kind == "all_done":
        return [
            "[task_reminder] No active task — every task on your list is "
            "complete. If there's more to do, create the next task with "
            "task_create. If the new work falls outside the goal above, "
            "treat it as a pivot. If the goal is fully done, confirm with "
            "the user before starting anything new.",
        ]
    if kind == "too_many_completed":
        completed = sum(1 for r in records if r.status == TaskStatus.COMPLETED)
        return [
            f"[task_reminder] {completed} completed tasks are piling up on "
            "your active plan. Clear the finished work out of it: archive the "
            "completed tasks with task_update status='archived' so they move "
            "into History and the plan shows only current and upcoming work. "
            "Keep any completed task that an open task still lists as a "
            "blocker.",
        ]
    in_progress = [r for r in records if r.status == TaskStatus.IN_PROGRESS]
    lines = [
        "[task_reminder] The task tools haven't been used in several turns. If you're working on tasks that would benefit from tracked progress:",
        "  - Mark the in_progress task `completed` THE MOMENT it's done — before starting the next step. Don't batch completions.",
        "  - If you've finished work that wasn't on the list, add a task_create + task_update completed pair so the panel reflects it.",
        "  - If you're umbrella-tracking ('reply to all posts' as one task), "
        "break it into one task per atomic action — one `task_create` call "
        "with one entry/batch per action.",
        "  - If any open task no longer applies (user pivoted, scope "
        "shifted, created in error), delete it via `task_update` with "
        "status='deleted'. Don't leave stale items on the list.",
    ]
    if in_progress:
        lines.append("  - Currently in_progress (check they're really still active): " + ", ".join(f'#{r.id} "{r.subject}"' for r in in_progress[:5]))
    return lines


def render_block(
    records: list[TaskRecord],
    *,
    drift_kind: str | None,
    include_snapshot: bool,
    goal: str | None = None,
) -> str:
    """Compose the task-reminder body, or ``""`` if empty.

    May carry the drift nudge, the task snapshot, or both. The
    ``<system-reminder>`` wrapper and anti-nag footer are added by the
    framework :class:`~framework.agent_loop.reminders.ReminderHub` — this
    returns just the body.
    """
    body: list[str] = []
    # "All complete" nudge: anchor on the goal, then the message — but never
    # re-print the (fully completed) task list. Done items add nothing here,
    # and the agent decides the next step / pivot on its own.
    if drift_kind == "all_done":
        if goal:
            body.append(f"Goal: {goal}")
            body.append("")
        body.extend(_drift_lines(drift_kind, records))
        return "\n".join(body)
    if drift_kind:
        body.extend(_drift_lines(drift_kind, records))
    if include_snapshot:
        snap = _snapshot_lines(records, goal=goal)
        if snap:
            if body:
                body.append("")
            body.extend(snap)
    return "\n".join(body)


# ---------------------------------------------------------------------------
# Framework ReminderSource adapter
# ---------------------------------------------------------------------------


async def _read_records(session_id: str) -> list[TaskRecord] | None:
    """Best-effort read of a session's ACTIVE task list. None on any failure.

    Mirrors the default ``task_list`` view the agent sees: archived tasks
    are excluded (they're parked in the user's History, not the working
    plan). Including them would re-surface archived items in the snapshot
    and — because archived != completed — inflate ``open_count``, which
    would suppress the "all done" nudge and fire false "stale" nudges.
    """
    try:
        from framework.tasks import get_task_store

        records = await get_task_store().list_tasks(session_id)
        return [r for r in records if r.status is not TaskStatus.ARCHIVED]
    except Exception:
        logger.debug("task reminder: list_tasks(%s) failed", session_id, exc_info=True)
        return None


async def _read_goal(session_id: str) -> str | None:
    """Best-effort read of the session's anchor goal. None on any failure."""
    try:
        from framework.tasks import get_task_store

        meta = await get_task_store().get_meta(session_id)
        return meta.goal if meta is not None else None
    except Exception:
        logger.debug("task reminder: get_meta(%s) failed", session_id, exc_info=True)
        return None


def _state_path(session_id: str) -> Path | None:
    """On-disk path for this session's reminder state — beside tasks.json."""
    try:
        from framework.tasks.store import session_storage_dir

        return session_storage_dir(session_id) / STATE_FILENAME
    except Exception:
        return None


def _load_state(session_id: str) -> ReminderState | None:
    """Read the persisted ReminderState, or None if absent/unreadable."""
    path = _state_path(session_id)
    if path is None or not path.exists():
        return None
    try:
        return ReminderState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        logger.debug("reminder state load failed for %s", session_id, exc_info=True)
        return None


def _save_state(session_id: str, state: ReminderState) -> None:
    """Atomically persist the ReminderState beside the session's task list."""
    path = _state_path(session_id)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            f.write(json.dumps(state.to_dict(), indent=2))
    except Exception:
        logger.debug("reminder state save failed for %s", session_id, exc_info=True)


class TaskReminderSource(ReminderSource):
    """Task-system reminders, adapted to the framework reminder hub.

    Fires at all five points: a task snapshot wherever the model could
    use fresh state, and the drift nudge when tracking has gone stale.
    All counter state lives in a single per-loop :class:`ReminderState`.
    """

    name = "tasks"

    # Points that re-assert the full list unconditionally (rare events,
    # and ones that drop context) rather than gating on snapshot_due.
    # POST_COMPACT (not PRE_COMPACT): re-read the list fresh from the store
    # and land it verbatim in the clean post-summary window, rather than
    # injecting into content the compaction is about to summarize/trim.
    _ALWAYS_SNAPSHOT = frozenset({ReminderPoint.SESSION_START, ReminderPoint.POST_COMPACT})

    def __init__(self) -> None:
        self._state = ReminderState()
        # Hydrated from disk on the first render of the session so the
        # counter survives a restart. See _ensure_loaded.
        self._loaded = False

    def points(self) -> set[ReminderPoint]:
        return {
            ReminderPoint.SESSION_START,
            ReminderPoint.USER_PROMPT_SUBMIT,
            ReminderPoint.POST_TOOL_USE,
            ReminderPoint.POST_COMPACT,
            ReminderPoint.STOP,
        }

    def applies_to(self, agent_ctx: Any) -> bool:
        """Task reminders apply only to agents that can write tasks.

        Without task_create / task_update the drift nudge would point at
        tools the agent doesn't have — so a worker (or any agent) spawned
        without the task tools gets no task reminders at all.
        """
        tools = getattr(agent_ctx, "available_tools", None) or []
        return any(getattr(t, "name", "") in TASK_WRITE_TOOLS for t in tools)

    def observe_turn(self, tool_names: list[str]) -> None:
        # In-memory only; the mutation is persisted by the next render().
        # Any task touch (read or write) counts as engagement; only writes
        # set ``ever_used`` — see ReminderState.on_turn.
        self._state.on_turn(
            is_task_turn=is_task_turn(tool_names),
            touched_tasks=any(n in ALL_TASK_TOOLS for n in tool_names),
        )

    async def _ensure_loaded(self, session_id: str) -> None:
        """Hydrate ``_state`` from disk once, on the first render.

        Safe because SESSION_START — the first render — fires before the
        turn loop runs any ``observe_turn`` tick, so the load never clobbers
        an in-memory mutation. (POST_TOOL_USE, by contrast, fires *after*
        its turn's observe_turn within _run_turn_loop.)
        """
        if self._loaded:
            return
        self._loaded = True
        loaded = await asyncio.to_thread(_load_state, session_id)
        if loaded is not None:
            self._state = loaded

    async def render(self, rctx: ReminderContext) -> str | None:
        session_id = getattr(rctx.agent_ctx, "session_id", None)
        if not session_id:
            return None
        await self._ensure_loaded(session_id)
        records = await _read_records(session_id)
        if records is None:
            return None
        goal = await _read_goal(session_id)
        if rctx.point is ReminderPoint.SESSION_START and records:
            # A session that already has tasks HAS tracked before — covers
            # the first run after this feature ships (no persisted file yet).
            self._state.task_tool_ever_used = True
        if rctx.point is ReminderPoint.POST_TOOL_USE:
            body = self._render_drift_or_snapshot(records, snapshot_gated=True, goal=goal, tool_names=rctx.tool_names)
        elif rctx.point is ReminderPoint.STOP:
            body = self._render_stop(records, goal=goal)
        else:
            body = self._render_snapshot(records, point=rctx.point, goal=goal)
        # Persist counter advances + this render's mutations so the state
        # survives a session restart.
        await asyncio.to_thread(_save_state, session_id, self._state)
        return body

    # ----- per-point renderers -----------------------------------------

    def _render_drift_or_snapshot(
        self,
        records: list[TaskRecord],
        *,
        snapshot_gated: bool,
        goal: str | None = None,
        tool_names: list[str] | None = None,
    ) -> str | None:
        """POST_TOOL_USE: snapshot (when due) and/or the drift nudge.

        When this turn only *updated* tasks (a status flip the agent just
        made and already saw echoed in the tool result), the snapshot's
        "list changed" trigger is self-induced — suppress it and leave only
        the heartbeat. A turn that *creates* tasks still shows the
        consolidated list (new structure worth anchoring on); and because a
        suppressed change does NOT advance the fingerprint, a concurrent
        worker edit to the shared list still surfaces on the next
        non-update turn.
        """
        s = self._state
        fp = fingerprint_tasks(records)
        open_count = sum(1 for r in records if r.status != TaskStatus.COMPLETED)
        completed_count = sum(1 for r in records if r.status == TaskStatus.COMPLETED)
        names = set(tool_names or [])
        update_only = bool(names & TASK_WRITE_TOOLS) and TASK_CREATE not in names
        snap_due = s.snapshot_due(fp, has_tasks=bool(records), ignore_fingerprint=update_only) if snapshot_gated else bool(records)
        # Drift needs no guard against firing on a task-write turn:
        # observe_turn() ticks earlier in the same inner turn (in
        # _run_turn_loop, before this POST_TOOL_USE fire), so a write has
        # already reset turns_since_task_op / set task_tool_ever_used —
        # drift_trigger can't report stale, untracked, or all_done here.
        # (too_many_completed is the exception: it is not staleness-gated,
        # so completing a task that tips the count over the threshold does
        # nudge for cleanup on that same turn — the cooldown then spaces it.)
        drift_kind = s.drift_trigger(open_count, completed_count)
        if not snap_due and drift_kind is None:
            return None
        # all_done renders goal + message only — never the completed list, so
        # it must not count as a snapshot (which would reset the heartbeat).
        include_snapshot = drift_kind != "all_done" and bool(records) and (snap_due or drift_kind is not None)
        body = render_block(records, drift_kind=drift_kind, include_snapshot=include_snapshot, goal=goal)
        if not body:
            return None
        if include_snapshot:
            s.note_snapshot_shown(fp)
        if drift_kind is not None:
            s.note_drift_sent()
        return body

    def _render_stop(self, records: list[TaskRecord], *, goal: str | None = None) -> str | None:
        """STOP: a text-only turn ended — nudge only if drift fired."""
        s = self._state
        open_count = sum(1 for r in records if r.status != TaskStatus.COMPLETED)
        completed_count = sum(1 for r in records if r.status == TaskStatus.COMPLETED)
        drift_kind = s.drift_trigger(open_count, completed_count)
        if drift_kind is None:
            return None
        # all_done shows goal + message only — no task list, so it does not
        # count as a snapshot (see _render_drift_or_snapshot).
        include_snapshot = drift_kind != "all_done"
        body = render_block(records, drift_kind=drift_kind, include_snapshot=include_snapshot, goal=goal)
        if not body:
            return None
        if include_snapshot and records:
            s.note_snapshot_shown(fingerprint_tasks(records))
        s.note_drift_sent()
        return body

    def _render_snapshot(
        self,
        records: list[TaskRecord],
        *,
        point: ReminderPoint,
        goal: str | None = None,
    ) -> str | None:
        """SESSION_START / USER_PROMPT_SUBMIT / POST_COMPACT: list refresh.

        SESSION_START and POST_COMPACT always re-assert the list (resumed
        session / compaction just dropped context); USER_PROMPT_SUBMIT
        gates on snapshot_due so a chatty user isn't shown a stale list
        every message.
        """
        s = self._state
        open_count = sum(1 for r in records if r.status != TaskStatus.COMPLETED)
        if open_count == 0:
            return None
        fp = fingerprint_tasks(records)
        if point not in self._ALWAYS_SNAPSHOT and not s.snapshot_due(fp, has_tasks=True):
            return None
        body = render_block(records, drift_kind=None, include_snapshot=True, goal=goal)
        if not body:
            return None
        s.note_snapshot_shown(fp)
        return body
