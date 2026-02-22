"""
Tests for node.py module - node protocol and data structures.

Tests cover:
- NodeResult success/failure creation, output data, error fields
- NodeSpec core fields and defaults (excluding output_model — already tested in test_pydantic_validation.py)
- NodeContext input data, memory, config, goal fields
- Excludes SharedMemory (already well-covered in test_hallucination_detection.py)
"""

import pytest

from framework.graph.node import NodeResult, NodeSpec, NodeContext, SharedMemory, NodeProtocol
from framework.runtime.core import Runtime


class TestNodeResultCreation:
    """Tests for NodeResult creation."""

    def test_success_result(self):
        result = NodeResult(success=True, output={"key": "value"})
        assert result.success is True
        assert result.output == {"key": "value"}
        assert result.error is None

    def test_failure_result(self):
        result = NodeResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"
        assert result.output == {}

    def test_result_with_output_data(self):
        result = NodeResult(
            success=True,
            output={"count": 5, "message": "hello"},
        )
        assert result.output["count"] == 5
        assert result.output["message"] == "hello"

    def test_result_with_error_field(self):
        result = NodeResult(
            success=False,
            error="Division by zero",
            output={"partial": "data"},
        )
        assert result.error == "Division by zero"
        assert result.output == {"partial": "data"}

    def test_result_default_output(self):
        result = NodeResult(success=True)
        assert result.output == {}

    def test_result_default_error(self):
        result = NodeResult(success=True)
        assert result.error is None


class TestNodeResultFields:
    """Tests for NodeResult fields."""

    def test_next_node(self):
        result = NodeResult(success=True, next_node="target_node")
        assert result.next_node == "target_node"

    def test_route_reason(self):
        result = NodeResult(success=True, route_reason="High confidence score")
        assert result.route_reason == "High confidence score"

    def test_tokens_used(self):
        result = NodeResult(success=True, tokens_used=1500)
        assert result.tokens_used == 1500

    def test_latency_ms(self):
        result = NodeResult(success=True, latency_ms=250)
        assert result.latency_ms == 250

    def test_validation_errors(self):
        result = NodeResult(
            success=False,
            validation_errors=["Missing field: name", "Invalid type for age"],
        )
        assert len(result.validation_errors) == 2
        assert "Missing field: name" in result.validation_errors

    def test_default_validation_errors(self):
        result = NodeResult(success=True)
        assert result.validation_errors == []

    def test_conversation_field(self):
        result = NodeResult(success=True, conversation=None)
        assert result.conversation is None


class TestNodeResultToSummary:
    """Tests for NodeResult.to_summary method."""

    def test_summary_failed_result(self):
        result = NodeResult(success=False, error="Test error")
        summary = result.to_summary()
        assert "Failed" in summary
        assert "Test error" in summary

    def test_summary_success_no_output(self):
        result = NodeResult(success=True, output={})
        summary = result.to_summary()
        assert "no output" in summary.lower()

    def test_summary_success_with_output(self):
        result = NodeResult(success=True, output={"key1": "value1", "key2": "value2"})
        summary = result.to_summary()
        assert summary


class TestNodeSpecCreation:
    """Tests for NodeSpec creation."""

    def test_basic_nodespec(self):
        node = NodeSpec(
            id="test_node",
            name="Test Node",
            description="A test node",
        )
        assert node.id == "test_node"
        assert node.name == "Test Node"
        assert node.description == "A test node"

    def test_nodespec_with_node_type(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            node_type="event_loop",
        )
        assert node.node_type == "event_loop"


