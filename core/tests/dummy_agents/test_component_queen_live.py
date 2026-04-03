"""Component tests: Queen Live Phase Switching — real LLM, real event bus.

Starts the actual queen via create_queen() with a real LLM provider and
verifies phase transitions, dynamic tool switching, prompt switching, and
event emission through the full queen lifecycle.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.server.session_manager import Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

QUEEN_STARTUP_TIMEOUT = 30  # seconds to wait for queen to initialize
QUEEN_RESPONSE_TIMEOUT = 60  # seconds to wait for queen to respond to a message


@dataclass
class PhaseCapture:
    """Captures QUEEN_PHASE_CHANGED events."""

    phases: list[str] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    _waiters: list[tuple[str, asyncio.Event]] = field(default_factory=list)

    async def on_event(self, event: AgentEvent) -> None:
        phase = event.data.get("phase", "")
        self.phases.append(phase)
        self.events.append(event)
        # Wake any waiters for this phase
        for target_phase, evt in self._waiters:
            if phase == target_phase:
                evt.set()

    async def wait_for_phase(self, phase: str, timeout: float = 30) -> bool:
        """Wait until a specific phase change is observed."""
        if phase in self.phases:
            return True
        evt = asyncio.Event()
        self._waiters.append((phase, evt))
        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout)
            return True
        except (TimeoutError, asyncio.TimeoutError):
            return False


@dataclass
class TextCapture:
    """Captures LLM text deltas to verify queen is responding."""

    chunks: list[str] = field(default_factory=list)
    _has_text: asyncio.Event = field(default_factory=asyncio.Event)

    async def on_event(self, event: AgentEvent) -> None:
        text = event.data.get("content", "")
        if text:
            self.chunks.append(text)
            self._has_text.set()

    async def wait_for_text(self, timeout: float = 30) -> bool:
        try:
            await asyncio.wait_for(self._has_text.wait(), timeout=timeout)
            return True
        except (TimeoutError, asyncio.TimeoutError):
            return False

    @property
    def full_text(self) -> str:
        return "".join(self.chunks)


def _make_mock_session_manager() -> MagicMock:
    """Create a minimal mock SessionManager that satisfies create_queen()."""
    mgr = MagicMock()
    # _subscribe_worker_handoffs needs to exist but can be a no-op for tests
    mgr._subscribe_worker_handoffs = MagicMock()
    return mgr


async def _start_queen(
    llm_provider,
    tmp_path: Path,
    *,
    worker_identity: str | None = None,
    initial_prompt: str | None = None,
) -> tuple[Session, asyncio.Task]:
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

    mgr = _make_mock_session_manager()

    task = await create_queen(
        session=session,
        session_manager=mgr,
        worker_identity=worker_identity,
        queen_dir=queen_dir,
        initial_prompt=initial_prompt,
    )

    # Wait for queen to initialize (queen_executor is set inside the task)
    for _ in range(QUEEN_STARTUP_TIMEOUT * 10):
        if session.queen_executor is not None:
            break
        await asyncio.sleep(0.1)

    assert session.queen_executor is not None, "Queen executor did not initialize"
    assert session.phase_state is not None, "Phase state not set"

    return session, task


async def _shutdown_queen(session: Session, task: asyncio.Task) -> None:
    """Cleanly shut down the queen."""
    # Signal the event loop node to stop
    node = session.queen_executor.node_registry.get("queen") if session.queen_executor else None
    if node and hasattr(node, "signal_shutdown"):
        node.signal_shutdown()

    # Cancel the task as backup
    if not task.done():
        task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5)
    except (asyncio.CancelledError, TimeoutError, asyncio.TimeoutError):
        pass


# ---------------------------------------------------------------------------
# Tests: Initial Phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queen_starts_in_planning_without_worker(llm_provider, tmp_path, artifact):
    """Queen with no worker_identity must start in 'planning' phase."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    try:
        actual_phase = session.phase_state.phase
        artifact.record_value(
            "phase", actual_phase, expected="phase == 'planning' when no worker_identity"
        )

        artifact.check(
            "phase is planning",
            actual_phase == "planning",
            actual=repr(actual_phase),
            expected_val="'planning'",
        )
        assert session.phase_state.phase == "planning", (
            f"Expected planning, got {session.phase_state.phase}"
        )
    finally:
        await _shutdown_queen(session, task)


