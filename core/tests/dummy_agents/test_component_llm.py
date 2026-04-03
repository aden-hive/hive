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
async def test_llm_acomplete_returns_content(llm_provider):
    """acomplete() should return a non-empty LLMResponse."""
    result = await llm_provider.acomplete(
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=16,
    )
    assert isinstance(result, LLMResponse)
    assert result.content and result.content.strip()


@pytest.mark.asyncio
async def test_llm_stream_yields_text_delta(llm_provider):
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

    assert len(text_deltas) >= 1, "Expected at least one TextDeltaEvent"
    assert len(finish_events) == 1, "Expected exactly one FinishEvent"


@pytest.mark.asyncio
async def test_llm_stream_tool_call(llm_provider):
    """stream() with a tool definition should produce a ToolCallEvent."""
    tool = Tool(
        name="record_result",
        description="Record the final result string.",
        parameters={
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "The result to record."},
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
                    "Call the record_result tool exactly once with value='OK'. "
                    "Do not answer with plain text."
                ),
            }
        ],
        tools=[tool],
        max_tokens=64,
    ):
        events.append(event)

    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) >= 1, "LLM should have called record_result"
    assert tool_calls[0].tool_name == "record_result"


@pytest.mark.asyncio
async def test_llm_token_counts_populated(llm_provider):
    """LLMResponse should have positive input_tokens and output_tokens."""
    result = await llm_provider.acomplete(
        messages=[{"role": "user", "content": "Reply OK."}],
        max_tokens=16,
    )
    assert result.input_tokens > 0, "input_tokens should be positive"
    assert result.output_tokens > 0, "output_tokens should be positive"


@pytest.mark.asyncio
async def test_llm_json_mode(llm_provider):
    """acomplete(json_mode=True) should return parseable JSON when supported."""
    try:
        result = await llm_provider.acomplete(
            messages=[
                {
                    "role": "user",
                    "content": 'Return a JSON object with key "status" and value "ok". Output only valid JSON, no other text.',
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

    parsed = json.loads(content)
    assert isinstance(parsed, dict)
    assert "status" in parsed
