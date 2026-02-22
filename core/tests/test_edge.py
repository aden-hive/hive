"""
Tests for edge.py module - edge protocol and graph specification.

Tests cover:
- EdgeSpec creation for all edge types (ON_SUCCESS, ON_FAILURE, ALWAYS, CONDITIONAL, LLM_DECIDE)
- Condition evaluation with various expression types
- Traversal logic (should_traverse) for each edge type
- GraphSpec validation, get_node(), get_outgoing_edges()
"""

import pytest

from framework.graph.edge import EdgeSpec, EdgeCondition, GraphSpec, AsyncEntryPointSpec


class TestEdgeCondition:
    """Tests for EdgeCondition enum."""

    def test_always_value(self):
        assert EdgeCondition.ALWAYS == "always"

    def test_on_success_value(self):
        assert EdgeCondition.ON_SUCCESS == "on_success"

    def test_on_failure_value(self):
        assert EdgeCondition.ON_FAILURE == "on_failure"

    def test_conditional_value(self):
        assert EdgeCondition.CONDITIONAL == "conditional"

    def test_llm_decide_value(self):
        assert EdgeCondition.LLM_DECIDE == "llm_decide"


class TestEdgeSpecCreation:
    """Tests for EdgeSpec creation for all edge types."""

    def test_always_edge(self):
        edge = EdgeSpec(
            id="test-always",
            source="node_a",
            target="node_b",
            condition=EdgeCondition.ALWAYS,
        )
        assert edge.id == "test-always"
        assert edge.source == "node_a"
        assert edge.target == "node_b"
        assert edge.condition == EdgeCondition.ALWAYS

    def test_on_success_edge(self):
        edge = EdgeSpec(
            id="test-success",
            source="node_a",
            target="node_b",
            condition=EdgeCondition.ON_SUCCESS,
        )
        assert edge.condition == EdgeCondition.ON_SUCCESS

    def test_on_failure_edge(self):
        edge = EdgeSpec(
            id="test-failure",
            source="node_a",
            target="node_b",
            condition=EdgeCondition.ON_FAILURE,
        )
        assert edge.condition == EdgeCondition.ON_FAILURE

    def test_conditional_edge(self):
        edge = EdgeSpec(
            id="test-cond",
            source="node_a",
            target="node_b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output.confidence > 0.8",
        )
        assert edge.condition == EdgeCondition.CONDITIONAL
        assert edge.condition_expr == "output.confidence > 0.8"

    def test_llm_decide_edge(self):
        edge = EdgeSpec(
            id="test-llm",
            source="node_a",
            target="node_b",
            condition=EdgeCondition.LLM_DECIDE,
            description="Let LLM decide routing",
        )
        assert edge.condition == EdgeCondition.LLM_DECIDE
        assert edge.description == "Let LLM decide routing"

    def test_edge_with_input_mapping(self):
        edge = EdgeSpec(
            id="test-mapping",
            source="node_a",
            target="node_b",
            input_mapping={"target_key": "source_key"},
        )
        assert edge.input_mapping == {"target_key": "source_key"}

    def test_edge_with_priority(self):
        edge = EdgeSpec(
            id="test-priority",
            source="node_a",
            target="node_b",
            priority=10,
        )
        assert edge.priority == 10

    def test_edge_default_priority(self):
        edge = EdgeSpec(
            id="test-default-priority",
            source="node_a",
            target="node_b",
        )
        assert edge.priority == 0

    def test_edge_default_condition(self):
        edge = EdgeSpec(
            id="test-default-cond",
            source="node_a",
            target="node_b",
        )
        assert edge.condition == EdgeCondition.ALWAYS

    def test_edge_extra_fields_allowed(self):
        edge = EdgeSpec(
            id="test-extra",
            source="node_a",
            target="node_b",
            custom_field="custom_value",
        )
        assert edge.custom_field == "custom_value"


