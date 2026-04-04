"""Component tests: Queen State Machine Edge Cases.

Race conditions, invalid transitions, stale events.

These tests confirm real bugs and edge cases in the queen's phase
state machine:
- Non-atomic phase switch + event emission
- Stale worker completion events ignored during wrong phase
- No guards against invalid phase transitions
- Double phase switch deduplication
- inject_notification after executor teardown
- Empty tool lists per phase
- Phase persistence across rapid cycling
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.server.session_manager import Session
from framework.tools.queen_lifecycle_tools import QueenPhaseState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

QUEEN_STARTUP_TIMEOUT = 30


async def _start_queen_session(llm_provider, tmp_path, *, worker_identity=None):
    """Start a real queen and return (session, task)."""
    from framework.server.queen_orchestrator import create_queen

    event_bus = EventBus()
    session = Session(
        id=f"test_{int(time.time())}",
        event_bus=event_bus,
        llm=llm_provider,
        loaded_at=time.time(),
    )
    queen_dir = tmp_path / "queen"
    queen_dir.mkdir(parents=True, exist_ok=True)

    mgr = MagicMock()
    mgr._subscribe_worker_handoffs = MagicMock()

    task = await create_queen(
        session=session,
        session_manager=mgr,
        worker_identity=worker_identity,
        queen_dir=queen_dir,
        initial_prompt="Hello",
    )

    for _ in range(QUEEN_STARTUP_TIMEOUT * 10):
        if session.queen_executor is not None:
            break
        await asyncio.sleep(0.1)

    assert session.queen_executor is not None
    return session, task


async def _shutdown(session, task):
    node = session.queen_executor.node_registry.get("queen") if session.queen_executor else None
    if node and hasattr(node, "signal_shutdown"):
        node.signal_shutdown()
    if not task.done():
        task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5)
    except (asyncio.CancelledError, TimeoutError, asyncio.TimeoutError):
        pass


# -----------------------------------------------------------------------
# BUG #1: Concurrent phase switches — no crash or lost events
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_phase_switches_no_crash(llm_provider, tmp_path, artifact):
    """Firing multiple phase switches concurrently must not crash."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    phases_seen = []

    async def _capture(event: AgentEvent):
        phases_seen.append(event.data.get("phase"))

    session.event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=_capture,
    )
    try:
        ps = session.phase_state
        # Fire 4 phase switches concurrently
        await asyncio.gather(
            ps.switch_to_building(source="test"),
            ps.switch_to_staging(source="test"),
            ps.switch_to_running(source="test"),
            ps.switch_to_planning(source="test"),
        )
        await asyncio.sleep(0.3)

        valid_phases = ("planning", "building", "staging", "running", "editing")

        artifact.record_value(
            "final_phase",
            ps.phase,
            expected="valid phase (not corrupted)",
        )
        artifact.record_value("phases_seen", phases_seen)

        artifact.check(
            "phase is valid",
            ps.phase in valid_phases,
            actual=repr(ps.phase),
            expected_val="one of planning/building/staging/running/editing",
        )
        assert ps.phase in valid_phases, f"Phase corrupted: {ps.phase}"

        artifact.check(
            "at least 1 phase event",
            len(phases_seen) >= 1,
            actual=str(len(phases_seen)),
            expected_val=">=1",
        )
        assert len(phases_seen) >= 1, "No phase change events"
    finally:
        await _shutdown(session, task)


# -----------------------------------------------------------------------
# BUG #3: Non-atomic phase change + event
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_changes_without_event_bus(artifact):
    """Phase must still change when event_bus is None (no crash)."""
    ps = QueenPhaseState(phase="planning", event_bus=None)

    await ps.switch_to_building(source="test")

    artifact.record_value(
        "phase",
        ps.phase,
        expected="'building' even without event bus",
    )

    artifact.check(
        "phase changed to building",
        ps.phase == "building",
        actual=repr(ps.phase),
        expected_val="'building'",
    )
    assert ps.phase == "building", "Phase should change even without event bus"


