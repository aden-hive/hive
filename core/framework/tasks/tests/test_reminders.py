"""Tests for task-system reminders + the framework reminder hub.

Covers three layers:
  - Policy: ``ReminderState`` counters, ``drift_trigger``, ``snapshot_due``.
  - Rendering: ``is_task_turn`` / ``fingerprint_tasks`` / ``render_block``.
  - Framework: ``ReminderHub`` fan-out and ``TaskReminderSource`` adapting
    the policy to the five lifecycle points.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.agent_loop.reminders import (
    ReminderContext,
    ReminderHub,
    ReminderPoint,
    ReminderSource,
    wrap_reminder,
)
from framework.tasks.models import TaskRecord, TaskStatus
from framework.tasks.reminders import (
    COMPLETED_CLEANUP_THRESHOLD,
    DRIFT_BACKOFF_FACTOR,
    DRIFT_SOFT_CAP,
    REMINDER_COOLDOWN_TURNS,
    REMINDER_THRESHOLD_TURNS,
    REMINDER_WARMUP_TURNS,
    SNAPSHOT_HEARTBEAT_TURNS,
    UNTRACKED_TURNS,
    ReminderState,
    TaskReminderSource,
    fingerprint_tasks,
    is_task_turn,
    render_block,
)


def _rec(id: int, subject: str, status: TaskStatus = TaskStatus.PENDING) -> TaskRecord:
    return TaskRecord(id=id, subject=subject, status=status)


# ---------------------------------------------------------------------------
# is_task_turn — did the turn write a task?
# ---------------------------------------------------------------------------


def test_is_task_turn() -> None:
    # A mutating task tool → task turn.
    assert is_task_turn(["task_create"]) is True
    assert is_task_turn(["read_file", "task_update"]) is True
    # Non-task work, read-only task tools, and pure conversation → not.
    assert is_task_turn(["browser_click"]) is False
    assert is_task_turn(["task_list", "task_get"]) is False
    assert is_task_turn([]) is False


# ---------------------------------------------------------------------------
# ReminderState.on_turn — the turns-since-task-write counter
# ---------------------------------------------------------------------------


def test_counter_advances_until_a_task_write() -> None:
    s = ReminderState()
    s.on_turn(is_task_turn=False)
    s.on_turn(is_task_turn=False)
    s.on_turn(is_task_turn=False)
    assert s.turns_since_task_op == 3
    assert s.turns_total == 3


def test_task_write_resets_counter_and_sets_flag() -> None:
    s = ReminderState()
    for _ in range(5):
        s.on_turn(is_task_turn=False)
    assert not s.task_tool_ever_used
    s.on_turn(is_task_turn=True)
    assert s.turns_since_task_op == 0
    assert s.task_tool_ever_used


def test_read_resets_counter_only_after_tracking_began() -> None:
    """A read (task_list / task_get) is engagement, not progress.

    WHY: a task left open while the agent keeps consulting its own list
    isn't "forgotten" — nagging there is the noise we're killing. But a
    read must NOT count before the first write, or it would mask the
    "untracked" nudge (worked a lot, created zero tasks).
    """
    s = ReminderState()
    # Before any write: a read does NOT reset — untracked stays armed.
    for _ in range(3):
        s.on_turn(is_task_turn=False, touched_tasks=True)
    assert s.turns_since_task_op == 3
    assert not s.task_tool_ever_used

    # After a write, a read resets the staleness counter...
    s.on_turn(is_task_turn=True)  # ever_used = True, counter = 0
    s.on_turn(is_task_turn=False)  # plain work turn → 1
    assert s.turns_since_task_op == 1
    s.on_turn(is_task_turn=False, touched_tasks=True)  # read → reset
    assert s.turns_since_task_op == 0
    # ...but a read never un-sets the write-only ever_used flag.
    assert s.task_tool_ever_used


def test_reading_open_tasks_suppresses_stale_nudge() -> None:
    """Consulting the list resets the stale clock so the nudge waits."""
    s = ReminderState()
    s.on_turn(is_task_turn=True)  # tracked once
    for _ in range(REMINDER_THRESHOLD_TURNS - 1):
        s.on_turn(is_task_turn=False)
    s.on_turn(is_task_turn=False, touched_tasks=True)  # a read resets
    assert s.drift_trigger(open_task_count=2) is None


# ---------------------------------------------------------------------------
# drift_trigger — untracked / stale / gating
# ---------------------------------------------------------------------------


def test_untracked_trigger_fires_without_any_task() -> None:
    s = ReminderState()
    for _ in range(UNTRACKED_TURNS):
        s.on_turn(is_task_turn=False)
    assert s.drift_trigger(open_task_count=0) == "untracked"


def test_stale_trigger_needs_open_tasks_and_prior_tracking() -> None:
    s = ReminderState()
    s.on_turn(is_task_turn=True)  # tracked once
    for _ in range(REMINDER_THRESHOLD_TURNS):
        s.on_turn(is_task_turn=False)
    assert s.drift_trigger(open_task_count=2) == "stale"
    # Zero open tasks is no longer stale-territory — once tracking has begun
    # and the list is fully worked, it is the all_done nudge instead.
    assert s.drift_trigger(open_task_count=0) == "all_done"


def test_all_done_trigger_fires_when_list_fully_complete() -> None:
    """Tracking began and every task is done -> nudge for the next task.

    WHY: an agent that finishes its list and has nothing open otherwise
    gets no reminder at all (untracked needs never-tracked; stale needs an
    open task). all_done closes that gap so the agent is prompted to create
    the next task or confirm the goal is done rather than drifting on inline.
    """
    s = ReminderState(task_tool_ever_used=True, turns_total=REMINDER_WARMUP_TURNS)
    s.turns_since_task_op = 1  # a turn has passed since the completing write
    assert s.drift_trigger(open_task_count=0) == "all_done"
    # With an open task it is stale-territory, not all_done.
    assert s.drift_trigger(open_task_count=1) is None


def test_all_done_not_on_the_completing_write_turn() -> None:
    """Completing the final task must not nag 'no active task' in the same turn.

    WHY: on a task-write turn observe_turn() has just reset
    turns_since_task_op to 0; all_done skips that turn the same way stale and
    untracked are implicitly skipped on a write, so finishing the list lands
    the nudge on the NEXT turn rather than in the same breath.
    """
    s = ReminderState(task_tool_ever_used=True, turns_total=REMINDER_WARMUP_TURNS)
    s.on_turn(is_task_turn=True)  # the completing write -> turns_since_task_op == 0
    assert s.drift_trigger(open_task_count=0) is None
    s.on_turn(is_task_turn=False)  # next turn
    assert s.drift_trigger(open_task_count=0) == "all_done"


def test_all_done_requires_prior_tracking() -> None:
    """Never-tracked + zero open tasks is the untracked case, not all_done."""
    s = ReminderState(turns_total=REMINDER_WARMUP_TURNS)
    s.turns_since_task_op = UNTRACKED_TURNS
    assert s.drift_trigger(open_task_count=0) == "untracked"


def test_too_many_completed_fires_over_threshold() -> None:
    """More than the threshold of completed tasks on the plan → cleanup nudge.

    WHY: completed tasks pile up on a long-running plan and clutter it. This
    nudge is NOT staleness-gated (a busy agent keeps completing tasks without
    drifting), so it fires on completed-count alone — mirroring the panel's
    "Clear done" button.
    """
    s = ReminderState(task_tool_ever_used=True, turns_total=REMINDER_WARMUP_TURNS)
    s.turns_since_task_op = 1
    # At the threshold: not yet ("more than", not "at least").
    assert s.drift_trigger(open_task_count=1, completed_task_count=COMPLETED_CLEANUP_THRESHOLD) is None
    # Over it → cleanup nudge, ahead of any stale/all_done kind.
    assert s.drift_trigger(open_task_count=1, completed_task_count=COMPLETED_CLEANUP_THRESHOLD + 1) == "too_many_completed"


def test_too_many_completed_takes_priority_over_all_done() -> None:
    """A fully-worked list that is ALSO over the completed threshold nudges
    for cleanup first — clearing the pile matters more than 'create the next
    task', and the agent creates new work after archiving anyway."""
    s = ReminderState(task_tool_ever_used=True, turns_total=REMINDER_WARMUP_TURNS)
    s.turns_since_task_op = 1
    assert s.drift_trigger(open_task_count=0, completed_task_count=COMPLETED_CLEANUP_THRESHOLD + 1) == "too_many_completed"


