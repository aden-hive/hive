"""Tests for the idle-nudge reminder source and the hub's temporal ticker.

The idle nudge is a :class:`ReminderSource` firing at the temporal
:class:`ReminderPoint.IDLE_TICK`. We exercise the source's policy in
isolation (cheap, deterministic) and the hub ticker end-to-end (it owns
the background poll and parks rendered reminders for the loop to drain).
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from framework.agent_loop.idle_nudge import IdleNudgeSource
from framework.agent_loop.internals.types import LoopConfig
from framework.agent_loop.reminders import (
    LoopActivity,
    LoopSignals,
    ParkReason,
    Reminder,
    ReminderContext,
    ReminderHub,
    ReminderPoint,
)


def _ctx(**signal_kwargs) -> ReminderContext:
    """A ReminderContext for IDLE_TICK with the given LoopSignals fields."""
    defaults = {
        "idle_seconds": 10.0,
        "awaiting_input": False,
        "stream_active": False,
        "first_event_seen": False,
    }
    defaults.update(signal_kwargs)
    return ReminderContext(
        point=ReminderPoint.IDLE_TICK,
        agent_ctx=SimpleNamespace(),
        signals=LoopSignals(**defaults),
    )


# ---------------------------------------------------------------------------
# ParkReason.activity — the park-reason → LoopActivity classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (ParkReason.ASK_USER, LoopActivity.AWAITING_USER),
        (ParkReason.COLONY_SUGGESTION, LoopActivity.AWAITING_USER),
        (ParkReason.TURN_DONE, LoopActivity.AWAITING_USER),
        (ParkReason.AWAITING_QUEEN, LoopActivity.AWAITING_USER),
        (ParkReason.USER_STOPPED, LoopActivity.INTERRUPTED),
        (ParkReason.LLM_ERROR, LoopActivity.INTERRUPTED),
        (ParkReason.EMPTY_RESPONSES, LoopActivity.INTERRUPTED),
        (ParkReason.DOOM_LOOP, LoopActivity.INTERRUPTED),
        (ParkReason.UNKNOWN, LoopActivity.INTERRUPTED),
    ],
)
def test_park_reason_activity_mapping(reason, expected) -> None:
    """Every ParkReason maps to its documented LoopActivity — the
    failure-sensitive table. A deliberate end-of-turn park is AWAITING_USER;
    every other park (broken, user-stopped, unknown) is INTERRUPTED."""
    assert reason.activity == expected


def test_park_reason_activity_is_total() -> None:
    """No ParkReason is left unclassified — .activity covers the enum."""
    for reason in ParkReason:
        assert reason.activity in (
            LoopActivity.AWAITING_USER,
            LoopActivity.INTERRUPTED,
        )


# ---------------------------------------------------------------------------
# ParkReason.is_silent_park — the "do not auto-resume" classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "is_silent"),
    [
        # Clean stopping points — agent finished or was stopped on purpose.
        (ParkReason.TURN_DONE, True),
        (ParkReason.USER_STOPPED, True),
        # External waits — blocked on another party, separate gate.
        (ParkReason.ASK_USER, False),
        (ParkReason.COLONY_SUGGESTION, False),
        (ParkReason.AWAITING_QUEEN, False),
        # Broken parks — the idle nudge SHOULD recover these.
        (ParkReason.LLM_ERROR, False),
        (ParkReason.EMPTY_RESPONSES, False),
        (ParkReason.DOOM_LOOP, False),
        # Unknown — ambiguous; falls through to the questionless-park
        # path so the idle nudge can recover a buggy state.
        (ParkReason.UNKNOWN, False),
    ],
)
def test_park_reason_is_silent_park(reason: ParkReason, is_silent: bool) -> None:
    """Silent parks (TURN_DONE / USER_STOPPED) suppress the idle nudge —
    the agent is at a natural stopping point and resuming would override
    the user's pause. Every other park reason is NOT silent."""
    assert reason.is_silent_park is is_silent


def test_park_reason_is_silent_park_disjoint_from_external_wait() -> None:
    """Silent parks and external-wait parks are mutually exclusive
    categories — a park is at most one. The idle nudge applies them as
    separate gates; overlap would be a classifier bug."""
    for reason in ParkReason:
        assert not (reason.is_silent_park and reason.is_external_wait), f"{reason} cannot be both silent and external_wait"


