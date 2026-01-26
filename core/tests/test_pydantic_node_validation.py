import pytest
from pydantic import BaseModel, Field
from framework.graph.node import NodeSpec, LLMNode, NodeContext, SharedMemory, register_model
from framework.runtime.core import Runtime
from framework.llm.provider import LLMProvider, LLMResponse
from unittest.mock import MagicMock

class UserProfile(BaseModel):
    name: str
    age: int
    interests: list[str]

def test_llm_node_pydantic_validation():
    # 1. Setup mock LLM
    mock_llm = MagicMock(spec=LLMProvider)
    # The LLM returns a JSON string that matches the Pydantic model
    mock_llm.complete.return_value = LLMResponse(
        content='{"name": "Alice", "age": 30, "interests": ["coding", "hiking"]}',
        model="test-model"
    )

    # 2. Setup NodeSpec with Pydantic model
    # register_model("UserProfile", UserProfile)
    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node with Pydantic output",
        node_type="llm_generate",
        output_model=UserProfile
    )

    # 3. Setup Context
    runtime = MagicMock(spec=Runtime)
    memory = SharedMemory()
    ctx = NodeContext(
        runtime=runtime,
        node_id="test_node",
        node_spec=node_spec,
        memory=memory,
        llm=mock_llm
    )

    # 4. Execute node
    node = LLMNode()
    import asyncio
    result = asyncio.run(node.execute(ctx))

    # 5. Verify results
    assert result.success
    assert result.output["name"] == "Alice"
    assert result.output["age"] == 30
    assert result.output["interests"] == ["coding", "hiking"]
    
    # Verify memory was written
    assert memory.read("name") == "Alice"
    assert memory.read("age") == 30

def test_llm_node_pydantic_validation_failure():
    # 1. Setup mock LLM
    mock_llm = MagicMock(spec=LLMProvider)
    # The LLM returns a JSON string that DOES NOT match the Pydantic model (age is missing)
    mock_llm.complete.return_value = LLMResponse(
        content='{"name": "Alice", "interests": ["coding"]}',
        model="test-model"
    )

    # 2. Setup NodeSpec with Pydantic model
    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node with Pydantic output",
        node_type="llm_generate",
        output_model=UserProfile
    )

    # 3. Setup Context
    runtime = MagicMock(spec=Runtime)
    memory = SharedMemory()
    ctx = NodeContext(
        runtime=runtime,
        node_id="test_node",
        node_spec=node_spec,
        memory=memory,
        llm=mock_llm
    )

    # 4. Execute node
    node = LLMNode()
    import asyncio
    result = asyncio.run(node.execute(ctx))

    # 5. Verify results
    assert not result.success
    assert "Pydantic validation failed" in result.error

def test_llm_node_pydantic_registry():
    # 1. Register model
    register_model("UserProfile", UserProfile)
    
    # 2. Setup mock LLM
    mock_llm = MagicMock(spec=LLMProvider)
    mock_llm.complete.return_value = LLMResponse(
        content='{"name": "Bob", "age": 25, "interests": ["gaming"]}',
        model="test-model"
    )

    # 3. Setup NodeSpec with model NAME
    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node with Pydantic output name",
        node_type="llm_generate",
        output_model="UserProfile"
    )

    # 4. Setup Context
    runtime = MagicMock(spec=Runtime)
    memory = SharedMemory()
    ctx = NodeContext(
        runtime=runtime,
        node_id="test_node",
        node_spec=node_spec,
        memory=memory,
        llm=mock_llm
    )

    # 5. Execute node
    node = LLMNode()
    import asyncio
    result = asyncio.run(node.execute(ctx))

    # 6. Verify results
    assert result.success
    assert result.output["name"] == "Bob"