def test_too_many_completed_respects_cooldown() -> None:
    """The cleanup nudge honors the drift cooldown, so it can't fire every
    turn once the pile stays large."""
    s = ReminderState(task_tool_ever_used=True, turns_total=REMINDER_WARMUP_TURNS)
    s.turns_since_task_op = 1
    over = COMPLETED_CLEANUP_THRESHOLD + 1
    assert s.drift_trigger(open_task_count=1, completed_task_count=over) == "too_many_completed"
    s.note_drift_sent()
    assert s.drift_trigger(open_task_count=1, completed_task_count=over) is None
    for _ in range(REMINDER_COOLDOWN_TURNS):
        s.on_turn(is_task_turn=False)
    assert s.drift_trigger(open_task_count=1, completed_task_count=over) == "too_many_completed"


def test_render_block_too_many_completed_text() -> None:
    records = [_rec(i, f"step {i}", TaskStatus.COMPLETED) for i in range(1, 22)]
    body = render_block(records, drift_kind="too_many_completed", include_snapshot=False)
    assert "21 completed tasks" in body
    assert "status='archived'" in body


def test_too_many_completed_takes_priority_over_untracked() -> None:
    """Ordering: the cleanup check sits before the untracked check, so an
    over-threshold pile wins even when tracking never started this run (a
    resumed session can inherit a pile without task_tool_ever_used set)."""
    s = ReminderState(task_tool_ever_used=False, turns_total=REMINDER_WARMUP_TURNS)
    s.turns_since_task_op = UNTRACKED_TURNS + 5  # untracked would fire
    assert s.drift_trigger(open_task_count=1, completed_task_count=COMPLETED_CLEANUP_THRESHOLD + 1) == "too_many_completed"


