"""Tests for Professional Rewriter agent."""

import pytest
from professional_rewriter import default_agent, goal, nodes, edges


def test_agent_structure():
    """Test basic agent structure."""
    assert default_agent.goal.id == "professional-rewriter-goal"
    assert len(default_agent.nodes) == 2
    assert len(default_agent.edges) == 2
    assert default_agent.entry_node == "rewrite"


def test_goal_definition():
    """Test goal has required success criteria and constraints."""
    assert len(goal.success_criteria) == 4
    assert len(goal.constraints) == 3
    
    # Check success criteria weights sum to 1.0
    total_weight = sum(sc.weight for sc in goal.success_criteria)
    assert abs(total_weight - 1.0) < 0.001


def test_node_configuration():
    """Test node specifications."""
    node_ids = {n.id for n in nodes}
    assert node_ids == {"rewrite", "validate"}
    
    # Find nodes
    rewrite_node = next(n for n in nodes if n.id == "rewrite")
    validate_node = next(n for n in nodes if n.id == "validate")
    
    # Test rewrite node
    assert rewrite_node.node_type == "event_loop"
    assert "text" in rewrite_node.input_keys
    assert "rewritten_text" in rewrite_node.output_keys
    assert "tone" in rewrite_node.output_keys
    assert "changes_made" in rewrite_node.output_keys
    assert "final_check" in rewrite_node.output_keys
    assert rewrite_node.tools == []  # LLM only
    
    # Test validate node
    assert validate_node.node_type == "event_loop"
    assert "rewritten_text" in validate_node.input_keys
    assert "validation_result" in validate_node.output_keys
    assert "final_output" in validate_node.output_keys
    assert validate_node.tools == []  # LLM only


def test_edge_configuration():
    """Test edge specifications."""
    edge_specs = {(e.source, e.target): e for e in edges}
    
    # Should have rewrite -> validate -> rewrite loop
    assert ("rewrite", "validate") in edge_specs
    assert ("validate", "rewrite") in edge_specs
    
    # Check edge conditions
    rewrite_to_validate = edge_specs[("rewrite", "validate")]
    assert rewrite_to_validate.condition.name == "ON_SUCCESS"
    
    validate_done = edge_specs[("validate", "rewrite")]
    assert validate_done.condition.name == "ON_SUCCESS"


def test_agent_validation():
    """Test agent passes internal validation."""
    validation = default_agent.validate()
    assert validation["valid"] is True
    assert len(validation["errors"]) == 0


def test_forever_alive_configuration():
    """Test agent is configured as forever-alive."""
    assert default_agent.terminal_nodes == []
    assert default_agent.entry_points == {"start": "rewrite"}


def test_system_prompts():
    """Test nodes have appropriate system prompts."""
    rewrite_node = next(n for n in nodes if n.id == "rewrite")
    validate_node = next(n for n in nodes if n.id == "validate")
    
    # Check key instructions are present
    assert "set_output" in rewrite_node.system_prompt
    assert "rewritten_text" in rewrite_node.system_prompt
    assert "changes_made" in rewrite_node.system_prompt
    assert "JSON" in validate_node.system_prompt
    assert "validation_result" in validate_node.system_prompt


def test_import_agent_package(agent_module):
    """Test that the agent package can be imported."""
    assert hasattr(agent_module, "default_agent")
    assert hasattr(agent_module, "goal")
    assert hasattr(agent_module, "nodes")
    assert hasattr(agent_module, "edges")


def test_agent_runner_loads(runner_loaded):
    """Test that AgentRunner can load the agent."""
    assert runner_loaded is not None