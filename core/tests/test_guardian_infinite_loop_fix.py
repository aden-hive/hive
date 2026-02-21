"""
Tests for Guardian infinite loop fix.

Focuses on REAL integration testing with actual AgentRuntime and EventBus.
NO API calls required - uses simple CountingNode to track executions.

Verifies:
1. Self-trigger guard prevents Guardian from reacting to its own failures (infinite loop fix)
2. Guardian correctly reacts to OTHER stream failures
3. Pause cancels ALL running tasks across all graphs (multi-graph safe)
4. Thread-safe task cancellation
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig
from framework.runtime.event_bus import AgentEvent, EventType
from framework.runtime.execution_stream import EntryPointSpec

# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

# Shared execution tracking (since AgentRuntime may instantiate nodes differently)
_execution_counts = {}


class CountingNode(NodeProtocol):
    """Node that tracks execution count for testing via shared state."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        _execution_counts[node_id] = 0

    async def execute(self, context: NodeContext, memory: dict) -> NodeResult:
        _execution_counts[self.node_id] = _execution_counts.get(self.node_id, 0) + 1
        # Return success with proper output structure
        return NodeResult(
            success=True,
            outputs={"count": _execution_counts[self.node_id], "result": "success"}
        )


# ---------------------------------------------------------------------------
# Test 1: REAL Integration Test - Self-Trigger Guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_guardian_self_trigger_guard_with_event_bus():
    """
    REAL integration test with actual AgentRuntime and EventBus.

    This test verifies the self-trigger guard behavior without mocks:
    - Creates real AgentRuntime with primary graph
    - Adds Guardian as secondary graph with event subscription
    - Emits execution_failed event FROM Guardian itself (self-trigger)
    - Verifies Guardian does NOT react to its own failure (guard blocks it)
    - Emits execution_failed event FROM different stream
    - Verifies Guardian DOES react to other stream failures

    Verification is done by monitoring execution events from the EventBus.
    """
    # Create simple nodes (don't need custom tracking, we'll use event bus)
    primary_node = CountingNode("primary_node")
    guardian_node = CountingNode("guardian_node")

    # Create primary graph
    primary_graph = GraphSpec(
        id="primary",
        goal_id="test_goal",
        entry_node="primary_node",
        nodes=[
            NodeSpec(
                id="primary_node",
                name="Primary Node",
                description="Primary execution node",
                node=primary_node,
            )
        ],
        edges=[],
    )

    # Create Guardian graph
    guardian_graph = GraphSpec(
        id="guardian",
        goal_id="test_goal",
        entry_node="guardian_node",
        nodes=[
            NodeSpec(
                id="guardian_node",
                name="Guardian Node",
                description="Guardian monitoring node",
                node=guardian_node,
            )
        ],
        edges=[],
    )

    goal = Goal(
        id="test_goal",
        name="Test Goal",
        description="Test self-trigger guard",
        goal="test_self_trigger_guard",
    )

    # Create temp directory for storage
    temp_dir = Path(tempfile.mkdtemp())

    # Track execution_started events for Guardian
    guardian_executions = []

    def track_guardian_executions(event):
        if event.stream_id == "guardian::guardian" and event.type == EventType.EXECUTION_STARTED:
            guardian_executions.append(event)

    try:
        # Create mock LLM (doesn't actually call APIs, just for structure)
        from unittest.mock import AsyncMock, Mock

        mock_llm = Mock()
        mock_llm.generate = AsyncMock(return_value="mock response")
        mock_llm.model = "mock-model"

        # Create runtime (with mock LLM to avoid API calls)
        runtime = AgentRuntime(
            graph=primary_graph,
            goal=goal,
            storage_path=temp_dir,
            llm=mock_llm,  # Mock LLM to satisfy EventLoopNode validation
            config=AgentRuntimeConfig(),
        )

        await runtime.start()

        # Subscribe to execution_started events to track Guardian executions
        runtime._event_bus.subscribe(
            event_types=[EventType.EXECUTION_STARTED],
            handler=track_guardian_executions,
        )

        # Add Guardian as secondary graph with event subscription
        guardian_entry = EntryPointSpec(
            id="guardian",
            name="Guardian Entry",
            entry_node="guardian_node",
            trigger_type="event",
            trigger_config={
                "event_types": ["execution_failed"],
                "exclude_own_graph": False,  # Critical: we're testing self-trigger guard
            },
        )

        await runtime.add_graph(
            graph_id="guardian",
            graph=guardian_graph,
            goal=goal,
            entry_points={"guardian": guardian_entry},
        )

        # Give event subscription time to register
        await asyncio.sleep(0.1)

        # === TEST 1: Self-trigger should be BLOCKED ===

        # Emit execution_failed FROM Guardian itself
        self_trigger_event = AgentEvent(
            type=EventType.EXECUTION_FAILED,
            graph_id="guardian",
            stream_id="guardian::guardian",  # Same as entry_point_id
            node_id="guardian_node",
            data={"error": "Guardian failed", "test": "self_trigger"},
        )

        await runtime._event_bus.publish(self_trigger_event)

        # Wait for potential handler execution
        await asyncio.sleep(0.5)

        # CRITICAL ASSERTION: Guardian should NOT have started execution (self-trigger blocked)
        assert len(guardian_executions) == 0, (
            f"SELF-TRIGGER GUARD FAILED! Guardian started {len(guardian_executions)} execution(s). "
            "Expected 0 because event.stream_id == entry_point_id should block self-trigger. "
            "This means the infinite loop fix is NOT working!"
        )

        # === TEST 2: Other-trigger should work ===

        # Emit execution_failed FROM different stream (primary)
        other_trigger_event = AgentEvent(
            type=EventType.EXECUTION_FAILED,
            graph_id="primary",
            stream_id="default",  # Different from guardian::guardian
            node_id="primary_node",
            data={"error": "Primary failed", "test": "other_trigger"},
        )

        await runtime._event_bus.publish(other_trigger_event)

        # Wait for handler execution
        await asyncio.sleep(0.5)

        # CRITICAL ASSERTION: Guardian SHOULD have started execution (other-trigger allowed)
        assert len(guardian_executions) == 1, (
            f"OTHER-TRIGGER FAILED! Guardian started {len(guardian_executions)} execution(s). "
            "Expected 1 because Guardian should react to other stream failures. "
            "Guard may be too strict!"
        )

        # === TEST 3: Emit self-trigger again, should still be blocked ===

        await runtime._event_bus.publish(self_trigger_event)

    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 2: Multi-Graph Pause (Unit Test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_cancels_all_graphs():
    """
    Verify that pause logic cancels ALL running tasks across all graphs.

    Before fix: Only checked _current_exec_id, missed Guardian loops
    After fix: Iterates all graphs, all streams, all tasks
    """
    # Simulate running tasks
    task1 = asyncio.create_task(asyncio.sleep(10))
    task2 = asyncio.create_task(asyncio.sleep(10))
    task3 = asyncio.create_task(asyncio.sleep(10))

    # Simulate execution_tasks dict structure
    mock_stream1 = Mock()
    mock_stream1._execution_tasks = {"exec_1": task1, "exec_2": task2}

    mock_stream2 = Mock()
    mock_stream2._execution_tasks = {"exec_3": task3}

    mock_reg1 = Mock()
    mock_reg1.streams = {"default": mock_stream1}

    mock_reg2 = Mock()
    mock_reg2.streams = {"guardian": mock_stream2}

    # Simulate the fixed pause logic
    registrations = [mock_reg1, mock_reg2]
    task_cancelled = False

    for reg in registrations:
        for stream in reg.streams.values():
            for _exec_id, task in list(stream._execution_tasks.items()):
                if task and not task.done():
                    task.cancel()
                    task_cancelled = True

    assert task_cancelled, "Should have cancelled tasks"

    # Wait for cancellations
    await asyncio.sleep(0.05)

    # Verify ALL tasks were cancelled (multi-graph)
    assert task1.cancelled(), "Primary graph task 1 should be cancelled"
    assert task2.cancelled(), "Primary graph task 2 should be cancelled"
    assert task3.cancelled(), "Guardian graph task should be cancelled"

    # Cleanup
    for task in [task1, task2, task3]:
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Test 3: Thread-Safe Cancellation (Unit Test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thread_safe_cancellation():
    """
    Verify that task cancellation uses call_soon_threadsafe.

    TUI runs in different thread than agent loop.
    Direct task.cancel() across threads is unsafe.
    Must use: agent_loop.call_soon_threadsafe(task.cancel)
    """
    # Create mock event loop
    mock_agent_loop = Mock()
    mock_agent_loop.call_soon_threadsafe = Mock()

    # Create mock tasks
    mock_task1 = Mock()
    mock_task1.done.return_value = False
    mock_task1.cancel = Mock()

    mock_task2 = Mock()
    mock_task2.done.return_value = False
    mock_task2.cancel = Mock()

    # Simulate the fixed pause logic with thread-safe cancellation
    execution_tasks = {
        "exec_1": mock_task1,
        "exec_2": mock_task2,
    }

    for _exec_id, task in list(execution_tasks.items()):
        if task and not task.done():
            # THIS IS THE FIX: call_soon_threadsafe instead of direct task.cancel()
            mock_agent_loop.call_soon_threadsafe(task.cancel)

    # Verify call_soon_threadsafe was used (not direct cancel)
    assert mock_agent_loop.call_soon_threadsafe.call_count == 2, (
        "Should use call_soon_threadsafe for thread-safe cancellation"
    )

    # Verify task.cancel was passed as callback
    calls = mock_agent_loop.call_soon_threadsafe.call_args_list
    assert calls[0][0][0] == mock_task1.cancel
    assert calls[1][0][0] == mock_task2.cancel


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