# ---------------------------------------------------------------------------
# IdleNudgeSource — policy in isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_fires_between_turns() -> None:
    """No stream task → substate=between_turns Reminder."""
    src = IdleNudgeSource(budget_seconds=5.0, max_nudges=3)
    out = await src.render(_ctx(idle_seconds=12.0, stream_active=False))
    assert isinstance(out, Reminder)
    assert out.source == "idle_nudge"
    assert out.meta["substate"] == "between_turns"
    assert out.meta["nudge_count"] == 1
    assert out.meta["cap"] == 3
    assert "between_turns" in out.body


@pytest.mark.asyncio
async def test_render_slow_ttft_substate() -> None:
    """Stream alive, no first event → substate=slow_ttft."""
    src = IdleNudgeSource(budget_seconds=5.0, max_nudges=3)
    out = await src.render(_ctx(idle_seconds=12.0, stream_active=True, first_event_seen=False))
    assert isinstance(out, Reminder)
    assert out.meta["substate"] == "slow_ttft"
    assert "slow_ttft" in out.body


@pytest.mark.asyncio
async def test_render_skips_active_stream_with_events() -> None:
    """Stream producing events → stream-level watchdog owns it, no nudge."""
    src = IdleNudgeSource(budget_seconds=5.0, max_nudges=3)
    out = await src.render(_ctx(idle_seconds=12.0, stream_active=True, first_event_seen=True))
    assert out is None


@pytest.mark.asyncio
async def test_render_skips_when_awaiting_input() -> None:
    """Awaiting input with no awaiting-budget configured → no nudge."""
    src = IdleNudgeSource(budget_seconds=5.0, max_nudges=3)
    out = await src.render(_ctx(idle_seconds=999.0, awaiting_input=True))
    assert out is None


@pytest.mark.asyncio
async def test_render_fires_parked_no_question() -> None:
    """Awaiting input with NO pending question → invalid park → nudge."""
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    out = await src.render(_ctx(idle_seconds=12.0, awaiting_input=True, park_reason=ParkReason.UNKNOWN))
    assert isinstance(out, Reminder)
    assert out.meta["substate"] == "parked_no_question"
    assert "no question" in out.body


@pytest.mark.asyncio
async def test_render_skips_awaiting_with_question() -> None:
    """Awaiting input backed by a real pending question → valid park, no nudge."""
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    out = await src.render(_ctx(idle_seconds=999.0, awaiting_input=True, park_reason=ParkReason.ASK_USER))
    assert out is None


@pytest.mark.asyncio
async def test_render_skips_external_wait_parks() -> None:
    """Every is_external_wait reason — ask_user, colony suggestion, a worker
    awaiting its queen — is a legitimate park the nudge leaves alone."""
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    for reason in (
        ParkReason.ASK_USER,
        ParkReason.COLONY_SUGGESTION,
        ParkReason.AWAITING_QUEEN,
    ):
        out = await src.render(_ctx(idle_seconds=999.0, awaiting_input=True, park_reason=reason))
        assert out is None, f"{reason} should suppress the nudge"


@pytest.mark.asyncio
async def test_render_fires_parked_broken() -> None:
    """A park caused by a failure → substate=parked_broken on the broken
    budget, naming the reason."""
    src = IdleNudgeSource(
        budget_seconds=120.0,
        max_nudges=3,
        awaiting_budget_seconds=120.0,
        broken_budget_seconds=5.0,
    )
    out = await src.render(_ctx(idle_seconds=8.0, awaiting_input=True, park_reason=ParkReason.LLM_ERROR))
    assert isinstance(out, Reminder)
    assert out.meta["substate"] == "parked_broken"
    assert out.meta["cap"] == 3
    assert "llm_error" in out.body


@pytest.mark.asyncio
async def test_parked_broken_body_is_reason_aware() -> None:
    """A DOOM_LOOP park must NOT tell the agent to re-attempt the blocked
    call (that re-arms the loop the breaker just stopped); it steers toward
    a different approach. Other broken reasons keep the generic re-attempt
    wording (retrying a transient LLM error is correct)."""
    src = IdleNudgeSource(
        budget_seconds=120.0,
        max_nudges=3,
        awaiting_budget_seconds=120.0,
        broken_budget_seconds=5.0,
    )
    doom = await src.render(_ctx(idle_seconds=8.0, awaiting_input=True, park_reason=ParkReason.DOOM_LOOP))
    assert isinstance(doom, Reminder)
    assert "different approach" in doom.body.lower()
    assert "do not repeat" in doom.body.lower()
    assert "re-attempt" not in doom.body.lower()

    src.reset()
    llm = await src.render(_ctx(idle_seconds=8.0, awaiting_input=True, park_reason=ParkReason.LLM_ERROR))
    assert isinstance(llm, Reminder)
    assert "re-attempt the work that failed" in llm.body


