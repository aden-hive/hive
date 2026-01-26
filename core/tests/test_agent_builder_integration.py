import pytest
import json
import os
from unittest.mock import MagicMock, patch
from framework.mcp.agent_builder_server import create_session, set_goal, add_node, get_session

@pytest.fixture
def mock_session_persistence():
    """Mock file operations to prevent writing to disk during tests."""
    with patch("framework.mcp.agent_builder_server._save_session") as mock_save, \
         patch("framework.mcp.agent_builder_server.SESSIONS_DIR") as mock_dir:
        mock_dir.exists.return_value = True
        yield mock_save

def test_create_session_success(mock_session_persistence):
    """Test creating a new session."""
    result = json.loads(create_session(name="Test Agent"))
    
    assert result["status"] == "created"
    assert result["name"] == "Test Agent"
    assert "session_id" in result
    
    # Verify session was "saved"
    session = get_session()
    assert session.name == "Test Agent"

def test_set_goal_valid(mock_session_persistence):
    """Test setting a valid goal."""
    create_session(name="Goal Agent")
    
    criteria = json.dumps([
        {"id": "c1", "description": "Works", "metric": "bool", "target": "true"}
    ])
    
    result = json.loads(set_goal(
        goal_id="g1",
        name="My Goal",
        description="Do something",
        success_criteria=criteria
    ))
    
    assert result["valid"] is True
    assert result["goal"]["id"] == "g1"
    
    session = get_session()
    assert session.goal.name == "My Goal"

def test_add_node_validation(mock_session_persistence):
    """Test that adding a node validates required fields."""
    create_session(name="Node Agent")
    
    # Missing required 'tools' for 'llm_tool_use' type
    result = json.loads(add_node(
        node_id="n1",
        name="Bad Node",
        description="desc",
        node_type="llm_tool_use",
        input_keys="[]",
        output_keys="[]",
        system_prompt="prompt",
        tools="[]" # Empty tool list should fail validation
    ))
    
    assert result["valid"] is False
    assert any("must specify tools" in err for err in result["errors"])
