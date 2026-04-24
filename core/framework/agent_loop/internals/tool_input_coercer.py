"""Generic coercion of LLM-emitted tool arguments to match each tool's JSON schema.

Small/mid-size models drift from tool schemas in predictable, boring ways:

- A number field comes back as a string (``"42"`` instead of ``42``).
- A boolean field comes back as a string (``"true"`` instead of ``True``).
- An array-of-string field comes back as an array of objects
  (``[{"label": "A"}, ...]`` instead of ``["A", ...]``).
- An array/object field comes back as a JSON-encoded string
  (``'["A","B"]'`` instead of ``["A", "B"]``).
- A lone scalar arrives where the schema expects an array.

This module centralizes the healing in one schema-driven pass that runs
on every tool call before dispatch. Coercion is conservative:

- Values that already match the expected type are untouched.
- Shapes we don't recognize are returned as-is, so real bugs surface
  instead of getting silently munged into something plausible.
- Every actual coercion is logged with the tool, property, and shape
  transition so we can see which models/tools are drifting.

Tool-specific prompt drift (e.g. ``</question>`` tags leaking into an
``ask_user`` prompt string) is NOT this module's job — that belongs in
per-tool sanitizers, because it's about prompt style, not schema shape.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from framework.llm.provider import Tool

logger = logging.getLogger(__name__)

# When an ``array<string>`` field arrives as an array of objects, look
# for a text-carrying field in preference order. Covers the wrappers
# small models tend to produce: ``[{"label": "A"}]``, ``[{"value": "A"}]``,
# ``[{"text": "A"}]``, etc.
_STRING_EXTRACT_KEYS: tuple[str, ...] = (
    "label",
    "value",
    "text",
    "name",
    "title",
    "display",
)


def coerce_tool_input(tool: Tool, raw_input: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce *raw_input* in place to match *tool*'s JSON schema.

    Returns the mutated input dict (same object as *raw_input* when
    possible, for callers that assume in-place mutation). Properties
    not present in the schema are left untouched.
    """
    if not isinstance(raw_input, dict):
        return raw_input or {}

    schema = tool.parameters or {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        return raw_input

    for key in list(raw_input.keys()):
        prop_schema = props.get(key)
        if not isinstance(prop_schema, dict):
            continue
        original = raw_input[key]
        coerced = _coerce(original, prop_schema)
        if coerced is not original:
            logger.info(
                "coerced tool input tool=%s prop=%s from=%s to=%s",
                tool.name,
                key,
                _shape(original),
                _shape(coerced),
            )
            raw_input[key] = coerced

    return raw_input


def _coerce(value: Any, schema: dict[str, Any]) -> Any:
    """Dispatch on the schema's ``type`` field.

    Returns the *same object* on passthrough so callers can detect
    no-ops via identity (``coerced is value``).
    """
    expected = schema.get("type")
    if not expected:
        return value

    # Union type: try each in order, return the first coercion that
    # actually changes the value. Falls back to the original.
    if isinstance(expected, list):
        for t in expected:
            sub_schema = {**schema, "type": t}
            coerced = _coerce(value, sub_schema)
            if coerced is not value:
                return coerced
        return value

    if expected == "integer":
        return _coerce_integer(value)
    if expected == "number":
        return _coerce_number(value)
    if expected == "boolean":
        return _coerce_boolean(value)
    if expected == "string":
        return _coerce_string(value)
    if expected == "array":
        return _coerce_array(value, schema)
    if expected == "object":
        return _coerce_object(value, schema)

    return value


def _coerce_integer(value: Any) -> Any:
    # bool is a subclass of int in Python; don't mistake True for 1 here.
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        parsed = _parse_number(value)
        if parsed is None:
            return value
        if parsed != int(parsed):
            # Has a fractional part — caller asked for int, don't truncate.
            return value
        return int(parsed)
    return value


def _coerce_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        parsed = _parse_number(value)
        if parsed is None:
            return value
        if parsed == int(parsed):
            return int(parsed)
        return parsed
    return value


def _coerce_boolean(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    return value


def _coerce_string(value: Any) -> Any:
    if isinstance(value, str):
        return value
    # Common drift: model sent ``{"label": "..."}`` when we wanted "...".
    if isinstance(value, dict):
        extracted = _extract_string_from_object(value)
        if extracted is not None:
            return extracted
    return value


def _coerce_array(value: Any, schema: dict[str, Any]) -> Any:
    # Heal: JSON-encoded array string → array.
    if isinstance(value, str):
        parsed = _try_parse_json(value)
        if isinstance(parsed, list):
            value = parsed
        else:
            # Scalar string where an array is expected — wrap it.
            return [value]
    elif not isinstance(value, list):
        # Any other scalar (int, bool, dict, ...) — wrap.
        return [value]

    items_schema = schema.get("items")
    if not isinstance(items_schema, dict):
        return value

    coerced_items: list[Any] = []
    changed = False
    for item in value:
        c = _coerce(item, items_schema)
        if c is not item:
            changed = True
        coerced_items.append(c)
    return coerced_items if changed else value


def _coerce_object(value: Any, schema: dict[str, Any]) -> Any:
    # Heal: JSON-encoded object string → object.
    if isinstance(value, str):
        parsed = _try_parse_json(value)
        if isinstance(parsed, dict):
            value = parsed
        else:
            return value
    if not isinstance(value, dict):
        return value

    sub_props = schema.get("properties")
    if not isinstance(sub_props, dict):
        return value

    changed = False
    for k in list(value.keys()):
        sub_schema = sub_props.get(k)
        if not isinstance(sub_schema, dict):
            continue
        original = value[k]
        coerced = _coerce(original, sub_schema)
        if coerced is not original:
            value[k] = coerced
            changed = True
    # Return the same dict on mutation so callers that passed a shared
    # reference see the updates. ``changed`` is only used to decide
    # whether we need to log at a coarser level upstream.
    return value if changed or not sub_props else value


def _extract_string_from_object(obj: dict[str, Any]) -> str | None:
    """Pick a likely-text field out of a wrapper object.

    Tries the known keys first, falls back to the sole value if the
    object has exactly one entry. Returns None when nothing plausible
    is found — the caller keeps the original.
    """
    for k in _STRING_EXTRACT_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v:
            return v
    if len(obj) == 1:
        (only,) = obj.values()
        if isinstance(only, str) and only:
            return only
    return None


def _try_parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _parse_number(raw: str) -> float | None:
    try:
        f = float(raw)
    except (ValueError, OverflowError):
        return None
    # Reject NaN and inf — they pass float() but aren't useful numeric
    # values for tool arguments.
    if f != f or f == float("inf") or f == float("-inf"):
        return None
    return f


def _shape(value: Any) -> str:
    """Short type/shape description used in coercion log lines."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return f"str[{len(value)}]"
    if isinstance(value, list):
        if not value:
            return "list[0]"
        return f"list[{len(value)}]<{_shape(value[0])}>"
    if isinstance(value, dict):
        keys = sorted(value.keys())[:3]
        suffix = ",…" if len(value) > 3 else ""
        return f"dict{{{','.join(keys)}{suffix}}}"
    return type(value).__name__
