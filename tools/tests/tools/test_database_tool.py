import sqlite3
import pytest
import os
from aden_tools.tools.database_tool.database_tool import register_tools

class MockMCP:
    def __init__(self):
        self.tools = {}
    
    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator

@pytest.fixture
def temp_db(tmp_path):
    """Creates a temporary SQLite database for testing."""
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    cursor.execute("INSERT INTO users VALUES (1, 'Anwesha'), (2, 'Hundao')")
    conn.commit()
    conn.close()
    return db_file

@pytest.fixture
def db_funcs():
    """Captures the registered functions directly."""
    mock_mcp = MockMCP()
    register_tools(mock_mcp)
    return mock_mcp.tools

def test_db_info_logic(db_funcs, temp_db):
    """Test the schema retrieval logic."""
    result = db_funcs["db_info"](
        path=str(temp_db),
        workspace_id=str(temp_db.parent),
        agent_id="test",
        session_id="test"
    )
    assert "error" not in result, f"Error: {result.get('error')}"
    assert result.get("success") is True
    assert "users" in result["schema"]

def test_db_query_logic_success(db_funcs, temp_db):
    """Test successful SELECT query logic."""
    result = db_funcs["db_query"](
        path=str(temp_db),
        workspace_id=str(temp_db.parent),
        agent_id="test",
        session_id="test",
        query="SELECT name FROM users WHERE id = 1"
    )
    assert "error" not in result, f"Error: {result.get('error')}"
    assert result.get("success") is True
    assert result["rows"][0]["name"] == "Anwesha"

def test_db_query_logic_security_block(db_funcs, temp_db):
    """Test that the security check blocks DELETE."""
    result = db_funcs["db_query"](
        path=str(temp_db),
        workspace_id=str(temp_db.parent),
        agent_id="test",
        session_id="test",
        query="DELETE FROM users"
    )
    assert "error" in result
    assert "Only SELECT queries are allowed" in result["error"]