@pytest.mark.asyncio
async def test_phase_change_committed_before_event(artifact):
    """Phase assignment before event emission — verify both occur."""
    bus = EventBus()
    phases_at_event_time = []

    async def _capture(event: AgentEvent):
        phases_at_event_time.append(event.data.get("phase"))

    bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=_capture,
    )

    ps = QueenPhaseState(phase="planning", event_bus=bus)
    await ps.switch_to_building(source="test")
    await asyncio.sleep(0.1)

    artifact.record_value(
        "phase",
        ps.phase,
        expected="'building', event reports 'building'",
    )
    artifact.record_value(
        "phases_at_event_time",
        phases_at_event_time,
    )

    artifact.check(
        "phase is building",
        ps.phase == "building",
        actual=repr(ps.phase),
        expected_val="'building'",
    )
    assert ps.phase == "building"

    artifact.check(
        "event reports building",
        phases_at_event_time == ["building"],
        actual=str(phases_at_event_time),
        expected_val="['building']",
    )
    assert phases_at_event_time == ["building"], (
        f"Event should report 'building', got: {phases_at_event_time}"
    )


# -----------------------------------------------------------------------
# BUG #4: Stale worker done events during non-running phase
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_done_ignored_in_non_running_phase(llm_provider, tmp_path, artifact):
    """Worker completion in planning phase must be silently dropped.

    This confirms BUG #4: the _on_worker_done handler only processes
    events when phase == 'running'. Events in other phases are lost.
    """
    session, task = await _start_queen_session(llm_provider, tmp_path)
    phase_changes = []

    async def _capture(event: AgentEvent):
        phase_changes.append(event.data.get("phase"))

    session.event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=_capture,
    )
    try:
        ps = session.phase_state

        artifact.check(
            "initial phase is planning",
            ps.phase == "planning",
            actual=repr(ps.phase),
            expected_val="'planning'",
        )
        assert ps.phase == "planning"

        # Simulate a stale worker completion event
        await session.event_bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_COMPLETED,
                stream_id="worker",
                data={"output": {"result": "stale output"}},
            )
        )
        await asyncio.sleep(0.5)

        artifact.record_value(
            "phase_after_stale_event",
            ps.phase,
            expected="still 'planning' (stale event ignored)",
        )
        artifact.record_value("phase_changes", phase_changes)

        artifact.check(
            "phase still planning",
            ps.phase == "planning",
            actual=repr(ps.phase),
            expected_val="'planning'",
        )
        assert ps.phase == "planning", f"Phase should still be planning, got: {ps.phase}"

        artifact.check(
            "no auto-switch to editing",
            "staging" not in phase_changes,
            actual=str(phase_changes),
            expected_val="does not contain 'staging'",
        )
        assert "staging" not in phase_changes, (
            "Should not auto-switch to editing from planning phase"
        )
    finally:
        await _shutdown(session, task)


# -----------------------------------------------------------------------
# BUG #10: No guards against invalid phase transitions
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_running_to_building_blocked(llm_provider, tmp_path, artifact):
    """RUNNING -> BUILDING must be blocked (must go through editing)."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    try:
        ps = session.phase_state
        await ps.switch_to_running(source="test")
        assert ps.phase == "running"

        await ps.switch_to_building(source="test")

        artifact.record_value(
            "phase_after_blocked_transition",
            ps.phase,
            expected="'running' (blocked, must go through editing)",
        )
        artifact.check(
            "phase still running",
            ps.phase == "running",
            actual=repr(ps.phase),
            expected_val="'running'",
        )
        assert ps.phase == "running", (
            f"running->building should be BLOCKED, got: {ps.phase}"
        )
    finally:
        await _shutdown(session, task)


@pytest.mark.asyncio
async def test_running_to_planning_blocked(llm_provider, tmp_path, artifact):
    """RUNNING -> PLANNING must be blocked (must go through editing)."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    try:
        ps = session.phase_state
        await ps.switch_to_running(source="test")
        assert ps.phase == "running"

        await ps.switch_to_planning(source="test")

        artifact.record_value(
            "phase_after_blocked_transition",
            ps.phase,
            expected="'running' (blocked, must go through editing)",
        )
        artifact.check(
            "phase still running",
            ps.phase == "running",
            actual=repr(ps.phase),
            expected_val="'running'",
        )
        assert ps.phase == "running", (
            f"running->planning should be BLOCKED, got: {ps.phase}"
        )
    finally:
        await _shutdown(session, task)


@pytest.mark.asyncio
async def test_editing_to_running_allowed(llm_provider, tmp_path, artifact):
    """EDITING -> RUNNING must be allowed (re-run)."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    try:
        ps = session.phase_state
        await ps.switch_to_editing(source="test")
        assert ps.phase == "editing"

        await ps.switch_to_running(source="test")

        artifact.check(
            "phase is running",
            ps.phase == "running",
            actual=repr(ps.phase),
            expected_val="'running'",
        )
        assert ps.phase == "running"
    finally:
        await _shutdown(session, task)


@pytest.mark.asyncio
async def test_editing_to_building_allowed(llm_provider, tmp_path, artifact):
    """EDITING -> BUILDING must be allowed (escalate to rebuild)."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    try:
        ps = session.phase_state
        await ps.switch_to_editing(source="test")
        assert ps.phase == "editing"

        await ps.switch_to_building(source="test")

        artifact.check(
            "phase is building",
            ps.phase == "building",
            actual=repr(ps.phase),
            expected_val="'building'",
        )
        assert ps.phase == "building"
    finally:
        await _shutdown(session, task)


