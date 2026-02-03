"""Tests for JSON utility functions.

Run with:
    cd core
    pytest tests/test_json_utils.py -v
"""

import pytest
from framework.utils import extract_json, find_json_object, strip_code_blocks


class TestJsonExtraction:
    """Test extract_json JSON extraction without LLM calls."""

    def test_clean_json(self):
        """Test parsing clean JSON directly."""
        result = extract_json('{"key": "value"}', ["key"])
        assert result == {"key": "value"}

    def test_json_with_whitespace(self):
        """Test parsing JSON with surrounding whitespace."""
        result = extract_json('  {"key": "value"}  \n', ["key"])
        assert result == {"key": "value"}

    def test_markdown_code_block_at_start(self):
        """Test extracting JSON from markdown code block at start."""
        input_text = '```json\n{"key": "value"}\n```'
        result = extract_json(input_text, ["key"])
        assert result == {"key": "value"}

    def test_markdown_code_block_without_json_label(self):
        """Test extracting JSON from markdown code block without 'json' label."""
        input_text = '```\n{"key": "value"}\n```'
        result = extract_json(input_text, ["key"])
        assert result == {"key": "value"}

    def test_prose_around_markdown_block(self):
        """Test extracting JSON when prose surrounds the markdown block."""
        input_text = 'Here is the result:\n```json\n{"key": "value"}\n```\nHope this helps!'
        result = extract_json(input_text, ["key"])
        assert result == {"key": "value"}

    def test_json_embedded_in_prose(self):
        """Test extracting JSON embedded in prose text."""
        input_text = 'The answer is {"key": "value"} as requested.'
        result = extract_json(input_text, ["key"])
        assert result == {"key": "value"}

    def test_nested_json(self):
        """Test parsing nested JSON objects."""
        input_text = '{"outer": {"inner": "value"}}'
        result = extract_json(input_text, ["outer"])
        assert result == {"outer": {"inner": "value"}}

    def test_deeply_nested_json(self):
        """Test parsing deeply nested JSON objects."""
        input_text = '{"a": {"b": {"c": {"d": "deep"}}}}'
        result = extract_json(input_text, ["a"])
        assert result == {"a": {"b": {"c": {"d": "deep"}}}}

    def test_json_with_array(self):
        """Test parsing JSON with array values."""
        input_text = '{"items": [1, 2, 3]}'
        result = extract_json(input_text, ["items"])
        assert result == {"items": [1, 2, 3]}

    def test_json_with_string_containing_braces(self):
        """Test parsing JSON where string values contain braces."""
        input_text = '{"code": "function() { return 1; }"}'
        result = extract_json(input_text, ["code"])
        assert result == {"code": "function() { return 1; }"}

    def test_json_with_escaped_quotes(self):
        """Test parsing JSON with escaped quotes in strings."""
        input_text = '{"message": "He said \\"hello\\""}'
        result = extract_json(input_text, ["message"])
        assert result == {"message": 'He said "hello"'}

    def test_multiple_json_objects_takes_first(self):
        """Test that when multiple JSON objects exist, first is taken."""
        input_text = '{"first": 1} and then {"second": 2}'
        result = extract_json(input_text, ["first"])
        assert result == {"first": 1}

    def test_json_with_boolean_and_null(self):
        """Test parsing JSON with boolean and null values."""
        input_text = '{"active": true, "deleted": false, "data": null}'
        result = extract_json(input_text, ["active", "deleted", "data"])
        assert result == {"active": True, "deleted": False, "data": None}

    def test_json_with_numbers(self):
        """Test parsing JSON with integer and float values."""
        input_text = '{"count": 42, "price": 19.99}'
        result = extract_json(input_text, ["count", "price"])
        assert result == {"count": 42, "price": 19.99}


class TestStripCodeBlocks:
    """Test strip_code_blocks utility."""

    def test_strip_json_block(self):
        assert strip_code_blocks('```json\n{"a":1}\n```') == '{"a":1}'

    def test_strip_generic_block(self):
        assert strip_code_blocks('```\n{"a":1}\n```') == '{"a":1}'

    def test_strip_no_block(self):
        assert strip_code_blocks('{"a":1}') == '{"a":1}'

    def test_strip_surrounding_whitespace(self):
        assert strip_code_blocks('  {"a":1}  ') == '{"a":1}'
