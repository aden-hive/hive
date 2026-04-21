"""Tests for ``coerce_tool_input``.

The coercer centralizes healing for the small handful of schema-shape
drift patterns that non-frontier models emit. These tests pin the
expected behavior for each pattern plus the passthrough / failure cases.
"""

from __future__ import annotations

from framework.agent_loop.internals.tool_input_coercer import coerce_tool_input
from framework.llm.provider import Tool


def _tool(parameters: dict) -> Tool:
    return Tool(name="t", description="test", parameters=parameters)


# ---- passthrough / no-op cases ---------------------------------------------


def test_empty_input_passes_through() -> None:
    tool = _tool({"type": "object", "properties": {"x": {"type": "string"}}})
    assert coerce_tool_input(tool, {}) == {}
    assert coerce_tool_input(tool, None) == {}


def test_missing_schema_is_noop() -> None:
    tool = _tool({})
    args = {"anything": 123}
    assert coerce_tool_input(tool, args) is args


def test_unknown_property_is_untouched() -> None:
    tool = _tool({"type": "object", "properties": {"known": {"type": "integer"}}})
    args = {"unknown": "42"}
    coerce_tool_input(tool, args)
    assert args == {"unknown": "42"}  # untouched


def test_type_already_matches_is_noop() -> None:
    tool = _tool({"type": "object", "properties": {"n": {"type": "integer"}}})
    args = {"n": 42}
    coerce_tool_input(tool, args)
    assert args == {"n": 42}


# ---- primitive coercion (the reference implementation's scope) -------------


def test_string_to_integer() -> None:
    tool = _tool({"type": "object", "properties": {"n": {"type": "integer"}}})
    args = {"n": "42"}
    coerce_tool_input(tool, args)
    assert args == {"n": 42}


def test_string_to_integer_rejects_fractional() -> None:
    tool = _tool({"type": "object", "properties": {"n": {"type": "integer"}}})
    args = {"n": "3.14"}
    coerce_tool_input(tool, args)
    assert args == {"n": "3.14"}  # kept as string — schema says int


def test_string_to_number_float() -> None:
    tool = _tool({"type": "object", "properties": {"n": {"type": "number"}}})
    args = {"n": "3.14"}
    coerce_tool_input(tool, args)
    assert args == {"n": 3.14}


def test_string_to_number_whole() -> None:
    tool = _tool({"type": "object", "properties": {"n": {"type": "number"}}})
    args = {"n": "42"}
    coerce_tool_input(tool, args)
    assert args == {"n": 42}  # whole numbers collapse to int


def test_string_to_boolean() -> None:
    tool = _tool(
        {
            "type": "object",
            "properties": {
                "a": {"type": "boolean"},
                "b": {"type": "boolean"},
                "c": {"type": "boolean"},
            },
        }
    )
    args = {"a": "true", "b": "False", "c": "nope"}
    coerce_tool_input(tool, args)
    assert args == {"a": True, "b": False, "c": "nope"}


def test_union_type_first_match_wins() -> None:
    tool = _tool(
        {
            "type": "object",
            "properties": {"x": {"type": ["integer", "string"]}},
        }
    )
    args = {"x": "42"}
    coerce_tool_input(tool, args)
    assert args == {"x": 42}


def test_nan_and_inf_rejected() -> None:
    tool = _tool({"type": "object", "properties": {"n": {"type": "number"}}})
    args = {"n": "inf"}
    coerce_tool_input(tool, args)
    assert args == {"n": "inf"}  # inf not a valid tool arg — keep original


# ---- the ask_user bug: [{"label": "..."}] -> ["..."] ------------------------


def test_array_of_label_objects_unwraps_to_strings() -> None:
    tool = _tool(
        {
            "type": "object",
            "properties": {
                "options": {"type": "array", "items": {"type": "string"}},
            },
        }
    )
    args = {"options": [{"label": "A"}, {"label": "B"}, {"label": "C"}]}
    coerce_tool_input(tool, args)
    assert args == {"options": ["A", "B", "C"]}


def test_array_of_value_objects_unwraps() -> None:
    tool = _tool(
        {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "string"}}}}
    )
    args = {"xs": [{"value": "A"}, {"text": "B"}, {"name": "C"}]}
    coerce_tool_input(tool, args)
    assert args == {"xs": ["A", "B", "C"]}


def test_single_key_object_falls_back_to_sole_value() -> None:
    tool = _tool(
        {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "string"}}}}
    )
    args = {"xs": [{"weirdkey": "A"}]}
    coerce_tool_input(tool, args)
    assert args == {"xs": ["A"]}


def test_unrecognized_object_is_preserved() -> None:
    tool = _tool(
        {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "string"}}}}
    )
    args = {"xs": [{"a": "x", "b": "y"}]}  # ambiguous — no known key, multi-value
    coerce_tool_input(tool, args)
    assert args == {"xs": [{"a": "x", "b": "y"}]}  # untouched


# ---- JSON-encoded-string-as-array ------------------------------------------


def test_json_string_array_is_parsed() -> None:
    tool = _tool(
        {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "string"}}}}
    )
    args = {"xs": '["A","B","C"]'}
    coerce_tool_input(tool, args)
    assert args == {"xs": ["A", "B", "C"]}


def test_scalar_wraps_into_singleton_array() -> None:
    tool = _tool(
        {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "string"}}}}
    )
    args = {"xs": "solo"}
    coerce_tool_input(tool, args)
    assert args == {"xs": ["solo"]}


def test_invalid_json_string_wraps_as_singleton() -> None:
    tool = _tool(
        {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "string"}}}}
    )
    args = {"xs": "not json [[]"}
    coerce_tool_input(tool, args)
    assert args == {"xs": ["not json [[]"]}


# ---- nested: the actual ask_user schema shape -------------------------------


def test_nested_questions_array_with_wrapped_options() -> None:
    """Exercises the real bug — questions[i].options arriving as [{label}]."""
    tool = _tool(
        {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "prompt": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                }
            },
        }
    )
    args = {
        "questions": [
            {
                "id": "q1",
                "prompt": "Pick one",
                "options": [{"label": "Email (Recommended)"}, {"label": "Slack"}],
            },
            {"id": "q2", "prompt": "Free form"},
        ]
    }
    coerce_tool_input(tool, args)
    assert args["questions"][0]["options"] == ["Email (Recommended)", "Slack"]
    assert args["questions"][1] == {"id": "q2", "prompt": "Free form"}


def test_json_string_for_object_is_parsed() -> None:
    tool = _tool(
        {
            "type": "object",
            "properties": {
                "cfg": {
                    "type": "object",
                    "properties": {"n": {"type": "integer"}},
                }
            },
        }
    )
    args = {"cfg": '{"n": "42"}'}
    coerce_tool_input(tool, args)
    assert args == {"cfg": {"n": 42}}


# ---- string property receiving a {label} object -----------------------------


def test_single_string_property_unwraps_label_object() -> None:
    tool = _tool({"type": "object", "properties": {"choice": {"type": "string"}}})
    args = {"choice": {"label": "Email"}}
    coerce_tool_input(tool, args)
    assert args == {"choice": "Email"}
