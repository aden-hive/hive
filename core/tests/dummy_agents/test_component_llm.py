"""Component tests: LLM Provider — streaming, tool calling, token counting.

Exercises LiteLLMProvider directly with real API calls to verify the
provider layer works before any graph/executor logic is involved.
"""

from __future__ import annotations

import json

import pytest

from framework.llm.provider import LLMResponse, Tool
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent


@pytest.mark.asyncio
async def test_llm_acomplete_returns_content(llm_provider, artifact):
    """acomplete() should return a non-empty LLMResponse."""
    result = await llm_provider.acomplete(
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=16,
    )
    artifact.record_value(
        "result_type",
        type(result).__name__,
        expected="LLMResponse with non-empty content",
    )
    artifact.record_value("content", result.content)

    artifact.check(
        "result is LLMResponse",
        isinstance(result, LLMResponse),
        actual=type(result).__name__,
        expected_val="LLMResponse",
    )
    assert isinstance(result, LLMResponse)

    content_ok = result.content and result.content.strip()
    artifact.check(
        "content is non-empty",
        bool(content_ok),
        actual=repr(result.content),
        expected_val="non-empty string",
    )
    assert result.content and result.content.strip()


@pytest.mark.asyncio
async def test_llm_stream_yields_text_delta(llm_provider, artifact):
    """stream() should yield at least one TextDeltaEvent and a FinishEvent."""
    text_deltas = []
    finish_events = []
    async for event in llm_provider.stream(
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=16,
    ):
        if isinstance(event, TextDeltaEvent):
            text_deltas.append(event)
        elif isinstance(event, FinishEvent):
            finish_events.append(event)

    artifact.record_value(
        "text_delta_count",
        len(text_deltas),
        expected=">=1 TextDeltaEvent and exactly 1 FinishEvent",
    )
    artifact.record_value("finish_event_count", len(finish_events))

    artifact.check(
        "at least one TextDeltaEvent",
        len(text_deltas) >= 1,
        actual=str(len(text_deltas)),
        expected_val=">=1",
    )
    assert len(text_deltas) >= 1, "Expected at least one TextDeltaEvent"

    artifact.check(
        "exactly one FinishEvent",
        len(finish_events) == 1,
        actual=str(len(finish_events)),
        expected_val="1",
    )
    assert len(finish_events) == 1, "Expected exactly one FinishEvent"


@pytest.mark.asyncio
async def test_llm_stream_tool_call(llm_provider, artifact):
    """stream() with a tool definition should produce a ToolCallEvent."""
    tool = Tool(
        name="record_result",
        description="Record the final result string.",
        parameters={
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "The result to record.",
                },
            },
            "required": ["value"],
        },
    )
    events = []
    async for event in llm_provider.stream(
        messages=[
            {
                "role": "user",
                "content": (
                    "Call the record_result tool exactly once "
                    "with value='OK'. "
                    "Do not answer with plain text."
                ),
            }
        ],
        tools=[tool],
        max_tokens=64,
    ):
        events.append(event)

    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]

    artifact.record_value(
        "tool_call_count",
        len(tool_calls),
        expected=">=1 ToolCallEvent, tool_name='record_result'",
    )
    artifact.record_value(
        "tool_names",
        [tc.tool_name for tc in tool_calls],
    )

    artifact.check(
        "LLM called record_result",
        len(tool_calls) >= 1,
        actual=str(len(tool_calls)),
        expected_val=">=1",
    )
    assert len(tool_calls) >= 1, "LLM should have called record_result"

    artifact.check(
        "tool_name is record_result",
        tool_calls[0].tool_name == "record_result",
        actual=tool_calls[0].tool_name,
        expected_val="record_result",
    )
    assert tool_calls[0].tool_name == "record_result"


@pytest.mark.asyncio
async def test_llm_token_counts_populated(llm_provider, artifact):
    """LLMResponse should have positive input_tokens and output_tokens."""
    result = await llm_provider.acomplete(
        messages=[{"role": "user", "content": "Reply OK."}],
        max_tokens=16,
    )

    artifact.record_value(
        "input_tokens",
        result.input_tokens,
        expected="positive input_tokens and output_tokens",
    )
    artifact.record_value("output_tokens", result.output_tokens)

    artifact.check(
        "input_tokens positive",
        result.input_tokens > 0,
        actual=str(result.input_tokens),
        expected_val=">0",
    )
    assert result.input_tokens > 0, "input_tokens should be positive"

    artifact.check(
        "output_tokens positive",
        result.output_tokens > 0,
        actual=str(result.output_tokens),
        expected_val=">0",
    )
    assert result.output_tokens > 0, "output_tokens should be positive"


@pytest.mark.asyncio
async def test_llm_json_mode(llm_provider, artifact):
    """acomplete(json_mode=True) should return parseable JSON."""
    try:
        result = await llm_provider.acomplete(
            messages=[
                {
                    "role": "user",
                    "content": (
                        'Return a JSON object with key "status" '
                        'and value "ok". Output only valid JSON, '
                        "no other text."
                    ),
                }
            ],
            max_tokens=64,
            json_mode=True,
        )
    except Exception as e:
        pytest.skip(f"Provider does not support json_mode: {e}")

    content = (result.content or "").strip()
    if not content:
        pytest.skip("Provider returned empty content for json_mode request")

    artifact.record_value(
        "content",
        content,
        expected="parseable JSON dict with 'status' key",
    )

    parsed = json.loads(content)

    artifact.check(
        "parsed is dict",
        isinstance(parsed, dict),
        actual=type(parsed).__name__,
        expected_val="dict",
    )
    assert isinstance(parsed, dict)

    artifact.check(
        "'status' key present",
        "status" in parsed,
        actual=str(list(parsed.keys())),
        expected_val="contains 'status'",
    )
    assert "status" in parsed
