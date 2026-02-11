"""Tests for CLI JSON input validation functionality."""

import io
import json
import sys

from framework.runner.cli import (
    _describe_json_error,
    _show_error_context,
    _validate_json_input,
)


class TestValidateJsonInput:
    """Test _validate_json_input function."""

    def test_valid_json_object(self):
        """Valid JSON object should be parsed correctly."""
        result = _validate_json_input('{"key": "value"}')
        assert result == {"key": "value"}

    def test_valid_json_with_multiple_keys(self):
        """Valid JSON with multiple keys should be parsed correctly."""
        result = _validate_json_input('{"name": "test", "count": 42}')
        assert result == {"name": "test", "count": 42}

    def test_valid_json_with_nested_object(self):
        """Valid JSON with nested object should be parsed correctly."""
        result = _validate_json_input('{"outer": {"inner": "value"}}')
        assert result == {"outer": {"inner": "value"}}

    def test_valid_json_with_array(self):
        """Valid JSON with array should be parsed correctly."""
        result = _validate_json_input('{"items": [1, 2, 3]}')
        assert result == {"items": [1, 2, 3]}

    def test_invalid_json_missing_quotes_on_key(self):
        """Invalid JSON with unquoted key should return None and print error."""
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture

        try:
            result = _validate_json_input('{key: "value"}', "--input")
            assert result is None

            error_output = stderr_capture.getvalue()
            assert "Invalid JSON format" in error_output
            assert "Missing quotes" in error_output
            assert "--input" in error_output
        finally:
            sys.stderr = old_stderr

    def test_invalid_json_missing_closing_quote(self):
        """Invalid JSON with missing closing quote should return None."""
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture

        try:
            result = _validate_json_input('{"key: "value"}', "--input")
            assert result is None

            error_output = stderr_capture.getvalue()
            assert "Invalid JSON format" in error_output
        finally:
            sys.stderr = old_stderr

    def test_invalid_json_missing_colon(self):
        """Invalid JSON with missing colon should return None."""
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture

        try:
            result = _validate_json_input('{"key" "value"}', "--input")
            assert result is None

            error_output = stderr_capture.getvalue()
            assert "Invalid JSON format" in error_output
        finally:
            sys.stderr = old_stderr

    def test_invalid_json_extra_data(self):
        """Invalid JSON with extra data should return None."""
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture

        try:
            result = _validate_json_input('"key": value', "--input")
            assert result is None

            error_output = stderr_capture.getvalue()
            assert "Invalid JSON format" in error_output
        finally:
            sys.stderr = old_stderr

    def test_custom_param_name_in_error(self):
        """Custom parameter name should appear in error message."""
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture

        try:
            result = _validate_json_input("{invalid}", "--custom-param")
            assert result is None

            error_output = stderr_capture.getvalue()
            assert "--custom-param" in error_output
        finally:
            sys.stderr = old_stderr


class TestDescribeJsonError:
    """Test _describe_json_error function."""

    def test_missing_property_name_quotes(self):
        """Should describe missing quotes around key names."""
        e = json.JSONDecodeError("Expecting property name", '{"key": "value"}', 0)
        result = _describe_json_error(e, '{key: "value"}')
        assert "Missing quotes" in result
        assert "key" in result.lower()

    def test_missing_value(self):
        """Should describe missing value after colon."""
        e = json.JSONDecodeError("Expecting value", '{"key": }', 8)
        result = _describe_json_error(e, '{"key": }')
        assert "Missing a value" in result

    def test_unterminated_string(self):
        """Should describe unterminated string."""
        e = json.JSONDecodeError("Unterminated string", '{"key": "value', 7)
        result = _describe_json_error(e, '{"key": "value')
        assert "Missing closing quote" in result

    def test_missing_colon(self):
        """Should describe missing colon."""
        e = json.JSONDecodeError("Expecting ':' delimiter", '{"key" "value"}', 6)
        result = _describe_json_error(e, '{"key" "value"}')
        assert "Missing colon" in result

    def test_missing_comma(self):
        """Should describe missing comma."""
        e = json.JSONDecodeError("Expecting ',' delimiter", '{"a": 1 "b": 2}', 9)
        result = _describe_json_error(e, '{"a": 1 "b": 2}')
        assert "Missing comma" in result

    def test_extra_data(self):
        """Should describe extra data error."""
        e = json.JSONDecodeError("Extra data", '{"a": 1}extra', 8)
        result = _describe_json_error(e, '{"a": 1}extra')
        assert "Unexpected characters" in result

    def test_unknown_error_fallback(self):
        """Should fall back to original message for unknown errors."""
        e = json.JSONDecodeError("Some unknown error", '{"key": "value"}', 0)
        result = _describe_json_error(e, '{"key": "value"}')
        assert "unknown error" in result.lower()


class TestShowErrorContext:
    """Test _show_error_context function."""

    def test_shows_error_context(self):
        """Should show context around error position."""
        output = io.StringIO()
        input_str = '{"key": "value"}'
        error_pos = 3  # At 'k' in 'key'

        _show_error_context(input_str, error_pos, file=output)

        result = output.getvalue()
        assert "Input near error" in result
        assert "^--- here" in result

    def test_handles_start_of_string(self):
        """Should handle error at start of string."""
        output = io.StringIO()
        input_str = '{"key": "value"}'
        error_pos = 0

        _show_error_context(input_str, error_pos, file=output)

        result = output.getvalue()
        assert "^--- here" in result

    def test_handles_end_of_string(self):
        """Should handle error at end of string."""
        output = io.StringIO()
        input_str = '{"key": "value"}'
        error_pos = len(input_str) - 1

        _show_error_context(input_str, error_pos, file=output)

        result = output.getvalue()
        assert "^--- here" in result

    def test_truncates_long_input(self):
        """Should truncate long input with ellipsis."""
        output = io.StringIO()
        input_str = '{"key": "' + "x" * 100 + '"}'
        error_pos = 50

        _show_error_context(input_str, error_pos, file=output)

        result = output.getvalue()
        assert "..." in result
