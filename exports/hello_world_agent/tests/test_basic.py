"""Basic tests for hello_world_agent."""
import pytest
from exports.hello_world_agent.tools import echo_function

def test_echo_function_default():
    """Test echo_function with default parameter."""
    result = echo_function()
    assert result["greeting"] == "Hello, World! Welcome to Hive."
    assert result["success"] is True

def test_echo_function_custom_name():
    """Test echo_function with custom name."""
    result = echo_function("Alice")
    assert result["greeting"] == "Hello, Alice! Welcome to Hive."
    assert result["message"] == "Greeting generated for 'Alice'"

def test_echo_function_empty_name():
    """Test echo_function with empty name."""
    result = echo_function("")
    assert result["greeting"] == "Hello, ! Welcome to Hive."
    assert result["success"] is True

def test_echo_function_return_structure():
    """Test that echo_function returns expected structure."""
    result = echo_function("Test")
    assert "greeting" in result
    assert "success" in result
    assert "message" in result
    assert isinstance(result["greeting"], str)
    assert isinstance(result["success"], bool)
    assert isinstance(result["message"], str)