@pytest.mark.asyncio
async def test_broken_park_keys_off_broken_budget() -> None:
    """A broken park uses broken_budget_seconds — under the awaiting budget
    but over the broken one still fires; with no broken budget it is inert."""
    # Idle 8s: under the 120s awaiting budget, over the 5s broken budget.
    src = IdleNudgeSource(
        budget_seconds=120.0,
        max_nudges=3,
        awaiting_budget_seconds=120.0,
        broken_budget_seconds=5.0,
    )
    out = await src.render(_ctx(idle_seconds=8.0, awaiting_input=True, park_reason=ParkReason.DOOM_LOOP))
    assert isinstance(out, Reminder)
    assert out.meta["substate"] == "parked_broken"
    # No broken budget configured → the broken-park path is disabled.
    src2 = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=120.0)
    assert await src2.render(_ctx(idle_seconds=999.0, awaiting_input=True, park_reason=ParkReason.DOOM_LOOP)) is None


@pytest.mark.asyncio
async def test_render_skips_when_user_stopped() -> None:
    """An explicitly user-stopped agent is never auto-resumed by the nudge."""
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    # Signals that would otherwise fire parked_no_question — but user_stopped.
    out = await src.render(
        _ctx(
            idle_seconds=999.0,
            awaiting_input=True,
            park_reason=ParkReason.UNKNOWN,
            user_stopped=True,
        )
    )
    assert out is None
    # Sanity: the identical park without the user-stop DOES fire.
    out2 = await src.render(
        _ctx(
            idle_seconds=999.0,
            awaiting_input=True,
            park_reason=ParkReason.UNKNOWN,
            user_stopped=False,
        )
    )
    assert isinstance(out2, Reminder)
    assert out2.meta["substate"] == "parked_no_question"


@pytest.mark.asyncio
async def test_awaiting_park_uses_its_own_budget() -> None:
    """The questionless-park path keys off awaiting_budget_seconds, not the
    general budget — and is inert when no awaiting budget is configured.
    UNKNOWN is the only park reason that reaches this path now that
    TURN_DONE is gated upstream by ``is_silent_park``."""
    # Idle 8s: under the 120s general budget, over the 5s awaiting budget.
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    out = await src.render(_ctx(idle_seconds=8.0, awaiting_input=True, park_reason=ParkReason.UNKNOWN))
    assert isinstance(out, Reminder)
    assert out.meta["substate"] == "parked_no_question"
    # Same idle, no awaiting budget → the questionless-park path is disabled.
    src2 = IdleNudgeSource(budget_seconds=120.0, max_nudges=3)
    assert await src2.render(_ctx(idle_seconds=8.0, awaiting_input=True, park_reason=ParkReason.UNKNOWN)) is None


@pytest.mark.asyncio
async def test_render_skips_when_park_is_turn_done() -> None:
    """TURN_DONE is a silent park — the queen finished cleanly and is
    awaiting the next user message. The idle nudge MUST NOT auto-resume
    her; doing so overrides the user's natural pause. The agent
    restarts only when the user sends a real message."""
    src = IdleNudgeSource(
        budget_seconds=120.0,
        max_nudges=3,
        awaiting_budget_seconds=5.0,
    )
    # Idle far past the awaiting budget — would normally fire
    # parked_no_question. Silent-park gate suppresses.
    out = await src.render(_ctx(idle_seconds=999.0, awaiting_input=True, park_reason=ParkReason.TURN_DONE))
    assert out is None


@pytest.mark.asyncio
async def test_render_still_fires_for_broken_parks() -> None:
    """Sanity counterpart to the TURN_DONE / USER_STOPPED gates: broken
    parks (LLM_ERROR, DOOM_LOOP, EMPTY_RESPONSES) still nudge, because
    the loop is stranded by failure and needs recovery."""
    src = IdleNudgeSource(
        budget_seconds=120.0,
        max_nudges=3,
        awaiting_budget_seconds=120.0,
        broken_budget_seconds=5.0,
    )
    for broken in (ParkReason.LLM_ERROR, ParkReason.DOOM_LOOP, ParkReason.EMPTY_RESPONSES):
        out = await src.render(_ctx(idle_seconds=10.0, awaiting_input=True, park_reason=broken))
        assert isinstance(out, Reminder), f"broken park {broken} should still nudge"
        assert out.meta["substate"] == "parked_broken"
        # Reset rate-limiter between probes (the test src is shared).
        src.reset()