@pytest.mark.asyncio
async def test_editing_to_planning_allowed(llm_provider, tmp_path, artifact):
    """EDITING -> PLANNING must be allowed (escalate to replan)."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    try:
        ps = session.phase_state
        await ps.switch_to_editing(source="test")
        assert ps.phase == "editing"

        await ps.switch_to_planning(source="test")

        artifact.check(
            "phase is planning",
            ps.phase == "planning",
            actual=repr(ps.phase),
            expected_val="'planning'",
        )
        assert ps.phase == "planning"
    finally:
        await _shutdown(session, task)


# -----------------------------------------------------------------------
# BUG #1 supplement: Double phase switch deduplication
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_switch_to_same_phase_is_noop(llm_provider, tmp_path, artifact):
    """switch_to_X when already in X must be a no-op (no event)."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    events = []

    async def _capture(event: AgentEvent):
        events.append(event.data.get("phase"))

    session.event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=_capture,
    )
    try:
        ps = session.phase_state
        await ps.switch_to_building(source="test")
        await asyncio.sleep(0.1)
        count_after_first = len(events)

        # Second call to same phase
        await ps.switch_to_building(source="test")
        await asyncio.sleep(0.1)

        artifact.record_value(
            "events_after_first",
            count_after_first,
            expected="no extra event after double switch",
        )
        artifact.record_value(
            "events_after_second",
            len(events),
        )
        artifact.record_value("all_events", events)

        artifact.check(
            "no extra event on double switch",
            len(events) == count_after_first,
            actual=f"first={count_after_first}, second={len(events)}",
            expected_val="same count",
        )
        assert len(events) == count_after_first, (
            f"Double switch should not emit extra event. Events: {events}"
        )
    finally:
        await _shutdown(session, task)


# -----------------------------------------------------------------------
# BUG #6: Phase with empty tool lists
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_with_empty_tools_returns_empty(llm_provider, tmp_path, artifact):
    """get_current_tools() with empty tool list returns [] not crash."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    try:
        ps = session.phase_state
        # Clear all running tools
        ps.running_tools = []
        await ps.switch_to_running(source="test")

        tools = ps.get_current_tools()

        artifact.record_value(
            "tool_count",
            len(tools),
            expected="0 (empty list, no crash)",
        )
        artifact.record_value(
            "tool_names",
            [t.name for t in tools],
        )

        artifact.check(
            "empty tools returns []",
            tools == [],
            actual=str([t.name for t in tools]),
            expected_val="[]",
        )
        assert tools == [], f"Expected empty list, got: {[t.name for t in tools]}"
    finally:
        await _shutdown(session, task)


# -----------------------------------------------------------------------
# Rapid phase cycling — verify final state is consistent
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rapid_phase_cycling_final_state(llm_provider, tmp_path, artifact):
    """Rapidly cycling through phases must leave state consistent."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    all_events = []

    async def _capture(event: AgentEvent):
        all_events.append(event.data.get("phase"))

    session.event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=_capture,
    )
    try:
        ps = session.phase_state

        # Cycle 3 times through all 5 phases:
        # planning → building → staging → running → editing → planning
        for _ in range(3):
            await ps.switch_to_building(source="test")
            await ps.switch_to_staging(source="test")
            await ps.switch_to_running(source="test")
            await ps.switch_to_editing(source="test")
            await ps.switch_to_planning(source="test")

        await asyncio.sleep(0.3)

        artifact.record_value(
            "final_phase",
            ps.phase,
            expected="'planning' after 3 full cycles",
        )
        artifact.record_value("event_count", len(all_events))
        artifact.record_value("all_events", all_events)

        artifact.check(
            "final phase is planning",
            ps.phase == "planning",
            actual=repr(ps.phase),
            expected_val="'planning'",
        )
        assert ps.phase == "planning", f"Expected planning, got: {ps.phase}"

        # Should have 15 phase change events (5 per cycle x 3)
        artifact.check(
            "15 phase events",
            len(all_events) == 15,
            actual=str(len(all_events)),
            expected_val="15",
        )
        assert len(all_events) == 15, f"Expected 15 events, got {len(all_events)}: {all_events}"

        # Tools and prompt should match planning phase
        prompt = ps.get_current_prompt()

        artifact.check(
            "prompt non-empty after cycling",
            len(prompt) > 0,
            actual=str(len(prompt)),
            expected_val=">0",
        )
        assert len(prompt) > 0, "Prompt should not be empty after cycling"
    finally:
        await _shutdown(session, task)