def test_drift_respects_warmup() -> None:
    s = ReminderState()
    s.turns_since_task_op = UNTRACKED_TURNS + 10
    s.turns_total = REMINDER_WARMUP_TURNS - 1
    assert s.drift_trigger(open_task_count=3) is None


def test_drift_respects_cooldown() -> None:
    s = ReminderState()
    for _ in range(UNTRACKED_TURNS):
        s.on_turn(is_task_turn=False)
    assert s.drift_trigger(0) == "untracked"

    s.note_drift_sent()
    assert s.drift_trigger(0) is None
    for _ in range(REMINDER_COOLDOWN_TURNS):
        s.on_turn(is_task_turn=False)
    assert s.drift_trigger(0) == "untracked"


def test_soft_cap_backs_off_instead_of_silencing() -> None:
    """Past the soft cap the nudge is slowed, not stopped.

    WHY: a long-running agent legitimately drifts many times; a hard cap
    would silence task reminders for the rest of its life. The back-off
    keeps them coming, just at a wider spacing.
    """
    s = ReminderState(task_tool_ever_used=True, turns_total=REMINDER_WARMUP_TURNS)
    s.drift_reminders_sent = DRIFT_SOFT_CAP  # at the cap → back-off engaged

    # One normal cooldown is no longer enough; the gate is now doubled.
    for _ in range(REMINDER_COOLDOWN_TURNS):
        s.on_turn(is_task_turn=False)
    assert s.drift_trigger(open_task_count=1) is None  # not silent — just waiting

    # After the stretched cooldown + threshold, it fires again.
    for _ in range(REMINDER_COOLDOWN_TURNS * DRIFT_BACKOFF_FACTOR):
        s.on_turn(is_task_turn=False)
    assert s.drift_trigger(open_task_count=1) == "stale"