@pytest.mark.asyncio
async def test_silent_park_gate_logs_once_across_ticks(caplog) -> None:
    """A steady silent park logs its suppression line ONCE, not per tick.

    The idle ticker polls every few seconds; the gate-dedup keeps a parked
    session from repeating the same 'suppressed' INFO line forever — the
    field-observed noise. Only idle_seconds changes between ticks, so the
    signature is stable and the line is emitted a single time."""
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    with caplog.at_level("INFO", logger="framework.agent_loop.idle_nudge"):
        for idle in (450.0, 495.0, 505.0, 600.0):
            out = await src.render(_ctx(idle_seconds=idle, awaiting_input=True, park_reason=ParkReason.TURN_DONE))
            assert out is None
    silent_lines = [r for r in caplog.records if "gate=silent_park" in r.message]
    assert len(silent_lines) == 1, f"expected one silent_park line, got {len(silent_lines)}"


@pytest.mark.asyncio
async def test_gate_relogs_after_user_message(caplog) -> None:
    """reset() (a user message) re-arms the gate dedup, so the same steady
    park logs once more in the next response cycle — the dedup is per
    cycle, not per whole session."""
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    with caplog.at_level("INFO", logger="framework.agent_loop.idle_nudge"):
        await src.render(_ctx(idle_seconds=450.0, awaiting_input=True, park_reason=ParkReason.TURN_DONE))
        await src.render(_ctx(idle_seconds=495.0, awaiting_input=True, park_reason=ParkReason.TURN_DONE))
        src.reset()  # user sent a message
        await src.render(_ctx(idle_seconds=540.0, awaiting_input=True, park_reason=ParkReason.TURN_DONE))
    silent_lines = [r for r in caplog.records if "gate=silent_park" in r.message]
    assert len(silent_lines) == 2, f"expected one line per cycle, got {len(silent_lines)}"


@pytest.mark.asyncio
async def test_render_skips_under_budget() -> None:
    """Idle time below budget → no nudge."""
    src = IdleNudgeSource(budget_seconds=5.0, max_nudges=3)
    out = await src.render(_ctx(idle_seconds=2.0))
    assert out is None


@pytest.mark.asyncio
async def test_render_self_rate_limits() -> None:
    """A second render within the budget window is suppressed."""
    src = IdleNudgeSource(budget_seconds=5.0, max_nudges=3)
    first = await src.render(_ctx(idle_seconds=12.0))
    assert isinstance(first, Reminder)
    # Immediately again — still idle, but inside the rate-limit window.
    second = await src.render(_ctx(idle_seconds=13.0))
    assert second is None


@pytest.mark.asyncio
async def test_render_respects_cap() -> None:
    """At most ``cap`` nudges per variant across a response cycle."""
    src = IdleNudgeSource(budget_seconds=5.0, max_nudges=2)
    fired = 0
    for _ in range(5):
        out = await src.render(_ctx(idle_seconds=99.0))
        if out is not None:
            fired += 1
        # Defeat the self-rate-limit so only the cap is under test.
        src._last_eval_at = 0.0
    assert fired == 2
    assert src._nudges["between_turns"] == 2


@pytest.mark.asyncio
async def test_parked_open_tasks_variant(monkeypatch) -> None:
    """A questionless park WITH open tasks → parked_open_tasks, names them."""
    import framework.agent_loop.idle_nudge as mod

    async def _fake_open_tasks(_agent_ctx):
        return [
            SimpleNamespace(id=7, subject="ship the thing", status=None),
            SimpleNamespace(id=8, subject="write docs", status=None),
        ]

    monkeypatch.setattr(mod, "_open_tasks", _fake_open_tasks)
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    out = await src.render(_ctx(idle_seconds=12.0, awaiting_input=True, park_reason=ParkReason.UNKNOWN))
    assert isinstance(out, Reminder)
    assert out.meta["substate"] == "parked_open_tasks"
    assert out.meta["cap"] == 3
    assert '#7 "ship the thing"' in out.body
    assert '#8 "write docs"' in out.body