@pytest.mark.asyncio
async def test_queen_starts_in_staging_with_worker(llm_provider, tmp_path, artifact):
    """Queen with worker_identity must start in 'staging' phase."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity="test_agent",
        initial_prompt="Hello",
    )
    try:
        actual_phase = session.phase_state.phase
        artifact.record_value(
            "phase", actual_phase, expected="phase == 'staging' when worker_identity is set"
        )

        artifact.check(
            "phase is staging",
            actual_phase == "staging",
            actual=repr(actual_phase),
            expected_val="'staging'",
        )
        assert session.phase_state.phase == "staging", (
            f"Expected staging, got {session.phase_state.phase}"
        )
    finally:
        await _shutdown_queen(session, task)


# ---------------------------------------------------------------------------
# Tests: Tool Availability Per Phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queen_planning_tools_available(llm_provider, tmp_path, artifact):
    """In planning phase, planning tools must be returned by get_current_tools()."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    try:
        ps = session.phase_state
        artifact.record_value(
            "phase",
            ps.phase,
            expected="phase='planning', tools include list_agent_tools, exclude edit_file",
        )

        artifact.check(
            "phase is planning",
            ps.phase == "planning",
            actual=repr(ps.phase),
            expected_val="'planning'",
        )
        assert ps.phase == "planning"

        tool_names = {t.name for t in ps.get_current_tools()}
        artifact.record_value("tool_names", sorted(tool_names))

        # Planning phase must have agent discovery tools
        artifact.check(
            "list_agent_tools in tools",
            "list_agent_tools" in tool_names,
            actual=str(sorted(tool_names)),
            expected_val="contains 'list_agent_tools'",
        )
        assert "list_agent_tools" in tool_names, (
            f"list_agent_tools missing from planning tools: {tool_names}"
        )
        # Planning phase must NOT have building-only tools
        artifact.check(
            "edit_file not in tools",
            "edit_file" not in tool_names,
            actual=str(sorted(tool_names)),
            expected_val="does not contain 'edit_file'",
        )
        assert "edit_file" not in tool_names, (
            f"edit_file should not be in planning tools: {tool_names}"
        )
    finally:
        await _shutdown_queen(session, task)


@pytest.mark.asyncio
async def test_queen_tools_change_on_phase_switch(llm_provider, tmp_path, artifact):
    """Switching phase must change the tools returned by get_current_tools()."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    try:
        ps = session.phase_state
        planning_tools = {t.name for t in ps.get_current_tools()}
        artifact.record_value(
            "planning_tools",
            sorted(planning_tools),
            expected="planning, building, and staging tool sets all differ",
        )

        # Switch to building
        await ps.switch_to_building(source="test")
        building_tools = {t.name for t in ps.get_current_tools()}
        artifact.record_value("building_tools", sorted(building_tools))

        artifact.check(
            "planning != building tools",
            planning_tools != building_tools,
            actual=f"planning={sorted(planning_tools)}, building={sorted(building_tools)}",
            expected_val="different sets",
        )
        assert planning_tools != building_tools, "Planning and building tools must differ"

        # Switch to staging
        await ps.switch_to_staging(source="test")
        staging_tools = {t.name for t in ps.get_current_tools()}
        artifact.record_value("staging_tools", sorted(staging_tools))

        artifact.check(
            "staging != building tools",
            staging_tools != building_tools,
            actual=f"staging={sorted(staging_tools)}, building={sorted(building_tools)}",
            expected_val="different sets",
        )
        assert staging_tools != building_tools, "Building and staging tools must differ"
    finally:
        await _shutdown_queen(session, task)


# ---------------------------------------------------------------------------
# Tests: Prompt Switching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queen_prompt_changes_on_phase_switch(llm_provider, tmp_path, artifact):
    """Switching phase must change the system prompt returned by get_current_prompt()."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    try:
        ps = session.phase_state
        planning_prompt = ps.get_current_prompt()
        artifact.record_value(
            "planning_prompt_len",
            len(planning_prompt),
            expected="non-empty planning and building prompts that differ",
        )

        artifact.check(
            "planning prompt non-empty",
            len(planning_prompt) > 0,
            actual=str(len(planning_prompt)),
            expected_val=">0",
        )
        assert len(planning_prompt) > 0, "Planning prompt should not be empty"

        await ps.switch_to_building(source="test")
        building_prompt = ps.get_current_prompt()
        artifact.record_value("building_prompt_len", len(building_prompt))

        artifact.check(
            "building prompt non-empty",
            len(building_prompt) > 0,
            actual=str(len(building_prompt)),
            expected_val=">0",
        )
        assert len(building_prompt) > 0, "Building prompt should not be empty"

        artifact.check(
            "prompts differ",
            planning_prompt != building_prompt,
            actual=f"planning_len={len(planning_prompt)}, building_len={len(building_prompt)}",
            expected_val="different prompts",
        )
        assert planning_prompt != building_prompt, "Planning and building prompts must differ"
    finally:
        await _shutdown_queen(session, task)


