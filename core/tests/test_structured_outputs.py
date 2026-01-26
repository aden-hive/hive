"""Tests for LLMNode Native Structured Outputs."""

import pytest
from unittest.mock import MagicMock
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
        
        # Verify instantiation
        instance = Model(summary="test", sentiment="positive", confidence="high")
        assert instance.summary == "test"

    def test_create_output_model_sanitization(self, node):
        """Test that invalid characters in model name are sanitized."""
        Model = node._create_output_model("Bad Name &@!", ["data"])
        assert Model.__name__ == "BadName"

    @pytest.mark.asyncio
    async def test_execute_uses_response_format(self, node):
        """Test that execute() passes the generated model to the LLM."""
        # Mock Context
        ctx = MagicMock(spec=NodeContext)
        
        ctx.node_id = "test_node_id"
        ctx.input_data = {}
        ctx.goal_context = ""  
        ctx.goal = None         
       
        
        # Setup Memory
        ctx.memory = MagicMock()
        ctx.memory.read_all.return_value = {}
        ctx.memory.read.return_value = None

        ctx.node_spec = NodeSpec(
            id="test",
            name="Test Node", 
            description="desc",
            node_type="llm_generate",
            output_keys=["reason", "conclusion"]
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
        await node.execute(ctx)

        # Verify success
        call_args = ctx.llm.complete.call_args
        assert call_args is not None
        
        kwargs = call_args[1]
        assert "response_format" in kwargs
        PassedModel = kwargs["response_format"]
        
        # Verify schema
        schema = PassedModel.model_json_schema()
        assert "reason" in schema["properties"]
        assert "conclusion" in schema["properties"]