@pytest.mark.asyncio
async def test_parked_open_tasks_respects_full_cap(monkeypatch) -> None:
    """parked_open_tasks may fire up to max_nudges (3) times."""
    import framework.agent_loop.idle_nudge as mod

    async def _fake_open_tasks(_agent_ctx):
        return [SimpleNamespace(id=1, subject="task", status=None)]

    monkeypatch.setattr(mod, "_open_tasks", _fake_open_tasks)
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    fired = 0
    for _ in range(6):
        out = await src.render(_ctx(idle_seconds=99.0, awaiting_input=True, park_reason=ParkReason.UNKNOWN))
        if out is not None:
            fired += 1
        src._last_eval_at = 0.0
    assert fired == 3
    assert src._nudges["parked_open_tasks"] == 3


@pytest.mark.asyncio
async def test_capped_park_does_not_rescan_every_tick(monkeypatch) -> None:
    """A park that has hit its nudge cap must not re-run the (blocking)
    task-store lookup on every poll tick.

    Regression for the long-idle runtime hang: the rate-limit used to key on
    the last *fire* time, which froze once a park stopped firing — so a
    capped, steadily-parked session re-ran ``_open_tasks`` (a thread-pool
    filesystem scan) on every ~5s idle tick, eventually starving the shared
    executor and hanging session-load reads. The throttle now keys on the
    last *evaluation*, so the lookup runs at most once per budget window
    regardless of cap state.
    """
    import framework.agent_loop.idle_nudge as mod

    calls = 0

    async def _counting_open_tasks(_agent_ctx):
        nonlocal calls
        calls += 1
        return [SimpleNamespace(id=1, subject="task", status=None)]

    monkeypatch.setattr(mod, "_open_tasks", _counting_open_tasks)
    # max_nudges=1 → the park is capped after a single fire; the ticks that
    # follow are the capped-and-parked state that used to re-scan every poll.
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=1, awaiting_budget_seconds=120.0)

    async def _tick():
        return await src.render(_ctx(idle_seconds=999.0, awaiting_input=True, park_reason=ParkReason.UNKNOWN))

    # First poll of the window: passes the budget gate, does ONE lookup, fires.
    assert await _tick() is not None
    assert calls == 1

    # The park is now capped. Simulate a budget window elapsing (the throttle
    # timestamp goes stale), then poll rapidly many times as the idle ticker
    # does. The eval-keyed throttle re-arms on the first poll and suppresses
    # the rest, so the blocking lookup runs at most ONCE for the whole window
    # — not once per tick (which is what wedged the runtime).
    src._last_eval_at = 0.0
    for _ in range(10):
        assert await _tick() is None
    assert calls == 2  # one rescan for the elapsed window, not 11


@pytest.mark.asyncio
async def test_parked_no_question_fires_only_once(monkeypatch) -> None:
    """A questionless park with NO open tasks is nudged exactly once."""
    import framework.agent_loop.idle_nudge as mod

    async def _no_tasks(_agent_ctx):
        return []

    monkeypatch.setattr(mod, "_open_tasks", _no_tasks)
    src = IdleNudgeSource(budget_seconds=120.0, max_nudges=3, awaiting_budget_seconds=5.0)
    fired = 0
    for _ in range(5):
        out = await src.render(_ctx(idle_seconds=99.0, awaiting_input=True, park_reason=ParkReason.UNKNOWN))
        if out is not None:
            fired += 1
        src._last_eval_at = 0.0
    assert fired == 1
    assert src._nudges["parked_no_question"] == 1


@pytest.mark.asyncio
async def test_reset_rearms_caps() -> None:
    """reset() clears per-variant counts so each variant may nudge afresh."""
    src = IdleNudgeSource(budget_seconds=5.0, max_nudges=2)
    for _ in range(3):
        await src.render(_ctx(idle_seconds=99.0))
        src._last_eval_at = 0.0
    assert src._nudges.get("between_turns") == 2
    # A user message re-arms the budget.
    src.reset()
    assert src._nudges == {}
    out = await src.render(_ctx(idle_seconds=99.0))
    assert isinstance(out, Reminder)
    assert out.meta["nudge_count"] == 1


@pytest.mark.asyncio
async def test_disabled_when_budget_zero() -> None:
    """Zero budget disables the source entirely."""
    src = IdleNudgeSource(budget_seconds=0.0, max_nudges=3)
    assert src.tick_interval() is None
    assert await src.render(_ctx(idle_seconds=999.0)) is None