# ---------------------------------------------------------------------------
# Tests: Phase Change Events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queen_emits_phase_change_events(llm_provider, tmp_path, artifact):
    """Each phase switch must emit a QUEEN_PHASE_CHANGED event."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    capture = PhaseCapture()
    session.event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=capture.on_event,
    )
    try:
        ps = session.phase_state

        # planning -> building
        await ps.switch_to_building(source="test")
        assert await capture.wait_for_phase("building", timeout=5)

        # building -> staging
        await ps.switch_to_staging(source="test")
        assert await capture.wait_for_phase("staging", timeout=5)

        # staging -> running
        await ps.switch_to_running(source="test")
        assert await capture.wait_for_phase("running", timeout=5)

        # running -> incubating
        await ps.switch_to_incubating(source="test")
        assert await capture.wait_for_phase("incubating", timeout=5)

        # incubating -> planning
        await ps.switch_to_planning(source="test")
        assert await capture.wait_for_phase("planning", timeout=5)

        expected_seq = ["building", "staging", "running", "incubating", "planning"]
        artifact.record_value("phases", capture.phases, expected=str(expected_seq))

        artifact.check(
            "phase sequence matches",
            capture.phases == expected_seq,
            actual=str(capture.phases),
            expected_val=str(expected_seq),
        )
        assert capture.phases == expected_seq, f"Phase sequence was: {capture.phases}"
    finally:
        await _shutdown_queen(session, task)


@pytest.mark.asyncio
async def test_queen_no_duplicate_phase_event_on_same_phase(llm_provider, tmp_path, artifact):
    """Switching to the same phase should NOT emit a duplicate event."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    capture = PhaseCapture()
    session.event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=capture.on_event,
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

        # Switch to building twice
        await ps.switch_to_building(source="test")
        await asyncio.sleep(0.2)
        await ps.switch_to_building(source="test")  # no-op
        await asyncio.sleep(0.2)

        # Should only have one "building" event
        building_events = [p for p in capture.phases if p == "building"]

        artifact.record_value(
            "building_event_count",
            len(building_events),
            expected="exactly 1 building event (no duplicate)",
        )
        artifact.record_value("all_phases", capture.phases)

        artifact.check(
            "only 1 building event",
            len(building_events) == 1,
            actual=str(len(building_events)),
            expected_val="1",
        )
        assert len(building_events) == 1, (
            f"Expected 1 building event, got {len(building_events)}: {capture.phases}"
        )
    finally:
        await _shutdown_queen(session, task)


