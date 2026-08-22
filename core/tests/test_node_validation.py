import pytest
from pydantic import ValidationError
from framework.orchestrator.node import NodeSpec

def test_node_spec_duplicate_output_keys():
    with pytest.raises(ValidationError, match="Duplicate keys found in output_keys"):
        NodeSpec(
            id="test",
            name="Test",
            description="Test node",
            output_keys=["result", "result"]
        )

def test_node_spec_duplicate_nullable_output_keys():
    with pytest.raises(ValidationError, match="Duplicate keys found in nullable_output_keys"):
        NodeSpec(
            id="test",
            name="Test",
            description="Test node",
            nullable_output_keys=["metadata", "metadata"]
        )

def test_node_spec_overlapping_keys():
    with pytest.raises(ValidationError, match="Overlap detected between output_keys and nullable_output_keys"):
        NodeSpec(
            id="test",
            name="Test",
            description="Test node",
            output_keys=["result", "metadata"],
            nullable_output_keys=["metadata"]
        )

def test_node_spec_empty_string_keys():
    with pytest.raises(ValidationError, match="Output keys cannot be empty strings"):
        NodeSpec(
            id="test",
            name="Test",
            description="Test node",
            output_keys=["result", ""]
        )

def test_node_spec_valid_keys():
    # Should not raise any error
    NodeSpec(
        id="test",
        name="Test",
        description="Test node",
        output_keys=["result"],
        nullable_output_keys=["metadata"]
    )