class TestEdgeShouldTraverse:
    """Tests for should_traverse method of EdgeSpec."""

    @pytest.mark.asyncio
    async def test_always_traverses(self):
        edge = EdgeSpec(
            id="test-always",
            source="a",
            target="b",
            condition=EdgeCondition.ALWAYS,
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_always_traverses_even_on_failure(self):
        edge = EdgeSpec(
            id="test-always",
            source="a",
            target="b",
            condition=EdgeCondition.ALWAYS,
        )
        result = await edge.should_traverse(
            source_success=False,
            source_output={},
            memory={},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_on_success_traverses_on_success(self):
        edge = EdgeSpec(
            id="test-success",
            source="a",
            target="b",
            condition=EdgeCondition.ON_SUCCESS,
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_on_success_does_not_traverse_on_failure(self):
        edge = EdgeSpec(
            id="test-success",
            source="a",
            target="b",
            condition=EdgeCondition.ON_SUCCESS,
        )
        result = await edge.should_traverse(
            source_success=False,
            source_output={},
            memory={},
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_on_failure_traverses_on_failure(self):
        edge = EdgeSpec(
            id="test-failure",
            source="a",
            target="b",
            condition=EdgeCondition.ON_FAILURE,
        )
        result = await edge.should_traverse(
            source_success=False,
            source_output={},
            memory={},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_on_failure_does_not_traverse_on_success(self):
        edge = EdgeSpec(
            id="test-failure",
            source="a",
            target="b",
            condition=EdgeCondition.ON_FAILURE,
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={},
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_conditional_true_expression(self):
        edge = EdgeSpec(
            id="test-cond",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output['confidence'] > 0.8",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={"confidence": 0.9},
            memory={},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_conditional_false_expression(self):
        edge = EdgeSpec(
            id="test-cond",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output['confidence'] > 0.8",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={"confidence": 0.5},
            memory={},
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_conditional_no_expression_returns_true(self):
        edge = EdgeSpec(
            id="test-cond",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr=None,
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_llm_decide_fallback_to_on_success_when_no_llm(self):
        edge = EdgeSpec(
            id="test-llm",
            source="a",
            target="b",
            condition=EdgeCondition.LLM_DECIDE,
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={},
            llm=None,
            goal=None,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_llm_decide_fallback_to_on_failure_when_no_llm(self):
        edge = EdgeSpec(
            id="test-llm",
            source="a",
            target="b",
            condition=EdgeCondition.LLM_DECIDE,
        )
        result = await edge.should_traverse(
            source_success=False,
            source_output={},
            memory={},
            llm=None,
            goal=None,
        )
        assert result is False


class TestConditionEvaluation:
    """Tests for condition evaluation with various expression types."""

    @pytest.mark.asyncio
    async def test_comparison_expression(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="count > 5",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={"count": 10},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_boolean_expression(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="is_valid and is_ready",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={"is_valid": True, "is_ready": True},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_memory_access_expression(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="memory['retry_count'] < 3",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={"retry_count": 1},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_result_shorthand_expression(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="result == 'success'",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={"result": "success"},
            memory={},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_direct_memory_key_access(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="retry_count < 3",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={"retry_count": 1},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_string_comparison_expression(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="status == 'complete'",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={"status": "complete"},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_in_operator_expression(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="'error' in status",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={"status": "error_timeout"},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_lowercase_true_false(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="true and not false",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_invalid_expression_returns_false(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output.invalid.syntax..error",
        )
        result = await edge.should_traverse(
            source_success=True,
            source_output={},
            memory={},
        )
        assert result is False


class TestInputMapping:
    """Tests for map_inputs method of EdgeSpec."""

    def test_no_mapping_returns_all_output(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
        )
        result = edge.map_inputs(
            source_output={"key1": "value1", "key2": "value2"},
            memory={},
        )
        assert result == {"key1": "value1", "key2": "value2"}

    def test_mapping_from_source_output(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            input_mapping={"target_key": "source_key"},
        )
        result = edge.map_inputs(
            source_output={"source_key": "source_value"},
            memory={},
        )
        assert result == {"target_key": "source_value"}

    def test_mapping_from_memory(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            input_mapping={"target_key": "memory_key"},
        )
        result = edge.map_inputs(
            source_output={},
            memory={"memory_key": "memory_value"},
        )
        assert result == {"target_key": "memory_value"}

    def test_source_output_takes_precedence_over_memory(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            input_mapping={"target_key": "shared_key"},
        )
        result = edge.map_inputs(
            source_output={"shared_key": "from_output"},
            memory={"shared_key": "from_memory"},
        )
        assert result == {"target_key": "from_output"}

    def test_missing_key_results_in_empty(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            input_mapping={"target_key": "nonexistent"},
        )
        result = edge.map_inputs(
            source_output={},
            memory={},
        )
        assert result == {}

    def test_multiple_mappings(self):
        edge = EdgeSpec(
            id="test",
            source="a",
            target="b",
            input_mapping={
                "key1": "source_key1",
                "key2": "memory_key2",
            },
        )
        result = edge.map_inputs(
            source_output={"source_key1": "value1"},
            memory={"memory_key2": "value2"},
        )
        assert result == {"key1": "value1", "key2": "value2"}


class TestAsyncEntryPointSpec:
    """Tests for AsyncEntryPointSpec."""

    def test_creation(self):
        entry = AsyncEntryPointSpec(
            id="webhook",
            name="Webhook Handler",
            entry_node="process-webhook",
        )
        assert entry.id == "webhook"
        assert entry.name == "Webhook Handler"
        assert entry.entry_node == "process-webhook"

    def test_default_trigger_type(self):
        entry = AsyncEntryPointSpec(
            id="test",
            name="Test",
            entry_node="start",
        )
        assert entry.trigger_type == "manual"

    def test_default_isolation_level(self):
        entry = AsyncEntryPointSpec(
            id="test",
            name="Test",
            entry_node="start",
        )
        assert entry.isolation_level == "shared"

    def test_custom_values(self):
        entry = AsyncEntryPointSpec(
            id="webhook",
            name="Webhook",
            entry_node="handler",
            trigger_type="webhook",
            trigger_config={"url": "/api/webhook"},
            isolation_level="isolated",
            priority=10,
            max_concurrent=5,
        )
        assert entry.trigger_type == "webhook"
        assert entry.trigger_config == {"url": "/api/webhook"}
        assert entry.isolation_level == "isolated"
        assert entry.priority == 10
        assert entry.max_concurrent == 5


class TestGraphSpecCreation:
    """Tests for GraphSpec creation."""

    def test_basic_graph_spec(self):
        graph = GraphSpec(
            id="test-graph",
            goal_id="test-goal",
            entry_node="start",
        )
        assert graph.id == "test-graph"
        assert graph.goal_id == "test-goal"
        assert graph.entry_node == "start"

    def test_graph_spec_with_nodes_and_edges(self):
        node = type("Node", (), {"id": "node_a"})()
        edge = EdgeSpec(
            id="edge1",
            source="node_a",
            target="node_b",
        )
        graph = GraphSpec(
            id="test-graph",
            goal_id="test-goal",
            entry_node="node_a",
            nodes=[node],
            edges=[edge],
        )
        assert len(graph.nodes) == 1
        assert len(graph.edges) == 1

    def test_default_version(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
        )
        assert graph.version == "1.0.0"

    def test_default_max_steps(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
        )
        assert graph.max_steps == 100


class TestGraphSpecGetNode:
    """Tests for GraphSpec.get_node method."""

    def test_get_existing_node(self):
        node = type("Node", (), {"id": "node_a"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="node_a",
            nodes=[node],
        )
        result = graph.get_node("node_a")
        assert result == node

    def test_get_nonexistent_node(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
        )
        result = graph.get_node("nonexistent")
        assert result is None


class TestGraphSpecGetOutgoingEdges:
    """Tests for GraphSpec.get_outgoing_edges method."""

    def test_get_outgoing_edges_sorted_by_priority(self):
        edge1 = EdgeSpec(id="e1", source="a", target="b", priority=5)
        edge2 = EdgeSpec(id="e2", source="a", target="c", priority=10)
        edge3 = EdgeSpec(id="e3", source="a", target="d", priority=3)

        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="a",
            edges=[edge1, edge2, edge3],
        )

        outgoing = graph.get_outgoing_edges("a")
        assert len(outgoing) == 3
        assert outgoing[0].priority == 10
        assert outgoing[1].priority == 5
        assert outgoing[2].priority == 3

    def test_get_outgoing_edges_empty(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
        )
        outgoing = graph.get_outgoing_edges("nonexistent")
        assert outgoing == []


class TestGraphSpecGetIncomingEdges:
    """Tests for GraphSpec.get_incoming_edges method."""

    def test_get_incoming_edges(self):
        edge1 = EdgeSpec(id="e1", source="a", target="c")
        edge2 = EdgeSpec(id="e2", source="b", target="c")
        edge3 = EdgeSpec(id="e3", source="a", target="b")

        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="a",
            edges=[edge1, edge2, edge3],
        )

        incoming = graph.get_incoming_edges("c")
        assert len(incoming) == 2
        sources = {e.source for e in incoming}
        assert sources == {"a", "b"}


class TestGraphSpecAsyncEntryPoints:
    """Tests for GraphSpec async entry point methods."""

    def test_has_async_entry_points_false(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
        )
        assert graph.has_async_entry_points() is False

    def test_has_async_entry_points_true(self):
        entry = AsyncEntryPointSpec(
            id="webhook",
            name="Webhook",
            entry_node="handler",
        )
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            async_entry_points=[entry],
        )
        assert graph.has_async_entry_points() is True

    def test_get_async_entry_point(self):
        entry = AsyncEntryPointSpec(
            id="webhook",
            name="Webhook",
            entry_node="handler",
        )
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            async_entry_points=[entry],
        )
        result = graph.get_async_entry_point("webhook")
        assert result == entry

    def test_get_async_entry_point_not_found(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
        )
        result = graph.get_async_entry_point("nonexistent")
        assert result is None


class TestGraphSpecFanDetection:
    """Tests for fan-out and fan-in detection."""

    def test_detect_fan_out_nodes(self):
        node_a = type("Node", (), {"id": "a"})()
        node_b = type("Node", (), {"id": "b"})()
        node_c = type("Node", (), {"id": "c"})()

        edge1 = EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ON_SUCCESS)
        edge2 = EdgeSpec(id="e2", source="a", target="c", condition=EdgeCondition.ON_SUCCESS)

        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="a",
            nodes=[node_a, node_b, node_c],
            edges=[edge1, edge2],
        )

        fan_outs = graph.detect_fan_out_nodes()
        assert "a" in fan_outs
        assert set(fan_outs["a"]) == {"b", "c"}

    def test_detect_no_fan_out(self):
        edge = EdgeSpec(id="e1", source="a", target="b")
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="a",
            edges=[edge],
        )

        fan_outs = graph.detect_fan_out_nodes()
        assert fan_outs == {}

    def test_detect_fan_in_nodes(self):
        node_a = type("Node", (), {"id": "a"})()
        node_b = type("Node", (), {"id": "b"})()
        node_c = type("Node", (), {"id": "c"})()

        edge1 = EdgeSpec(id="e1", source="a", target="c")
        edge2 = EdgeSpec(id="e2", source="b", target="c")

        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="a",
            nodes=[node_a, node_b, node_c],
            edges=[edge1, edge2],
        )

        fan_ins = graph.detect_fan_in_nodes()
        assert "c" in fan_ins
        assert set(fan_ins["c"]) == {"a", "b"}


class TestGraphSpecGetEntryPoint:
    """Tests for GraphSpec.get_entry_point method."""

    def test_default_entry_point(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
        )
        assert graph.get_entry_point() == "start"

    def test_resume_from_pause_node(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            pause_nodes=["pause"],
            entry_points={"pause_resume": "resume"},
        )
        result = graph.get_entry_point({"paused_at": "pause"})
        assert result == "resume"

    def test_resume_from_explicit_resume_from(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            entry_points={"custom": "custom_entry"},
        )
        result = graph.get_entry_point({"resume_from": "custom"})
        assert result == "custom_entry"

    def test_resume_from_node_id(self):
        node = type("Node", (), {"id": "node_a"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            nodes=[node],
        )
        result = graph.get_entry_point({"resume_from": "node_a"})
        assert result == "node_a"


class TestGraphSpecValidation:
    """Tests for GraphSpec.validate method."""

    def test_valid_graph_no_errors(self):
        node = type("Node", (), {"id": "start"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            nodes=[node],
        )
        errors = graph.validate()
        assert errors == []

    def test_missing_entry_node_error(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="nonexistent",
        )
        errors = graph.validate()
        assert len(errors) > 0
        assert any("Entry node" in e for e in errors)

    def test_missing_terminal_node_error(self):
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            terminal_nodes=["nonexistent"],
        )
        errors = graph.validate()
        assert any("Terminal node" in e for e in errors)

    def test_edge_missing_source_error(self):
        edge = EdgeSpec(id="e1", source="missing", target="start")
        node = type("Node", (), {"id": "start"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            nodes=[node],
            edges=[edge],
        )
        errors = graph.validate()
        assert any("missing source" in e for e in errors)

    def test_edge_missing_target_error(self):
        edge = EdgeSpec(id="e1", source="start", target="missing")
        node = type("Node", (), {"id": "start"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            nodes=[node],
            edges=[edge],
        )
        errors = graph.validate()
        assert any("missing target" in e for e in errors)

    def test_unreachable_node_error(self):
        node_start = type("Node", (), {"id": "start"})()
        node_unreachable = type("Node", (), {"id": "unreachable"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            nodes=[node_start, node_unreachable],
        )
        errors = graph.validate()
        assert any("unreachable" in e for e in errors)

    def test_duplicate_async_entry_point_id_error(self):
        entry1 = AsyncEntryPointSpec(id="webhook", name="W1", entry_node="a")
        entry2 = AsyncEntryPointSpec(id="webhook", name="W2", entry_node="b")
        node = type("Node", (), {"id": "start"})()
        node_a = type("Node", (), {"id": "a"})()
        node_b = type("Node", (), {"id": "b"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            nodes=[node, node_a, node_b],
            async_entry_points=[entry1, entry2],
        )
        errors = graph.validate()
        assert any("Duplicate async entry point ID" in e for e in errors)

    def test_invalid_isolation_level_error(self):
        entry = AsyncEntryPointSpec(
            id="test",
            name="Test",
            entry_node="start",
            isolation_level="invalid",
        )
        node = type("Node", (), {"id": "start"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            nodes=[node],
            async_entry_points=[entry],
        )
        errors = graph.validate()
        assert any("invalid isolation_level" in e for e in errors)

    def test_invalid_trigger_type_error(self):
        entry = AsyncEntryPointSpec(
            id="test",
            name="Test",
            entry_node="start",
            trigger_type="invalid_type",
        )
        node = type("Node", (), {"id": "start"})()
        graph = GraphSpec(
            id="test",
            goal_id="goal",
            entry_node="start",
            nodes=[node],
            async_entry_points=[entry],
        )
        errors = graph.validate()
        assert any("invalid trigger_type" in e for e in errors)