# ---------------------------------------------------------------------------
# Tests: Queen Responds in Correct Phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queen_responds_to_message(llm_provider, tmp_path, artifact):
    """Queen must produce an LLM turn when started with an initial prompt."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello, I want to build an agent.",
    )
    turn_complete = asyncio.Event()

    async def _on_turn(event: AgentEvent) -> None:
        turn_complete.set()

    session.event_bus.subscribe(
        event_types=[EventType.LLM_TURN_COMPLETE],
        handler=_on_turn,
        filter_stream="queen",
    )
    try:
        # Queen should complete at least one LLM turn (text or tool call)
        got_turn = False
        try:
            await asyncio.wait_for(turn_complete.wait(), timeout=QUEEN_RESPONSE_TIMEOUT)
            got_turn = True
        except (TimeoutError, asyncio.TimeoutError):
            pass

        artifact.record_value(
            "got_turn", got_turn, expected="queen completes at least one LLM turn"
        )

        artifact.check(
            "queen completed LLM turn", got_turn, actual=str(got_turn), expected_val="True"
        )
        assert got_turn, "Queen did not complete any LLM turn"
    finally:
        await _shutdown_queen(session, task)


@pytest.mark.asyncio
async def test_queen_responds_after_injected_message(llm_provider, tmp_path, artifact):
    """Injecting a user message must trigger a new queen LLM turn."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    try:
        # Wait for initial response to settle
        first_turn = asyncio.Event()

        async def _on_first_turn(event: AgentEvent) -> None:
            first_turn.set()

        sub_id = session.event_bus.subscribe(
            event_types=[EventType.LLM_TURN_COMPLETE],
            handler=_on_first_turn,
            filter_stream="queen",
        )
        try:
            await asyncio.wait_for(first_turn.wait(), timeout=QUEEN_RESPONSE_TIMEOUT)
        except (TimeoutError, asyncio.TimeoutError):
            pass
        session.event_bus.unsubscribe(sub_id)

        # Now inject a follow-up and listen for a new turn
        second_turn = asyncio.Event()

        async def _on_second_turn(event: AgentEvent) -> None:
            second_turn.set()

        session.event_bus.subscribe(
            event_types=[EventType.LLM_TURN_COMPLETE],
            handler=_on_second_turn,
            filter_stream="queen",
        )

        node = session.queen_executor.node_registry.get("queen")
        assert node is not None
        await node.inject_event(
            "What tools do you have available?",
            is_client_input=True,
        )

        got_turn = False
        try:
            await asyncio.wait_for(second_turn.wait(), timeout=QUEEN_RESPONSE_TIMEOUT)
            got_turn = True
        except (TimeoutError, asyncio.TimeoutError):
            pass

        artifact.record_value(
            "got_second_turn", got_turn, expected="queen responds to injected message"
        )

        artifact.check(
            "queen responded to injected message",
            got_turn,
            actual=str(got_turn),
            expected_val="True",
        )
        assert got_turn, "Queen did not respond to injected message"
    finally:
        await _shutdown_queen(session, task)


