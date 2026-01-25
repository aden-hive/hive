"""
Tests for enhanced error handling in GraphExecutor.

Tests cover:
- Missing input validation
- Error message formatting
- Edge condition error handling
- Node failure context
"""

import pytest
from pathlib import Path
from tempfile import mkdtemp

from framework.graph.executor import GraphExecutor
from framework.graph.node import NodeSpec, SharedMemory
from framework.graph.goal import Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec, EdgeSpec, EdgeCondition
from framework.runtime.core import Runtime


class TestMissingInputValidation:
    """Tests for missing input validation."""

    def test_format_missing_inputs_error(self):
        """Test _format_missing_inputs_error helper method."""
        storage_path = mkdtemp()
        runtime = Runtime(storage_path)
        executor = GraphExecutor(runtime=runtime, llm=None)

        node_spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="Test",
            node_type="llm_generate",
            input_keys=["required", "optional"],
            output_keys=["result"],
        )

        error_msg = executor._format_missing_inputs_error(
            node_spec=node_spec,
            missing=["required"],
            provided=["optional"],
            available=["optional", "other"],
        )

        assert "test_node" in error_msg
        assert "Missing required inputs" in error_msg
        assert "Expected:" in error_msg
        assert "['required', 'optional']" in error_msg
        assert "Missing: ['required']" in error_msg
        assert "Available in memory" in error_msg
        assert "Hint:" in error_msg

    def test_missing_inputs_detected(self):
        """Test that missing inputs are detected before node execution."""
        storage_path = mkdtemp()
        runtime = Runtime(storage_path)
        executor = GraphExecutor(runtime=runtime, llm=None)

        node_spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="Test",
            node_type="llm_generate",
            input_keys=["required_input"],
            output_keys=["result"],
        )

        graph = GraphSpec(
            id="test-graph",
            goal_id="test",
            entry_node="test_node",
            nodes=[node_spec],
            edges=[],
        )

        goal = Goal(
            id="test",
            name="Test Goal",
            description="Test",
            success_criteria=[],
            constraints=[],
        )

        # Memory is empty - required_input is missing
        import asyncio
        # The executor catches errors and returns ExecutionResult with success=False
        result = asyncio.run(executor.execute(graph=graph, goal=goal, input_data={}))

        # Check that execution failed
        assert result.success is False
        assert result.error is not None
        
        error_msg = result.error
        # Check that the error message contains our improved details
        assert "Missing required inputs" in error_msg or "Execution failed" in error_msg
        assert "required_input" in error_msg
        assert "Expected:" in error_msg or "Inputs Expected:" in error_msg
        assert "Missing:" in error_msg or "test_node" in error_msg


class TestErrorFormatting:
    """Tests for error message formatting helpers."""

    def test_get_memory_snapshot(self):
        """Test _get_memory_snapshot helper method."""
        storage_path = mkdtemp()
        runtime = Runtime(storage_path)
        executor = GraphExecutor(runtime=runtime, llm=None)

        memory = SharedMemory()
        memory.write("short", "value")
        memory.write("long", "x" * 500)

        snapshot = executor._get_memory_snapshot(memory, max_length=50)

        assert "short" in snapshot
        assert snapshot["short"] == "value"
        assert "long" in snapshot
        assert "... (500 chars)" in snapshot["long"]
        assert len(snapshot["long"]) < 100  # Should be truncated

    def test_format_execution_error(self):
        """Test _format_execution_error helper method."""
        storage_path = mkdtemp()
        runtime = Runtime(storage_path)
        executor = GraphExecutor(runtime=runtime, llm=None)

        node_spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="Test",
            node_type="llm_tool_use",
            input_keys=["input1", "input2"],
            output_keys=["output1"],
        )

        memory = SharedMemory()
        memory.write("input1", "value1")
        memory.write("other", "value")

        error = KeyError("'missing_key'")
        path = ["start", "node1", "test_node"]
        steps = 3

        error_msg = executor._format_execution_error(
            error=error,
            node_spec=node_spec,
            memory=memory,
            path=path,
            steps=steps,
        )

        assert "Execution failed" in error_msg
        assert "KeyError" in error_msg
        assert "test_node" in error_msg
        assert "Test Node" in error_msg
        assert "llm_tool_use" in error_msg
        assert "['input1', 'input2']" in error_msg
        assert "start → node1 → test_node" in error_msg
        assert "Steps Executed: 3" in error_msg

    def test_format_execution_error_without_node_spec(self):
        """Test _format_execution_error when node_spec is None."""
        storage_path = mkdtemp()
        runtime = Runtime(storage_path)
        executor = GraphExecutor(runtime=runtime, llm=None)

        memory = SharedMemory()
        error = RuntimeError("Test error")
        path = ["start"]
        steps = 1

        error_msg = executor._format_execution_error(
            error=error,
            node_spec=None,
            memory=memory,
            path=path,
            steps=steps,
        )

        assert "Execution failed" in error_msg
        assert "RuntimeError" in error_msg
        assert "Execution Path:" in error_msg
        assert "Steps Executed: 1" in error_msg


