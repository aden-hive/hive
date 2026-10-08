"""Tests for Sentinel's decision engine (framework.sentinel.escalation_source).

Mirrors test_idle_nudge.py: drive ``render`` with synthetic LoopSignals and
fakes, asserting the three outcomes — nudge (returns a Reminder, wakes the
loop), escalate (side-effect + returns None, stays parked), nothing (None).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import framework.sentinel.store as store_mod
from framework.agent_loop.reminders import (
    LoopSignals,
    ParkReason,
    Reminder,
    ReminderContext,
    ReminderPoint,
)
from framework.sentinel.classifier import (
    VERDICT_CONTINUE,
    VERDICT_DONE,
    VERDICT_NEEDS_HUMAN,
    ClassifierVerdict,
    ParkContext,
)
from framework.sentinel.escalation_source import EscalationSource
from framework.sentinel.store import NotificationsConfig


@pytest.fixture
def patched_store(monkeypatch):
    monkeypatch.setattr(store_mod, "classify_after_seconds", lambda: 100.0)
    monkeypatch.setattr(store_mod, "escalate_when_ui_attached", lambda: False)
    monkeypatch.setattr(store_mod, "max_nudges_before_escalate", lambda: 3)
    monkeypatch.setattr(
        store_mod,
        "load_notifications_config",
        lambda cid: NotificationsConfig(sentinel_enabled=True, channel="telegram", target={"chat_id": "1"}, allowlist=[], thread={}),
    )


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _make_source(
    *,
    verdict=VERDICT_CONTINUE,
    errored=False,
    open_tasks=("t1",),
    goal="enrich 1000 leads",
    ui=False,
    clock=None,
    forbid_classify=False,
    running_workers=(),
):
    escalated: list[dict] = []
    clock = clock or _Clock()

    async def provider():
        return ParkContext(
            park_reason="turn_done",
            goal=goal,
            open_tasks=list(open_tasks),
            last_assistant_text="Done 200. Shall I continue?",
            running_workers=list(running_workers),
        )

    async def classify(pctx, llm):
        if forbid_classify:
            raise AssertionError("classifier must not be called on this path")
        return ClassifierVerdict(verdict, errored=errored)

    src = EscalationSource(
        park_context_provider=provider,
        on_escalate=lambda p: escalated.append(p) or True,
        has_attached_ui=lambda sid: ui,
        classify_fn=classify,
        now_fn=clock,
    )
    return src, escalated, clock


def _ctx(reason=ParkReason.TURN_DONE, idle=200.0, awaiting=True, user_stopped=False, colony="c1", session="s1", queen=True):
    return ReminderContext(
        point=ReminderPoint.IDLE_TICK,
        agent_ctx=SimpleNamespace(is_queen_stream=queen, colony_id=colony, session_id=session, llm=None),
        signals=LoopSignals(idle_seconds=idle, awaiting_input=awaiting, park_reason=reason, user_stopped=user_stopped),
    )


# ----- applies_to ---------------------------------------------------------


def test_applies_to_colony_queen():
    src, *_ = _make_source()
    assert src.applies_to(SimpleNamespace(is_queen_stream=True, colony_id="c1")) is True


def test_applies_to_skips_worker():
    src, *_ = _make_source()
    assert src.applies_to(SimpleNamespace(is_queen_stream=False, colony_id="c1")) is False


def test_applies_to_skips_dm_queen():
    src, *_ = _make_source()
    assert src.applies_to(SimpleNamespace(is_queen_stream=True, colony_id=None)) is False


# ----- nudge vs escalate --------------------------------------------------


@pytest.mark.asyncio
async def test_nudge_returns_reminder(patched_store):
    src, escalated, _ = _make_source(verdict=VERDICT_CONTINUE)
    out = await src.render(_ctx())
    assert isinstance(out, Reminder)
    assert not escalated
    assert src._nudge_count == 1


@pytest.mark.asyncio
async def test_nudge_surfaces_running_workers(patched_store):
    # When the queen parked while a fan-out is still running, the nudge must
    # tell it to WAIT for WORKER_REPORTs rather than the bare "continue now"
    # — otherwise the resumed queen re-dispatches the same tasks.
    src, _, _ = _make_source(
        verdict=VERDICT_CONTINUE,
        running_workers=[{"worker_id": "w1", "status": "running", "task": "scrape influencer A", "elapsed_seconds": 750}],
    )
    out = await src.render(_ctx())
    assert isinstance(out, Reminder)
    assert "w1" in out.body and "still running" in out.body.lower()
    assert "12m" in out.body  # how long it's been running
    assert "WORKER_REPORT" in out.body and "wait" in out.body.lower()


@pytest.mark.asyncio
async def test_nudge_omits_worker_note_when_none(patched_store):
    # No live workers → no worker note (the plain autonomous-continue nudge).
    src, _, _ = _make_source(verdict=VERDICT_CONTINUE, running_workers=())
    out = await src.render(_ctx())
    assert isinstance(out, Reminder)
    assert "still running" not in out.body.lower()


@pytest.mark.asyncio
async def test_escalate_side_effect_and_none(patched_store):
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN)
    out = await src.render(_ctx())
    assert out is None  # stays parked
    assert len(escalated) == 1
    payload = escalated[0]
    assert payload["colony_id"] == "c1"
    assert payload["session_id"] == "s1"
    assert payload["correlation_token"]
    assert "continue" in payload["question_text"].lower()
    assert payload["kind"] == "blocker"  # classifier needs_human → blocker
    assert src._held  # a blocker parks the source until resume


@pytest.mark.asyncio
async def test_escalate_suppressed_when_ui_attached(patched_store):
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN, ui=True)
    out = await src.render(_ctx())
    assert out is None
    assert not escalated


@pytest.mark.asyncio
async def test_per_colony_budget_overrides_global(monkeypatch):
    # Global budget is small (100s) but this colony sets a larger per-colony
    # budget (500s). At 200s idle the colony is still under its OWN budget, so
    # sentinel waits rather than acting on the global value — even though the
    # classifier would say needs_human.
    monkeypatch.setattr(store_mod, "classify_after_seconds", lambda: 100.0)
    monkeypatch.setattr(store_mod, "escalate_when_ui_attached", lambda: False)
    monkeypatch.setattr(store_mod, "max_nudges_before_escalate", lambda: 3)
    monkeypatch.setattr(
        store_mod,
        "load_notifications_config",
        lambda cid: NotificationsConfig(
            sentinel_enabled=True,
            channel="telegram",
            target={"chat_id": "1"},
            allowlist=[],
            thread={},
            classify_after_seconds=500.0,
        ),
    )
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN)
    out = await src.render(_ctx(idle=200.0))
    assert out is None  # under the per-colony budget → waiting, not escalating
    assert not escalated
    assert src._nudge_count == 0


@pytest.mark.asyncio
async def test_broken_park_escalates_without_classifier(patched_store):
    src, escalated, _ = _make_source(forbid_classify=True)
    out = await src.render(_ctx(reason=ParkReason.LLM_ERROR))
    assert out is None
    assert len(escalated) == 1
    assert escalated[0]["kind"] == "blocker"  # broken park → blocker


@pytest.mark.asyncio
async def test_nudge_budget_escalates_as_heartbeat(patched_store):
    # After the nudge budget is spent, escalate — but tagged "heartbeat" (a
    # redirectable checkpoint), NOT "blocker". The classifier is not consulted
    # (forbid_classify proves the budget short-circuits before it).
    src, escalated, _ = _make_source(forbid_classify=True)
    src._nudge_count = 3  # patched_store sets max_nudges_before_escalate() == 3
    out = await src.render(_ctx())
    assert out is None
    assert len(escalated) == 1
    assert escalated[0]["kind"] == "heartbeat"


@pytest.mark.asyncio
async def test_no_goal_and_no_tasks_does_nothing(patched_store):
    # The only "nothing to act on" case: no goal AND no open tasks.
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN, open_tasks=(), goal=None)
    out = await src.render(_ctx())
    assert out is None
    assert not escalated
    assert src._nudge_count == 0


@pytest.mark.asyncio
async def test_goal_without_open_tasks_still_acts(patched_store):
    # A goal alone is enough — an empty task list no longer blocks sentinel, so
    # a genuine blocker still escalates even when no tasks are tracked.
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN, open_tasks=(), goal="enrich 1000 leads")
    out = await src.render(_ctx())
    assert out is None  # escalate path returns None (stays parked)
    assert len(escalated) == 1


@pytest.mark.asyncio
async def test_classifier_error_does_not_nudge(patched_store):
    # A failed/absent classifier returns continue-but-errored. That must NOT
    # be turned into a nudge (the observed bug: a transient LLM error re-poked a
    # parked, done queen). No nudge, no escalation, source not held → it simply
    # re-evaluates next window.
    clock = _Clock()
    src, escalated, _ = _make_source(verdict=VERDICT_CONTINUE, errored=True, clock=clock)
    out = await src.render(_ctx())
    assert out is None
    assert not escalated
    assert src._nudge_count == 0
    assert not src._held
    # Still errored next window → still a no-op, never a stuck escalation.
    clock.t += 200
    assert await src.render(_ctx()) is None
    assert not escalated


@pytest.mark.asyncio
async def test_loop_breaker_stops_nudging_done_queen(patched_store):
    # A turn-done park with NO open tasks gets exactly ONE classifier-driven
    # nudge; if it comes back parked in the same state, Sentinel stops nudging
    # and surfaces a single heartbeat instead of re-poking every window until
    # the max-nudge cap. This is the InMail "goal complete / nudge / repeat" fix.
    clock = _Clock()
    src, escalated, _ = _make_source(verdict=VERDICT_CONTINUE, open_tasks=(), goal="enrich 1000 leads", clock=clock)
    out = await src.render(_ctx())
    assert isinstance(out, Reminder)  # first nudge allowed
    assert src._nudge_count == 1
    clock.t += 200  # past the rate-limit window
    out = await src.render(_ctx())
    assert out is None  # no second nudge
    assert len(escalated) == 1
    assert escalated[0]["kind"] == "heartbeat"  # surfaced once, then holds
    assert src._held


@pytest.mark.asyncio
async def test_loop_breaker_does_not_fire_with_open_tasks(patched_store):
    # The loop-breaker is scoped to the empty-task-list case. With open tasks,
    # repeated nudges remain valid (the queen has concrete work to resume), up
    # to the normal max-nudge cap.
    clock = _Clock()
    src, escalated, _ = _make_source(verdict=VERDICT_CONTINUE, open_tasks=("t1",), clock=clock)
    assert isinstance(await src.render(_ctx()), Reminder)
    clock.t += 200
    assert isinstance(await src.render(_ctx()), Reminder)  # still nudges
    assert src._nudge_count == 2
    assert not escalated


@pytest.mark.asyncio
async def test_done_reports_completion(patched_store):
    # The judge says the colony finished: Sentinel emits a `done` completion
    # report (no nudge, not parked as a blocker) instead of re-poking a done
    # colony. Completion is judged, never inferred from an empty task list.
    src, escalated, _ = _make_source(verdict=VERDICT_DONE, open_tasks=(), goal="enrich 1000 leads")
    out = await src.render(_ctx())
    assert out is None  # not nudged
    assert len(escalated) == 1
    assert escalated[0]["kind"] == "done"


# ----- gates --------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_per_colony(patched_store, monkeypatch):
    monkeypatch.setattr(
        store_mod,
        "load_notifications_config",
        lambda cid: NotificationsConfig(sentinel_enabled=False),
    )
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN)
    assert await src.render(_ctx()) is None
    assert not escalated


@pytest.mark.asyncio
async def test_under_budget_does_nothing(patched_store):
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN)
    assert await src.render(_ctx(idle=10.0)) is None  # budget is 100
    assert not escalated


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [ParkReason.USER_STOPPED, ParkReason.COLONY_SUGGESTION, ParkReason.AWAITING_QUEEN])
async def test_sacred_parks_skipped(patched_store, reason):
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN)
    assert await src.render(_ctx(reason=reason)) is None
    assert not escalated


@pytest.mark.asyncio
async def test_user_stopped_flag_skipped(patched_store):
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN)
    assert await src.render(_ctx(user_stopped=True)) is None
    assert not escalated


# ----- dedup / rate-limit / nudge cap -------------------------------------


@pytest.mark.asyncio
async def test_escalate_dedups_until_reset(patched_store):
    clock = _Clock()
    src, escalated, _ = _make_source(verdict=VERDICT_NEEDS_HUMAN, clock=clock)
    assert await src.render(_ctx()) is None
    assert len(escalated) == 1
    # Advance past the rate-limit window — still no second escalation.
    clock.t += 1000
    assert await src.render(_ctx()) is None
    assert len(escalated) == 1
    # A real resume re-arms it.
    src.reset()
    clock.t += 1000
    assert await src.render(_ctx()) is None
    assert len(escalated) == 2


@pytest.mark.asyncio
async def test_rate_limited_within_window(patched_store):
    clock = _Clock()
    src, escalated, _ = _make_source(verdict=VERDICT_CONTINUE, clock=clock)
    assert isinstance(await src.render(_ctx()), Reminder)
    assert src._nudge_count == 1
    clock.t += 50  # within the 100s window
    assert await src.render(_ctx()) is None
    assert src._nudge_count == 1
    clock.t += 100  # past the window
    assert isinstance(await src.render(_ctx()), Reminder)
    assert src._nudge_count == 2


@pytest.mark.asyncio
async def test_escalates_after_max_nudges(patched_store):
    clock = _Clock()
    src, escalated, _ = _make_source(verdict=VERDICT_CONTINUE, clock=clock)
    # max_nudges_before_escalate is 3 → three nudges, then escalate.
    for _ in range(3):
        out = await src.render(_ctx())
        assert isinstance(out, Reminder)
        clock.t += 200
    out = await src.render(_ctx())
    assert out is None
    assert len(escalated) == 1


# ----- single-owner rule: idle-nudge defers to Sentinel -------------------


def test_idle_nudge_defers_to_active_autopilot(monkeypatch):
    """When autopilot is enabled for a colony queen, the idle-nudge source
    must self-skip so the two never double-nudge."""
    from framework.agent_loop.idle_nudge import _sentinel_autopilot_active

    monkeypatch.setattr(
        store_mod,
        "load_notifications_config",
        lambda cid: NotificationsConfig(sentinel_enabled=True),
    )
    assert _sentinel_autopilot_active(SimpleNamespace(is_queen_stream=True, colony_id="c1")) is True
    # Not a colony queen → idle nudge keeps its normal behavior.
    assert _sentinel_autopilot_active(SimpleNamespace(is_queen_stream=False, colony_id="c1")) is False
    assert _sentinel_autopilot_active(SimpleNamespace(is_queen_stream=True, colony_id=None)) is False

    monkeypatch.setattr(
        store_mod,
        "load_notifications_config",
        lambda cid: NotificationsConfig(sentinel_enabled=False),
    )
    assert _sentinel_autopilot_active(SimpleNamespace(is_queen_stream=True, colony_id="c1")) is False