# ---------------------------------------------------------------------------
# Tests: Phase Transition Cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queen_full_phase_cycle_with_events(llm_provider, tmp_path, artifact):
    """Walk through all 4 phases and verify state + events at each step."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    capture = PhaseCapture()
    session.event_bus.subscribe(
        event_types=[EventType.QUEEN_PHASE_CHANGED],
        handler=capture.on_event,
    )
    try:
        ps = session.phase_state

        # Start: planning
        artifact.check(
            "initial phase is planning",
            ps.phase == "planning",
            actual=repr(ps.phase),
            expected_val="'planning'",
        )
        assert ps.phase == "planning"
        planning_tools = {t.name for t in ps.get_current_tools()}

        # -> building
        await ps.switch_to_building(source="test")
        artifact.check(
            "phase is building",
            ps.phase == "building",
            actual=repr(ps.phase),
            expected_val="'building'",
        )
        assert ps.phase == "building"
        building_tools = {t.name for t in ps.get_current_tools()}

        artifact.check(
            "building tools differ from planning",
            building_tools != planning_tools,
            actual=f"building={sorted(building_tools)}",
            expected_val="different from planning",
        )
        assert building_tools != planning_tools

        # -> staging
        await ps.switch_to_staging(source="test")
        artifact.check(
            "phase is staging",
            ps.phase == "staging",
            actual=repr(ps.phase),
            expected_val="'staging'",
        )
        assert ps.phase == "staging"
        staging_tools = {t.name for t in ps.get_current_tools()}

        # -> running
        await ps.switch_to_running(source="test")
        artifact.check(
            "phase is running",
            ps.phase == "running",
            actual=repr(ps.phase),
            expected_val="'running'",
        )
        assert ps.phase == "running"
        running_tools = {t.name for t in ps.get_current_tools()}

        # -> incubating
        await ps.switch_to_incubating(source="test")
        assert ps.phase == "incubating"
        incubating_tools = {t.name for t in ps.get_current_tools()}

        # -> back to planning (from incubating, allowed)
        await ps.switch_to_planning(source="test")
        artifact.check(
            "phase is planning again",
            ps.phase == "planning",
            actual=repr(ps.phase),
            expected_val="'planning'",
        )
        assert ps.phase == "planning"
        final_tools = {t.name for t in ps.get_current_tools()}

        artifact.check(
            "final tools match original planning set",
            final_tools == planning_tools,
            actual=f"final={sorted(final_tools)}",
            expected_val=f"planning={sorted(planning_tools)}",
        )
        assert final_tools == planning_tools, "Tools should match original planning set"

        # Verify events
        await asyncio.sleep(0.3)
        expected_seq = ["building", "staging", "running", "incubating", "planning"]
        artifact.record_value("phase_events", capture.phases, expected=str(expected_seq))

        artifact.check(
            "phase event sequence",
            capture.phases == expected_seq,
            actual=str(capture.phases),
            expected_val=str(expected_seq),
        )
        assert capture.phases == expected_seq

        # Verify all 5 phase tool sets are distinct
        all_sets = [planning_tools, building_tools, staging_tools, running_tools, incubating_tools]
        phase_names = ["planning", "building", "staging", "running", "incubating"]
        for i, a in enumerate(all_sets):
            for j, b in enumerate(all_sets):
                if i != j:
                    artifact.check(
                        f"{phase_names[i]} != {phase_names[j]} tools",
                        a != b,
                        actual=f"{phase_names[i]}={sorted(a)}, {phase_names[j]}={sorted(b)}",
                        expected_val="different",
                    )
                    assert a != b, f"Phase tool sets {i} and {j} should differ but are identical"
    finally:
        await _shutdown_queen(session, task)


@pytest.mark.asyncio
async def test_queen_phase_state_persists_draft(llm_provider, tmp_path, artifact):
    """Draft graph on phase_state must survive phase transitions."""
    session, task = await _start_queen(
        llm_provider,
        tmp_path,
        worker_identity=None,
        initial_prompt="Hello",
    )
    try:
        ps = session.phase_state
        ps.draft_graph = {"nodes": ["a", "b"], "edges": ["a->b"]}

        await ps.switch_to_building(source="test")
        artifact.check(
            "draft survives building switch",
            ps.draft_graph is not None,
            actual=repr(ps.draft_graph),
            expected_val="non-None",
        )
        assert ps.draft_graph is not None

        artifact.check(
            "draft nodes intact after building",
            ps.draft_graph["nodes"] == ["a", "b"],
            actual=str(ps.draft_graph["nodes"]),
            expected_val="['a', 'b']",
        )
        assert ps.draft_graph["nodes"] == ["a", "b"]

        await ps.switch_to_staging(source="test")
        artifact.check(
            "draft survives staging switch",
            ps.draft_graph is not None,
            actual=repr(ps.draft_graph),
            expected_val="non-None",
        )
        assert ps.draft_graph is not None

        await ps.switch_to_running(source="test")
        artifact.check(
            "draft survives running switch",
            ps.draft_graph is not None,
            actual=repr(ps.draft_graph),
            expected_val="non-None",
        )
        assert ps.draft_graph is not None

        artifact.record_value(
            "final_draft_graph",
            ps.draft_graph,
            expected="draft_graph survives all phase transitions",
        )
    finally:
        await _shutdown_queen(session, task)
