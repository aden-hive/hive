"""Tests for example_tool - A simple text processing tool."""

import pytest
from fastmcp import FastMCP

from aden_tools.tools.example_tool.example_tool import register_tools


@pytest.fixture
def example_tool_fn(mcp: FastMCP):
    """Register and return the example_tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["example_tool"].fn


class TestExampleTool:
    """Tests for example_tool function."""

    def test_valid_message(self, example_tool_fn):
        """Basic message returns unchanged."""
        result = example_tool_fn(message="Hello, World!")

        assert result == "Hello, World!"

    def test_uppercase_true(self, example_tool_fn):
        """uppercase=True converts message to uppercase."""
        result = example_tool_fn(message="hello", uppercase=True)

        assert result == "HELLO"

    def test_uppercase_false(self, example_tool_fn):
        """uppercase=False (default) preserves case."""
        result = example_tool_fn(message="Hello", uppercase=False)

        assert result == "Hello"

    def test_repeat_multiple(self, example_tool_fn):
        """repeat=3 joins message with spaces."""
        result = example_tool_fn(message="Hi", repeat=3)

        assert result == "Hi Hi Hi"

    def test_repeat_default(self, example_tool_fn):
        """repeat=1 (default) returns single message."""
        result = example_tool_fn(message="Hello", repeat=1)

        assert result == "Hello"

    def test_uppercase_and_repeat_combined(self, example_tool_fn):
        """uppercase and repeat work together."""
        result = example_tool_fn(message="hi", uppercase=True, repeat=2)

        assert result == "HI HI"

    def test_empty_message_error(self, example_tool_fn):
        """Empty string returns error string."""
        result = example_tool_fn(message="")

        assert "Error" in result
        assert "1-1000" in result

    def test_message_too_long_error(self, example_tool_fn):
        """Message over 1000 chars returns error string."""
        long_message = "x" * 1001
        result = example_tool_fn(message=long_message)

        assert "Error" in result
        assert "1-1000" in result

    def test_message_at_max_length(self, example_tool_fn):
        """Message exactly 1000 chars is valid."""
        max_message = "x" * 1000
        result = example_tool_fn(message=max_message)

        assert result == max_message

    def test_repeat_zero_error(self, example_tool_fn):
        """repeat=0 returns error string."""
        result = example_tool_fn(message="Hi", repeat=0)

        assert "Error" in result
        assert "1-10" in result

    def test_repeat_eleven_error(self, example_tool_fn):
        """repeat=11 returns error string."""
        result = example_tool_fn(message="Hi", repeat=11)

        assert "Error" in result
        assert "1-10" in result

    def test_repeat_at_max(self, example_tool_fn):
        """repeat=10 (maximum) is valid."""
        result = example_tool_fn(message="Hi", repeat=10)

        assert result == " ".join(["Hi"] * 10)

    def test_repeat_negative_error(self, example_tool_fn):
        """Negative repeat returns error string."""
        result = example_tool_fn(message="Hi", repeat=-1)

        assert "Error" in result
        assert "1-10" in result

    def test_whitespace_only_message(self, example_tool_fn):
        """Whitespace-only message is valid (non-empty)."""
        result = example_tool_fn(message="   ")

        assert result == "   "

    def test_special_characters_in_message(self, example_tool_fn):
        """Special characters are preserved."""
        result = example_tool_fn(message="Hello! @#$%^&*()")

        assert result == "Hello! @#$%^&*()"

    def test_unicode_message(self, example_tool_fn):
        """Unicode characters are handled correctly."""
        result = example_tool_fn(message="Hello 世界 🌍")

        assert result == "Hello 世界 🌍"

    def test_unicode_uppercase(self, example_tool_fn):
        """Unicode uppercase conversion works."""
        result = example_tool_fn(message="café", uppercase=True)

        assert result == "CAFÉ"
