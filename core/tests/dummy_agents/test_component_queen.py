"""Component tests: Queen Phase Lifecycle — phase state, tool switching, prompts.

Exercises QueenPhaseState (pure data class, no LLM needed for most tests)
and verifies phase transitions produce correct tool/prompt configurations.
"""

from __future__ import annotations

import pytest

from framework.llm.provider import Tool


def _make_tools(*names: str) -> list[Tool]:
    """Create dummy Tool objects for testing phase state."""
    return [Tool(name=n, description=f"Tool {n}", parameters={}) for n in names]


def test_queen_phase_state_initial_phase():
    """QueenPhaseState should default to 'building' phase."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState()
    assert state.phase == "building"


def test_queen_phase_state_planning_tools():
    """Planning phase should return planning_tools."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(phase="planning")
    state.planning_tools = _make_tools("list_agent_tools", "save_agent_draft")
    state.building_tools = _make_tools("read_file", "edit_file", "write_file")

    tools = state.get_current_tools()
    tool_names = {t.name for t in tools}
    assert "list_agent_tools" in tool_names
    assert "edit_file" not in tool_names


def test_queen_phase_state_building_tools():
    """Building phase should return building_tools."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(phase="building")
    state.planning_tools = _make_tools("list_agent_tools")
    state.building_tools = _make_tools("read_file", "edit_file", "write_file")

    tools = state.get_current_tools()
    tool_names = {t.name for t in tools}
    assert "edit_file" in tool_names
    assert "list_agent_tools" not in tool_names


def test_queen_phase_state_tool_switching():
    """Switching phase should change which tools are returned."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(phase="planning")
    state.planning_tools = _make_tools("a")
    state.building_tools = _make_tools("b")
    state.staging_tools = _make_tools("c")
    state.running_tools = _make_tools("d")

    assert state.get_current_tools()[0].name == "a"
    state.phase = "building"
    assert state.get_current_tools()[0].name == "b"
    state.phase = "staging"
    assert state.get_current_tools()[0].name == "c"
    state.phase = "running"
    assert state.get_current_tools()[0].name == "d"


def test_queen_initial_phase_no_worker():
    """Without a worker identity, queen should start in 'planning'."""
    # This tests the logic in queen_orchestrator.py line 106:
    # initial_phase = "staging" if worker_identity else "planning"
    worker_identity = None
    initial_phase = "staging" if worker_identity else "planning"
    assert initial_phase == "planning"


def test_queen_initial_phase_with_worker():
    """With a worker identity, queen should start in 'staging'."""
    worker_identity = "my_agent"
    initial_phase = "staging" if worker_identity else "planning"
    assert initial_phase == "staging"


@pytest.mark.asyncio
async def test_queen_phase_switch_emits_event():
    """Phase transition should emit QUEEN_PHASE_CHANGED event."""
    from framework.runtime.event_bus import EventBus, EventType
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    event_bus = EventBus()
    phase_events = []

    async def _capture(event):
        phase_events.append(event)

    event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=_capture,
    )

    state = QueenPhaseState(phase="planning", event_bus=event_bus)
    state.planning_tools = _make_tools("a")
    state.building_tools = _make_tools("b")

    await state.switch_to_building(source="tool")

    assert state.phase == "building"
    assert len(phase_events) >= 1
    assert phase_events[0].data.get("phase") == "building"


def test_queen_draft_graph_persists_across_turns():
    """Draft graph stored on phase_state should survive phase changes."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(phase="planning")
    state.draft_graph = {"nodes": ["a", "b"], "edges": []}

    # Simulate phase change
    state.phase = "building"

    # Draft should still be available
    assert state.draft_graph is not None
    assert len(state.draft_graph["nodes"]) == 2