# -----------------------------------------------------------------------
# Tool availability is correct per phase (strict verification)
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_sets_are_disjoint_across_phases(llm_provider, tmp_path, artifact):
    """Each phase must have a distinct non-empty tool set."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    try:
        ps = session.phase_state

        phase_tools = {}
        for phase in ("planning", "building", "staging", "running", "editing"):
            ps.phase = phase
            tools = {t.name for t in ps.get_current_tools()}
            phase_tools[phase] = tools

        # All phases should have at least 1 tool
        for phase, tools in phase_tools.items():
            artifact.check(
                f"{phase} has tools",
                len(tools) > 0,
                actual=str(len(tools)),
                expected_val=">0",
            )
            assert len(tools) > 0, f"{phase} has no tools"

        artifact.record_value(
            "phase_tools",
            {k: sorted(v) for k, v in phase_tools.items()},
            expected="all 4 phases have distinct tool sets",
        )

        # Pairwise comparison: all sets should differ
        phases = list(phase_tools.keys())
        for i in range(len(phases)):
            for j in range(i + 1, len(phases)):
                a, b = phases[i], phases[j]
                artifact.check(
                    f"{a} != {b} tools",
                    phase_tools[a] != phase_tools[b],
                    actual=(f"{a}={sorted(phase_tools[a])}, {b}={sorted(phase_tools[b])}"),
                    expected_val="different",
                )
                assert phase_tools[a] != phase_tools[b], (
                    f"{a} and {b} have identical tools: {phase_tools[a]}"
                )
    finally:
        await _shutdown(session, task)


# -----------------------------------------------------------------------
# Worker completion -> auto-staging transition
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_completion_triggers_auto_editing(llm_provider, tmp_path, artifact):
    """EXECUTION_COMPLETED in running phase must auto-switch to editing."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    phase_changes = []

    async def _capture(event: AgentEvent):
        phase_changes.append(event.data.get("phase"))

    session.event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=_capture,
    )
    try:
        ps = session.phase_state
        # Move to running phase
        await ps.switch_to_running(source="test")
        await asyncio.sleep(0.3)
        phase_changes.clear()  # Reset after manual switch

        # Simulate worker completion event
        await session.event_bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_COMPLETED,
                stream_id="worker",
                data={"output": {"result": "done"}},
            )
        )
        await asyncio.sleep(1.0)

        artifact.record_value(
            "phase_after_completion",
            ps.phase,
            expected="'staging' (auto-switch on completion)",
        )
        artifact.record_value("phase_changes", phase_changes)

        artifact.check(
            "auto-switched to staging",
            ps.phase == "editing",
            actual=repr(ps.phase),
            expected_val="'staging'",
        )
        assert ps.phase == "editing", f"Expected auto-switch to editing, got: {ps.phase}"

        artifact.check(
            "editing event emitted",
            "editing" in phase_changes,
            actual=str(phase_changes),
            expected_val="contains 'editing'",
        )
        assert "editing" in phase_changes, (
            f"QUEEN_PHASE_CHANGED(editing) not emitted. Events: {phase_changes}"
        )
    finally:
        await _shutdown(session, task)


@pytest.mark.asyncio
async def test_worker_failure_triggers_auto_editing(llm_provider, tmp_path, artifact):
    """EXECUTION_FAILED in running phase must auto-switch to editing."""
    session, task = await _start_queen_session(llm_provider, tmp_path)
    try:
        ps = session.phase_state
        await ps.switch_to_running(source="test")
        await asyncio.sleep(0.3)

        # Simulate worker failure event
        await session.event_bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_FAILED,
                stream_id="worker",
                data={"error": "worker crashed"},
            )
        )
        await asyncio.sleep(1.0)

        artifact.record_value(
            "phase_after_failure",
            ps.phase,
            expected="'staging' (auto-switch on failure)",
        )

        artifact.check(
            "auto-switched to staging on failure",
            ps.phase == "editing",
            actual=repr(ps.phase),
            expected_val="'staging'",
        )
        assert ps.phase == "editing", f"Expected auto-switch to editing on failure, got: {ps.phase}"
    finally:
        await _shutdown(session, task)