def test_task_write_resets_soft_cap_budget() -> None:
    """Re-engaging (a task write) refunds the soft-cap count, so the cap
    tracks consecutive *ignored* nudges rather than lifetime ones."""
    s = ReminderState()
    s.drift_reminders_sent = DRIFT_SOFT_CAP + 1
    s.on_turn(is_task_turn=True)
    assert s.drift_reminders_sent == 0
    # A read does NOT refund it — only a write counts as re-engagement.
    s.drift_reminders_sent = DRIFT_SOFT_CAP + 1
    s.on_turn(is_task_turn=False, touched_tasks=True)
    assert s.drift_reminders_sent == DRIFT_SOFT_CAP + 1


# ---------------------------------------------------------------------------
# snapshot_due — change-driven + heartbeat
# ---------------------------------------------------------------------------


def test_snapshot_due_on_change_then_quiet() -> None:
    s = ReminderState()
    s.turns_total = REMINDER_WARMUP_TURNS
    assert s.snapshot_due("fp1", has_tasks=True)
    s.note_snapshot_shown("fp1")
    assert not s.snapshot_due("fp1", has_tasks=True)
    assert s.snapshot_due("fp2", has_tasks=True)


def test_snapshot_heartbeat_reshows_unchanged_list() -> None:
    s = ReminderState()
    s.turns_total = REMINDER_WARMUP_TURNS
    s.note_snapshot_shown("fp1")
    s.turns_since_snapshot = SNAPSHOT_HEARTBEAT_TURNS
    assert s.snapshot_due("fp1", has_tasks=True)


def test_snapshot_skipped_when_no_tasks() -> None:
    s = ReminderState()
    s.turns_total = REMINDER_WARMUP_TURNS
    assert not s.snapshot_due("fp1", has_tasks=False)


# ---------------------------------------------------------------------------
# fingerprint_tasks + render_block
# ---------------------------------------------------------------------------


def test_fingerprint_changes_on_status() -> None:
    before = [_rec(1, "a"), _rec(2, "b")]
    after = [_rec(1, "a"), _rec(2, "b", TaskStatus.COMPLETED)]
    assert fingerprint_tasks(before) != fingerprint_tasks(after)
    assert fingerprint_tasks(before) == fingerprint_tasks(list(reversed(before)))


def test_render_block_drift_plus_snapshot() -> None:
    records = [_rec(1, "step 1"), _rec(2, "step 2", TaskStatus.IN_PROGRESS)]
    body = render_block(records, drift_kind="stale", include_snapshot=True)
    # render_block returns the bare body — no <system-reminder> wrapper.
    assert not body.startswith("<system-reminder>")
    assert "task_reminder" in body
    assert "Here are the existing tasks:" in body
    assert "step 1" in body and "step 2" in body


def test_render_block_snapshot_only_has_no_nudge() -> None:
    body = render_block([_rec(1, "step 1")], drift_kind=None, include_snapshot=True)
    assert "Here are the existing tasks:" in body
    assert "task_reminder" not in body


def test_render_block_untracked_nudge_text() -> None:
    body = render_block([], drift_kind="untracked", include_snapshot=False)
    assert "haven't created any tasks" in body
    assert "Here are the existing tasks:" not in body


def test_render_block_empty_when_nothing_to_say() -> None:
    assert render_block([], drift_kind=None, include_snapshot=True) == ""


