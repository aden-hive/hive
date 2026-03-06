"""Tests for _heuristic_repair improvements in OutputCleaner."""

import pytest

from framework.graph.output_cleaner import _heuristic_repair


class TestMarkdownStripping:
    """Test markdown code block removal."""

    def test_json_in_markdown_block(self):
        text = '```json\n{"key": "value"}\n```'
        assert _heuristic_repair(text) == {"key": "value"}

    def test_json_in_plain_markdown_block(self):
        text = '```\n{"key": "value"}\n```'
        assert _heuristic_repair(text) == {"key": "value"}


class TestPythonConstants:
    """Test Python constant substitution."""

    def test_python_booleans(self):
        text = '{"active": True, "deleted": False}'
        assert _heuristic_repair(text) == {"active": True, "deleted": False}

    def test_python_none(self):
        text = '{"value": None}'
        assert _heuristic_repair(text) == {"value": None}


class TestTrailingCommas:
    """Test trailing comma removal."""

    def test_trailing_comma_in_object(self):
        text = '{"key": "value", "key2": "value2",}'
        result = _heuristic_repair(text)
        assert result == {"key": "value", "key2": "value2"}

    def test_trailing_comma_in_array(self):
        text = '["a", "b", "c",]'
        result = _heuristic_repair(text)
        assert result == ["a", "b", "c"]

    def test_trailing_comma_with_whitespace(self):
        text = '{"key": "value" ,  }'
        result = _heuristic_repair(text)
        assert result == {"key": "value"}

    def test_nested_trailing_commas(self):
        text = '{"outer": {"inner": "value",},}'
        result = _heuristic_repair(text)
        assert result == {"outer": {"inner": "value"}}


class TestTruncatedJSON:
    """Test truncated JSON recovery."""

    def test_truncated_object_missing_closing_brace(self):
        text = '{"key": "value", "key2": "value2"'
        result = _heuristic_repair(text)
        assert result == {"key": "value", "key2": "value2"}

    def test_truncated_nested_object(self):
        text = '{"outer": {"inner": "value"}'
        result = _heuristic_repair(text)
        assert result == {"outer": {"inner": "value"}}

    def test_truncated_array(self):
        text = '["a", "b", "c"'
        result = _heuristic_repair(text)
        assert result == ["a", "b", "c"]

    def test_truncated_with_trailing_comma(self):
        text = '{"key": "value",'
        result = _heuristic_repair(text)
        assert result == {"key": "value"}

    def test_deeply_nested_truncation(self):
        text = '{"a": {"b": {"c": "deep"'
        result = _heuristic_repair(text)
        assert result == {"a": {"b": {"c": "deep"}}}


class TestControlCharacters:
    """Test unescaped control character fixing."""

    def test_unescaped_newline_in_string(self):
        text = '{"text": "line1\nline2"}'
        result = _heuristic_repair(text)
        assert result is not None
        assert result["text"] == "line1\nline2"

    def test_unescaped_tab_in_string(self):
        text = '{"text": "col1\tcol2"}'
        result = _heuristic_repair(text)
        assert result is not None
        assert result["text"] == "col1\tcol2"


class TestSingleQuotes:
    """Test single quote to double quote conversion."""

    def test_single_quoted_keys_and_values(self):
        text = "{'key': 'value'}"
        result = _heuristic_repair(text)
        assert result == {"key": "value"}


class TestEdgeCases:
    """Test edge cases and non-JSON inputs."""

    def test_none_input(self):
        assert _heuristic_repair(None) is None

    def test_empty_string(self):
        assert _heuristic_repair("") is None

    def test_plain_text(self):
        assert _heuristic_repair("not json at all") is None

    def test_valid_json_passthrough(self):
        text = '{"already": "valid"}'
        assert _heuristic_repair(text) == {"already": "valid"}

    def test_json_surrounded_by_text(self):
        text = 'Here is the result: {"key": "value"} as requested.'
        result = _heuristic_repair(text)
        assert result == {"key": "value"}

    def test_integer_input(self):
        assert _heuristic_repair(42) is None
