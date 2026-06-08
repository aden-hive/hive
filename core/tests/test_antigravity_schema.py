"""Tests for the Antigravity Gemini schema sanitizer.

Run with:
    cd core
    pytest tests/test_antigravity_schema.py -v
"""

import pytest

from framework.llm.antigravity import _sanitize_schema_for_gemini


def test_union_with_null_becomes_nullable():
    assert _sanitize_schema_for_gemini({"type": ["string", "null"]}) == {
        "type": "string",
        "nullable": True,
    }


def test_plain_schema_passthrough():
    assert _sanitize_schema_for_gemini({"type": "string"}) == {"type": "string"}


def test_recurses_into_properties():
    out = _sanitize_schema_for_gemini(
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "owner": {"type": ["string", "null"]},
            },
            "required": ["id"],
        }
    )
    assert out["properties"]["id"] == {"type": "integer"}
    assert out["properties"]["owner"] == {"type": "string", "nullable": True}
    assert out["required"] == ["id"]


def test_recurses_into_items():
    assert _sanitize_schema_for_gemini({"type": "array", "items": {"type": ["integer", "null"]}}) == {
        "type": "array",
        "items": {"type": "integer", "nullable": True},
    }


def test_recurses_into_combinators():
    assert _sanitize_schema_for_gemini({"anyOf": [{"type": ["string", "null"]}, {"type": "integer"}]}) == {
        "anyOf": [{"type": "string", "nullable": True}, {"type": "integer"}]
    }


def test_does_not_mutate_input():
    schema = {"type": "object", "properties": {"x": {"type": ["string", "null"]}}}
    snapshot = {"type": "object", "properties": {"x": {"type": ["string", "null"]}}}
    _sanitize_schema_for_gemini(schema)
    assert schema == snapshot


def test_pure_null_type_falls_back_to_string():
    assert _sanitize_schema_for_gemini({"type": ["null"]}) == {
        "type": "string",
        "nullable": True,
    }


def test_multi_type_non_null_union_raises():
    """Silently picking one type would change the contract; fail loud instead."""
    with pytest.raises(ValueError, match="Unsupported Gemini schema union"):
        _sanitize_schema_for_gemini({"type": ["string", "integer", "null"]})

    with pytest.raises(ValueError, match="Unsupported Gemini schema union"):
        _sanitize_schema_for_gemini({"type": ["string", "integer"]})