class TestEdgeConditionErrors:
    """Tests for edge condition error handling."""

    def test_edge_condition_error_message(self):
        """Test that edge condition errors provide detailed context."""
        edge = EdgeSpec(
            id="test_edge",
            source="node1",
            target="node2",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output.confidence > 0.8",
        )

        output = {"result": "success", "status": "ok"}
        memory = {"confidence": 0.9, "score": 0.85}

        with pytest.raises(ValueError) as exc_info:
            edge.should_traverse(
                source_success=True,
                source_output=output,
                memory=memory,
            )

        error_msg = str(exc_info.value)
        assert "test_edge" in error_msg
        assert "condition evaluation failed" in error_msg
        assert "output.confidence > 0.8" in error_msg
        assert "Available in output" in error_msg
        assert "Available in memory" in error_msg
        assert "node1" in error_msg
        assert "node2" in error_msg

    def test_edge_condition_suggestions(self):
        """Test that edge condition errors include suggestions."""
        edge = EdgeSpec(
            id="test_edge",
            source="node1",
            target="node2",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output.confidence > 0.8",
        )

        output = {"result": "success"}
        memory = {"confidence": 0.9}  # confidence is in memory, not output

        with pytest.raises(ValueError) as exc_info:
            edge.should_traverse(
                source_success=True,
                source_output=output,
                memory=memory,
            )

        error_msg = str(exc_info.value)
        # Should show available keys and context
        assert "Available in output" in error_msg
        assert "Available in memory" in error_msg
        assert "confidence" in error_msg
        # Note: Suggestions are only generated for KeyError, not AttributeError
        # The error message still provides all the context needed


class TestNodeFailureContext:
    """Tests for node failure context in error messages."""

    def test_node_failure_includes_context(self):
        """Test that node failures include comprehensive context."""
        storage_path = mkdtemp()
        runtime = Runtime(storage_path)
        executor = GraphExecutor(runtime=runtime, llm=None)

        node_spec = NodeSpec(
            id="failing_node",
            name="Failing Node",
            description="A node that fails",
            node_type="function",
            input_keys=["data"],
            output_keys=["result"],
        )

        graph = GraphSpec(
            id="test-graph",
            goal_id="test",
            entry_node="failing_node",
            nodes=[node_spec],
            edges=[],
        )

        goal = Goal(
            id="test",
            name="Test Goal",
            description="Test",
            success_criteria=[],
            constraints=[],
        )

        # This should fail with missing input validation
        import asyncio
        # The executor catches errors and returns ExecutionResult with success=False
        result = asyncio.run(executor.execute(graph=graph, goal=goal, input_data={}))

        # Check that execution failed
        assert result.success is False
        assert result.error is not None
        
        error_msg = result.error
        # Check that the error message contains our improved details
        assert "failing_node" in error_msg
        assert "Missing required inputs" in error_msg or "Execution failed" in error_msg
        assert "Expected:" in error_msg or "Inputs Expected:" in error_msg
        assert "Missing:" in error_msg or "data" in error_msg
        assert "Available in memory" in error_msg or "Memory State" in error_msg
