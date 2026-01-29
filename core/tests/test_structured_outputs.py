"""Tests for LLMNode Native Structured Outputs."""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from framework.graph.node import LLMNode, NodeContext, NodeSpec


class TestStructuredOutputs:
    """Test dynamic Pydantic model generation and usage in LLMNode."""

    @pytest.fixture
    def node(self):
        return LLMNode()

    def test_create_output_model_structure(self, node):
        """Test that _create_output_model generates a valid Pydantic class."""
        keys = ["summary", "sentiment", "confidence"]
        Model = node._create_output_model("TestNode", keys)

        # Verify it's a Pydantic model
        assert issubclass(Model, BaseModel)
        assert Model.__name__ == "TestNode"

        # Verify fields exist
        schema = Model.model_json_schema()
        properties = schema.get("properties", {})
        assert "summary" in properties
        assert "sentiment" in properties
        assert "confidence" in properties

    def test_create_output_model_sanitization(self, node):
        """Test that invalid characters in model name are sanitized."""
        Model = node._create_output_model("Bad Name &@!", ["data"])
        assert Model.__name__ == "BadName"

    @pytest.mark.asyncio
    async def test_execute_uses_response_format(self, node):
        """Test that execute() auto-generates model from output_keys (Priority 2)."""
        # Mock Context
        ctx = MagicMock(spec=NodeContext)

        # Explicitly set ALL attributes to avoid MagicMock leakage
        ctx.node_id = "test_node_id"
        ctx.input_data = {}
        ctx.goal_context = ""
        ctx.goal = None
        ctx.max_tokens = 1000

        # Setup Memory
        ctx.memory = MagicMock()
        ctx.memory.read_all.return_value = {}
        ctx.memory.read.return_value = None

        ctx.node_spec = NodeSpec(
            id="test",
            name="Test Node",
            description="desc",
            node_type="llm_generate",
            output_keys=["reason", "conclusion"],
        )
        ctx.llm = MagicMock()
        ctx.available_tools = []
        ctx.runtime = MagicMock()

        # Mock LLM Response
        mock_response = MagicMock()
        mock_response.content = '{"reason": "logic", "conclusion": "yes"}'
        mock_response.input_tokens = 10
        mock_response.output_tokens = 10
        ctx.llm.complete.return_value = mock_response

        # Execute
        result = await node.execute(ctx)

        # Verify Execution Success first
        assert result.success is True, f"Execution failed with error: {result.error}"

        # Verify success
        call_args = ctx.llm.complete.call_args
        assert call_args is not None

        kwargs = call_args[1]
        assert "response_format" in kwargs
        PassedModel = kwargs["response_format"]

        # Verify schema is the auto-generated one
        schema = PassedModel.model_json_schema()
        assert "reason" in schema["properties"]
        assert "conclusion" in schema["properties"]

    @pytest.mark.asyncio
    async def test_execute_prioritizes_explicit_model(self, node):
        """Test that explicit output_model takes precedence over output_keys (Priority 1)."""

        # Define an explicit model
        class ExplicitModel(BaseModel):
            explicit_field: str

        # Mock Context
        ctx = MagicMock(spec=NodeContext)
        ctx.node_id = "test_node_id"
        ctx.input_data = {}
        ctx.goal_context = ""
        ctx.goal = None
        ctx.max_tokens = 1000  # <--- Fix

        ctx.memory = MagicMock()
        ctx.memory.read_all.return_value = {}
        ctx.memory.read.return_value = None

        # NodeSpec has BOTH output_keys AND output_model
        ctx.node_spec = NodeSpec(
            id="test",
            name="Test Node",
            description="desc",
            node_type="llm_generate",
            output_keys=["ignored_key"],  # Should be ignored for schema generation
            output_model=ExplicitModel,  # Should be used
        )

        ctx.llm = MagicMock()
        ctx.available_tools = []
        ctx.runtime = MagicMock()

        # Mock Response
        mock_response = MagicMock()
        mock_response.content = '{"explicit_field": "value"}'
        mock_response.input_tokens = 10
        mock_response.output_tokens = 10
        ctx.llm.complete.return_value = mock_response

        # Execute
        result = await node.execute(ctx)

        # Verify Execution Success
        assert result.success is True, f"Execution failed with error: {result.error}"

        # Verify
        call_args = ctx.llm.complete.call_args
        kwargs = call_args[1]

        # Assert that the passed model is the ExplicitModel, not an auto-generated one
        assert kwargs["response_format"] == ExplicitModel