class TestNodeSpecDefaults:
    """Tests for NodeSpec default values."""

    def test_default_node_type(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.node_type == "event_loop"

    def test_default_input_keys(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.input_keys == []

    def test_default_output_keys(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.output_keys == []

    def test_default_nullable_output_keys(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.nullable_output_keys == []

    def test_default_system_prompt(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.system_prompt is None

    def test_default_tools(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.tools == []

    def test_default_model(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.model is None

    def test_default_routes(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.routes == {}

    def test_default_max_retries(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.max_retries == 3

    def test_default_retry_on(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.retry_on == []

    def test_default_max_node_visits(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.max_node_visits == 0

    def test_default_output_model(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.output_model is None

    def test_default_max_validation_retries(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.max_validation_retries == 2

    def test_default_client_facing(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.client_facing is False

    def test_default_success_criteria(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.success_criteria is None

    def test_default_input_schema(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.input_schema == {}

    def test_default_output_schema(self):
        node = NodeSpec(id="test", name="Test", description="Test")
        assert node.output_schema == {}


class TestNodeSpecFields:
    """Tests for NodeSpec field values."""

    def test_custom_node_type(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            node_type="router",
        )
        assert node.node_type == "router"

    def test_input_keys(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            input_keys=["input1", "input2"],
        )
        assert node.input_keys == ["input1", "input2"]

    def test_output_keys(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            output_keys=["result", "status"],
        )
        assert node.output_keys == ["result", "status"]

    def test_nullable_output_keys(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            nullable_output_keys=["optional_field"],
        )
        assert node.nullable_output_keys == ["optional_field"]

    def test_system_prompt(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            system_prompt="You are a helpful assistant.",
        )
        assert node.system_prompt == "You are a helpful assistant."

    def test_tools(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            tools=["search", "calculate"],
        )
        assert node.tools == ["search", "calculate"]

    def test_model(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            model="claude-3-opus",
        )
        assert node.model == "claude-3-opus"

    def test_routes(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            routes={"high_confidence": "node_a", "low_confidence": "node_b"},
        )
        assert node.routes["high_confidence"] == "node_a"

    def test_max_retries(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            max_retries=5,
        )
        assert node.max_retries == 5

    def test_retry_on(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            retry_on=["TimeoutError", "ConnectionError"],
        )
        assert "TimeoutError" in node.retry_on

    def test_max_node_visits(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            max_node_visits=10,
        )
        assert node.max_node_visits == 10

    def test_client_facing(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            client_facing=True,
        )
        assert node.client_facing is True

    def test_success_criteria(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            success_criteria="All output keys are filled",
        )
        assert node.success_criteria == "All output keys are filled"

    def test_input_schema(self):
        schema = {"query": {"type": "string", "required": True}}
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            input_schema=schema,
        )
        assert node.input_schema == schema

    def test_output_schema(self):
        schema = {"result": {"type": "dict", "required": True}}
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            output_schema=schema,
        )
        assert node.output_schema == schema


class TestNodeSpecExtraFields:
    """Tests for NodeSpec extra fields functionality."""

    def test_extra_fields_allowed(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            custom_field="custom_value",
        )
        assert node.custom_field == "custom_value"

    def test_multiple_extra_fields(self):
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            metadata={"key": "value"},
            priority=10,
        )
        assert node.metadata == {"key": "value"}
        assert node.priority == 10


class TestNodeSpecModelDump:
    """Tests for NodeSpec serialization."""

    def test_model_dump(self):
        node = NodeSpec(
            id="test",
            name="Test Node",
            description="Test description",
            node_type="event_loop",
        )
        dumped = node.model_dump()
        assert dumped["id"] == "test"
        assert dumped["name"] == "Test Node"
        assert dumped["description"] == "Test description"


class TestNodeContextCreation:
    """Tests for NodeContext creation."""

    def test_basic_node_context(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test_node",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.runtime == runtime
        assert context.node_id == "test_node"
        assert context.node_spec == node_spec
        assert context.memory == memory

    def test_node_context_with_input_data(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            input_data={"key": "value"},
        )

        assert context.input_data == {"key": "value"}


class TestNodeContextDefaults:
    """Tests for NodeContext default values."""

    def test_default_input_data(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.input_data == {}

    def test_default_llm(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.llm is None

    def test_default_available_tools(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.available_tools == []

    def test_default_goal_context(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.goal_context == ""

    def test_default_goal(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.goal is None

    def test_default_max_tokens(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.max_tokens == 4096

    def test_default_attempt(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.attempt == 1

    def test_default_max_attempts(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.max_attempts == 3

    def test_default_continuous_mode(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.continuous_mode is False

    def test_default_cumulative_output_keys(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.cumulative_output_keys == []

    def test_default_accounts_prompt(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.accounts_prompt == ""

    def test_default_event_triggered(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.event_triggered is False

    def test_default_execution_id(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
        )

        assert context.execution_id == ""


class TestNodeContextFields:
    """Tests for NodeContext field values."""

    def test_llm_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            llm=None,
        )

        assert context.llm is None

    def test_goal_context_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            goal_context="Complete the task",
        )

        assert context.goal_context == "Complete the task"

    def test_max_tokens_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            max_tokens=8192,
        )

        assert context.max_tokens == 8192

    def test_attempt_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            attempt=2,
        )

        assert context.attempt == 2

    def test_max_attempts_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            max_attempts=5,
        )

        assert context.max_attempts == 5

    def test_continuous_mode_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            continuous_mode=True,
        )

        assert context.continuous_mode is True

    def test_cumulative_output_keys_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            cumulative_output_keys=["key1", "key2", "key3"],
        )

        assert context.cumulative_output_keys == ["key1", "key2", "key3"]

    def test_event_triggered_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            event_triggered=True,
        )

        assert context.event_triggered is True

    def test_execution_id_field(self, tmp_path):
        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(id="test", name="Test", description="Test")
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            execution_id="exec-123",
        )

        assert context.execution_id == "exec-123"


class TestNodeProtocol:
    """Tests for NodeProtocol abstract class."""

    def test_node_protocol_is_abstract(self):
        assert NodeProtocol.__abstractmethods__ == frozenset({"execute"})

    def test_validate_input_with_missing_keys(self, tmp_path):
        class TestNode(NodeProtocol):
            async def execute(self, ctx):
                return NodeResult(success=True)

        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            input_keys=["required_key"],
        )
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            input_data={},
        )

        node = TestNode()
        errors = node.validate_input(context)
        assert len(errors) == 1
        assert "required_key" in errors[0]

    def test_validate_input_with_present_keys_in_input_data(self, tmp_path):
        class TestNode(NodeProtocol):
            async def execute(self, ctx):
                return NodeResult(success=True)

        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            input_keys=["required_key"],
        )
        memory = SharedMemory()

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            input_data={"required_key": "value"},
        )

        node = TestNode()
        errors = node.validate_input(context)
        assert errors == []

    def test_validate_input_with_present_keys_in_memory(self, tmp_path):
        class TestNode(NodeProtocol):
            async def execute(self, ctx):
                return NodeResult(success=True)

        runtime = Runtime(tmp_path)
        node_spec = NodeSpec(
            id="test",
            name="Test",
            description="Test",
            input_keys=["required_key"],
        )
        memory = SharedMemory()
        memory.write("required_key", "value")

        context = NodeContext(
            runtime=runtime,
            node_id="test",
            node_spec=node_spec,
            memory=memory,
            input_data={},
        )

        node = TestNode()
        errors = node.validate_input(context)
        assert errors == []


class TestHelperFunctions:
    """Tests for helper functions in node.py."""

    def test_find_json_object_simple(self):
        from framework.graph.node import find_json_object

        text = '{"key": "value"}'
        result = find_json_object(text)
        assert result == '{"key": "value"}'

    def test_find_json_object_nested(self):
        from framework.graph.node import find_json_object

        text = '{"outer": {"inner": 1}}'
        result = find_json_object(text)
        assert result == '{"outer": {"inner": 1}}'

    def test_find_json_object_with_surrounding_text(self):
        from framework.graph.node import find_json_object

        text = 'Here is the result: {"key": "value"} and more text'
        result = find_json_object(text)
        assert result == '{"key": "value"}'

    def test_find_json_object_no_json(self):
        from framework.graph.node import find_json_object

        text = "This is just plain text"
        result = find_json_object(text)
        assert result is None

    def test_find_json_object_empty(self):
        from framework.graph.node import find_json_object

        result = find_json_object("")
        assert result is None

    def test_fix_unescaped_newlines_in_json(self):
        from framework.graph.node import _fix_unescaped_newlines_in_json

        json_str = '{"text": "line1\nline2"}'
        result = _fix_unescaped_newlines_in_json(json_str)
        assert "\\n" in result
        assert "\n" not in result.split('"text": "')[1].split('"')[0]
