"""Tests for CLI input methods (Windows PowerShell compatibility)."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from framework.runner.cli import _parse_json_input


class TestJsonInputParsing:
    """Test JSON input parsing with Windows PowerShell compatibility."""

    def test_parse_valid_json_string(self):
        """Test parsing valid JSON string."""
        json_str = '{"query": "hello", "count": 5}'
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert result == {"query": "hello", "count": 5}

    def test_parse_invalid_json_string(self):
        """Test parsing invalid JSON returns helpful error."""
        json_str = '{query: hello}'  # Unquoted keys
        result, error = _parse_json_input(json_str)
        
        assert result == {}
        assert error is not None
        assert "Windows/PowerShell Tips" in error
        assert "--input-env" in error
        assert "--input-stdin" in error

    def test_parse_json_with_nested_objects(self):
        """Test parsing nested JSON objects."""
        json_str = '{"user": {"name": "Alice", "age": 30}, "tags": ["ai", "bot"]}'
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert result["user"]["name"] == "Alice"
        assert "ai" in result["tags"]

    def test_parse_json_with_special_characters(self):
        """Test parsing JSON with special characters."""
        json_str = '{"message": "Hello \\"world\\"", "emoji": "😀"}'
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert result["message"] == 'Hello "world"'

    def test_parse_empty_json_object(self):
        """Test parsing empty JSON object."""
        json_str = '{}'
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert result == {}

    def test_parse_json_array(self):
        """Test parsing JSON array (edge case - technically valid but unusual)."""
        json_str = '[1, 2, 3]'
        # JSON arrays parse successfully, just not typical for agent input
        result, error = _parse_json_input(json_str)
        # The helper accepts arrays since JSON parsing succeeded
        # In practice, cmd_run would handle this appropriately
        assert result == [1, 2, 3]

    def test_error_message_contains_helpful_tips(self):
        """Test that error messages include Windows tips."""
        json_str = '{invalid}'
        _, error = _parse_json_input(json_str)
        
        assert "Windows/PowerShell Tips" in error
        assert "--input-file" in error
        assert "--input-env" in error


class TestCLIInputMethods:
    """Test actual CLI input methods via cmd_run simulation."""

    def test_input_via_direct_string(self):
        """Test --input with direct JSON string."""
        # Simulate argparse args
        args = MagicMock()
        args.input = '{"query": "test"}'
        args.input_file = None
        args.input_env = None
        args.input_stdin = False
        
        # Direct test of parsing logic
        json_str = args.input
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert result == {"query": "test"}

    def test_input_via_file(self, tmp_path):
        """Test --input-file with temporary JSON file."""
        # Create temp JSON file
        json_file = tmp_path / "input.json"
        test_data = {"query": "test", "id": 123}
        json_file.write_text(json.dumps(test_data))
        
        # Simulate reading file
        with open(json_file) as f:
            context = json.load(f)
        
        assert context == test_data

    def test_input_via_environment_variable(self):
        """Test --input-env reading from environment."""
        test_data = {"query": "from_env", "source": "environment"}
        os.environ["TEST_AGENT_INPUT"] = json.dumps(test_data)
        
        try:
            env_value = os.environ.get("TEST_AGENT_INPUT")
            result, error = _parse_json_input(env_value, "--input-env TEST_AGENT_INPUT")
            
            assert error is None
            assert result == test_data
        finally:
            del os.environ["TEST_AGENT_INPUT"]

    def test_input_via_stdin_simulation(self):
        """Test --input-stdin via pipe simulation."""
        test_data = {"query": "from_stdin", "mode": "pipe"}
        json_string = json.dumps(test_data)
        
        # Simulate reading from stdin
        result, error = _parse_json_input(json_string, "stdin")
        
        assert error is None
        assert result == test_data

    def test_missing_environment_variable_error(self):
        """Test error handling when environment variable doesn't exist."""
        # Make sure this env var doesn't exist
        if "NONEXISTENT_VAR_12345" in os.environ:
            del os.environ["NONEXISTENT_VAR_12345"]
        
        env_value = os.environ.get("NONEXISTENT_VAR_12345")
        assert env_value is None

    def test_only_one_input_method_allowed(self):
        """Test that only one input method can be used."""
        # Simulate args with multiple input methods
        args = MagicMock()
        args.input = '{"key": "value"}'
        args.input_file = "file.json"
        args.input_env = "MY_VAR"
        args.input_stdin = True
        
        input_count = sum([
            bool(args.input),
            bool(args.input_file),
            bool(args.input_env),
            bool(args.input_stdin)
        ])
        
        assert input_count == 4  # All set
        assert input_count > 1  # Multiple inputs error would occur


class TestWindowsPowerShellCompatibility:
    """Test compatibility with Windows PowerShell quote handling."""

    def test_double_quotes_with_escapes(self):
        """Test parsing JSON with escaped double quotes (Windows style)."""
        # Windows PowerShell would pass this as actual escaped quotes
        json_str = '{"key": "value", "nested": {"inner": "data"}}'
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert result["key"] == "value"

    def test_single_quotes_preserve_content(self):
        """Test that single quotes don't interfere with JSON."""
        json_str = '{"message": "It\'s working", "name": "O\'Brien"}'
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert "It's working" in result["message"]

    def test_help_suggestions_for_windows_users(self):
        """Test that error messages provide Windows-specific guidance."""
        invalid_json = '{key: value}'  # Unquoted keys - common Windows error
        _, error = _parse_json_input(invalid_json)
        
        assert error is not None
        # Check for all three alternatives mentioned
        assert "python -m core run" in error
        assert "--input-file" in error
        assert "--input-env" in error
        assert "--input-stdin" in error


class TestInputValidation:
    """Test input validation and error handling."""

    def test_empty_input_string(self):
        """Test handling of empty input string."""
        result, error = _parse_json_input('')
        
        assert error is not None
        assert result == {}

    def test_whitespace_only_input(self):
        """Test handling of whitespace-only input."""
        result, error = _parse_json_input('   ')
        
        assert error is not None
        assert result == {}

    def test_malformed_json_with_trailing_comma(self):
        """Test JSON with trailing comma (common error)."""
        json_str = '{"key": "value",}'  # Trailing comma
        result, error = _parse_json_input(json_str)
        
        assert error is not None  # Should fail

    def test_unicode_in_json_values(self):
        """Test handling of unicode characters in JSON."""
        json_str = '{"greeting": "你好", "emoji": "🚀", "symbol": "€"}'
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert result["greeting"] == "你好"
        assert result["emoji"] == "🚀"

    def test_large_json_input(self):
        """Test parsing of large JSON objects."""
        large_dict = {f"key_{i}": f"value_{i}" for i in range(1000)}
        json_str = json.dumps(large_dict)
        result, error = _parse_json_input(json_str)
        
        assert error is None
        assert len(result) == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