def test_render_block_all_done_shows_goal_and_message_not_task_list() -> None:
    """all_done: the goal anchors the nudge; the completed list is omitted.

    WHY: re-printing tasks the agent just finished adds nothing — the value
    is the goal (so the agent can judge whether new work fits it) plus the
    'no active task' prompt. Passing include_snapshot=True must NOT leak the
    completed list for this kind.
    """
    records = [_rec(1, "step 1", TaskStatus.COMPLETED), _rec(2, "step 2", TaskStatus.COMPLETED)]
    body = render_block(records, drift_kind="all_done", include_snapshot=True, goal="Ship the feature")
    assert "No active task" in body
    assert "Goal: Ship the feature" in body
    # No completed-task listing.
    assert "Here are the existing tasks:" not in body
    assert "step 1" not in body and "step 2" not in body


# ---------------------------------------------------------------------------
# Framework: ReminderHub fan-out + wrapping
# ---------------------------------------------------------------------------


def test_wrap_reminder_adds_tags_and_footer() -> None:
    out = wrap_reminder(["body one", "body two"])
    assert out.startswith("<system-reminder>")
    assert out.rstrip().endswith("</system-reminder>")
    assert "body one" in out and "body two" in out
    assert "NEVER mention this reminder to the user" in out
    assert wrap_reminder([]) == ""
    assert wrap_reminder(["   "]) == ""


class _FakeSource(ReminderSource):
    """Minimal source firing a fixed body at one point."""

    def __init__(self, name: str, point: ReminderPoint, body: str | None) -> None:
        self.name = name
        self._point = point
        self._body = body
        self.observed: list[list[str]] = []

    def points(self) -> set[ReminderPoint]:
        return {self._point}

    def observe_turn(self, tool_names: list[str]) -> None:
        self.observed.append(tool_names)

    async def render(self, rctx: ReminderContext) -> str | None:
        return self._body


@pytest.mark.asyncio
async def test_hub_fires_only_matching_sources() -> None:
    hub = ReminderHub()
    hub.register(_FakeSource("a", ReminderPoint.STOP, "stop body"))
    hub.register(_FakeSource("b", ReminderPoint.SESSION_START, "start body"))

    block = await hub.fire(ReminderPoint.STOP, agent_ctx=SimpleNamespace())
    assert block is not None and "stop body" in block
    assert "start body" not in block
    # No source fires at POST_TOOL_USE.
    assert await hub.fire(ReminderPoint.POST_TOOL_USE, agent_ctx=SimpleNamespace()) is None


@pytest.mark.asyncio
async def test_hub_merges_multiple_sources_into_one_block() -> None:
    hub = ReminderHub()
    hub.register(_FakeSource("a", ReminderPoint.STOP, "first"))
    hub.register(_FakeSource("b", ReminderPoint.STOP, "second"))
    block = await hub.fire(ReminderPoint.STOP, agent_ctx=SimpleNamespace())
    assert block.count("<system-reminder>") == 1  # one wrapper, not two
    assert "first" in block and "second" in block


@pytest.mark.asyncio
async def test_hub_survives_a_throwing_source() -> None:
    class _Boom(ReminderSource):
        name = "boom"

        def points(self) -> set[ReminderPoint]:
            return {ReminderPoint.STOP}

        async def render(self, rctx: ReminderContext) -> str | None:
            raise RuntimeError("kaboom")

    hub = ReminderHub()
    hub.register(_Boom())
    hub.register(_FakeSource("ok", ReminderPoint.STOP, "survived"))
    block = await hub.fire(ReminderPoint.STOP, agent_ctx=SimpleNamespace())
    assert block is not None and "survived" in block


def test_hub_observe_turn_fans_out() -> None:
    hub = ReminderHub()
    src = _FakeSource("a", ReminderPoint.STOP, None)
    hub.register(src)
    hub.observe_turn(["browser_click"])
    assert src.observed == [["browser_click"]]


# ---------------------------------------------------------------------------
# Framework: applies_to / bind — per-agent source gating
# ---------------------------------------------------------------------------


class _ScopedSource(_FakeSource):
    """A _FakeSource that declares a fixed applies_to verdict."""

    def __init__(self, name: str, point: ReminderPoint, body: str | None, *, applies: bool) -> None:
        super().__init__(name, point, body)
        self._applies = applies

    def applies_to(self, agent_ctx) -> bool:
        return self._applies


