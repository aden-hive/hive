"""
Tests for Agent Lifecycle (Pause/Resume).
"""

import asyncio
import pytest
import tempfile
from pathlib import Path

from framework.graph import Goal
from framework.graph.edge import GraphSpec, AsyncEntryPointSpec
from framework.graph.node import NodeSpec
from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.execution_stream import EntryPointSpec
from framework.runtime.event_bus import EventType, AgentEvent

# === Fixtures ===

@pytest.fixture
def lifecycle_goal():
    return Goal(
        id="lifecycle-goal",
        name="Lifecycle Test",
        description="Testing pause/resume",
        success_criteria=[],
    )

@pytest.fixture
def lifecycle_graph():
    return GraphSpec(
        id="lifecycle-graph",
        goal_id="lifecycle-goal",
        version="1.0.0",
        entry_node="start-node",
        entry_points={"start": "start-node"},
        async_entry_points=[
            AsyncEntryPointSpec(
                id="test-stream",
                name="Test Stream",
                entry_node="start-node",
                trigger_type="manual",
            )
        ],
        nodes=[
            NodeSpec(
                id="start-node",
                name="Start",
                description="Start node",
                node_type="pass_through", # Simple node
                input_keys=["input"],
                output_keys=["output"],
            ),
             NodeSpec(
                id="end-node",
                name="End",
                description="End node",
                node_type="terminal",
                input_keys=["output"],
                output_keys=["final"],
            ),
        ],
        edges=[], # No edges needed if we just run one node or rely on graph execution logic
    )

@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

class TestLifecycle:
    """Tests for pause and resume functionality."""
    
    @pytest.mark.asyncio
    async def test_pause_resume_flow(self, lifecycle_graph, lifecycle_goal, temp_storage):
        """Test the full pause -> resume flow."""
        runtime = AgentRuntime(
             graph=lifecycle_graph,
             goal=lifecycle_goal,
             storage_path=temp_storage,
        )
        
        entry_spec = EntryPointSpec(
            id="test-stream",
            name="Test Stream",
            entry_node="start-node",
            trigger_type="manual",
        )
        runtime.register_entry_point(entry_spec)
        await runtime.start()
        
        try:
            # 1. Setup Pause Trigger
            # We want to pause as soon as execution starts
            paused_event = asyncio.Event()
            
            async def pause_handler(event: AgentEvent):
                # Pause the execution
                success = await runtime.pause_execution(
                    entry_point_id=event.stream_id,
                    execution_id=event.execution_id,
                )
                if success:
                    paused_event.set()
            
            runtime.subscribe_to_events(
                event_types=[EventType.EXECUTION_STARTED],
                handler=pause_handler,
            )
            
            # 2. Trigger Execution
            exec_id = await runtime.trigger(
                "test-stream", 
                {"input": "initial_data"}
            )
            
            # Wait for pause
            try:
                await asyncio.wait_for(paused_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pytest.fail("Execution did not pause in time")
            
            # 3. Verify Paused State
            stream = runtime.get_stream("test-stream")
            ctx = stream.get_context(exec_id)
            assert ctx.status == "paused"
            assert ctx.session_state is not None
            assert "paused_at" in ctx.session_state
            
            # 4. Resume Execution
            # We need to mock the completion of the resumed execution
            # Since our graph is simple (start-node has no edges), it might fail or complete
            # But we just want to verify resume logic works (starts new execution)
            
            new_exec_id = await runtime.resume_execution(
                entry_point_id="test-stream",
                execution_id=exec_id,
                input_data={"input": "resumed_data"}
            )
            
            assert new_exec_id is not None
            assert new_exec_id != exec_id
            
            # Verify new execution started
            new_ctx = stream.get_context(new_exec_id)
            assert new_ctx is not None
            assert new_ctx.status in ["running", "completed", "failed"] 
            # It might complete fast
            
            # Verify session_state was passed
            # (We can't easily check internal state of the new execution from outside
            # without inspecting memory, but if it started, resume worked)
            
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_pause_invalid_execution(self, lifecycle_graph, lifecycle_goal, temp_storage):
        """Test pausing a non-existent execution."""
        runtime = AgentRuntime(
             graph=lifecycle_graph,
             goal=lifecycle_goal,
             storage_path=temp_storage,
        )
        entry_spec = EntryPointSpec(
            id="test-stream",
            name="Test Stream",
            entry_node="start-node",
            trigger_type="manual",
        )
        runtime.register_entry_point(entry_spec)
        await runtime.start()
        
        success = await runtime.pause_execution("test-stream", "non-existent")
        assert success is False
        
        await runtime.stop()
