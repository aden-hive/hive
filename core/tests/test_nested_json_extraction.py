"""
Tests for nested JSON extraction using find_json_object().

Verifies that the proper JSON extraction function handles nested
structures correctly, unlike the simple regex r'\\{[^{}]*\\}'.
"""

import pytest
from framework.graph.node import find_json_object


class TestFindJsonObject:
    """Tests for find_json_object() function."""

    def test_simple_json(self):
        """Simple JSON without nesting should work."""
        text = '{"key": "value"}'
        result = find_json_object(text)
        assert result == '{"key": "value"}'

    def test_nested_json(self):
        """Nested JSON objects should be extracted correctly."""
        text = '{"outer": {"inner": "value"}}'
        result = find_json_object(text)
        assert result == '{"outer": {"inner": "value"}}'

    def test_deeply_nested_json(self):
        """Deeply nested JSON should work."""
        text = '{"a": {"b": {"c": {"d": "value"}}}}'
        result = find_json_object(text)
        assert result == '{"a": {"b": {"c": {"d": "value"}}}}'

    def test_json_with_braces_in_string(self):
        """Braces inside string values should not break extraction."""
        text = '{"message": "The output contains {data} here"}'
        result = find_json_object(text)
        assert result == '{"message": "The output contains {data} here"}'

    def test_json_with_prose_before(self):
        """JSON preceded by prose should be extracted."""
        text = 'Here is the result: {"proceed": true, "reason": "looks good"}'
        result = find_json_object(text)
        assert result == '{"proceed": true, "reason": "looks good"}'

    def test_json_with_prose_after(self):
        """JSON followed by prose should be extracted."""
        text = '{"proceed": true} Hope this helps!'
        result = find_json_object(text)
        assert result == '{"proceed": true}'

    def test_json_with_escaped_quotes(self):
        """Escaped quotes in strings should be handled."""
        text = '{"message": "He said \\"hello\\""}'
        result = find_json_object(text)
        assert result == '{"message": "He said \\"hello\\""}'

    def test_no_json_returns_none(self):
        """Text without JSON should return None."""
        text = 'This is just plain text'
        result = find_json_object(text)
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        result = find_json_object('')
        assert result is None

    def test_routing_response_with_nested_reasoning(self):
        """Real-world routing response with nested content."""
        text = '''Based on my analysis:
{"proceed": true, "reasoning": "The response contains valid data {id: 123}"}
Let me know if you need more details.'''
        result = find_json_object(text)
        assert result is not None
        import json
        data = json.loads(result)
        assert data["proceed"] is True
        assert "{id: 123}" in data["reasoning"]

    def test_capability_response_format(self):
        """Capability evaluation response format."""
        text = '{"level": "best_fit", "confidence": 0.95, "reasoning": "Agent handles {type: api} requests"}'
        result = find_json_object(text)
        assert result is not None
        import json
        data = json.loads(result)
        assert data["level"] == "best_fit"
        assert data["confidence"] == 0.95


class TestSimpleRegexFailsCases:
    """
    These tests demonstrate cases where the simple regex r'\\{[^{}]*\\}'
    would fail but find_json_object() succeeds.
    """

    def test_simple_regex_fails_nested(self):
        """Simple regex fails on nested JSON - find_json_object succeeds."""
        import re
        text = '{"outer": {"inner": "value"}}'

        # Simple regex fails (matches only first level)
        simple_match = re.search(r'\{[^{}]*\}', text)
        # It would match '{"inner": "value"}' not the full object

        # find_json_object succeeds
        result = find_json_object(text)
        assert result == text

    def test_simple_regex_fails_braces_in_string(self):
        """Simple regex fails with braces in string values."""
        import re
        text = '{"message": "Use {braces} here"}'

        # Simple regex would incorrectly match
        simple_match = re.search(r'\{[^{}]*\}', text)
        # It would match '{braces}' not the full object

        # find_json_object succeeds
        result = find_json_object(text)
        assert result == text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