def test_source_applies_to_defaults_true() -> None:
    assert _FakeSource("x", ReminderPoint.STOP, "b").applies_to(SimpleNamespace()) is True


@pytest.mark.asyncio
async def test_bind_excludes_non_applicable_sources() -> None:
    hub = ReminderHub()
    keep = _ScopedSource("keep", ReminderPoint.STOP, "keep-body", applies=True)
    drop = _ScopedSource("drop", ReminderPoint.STOP, "drop-body", applies=False)
    hub.register(keep)
    hub.register(drop)
    hub.bind(SimpleNamespace())

    block = await hub.fire(ReminderPoint.STOP, agent_ctx=SimpleNamespace())
    assert block is not None and "keep-body" in block
    assert "drop-body" not in block  # filtered out at bind()

    # The excluded source is not even observed.
    hub.observe_turn(["browser_click"])
    assert keep.observed == [["browser_click"]]
    assert drop.observed == []


def test_task_source_applies_to_requires_task_write_tools() -> None:
    src = TaskReminderSource()
    has_write = SimpleNamespace(available_tools=[SimpleNamespace(name="task_update")])
    only_other = SimpleNamespace(available_tools=[SimpleNamespace(name="browser_click")])
    assert src.applies_to(has_write) is True
    assert src.applies_to(only_other) is False
    assert src.applies_to(SimpleNamespace(available_tools=[])) is False
    assert src.applies_to(SimpleNamespace()) is False  # no available_tools attr


# ---------------------------------------------------------------------------
# Framework: TaskReminderSource
# ---------------------------------------------------------------------------


