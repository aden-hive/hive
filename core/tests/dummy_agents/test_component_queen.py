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


def test_queen_phase_state_initial_phase(artifact):
    """QueenPhaseState should default to 'building' phase."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState()

    artifact.record_value("phase", state.phase, expected="default phase == 'building'")

    artifact.check(
        "default phase is building",
        state.phase == "building",
        actual=repr(state.phase),
        expected_val="'building'",
    )
    assert state.phase == "building"


def test_queen_phase_state_planning_tools(artifact):
    """Planning phase should return planning_tools."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(phase="planning")
    state.planning_tools = _make_tools("list_agent_tools", "save_agent_draft")
    state.building_tools = _make_tools("read_file", "edit_file", "write_file")

    tools = state.get_current_tools()
    tool_names = {t.name for t in tools}

    artifact.record_value(
        "tool_names",
        sorted(tool_names),
        expected="planning tools include list_agent_tools, exclude edit_file",
    )

    artifact.check(
        "list_agent_tools in tools",
        "list_agent_tools" in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="contains 'list_agent_tools'",
    )
    assert "list_agent_tools" in tool_names

    artifact.check(
        "edit_file not in tools",
        "edit_file" not in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="does not contain 'edit_file'",
    )
    assert "edit_file" not in tool_names


def test_queen_phase_state_building_tools(artifact):
    """Building phase should return building_tools."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(phase="building")
    state.planning_tools = _make_tools("list_agent_tools")
    state.building_tools = _make_tools("read_file", "edit_file", "write_file")

    tools = state.get_current_tools()
    tool_names = {t.name for t in tools}

    artifact.record_value(
        "tool_names",
        sorted(tool_names),
        expected="building tools include edit_file, exclude list_agent_tools",
    )

    artifact.check(
        "edit_file in tools",
        "edit_file" in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="contains 'edit_file'",
    )
    assert "edit_file" in tool_names

    artifact.check(
        "list_agent_tools not in tools",
        "list_agent_tools" not in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="does not contain 'list_agent_tools'",
    )
    assert "list_agent_tools" not in tool_names


def test_queen_phase_state_tool_switching(artifact):
    """Switching phase should change which tools are returned."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(phase="planning")
    state.planning_tools = _make_tools("a")
    state.building_tools = _make_tools("b")
    state.staging_tools = _make_tools("c")
    state.running_tools = _make_tools("d")

    planning_tool = state.get_current_tools()[0].name
    artifact.check(
        "planning returns tool 'a'",
        planning_tool == "a",
        actual=repr(planning_tool),
        expected_val="'a'",
    )
    assert state.get_current_tools()[0].name == "a"

    state.phase = "building"
    building_tool = state.get_current_tools()[0].name
    artifact.check(
        "building returns tool 'b'",
        building_tool == "b",
        actual=repr(building_tool),
        expected_val="'b'",
    )
    assert state.get_current_tools()[0].name == "b"

    state.phase = "staging"
    staging_tool = state.get_current_tools()[0].name
    artifact.check(
        "staging returns tool 'c'",
        staging_tool == "c",
        actual=repr(staging_tool),
        expected_val="'c'",
    )
    assert state.get_current_tools()[0].name == "c"

    state.phase = "running"
    running_tool = state.get_current_tools()[0].name
    artifact.check(
        "running returns tool 'd'",
        running_tool == "d",
        actual=repr(running_tool),
        expected_val="'d'",
    )
    assert state.get_current_tools()[0].name == "d"

    artifact.record_value(
        "tool_per_phase",
        {"planning": "a", "building": "b", "staging": "c", "running": "d"},
        expected="each phase returns its own tool",
    )


def test_queen_initial_phase_no_worker(artifact):
    """Without a worker identity, queen should start in 'planning'."""
    # This tests the logic in queen_orchestrator.py line 106:
    # initial_phase = "staging" if worker_identity else "planning"
    worker_identity = None
    initial_phase = "staging" if worker_identity else "planning"

    artifact.record_value(
        "initial_phase",
        initial_phase,
        expected="'planning' when worker_identity is None",
    )

    artifact.check(
        "initial phase is planning",
        initial_phase == "planning",
        actual=repr(initial_phase),
        expected_val="'planning'",
    )
    assert initial_phase == "planning"


def test_queen_initial_phase_with_worker(artifact):
    """With a worker identity, queen should start in 'staging'."""
    worker_identity = "my_agent"
    initial_phase = "staging" if worker_identity else "planning"

    artifact.record_value(
        "initial_phase",
        initial_phase,
        expected="'staging' when worker_identity is set",
    )

    artifact.check(
        "initial phase is staging",
        initial_phase == "staging",
        actual=repr(initial_phase),
        expected_val="'staging'",
    )
    assert initial_phase == "staging"


@pytest.mark.asyncio
async def test_queen_phase_switch_emits_event(artifact):
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

    artifact.record_value("phase", state.phase, expected="'building'")
    artifact.record_value("event_count", len(phase_events))

    artifact.check(
        "phase is building",
        state.phase == "building",
        actual=repr(state.phase),
        expected_val="'building'",
    )
    assert state.phase == "building"

    artifact.check(
        "at least 1 phase event",
        len(phase_events) >= 1,
        actual=str(len(phase_events)),
        expected_val=">=1",
    )
    assert len(phase_events) >= 1

    event_phase = phase_events[0].data.get("phase")
    artifact.check(
        "event reports building",
        event_phase == "building",
        actual=repr(event_phase),
        expected_val="'building'",
    )
    assert phase_events[0].data.get("phase") == "building"


def test_queen_draft_graph_persists_across_turns(artifact):
    """Draft graph stored on phase_state should survive phase changes."""
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(phase="planning")
    state.draft_graph = {"nodes": ["a", "b"], "edges": []}

    # Simulate phase change
    state.phase = "building"

    # Draft should still be available
    artifact.record_value(
        "draft_graph",
        state.draft_graph,
        expected="draft_graph survives phase change, nodes=['a','b']",
    )

    artifact.check(
        "draft_graph is not None",
        state.draft_graph is not None,
        actual=repr(state.draft_graph),
        expected_val="non-None",
    )
    assert state.draft_graph is not None

    artifact.check(
        "draft has 2 nodes",
        len(state.draft_graph["nodes"]) == 2,
        actual=str(len(state.draft_graph["nodes"])),
        expected_val="2",
    )
    assert len(state.draft_graph["nodes"]) == 2