def test_tick_interval_scales_with_budget() -> None:
    """tick_interval = budget/2, clamped to [0.01, 5.0]."""
    assert IdleNudgeSource(budget_seconds=120.0, max_nudges=3).tick_interval() == 5.0
    assert IdleNudgeSource(budget_seconds=4.0, max_nudges=3).tick_interval() == 2.0
    assert IdleNudgeSource(budget_seconds=0.05, max_nudges=3).tick_interval() == 0.025


# ---------------------------------------------------------------------------
# ReminderHub temporal ticker — end to end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hub_ticker_parks_idle_nudge() -> None:
    """The ticker polls, the source renders, the hub parks the Reminder."""
    hub = ReminderHub()
    hub.register(IdleNudgeSource(budget_seconds=0.05, max_nudges=2))
    woken = []

    def signals() -> LoopSignals:
        # Always look idle past the budget.
        return LoopSignals(idle_seconds=10.0, stream_active=False)

    await hub.start(
        SimpleNamespace(),
        signals_provider=signals,
        wake=lambda: woken.append(True),
    )
    # Give the ticker a couple of poll cycles.
    await asyncio.sleep(0.3)
    await hub.stop()

    # stop() clears the buffer, so capture is done via wake side effect:
    # at least one tick must have parked something and woken the loop.
    assert woken, "ticker never parked a reminder / called wake"


@pytest.mark.asyncio
async def test_hub_take_pending_hands_off_and_clears() -> None:
    """take_pending returns parked reminders once, then empties."""
    hub = ReminderHub()
    hub.register(IdleNudgeSource(budget_seconds=0.05, max_nudges=3))

    await hub.start(
        SimpleNamespace(),
        signals_provider=lambda: LoopSignals(idle_seconds=10.0, stream_active=False),
    )
    # Poll long enough for at least one nudge to be parked.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        if hub._pending:
            break
    # Stop the ticker BEFORE draining so the buffer can't grow under us.
    hub._ticker_task.cancel()
    try:
        await hub._ticker_task
    except asyncio.CancelledError:
        pass

    first = hub.take_pending()
    assert len(first) >= 1
    assert all(r.source == "idle_nudge" for r in first)
    # Second drain is empty — take_pending cleared the buffer.
    assert hub.take_pending() == []


@pytest.mark.asyncio
async def test_hub_start_noop_without_temporal_sources() -> None:
    """No source declares a tick_interval → no ticker task is created."""
    hub = ReminderHub()
    await hub.start(SimpleNamespace())
    assert hub._ticker_task is None
    await hub.stop()  # safe even when nothing started


@pytest.mark.asyncio
async def test_hub_ticker_skips_while_awaiting_input() -> None:
    """While awaiting_input the source renders nothing → buffer stays empty."""
    hub = ReminderHub()
    hub.register(IdleNudgeSource(budget_seconds=0.05, max_nudges=3))
    await hub.start(
        SimpleNamespace(),
        signals_provider=lambda: LoopSignals(idle_seconds=999.0, awaiting_input=True),
    )
    await asyncio.sleep(0.3)
    pending = hub.take_pending()
    await hub.stop()
    assert pending == []


# ---------------------------------------------------------------------------
# ReminderHub.post() — reactive reminders
# ---------------------------------------------------------------------------


def test_hub_post_then_take_pending_round_trip() -> None:
    """post() parks a reminder; take_pending() hands it off and clears."""
    hub = ReminderHub()
    r = Reminder(source="tool_budget", body="deferred 3 calls")
    hub.post(r)
    out = hub.take_pending()
    assert out == [r]
    # Buffer cleared — second drain is empty.
    assert hub.take_pending() == []


def test_hub_post_coexists_with_ticker_buffer() -> None:
    """post() appends to the same buffer the ticker uses."""
    hub = ReminderHub()
    hub.post(Reminder(source="tool_budget", body="a"))
    hub.post(Reminder(source="tool_budget", body="b"))
    out = hub.take_pending()
    assert [r.body for r in out] == ["a", "b"]


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_default_config_values() -> None:
    """Defaults match the budget the user observed missing in the field."""
    cfg = LoopConfig()
    assert cfg.session_idle_nudge_seconds == 120.0
    assert cfg.session_idle_nudge_max_per_session == 3
    assert cfg.session_idle_nudge_awaiting_seconds == 120.0
    assert cfg.session_idle_nudge_broken_seconds == 30.0