@pytest.fixture
def task_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Process-singleton task store rooted at a fresh tmp dir."""
    monkeypatch.setenv("HIVE_HOME", str(tmp_path))
    import framework.tasks.store as store_mod

    monkeypatch.setattr(store_mod, "_default_store", None)
    from framework.tasks import get_task_store

    return get_task_store()


def test_task_source_declares_all_five_points() -> None:
    # The task source fires at every *lifecycle* point — but not at the
    # non-lifecycle points (temporal IDLE_TICK, reactive STREAM_STALLED).
    assert TaskReminderSource().points() == {
        ReminderPoint.SESSION_START,
        ReminderPoint.USER_PROMPT_SUBMIT,
        ReminderPoint.POST_TOOL_USE,
        ReminderPoint.POST_COMPACT,
        ReminderPoint.STOP,
    }


@pytest.mark.asyncio
async def test_task_source_none_without_session_id() -> None:
    src = TaskReminderSource()
    rctx = ReminderContext(point=ReminderPoint.POST_TOOL_USE, agent_ctx=SimpleNamespace())
    assert await src.render(rctx) is None


@pytest.mark.asyncio
async def test_task_source_post_tool_use_shows_snapshot(task_store) -> None:
    session_id = "s1"
    await task_store.create_task(session_id, subject="verify the sheet")
    src = TaskReminderSource()
    src._state.turns_total = REMINDER_WARMUP_TURNS  # past warm-up
    ctx = SimpleNamespace(session_id=session_id)

    body = await src.render(ReminderContext(ReminderPoint.POST_TOOL_USE, ctx))
    assert body is not None and "verify the sheet" in body
    # Unchanged list, recently shown → no repeat.
    assert await src.render(ReminderContext(ReminderPoint.POST_TOOL_USE, ctx)) is None


@pytest.mark.asyncio
async def test_task_source_session_start_reasserts_resumed_list(task_store) -> None:
    session_id = "s1"
    await task_store.create_task(session_id, subject="resumed work")
    src = TaskReminderSource()
    ctx = SimpleNamespace(session_id=session_id)
    # SESSION_START fires at turns_total == 0 — bypasses the warm-up gate.
    body = await src.render(ReminderContext(ReminderPoint.SESSION_START, ctx))
    assert body is not None and "resumed work" in body


@pytest.mark.asyncio
async def test_task_source_stop_emits_untracked_drift(task_store) -> None:
    src = TaskReminderSource()
    # Several turns, never a task write → "untracked" drift.
    for _ in range(UNTRACKED_TURNS):
        src.observe_turn(["browser_click"])
    ctx = SimpleNamespace(session_id="s1")
    body = await src.render(ReminderContext(ReminderPoint.STOP, ctx))
    assert body is not None and "haven't created any tasks" in body


async def _seed_completed_pile(task_store, session_id: str, completed: int, open_: int = 1) -> None:
    """Create ``completed`` completed + ``open_`` pending tasks in one batch."""
    specs = [{"subject": f"done {i}"} for i in range(1, completed + 1)]
    specs += [{"subject": f"open {i}"} for i in range(1, open_ + 1)]
    await task_store.create_tasks_batch(session_id, specs, goal="Long-running goal")
    for task_id in range(1, completed + 1):
        await task_store.update_task(session_id, task_id, status=TaskStatus.COMPLETED)


@pytest.mark.asyncio
async def test_task_source_nudges_cleanup_on_completing_write_turn(task_store) -> None:
    """Engine-level: an over-threshold completed pile fires the cleanup nudge
    at POST_TOOL_USE — including on the very task-write turn that tipped the
    count over. Unlike stale/untracked (reset by the write in observe_turn),
    too_many_completed is not staleness-gated; this pins the documented
    exception through the real render pipeline."""
    session_id = "s1"
    await _seed_completed_pile(task_store, session_id, COMPLETED_CLEANUP_THRESHOLD + 1)
    src = TaskReminderSource()
    src._state.turns_total = REMINDER_WARMUP_TURNS
    ctx = SimpleNamespace(session_id=session_id)

    # The write turn itself: observe_turn ticks first (as in _run_turn_loop),
    # then POST_TOOL_USE renders with the write's tool names.
    src.observe_turn(["task_update"])
    body = await src.render(ReminderContext(ReminderPoint.POST_TOOL_USE, ctx, tool_names=["task_update"]))
    assert body is not None
    assert f"{COMPLETED_CLEANUP_THRESHOLD + 1} completed tasks" in body
    assert "status='archived'" in body


@pytest.mark.asyncio
async def test_task_source_stop_nudges_cleanup(task_store) -> None:
    """The cleanup nudge also lands on a text-only turn's STOP fire."""
    session_id = "s1"
    await _seed_completed_pile(task_store, session_id, COMPLETED_CLEANUP_THRESHOLD + 1)
    src = TaskReminderSource()
    src._state.turns_total = REMINDER_WARMUP_TURNS
    body = await src.render(ReminderContext(ReminderPoint.STOP, SimpleNamespace(session_id=session_id)))
    assert body is not None and "completed tasks are piling up" in body


@pytest.mark.asyncio
async def test_task_source_cleanup_nudge_stops_after_archiving(task_store) -> None:
    """Archiving (the nudge's own advice / the "Clear done" button) ends the
    nudge: archived tasks are excluded from the reminder's records, so the
    completed count drops back under the threshold."""
    session_id = "s1"
    await _seed_completed_pile(task_store, session_id, COMPLETED_CLEANUP_THRESHOLD + 1)
    src = TaskReminderSource()
    src._state.turns_total = REMINDER_WARMUP_TURNS
    ctx = SimpleNamespace(session_id=session_id)

    body = await src.render(ReminderContext(ReminderPoint.STOP, ctx))
    assert body is not None and "piling up" in body

    archived = await task_store.archive_completed_tasks(session_id)
    assert len(archived) == COMPLETED_CLEANUP_THRESHOLD + 1
    # Clear the cooldown the first nudge started, so only the completed
    # count decides the outcome.
    for _ in range(REMINDER_COOLDOWN_TURNS):
        src.observe_turn(["browser_click"])
    body = await src.render(ReminderContext(ReminderPoint.STOP, ctx))
    assert body is None or "piling up" not in body


