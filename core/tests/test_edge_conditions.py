import pytest
import logging
from typing import Any
from framework.graph.edge import EdgeSpec, EdgeCondition

def test_basic_condition_evaluation():
    """Test that simple conditions evaluate correctly."""
    edge = EdgeSpec(
        id="test-edge",
        source="node1",
        target="node2",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="x > 5"
    )
    
    # Simple success
    assert edge._evaluate_condition(output={}, memory={"x": 10}) is True
    # Simple failure
    assert edge._evaluate_condition(output={}, memory={"x": 3}) is False

def test_memory_access_in_expression():
    """Test that conditions can access variables in agent memory."""
    edge = EdgeSpec(
        id="test-edge",
        source="node1",
        target="node2",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="status == 'complete' and confidence > 0.8"
    )
    
    memory = {"status": "complete", "confidence": 0.9}
    assert edge._evaluate_condition(output={}, memory=memory) is True
    
    memory = {"status": "pending", "confidence": 0.9}
    assert edge._evaluate_condition(output={}, memory=memory) is False

def test_reserved_keys_protection():
    """
    Verify that memory keys do NOT overwrite reserved context variables.
    This is a regression test for Issue #595.
    """
    edge = EdgeSpec(
        id="test-edge",
        source="node1",
        target="node2",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="result == 'actual_result'"
    )
    
    # 'result' in context should be output.get("result"), NOT memory['result']
    output = {"result": "actual_result"}
    memory = {"result": "malicious_shadow"}
    
    # If the fix works, 'result' in the expression will be 'actual_result'
    assert edge._evaluate_condition(output=output, memory=memory) is True
    
    # Another test for 'output' protection
    edge_output = EdgeSpec(
        id="test-edge-output",
        source="node1",
        target="node2",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="output['type'] == 'success'"
    )
    
    output = {"type": "success"}
    memory = {"output": "shadow_value"}
    
    # If the fix works, 'output' in the expression refers to the real output dict
    assert edge_output._evaluate_condition(output=output, memory=memory) is True

def test_access_shadowed_keys_via_memory_dict():
    """Verify that shadowed variables can still be accessed via the memory dictionary."""
    edge = EdgeSpec(
        id="test-edge",
        source="node1",
        target="node2",
        condition=EdgeCondition.CONDITIONAL,
        # Accessing 'result' from memory explicitly via memory['result']
        condition_expr="memory['result'] == 'shadow_value'"
    )
    
    output = {"result": "real_result"}
    memory = {"result": "shadow_value"}
    
    assert edge._evaluate_condition(output=output, memory=memory) is True

def test_true_false_lowercase():
    """Verify that lowercase true and false are available in conditions."""
    edge = EdgeSpec(
        id="test-edge",
        source="node1",
        target="node2",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="x == true and y == false"
    )
    
    assert edge._evaluate_condition(output={}, memory={"x": True, "y": False}) is True

def test_invalid_expression_failure_is_graceful(caplog):
    """Verify that invalid conditions are handled safely (return False) and logged."""
    edge = EdgeSpec(
        id="test-edge",
        source="node1",
        target="node2",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="non_existent_var > 10"  # Will cause NameError
    )
    
    with caplog.at_level(logging.WARNING):
        result = edge._evaluate_condition(output={}, memory={})
        
    assert result is False
    assert "Condition evaluation failed" in caplog.text
    assert "non_existent_var" in caplog.text

def test_complex_safe_eval_features():
    """Test more complex expressions supported by safe_eval."""
    edge = EdgeSpec(
        id="test-edge",
        source="node1",
        target="node2",
        condition=EdgeCondition.CONDITIONAL,
        # Using len() and list access
        condition_expr="len(items) > 0 and items[0] == 'first'"
    )
    
    memory = {"items": ["first", "second"]}
    assert edge._evaluate_condition(output={}, memory=memory) is True
    
    memory = {"items": []}
    assert edge._evaluate_condition(output={}, memory=memory) is False
