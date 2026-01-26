import pytest
from framework.llm.json_utils import extract_json_object

"""
Unit tests for JSON extraction utilities.

Hive often relies on structured JSON outputs from LLM responses
(for routing, orchestration, HITL parsing, and capability evaluation).

Previously, JSON was extracted using regex, which fails on nested objects.

These tests ensure that `extract_json_object()` correctly handles:
- simple JSON objects
- nested JSON structures
- invalid/missing JSON responses
"""


def test_extract_simple_json():
    text = '{"proceed": true}'
    assert extract_json_object(text)["proceed"] is True


def test_extract_nested_json():
    text = """
    Here is your result:
    {
        "selected": ["support"],
        "meta": {
            "confidence": 0.92,
            "reason": "nested works"
        }
    }
    """

    data = extract_json_object(text)
    assert data["meta"]["confidence"] == 0.92


def test_extract_invalid_json():
    text = "No JSON here"
    with pytest.raises(ValueError):
        extract_json_object(text)