@pytest.mark.asyncio
async def test_session_start_seeds_ever_tracked_flag(task_store) -> None:
    """A resumed session that already has tasks must never fire the bogus
    'untracked' nudge — SESSION_START seeds the flag from persisted state."""
    session_id = "s1"
    await task_store.create_task(session_id, subject="pre-existing work")
    src = TaskReminderSource()
    ctx = SimpleNamespace(session_id=session_id)

    await src.render(ReminderContext(ReminderPoint.SESSION_START, ctx))
    assert src._state.task_tool_ever_used is True

    # Long silent stretch after the restart → "stale" (it has open tasks),
    # never the wrong "untracked".
    for _ in range(UNTRACKED_TURNS + REMINDER_THRESHOLD_TURNS):
        src.observe_turn(["browser_click"])
    assert src._state.drift_trigger(open_task_count=1) == "stale"


@pytest.mark.asyncio
async def test_reminder_state_survives_resume(task_store) -> None:
    """The counter is persisted to disk; a fresh source — as built on a
    session restart — reloads it. Drift counts and the per-session nudge
    cap survive the restart instead of silently resetting."""
    session_id = "s1"
    await task_store.create_task(session_id, subject="work")
    ctx = SimpleNamespace(session_id=session_id)

    # Run 1: advance counters; a render persists them to disk.
    src1 = TaskReminderSource()
    src1.observe_turn(["task_create"])  # task write → counter 0, ever_used
    for _ in range(4):
        src1.observe_turn(["browser_click"])  # counter → 4 (below stale)
    src1._state.drift_reminders_sent = 2
    await src1.render(ReminderContext(ReminderPoint.POST_TOOL_USE, ctx))

    # Run 2: a brand-new source — exactly what a restart constructs.
    src2 = TaskReminderSource()
    await src2.render(ReminderContext(ReminderPoint.SESSION_START, ctx))
    assert src2._state.turns_since_task_op == 4  # counter survived
    assert src2._state.drift_reminders_sent == 2  # nudge cap survived
    assert src2._state.task_tool_ever_used is True


def test_reminder_state_dict_roundtrip_tolerates_unknown_keys() -> None:
    s = ReminderState(turns_total=7, drift_reminders_sent=3)
    restored = ReminderState.from_dict({**s.to_dict(), "removed_field": 99})
    assert restored.turns_total == 7
    assert restored.drift_reminders_sent == 3


@pytest.mark.asyncio
async def test_read_records_excludes_archived(task_store) -> None:
    """The reminder must mirror the agent's default task_list — archived
    tasks are parked in History, not the working plan. Leaking them would
    re-surface archived items in the snapshot AND (archived != completed)
    inflate open_count, suppressing all_done and firing false stale nudges."""
    from framework.tasks.models import TaskStatus
    from framework.tasks.reminders import _read_records

    session_id = "s_arch"
    await task_store.create_task(session_id, subject="active")
    await task_store.create_task(session_id, subject="parked")
    await task_store.update_task(session_id, 2, status=TaskStatus.ARCHIVED)

    records = await _read_records(session_id)
    assert [r.subject for r in records] == ["active"]  # #2 archived, excluded


@pytest.mark.asyncio
async def test_open_count_ignores_archived(task_store) -> None:
    """Once every non-archived task is complete, open_count reaches 0 even
    with an archived task on the list — proof archived no longer counts as
    open (which had suppressed all_done and fired false stale nudges)."""
    from framework.tasks.models import TaskStatus
    from framework.tasks.reminders import _read_records

    session_id = "s_done"
    await task_store.create_task(session_id, subject="finished")
    await task_store.create_task(session_id, subject="parked")
    await task_store.update_task(session_id, 1, status=TaskStatus.COMPLETED)
    await task_store.update_task(session_id, 2, status=TaskStatus.ARCHIVED)

    records = await _read_records(session_id)
    open_count = sum(1 for r in records if r.status != TaskStatus.COMPLETED)
    assert open_count == 0  # archived task does NOT count as open
