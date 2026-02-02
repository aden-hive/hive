"""Real-API streaming tests for LiteLLM provider.

Calls live LLM APIs and dumps stream events to JSON files for review.
Results are saved to core/tests/stream_event_dumps/{provider}_{model}_{scenario}.json

Run with:
    cd core && python -m pytest tests/test_litellm_streaming.py -v -s -k "RealAPI"

Requires API keys set in environment:
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY (or via credential store)
"""

import asyncio
import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import Tool
from framework.llm.stream_events import (
    FinishEvent,
    StreamEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)

DUMP_DIR = Path(__file__).parent / "stream_event_dumps"


def _serialize_event(index: int, event: StreamEvent) -> dict:
    """Serialize a StreamEvent to a JSON-safe dict."""
    d = asdict(event)  # type: ignore[arg-type]
    d["index"] = index
    # Move index to front for readability
    return {"index": index, **{k: v for k, v in d.items() if k != "index"}}


def _dump_events(events: list[StreamEvent], filename: str) -> Path:
    """Write stream events to a JSON file in the dump directory."""
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    filepath = DUMP_DIR / filename
    serialized = [_serialize_event(i, e) for i, e in enumerate(events)]
    filepath.write_text(json.dumps(serialized, indent=2) + "\n")
    logger.info(f"Dumped {len(events)} events to {filepath}")
    return filepath


async def _collect_stream(provider: LiteLLMProvider, **kwargs) -> list[StreamEvent]:
    """Collect all stream events from a provider.stream() call."""
    events: list[StreamEvent] = []
    async for event in provider.stream(**kwargs):
        events.append(event)
        # Log each event type as it arrives
        logger.debug(f"  [{len(events) - 1}] {event.type}: {event}")
    return events


# ---------------------------------------------------------------------------
# Test matrix: (model_id, dump_prefix, env_var_for_skip)
# ---------------------------------------------------------------------------
MODELS = [
    (
        "anthropic/claude-haiku-4-5-20251001",
        "anthropic_claude-haiku-4-5-20251001",
        "ANTHROPIC_API_KEY",
    ),
    ("gpt-4.1-nano", "gpt-4.1-nano", "OPENAI_API_KEY"),
    ("gemini/gemini-2.0-flash", "gemini_gemini-2.0-flash", "GEMINI_API_KEY"),
]

WEATHER_TOOL = Tool(
    name="get_weather",
    description="Get the current weather for a city.",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name, e.g. 'Tokyo'",
            }
        },
        "required": ["city"],
    },
)

SEARCH_TOOL = Tool(
    name="web_search",
    description="Search the web for information.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (1-10)",
            },
        },
        "required": ["query"],
    },
)

CALCULATOR_TOOL = Tool(
    name="calculator",
    description="Perform arithmetic calculations.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Math expression to evaluate, e.g. '2 + 2'",
            }
        },
        "required": ["expression"],
    },
)


def _has_api_key(env_var: str) -> bool:
    """Check if an API key is available (env var or credential store)."""
    if os.environ.get(env_var):
        return True
    # Try credential store
    try:
        from aden_tools.credentials import CredentialStoreAdapter

        creds = CredentialStoreAdapter.with_env_storage()
        provider_name = env_var.replace("_API_KEY", "").lower()
        return creds.is_available(provider_name)
    except (ImportError, Exception):
        return False


# ---------------------------------------------------------------------------
# Real API tests — text streaming
# ---------------------------------------------------------------------------
class TestRealAPITextStreaming:
    """Stream a simple text response from each provider and dump events."""

    @pytest.mark.parametrize("model,prefix,env_var", MODELS, ids=[m[1] for m in MODELS])
    @pytest.mark.asyncio
    async def test_text_stream(self, model: str, prefix: str, env_var: str):
        """Stream a multi-paragraph response to exercise chunked delivery."""
        if not _has_api_key(env_var):
            pytest.skip(f"{env_var} not set")

        provider = LiteLLMProvider(model=model)
        events = await _collect_stream(
            provider,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Explain in 3 numbered paragraphs how a CPU executes an instruction. "
                        "Cover fetch, decode, and execute stages. Be concise but thorough."
                    ),
                }
            ],
            system="You are a computer science teacher. Give clear, structured explanations.",
            max_tokens=512,
        )

        # Dump to file
        _dump_events(events, f"{prefix}_text.json")

        # Basic structural assertions
        assert len(events) >= 4, f"Expected at least 4 events, got {len(events)}"

        # Must have multiple text deltas for a longer response
        text_deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        assert len(text_deltas) >= 3, f"Expected 3+ TextDeltaEvents, got {len(text_deltas)}"

        # Snapshot must accumulate monotonically
        for i in range(1, len(text_deltas)):
            assert len(text_deltas[i].snapshot) > len(text_deltas[i - 1].snapshot), (
                f"Snapshot did not grow at index {i}"
            )

        # Must end with TextEndEvent then FinishEvent
        text_ends = [e for e in events if isinstance(e, TextEndEvent)]
        assert len(text_ends) == 1, f"Expected 1 TextEndEvent, got {len(text_ends)}"

        finish_events = [e for e in events if isinstance(e, FinishEvent)]
        assert len(finish_events) == 1, f"Expected 1 FinishEvent, got {len(finish_events)}"
        assert finish_events[0].stop_reason in ("stop", "end_turn")

        # TextEndEvent.full_text should match last snapshot
        assert text_ends[0].full_text == text_deltas[-1].snapshot

        # Response should actually contain multi-paragraph content
        full_text = text_ends[0].full_text
        assert len(full_text) > 200, f"Response too short ({len(full_text)} chars)"


# ---------------------------------------------------------------------------
# Real API tests — tool call streaming
# ---------------------------------------------------------------------------
class TestRealAPIToolCallStreaming:
    """Stream a tool call response from each provider and dump events."""

    @pytest.mark.parametrize("model,prefix,env_var", MODELS, ids=[m[1] for m in MODELS])
    @pytest.mark.asyncio
    async def test_tool_call_stream(self, model: str, prefix: str, env_var: str):
        """Stream a single tool call with complex arguments."""
        if not _has_api_key(env_var):
            pytest.skip(f"{env_var} not set")

        provider = LiteLLMProvider(model=model)
        events = await _collect_stream(
            provider,
            messages=[
                {
                    "role": "user",
                    "content": "Search the web for 'Python 3.13 release notes'.",
                }
            ],
            system="You have access to tools. Use the appropriate tool.",
            tools=[WEATHER_TOOL, SEARCH_TOOL, CALCULATOR_TOOL],
            max_tokens=512,
        )

        # Dump to file
        _dump_events(events, f"{prefix}_tool_call.json")

        # Basic structural assertions
        assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}"

        # Must have a tool call event
        tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
        assert len(tool_calls) >= 1, "No ToolCallEvent received"

        tc = tool_calls[0]
        assert tc.tool_name == "web_search"
        assert "query" in tc.tool_input
        assert tc.tool_use_id != ""

        # Must end with FinishEvent
        finish_events = [e for e in events if isinstance(e, FinishEvent)]
        assert len(finish_events) == 1
        assert finish_events[0].stop_reason in ("tool_calls", "tool_use", "stop")

    @pytest.mark.parametrize("model,prefix,env_var", MODELS, ids=[m[1] for m in MODELS])
    @pytest.mark.asyncio
    async def test_multi_tool_call_stream(self, model: str, prefix: str, env_var: str):
        """Stream a response that should invoke multiple tool calls."""
        if not _has_api_key(env_var):
            pytest.skip(f"{env_var} not set")

        provider = LiteLLMProvider(model=model)
        events = await _collect_stream(
            provider,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "I need three things done in parallel: "
                        "1) Get the weather in London, "
                        "2) Get the weather in New York, "
                        "3) Calculate 1337 * 42. "
                        "Use the tools for all three."
                    ),
                }
            ],
            system=(
                "You have access to tools. When the user asks for multiple things, "
                "call all the needed tools. Always use tools, never guess results."
            ),
            tools=[WEATHER_TOOL, SEARCH_TOOL, CALCULATOR_TOOL],
            max_tokens=512,
        )

        # Dump to file
        _dump_events(events, f"{prefix}_multi_tool.json")

        # Must have multiple tool call events
        tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
        assert len(tool_calls) >= 2, (
            f"Expected 2+ ToolCallEvents for parallel requests, got {len(tool_calls)}"
        )

        # Verify tool names used
        tool_names = {tc.tool_name for tc in tool_calls}
        assert "get_weather" in tool_names, "Expected get_weather tool call"

        # All tool calls should have non-empty IDs
        for tc in tool_calls:
            assert tc.tool_use_id != "", f"Empty tool_use_id on {tc.tool_name}"
            assert tc.tool_input, f"Empty tool_input on {tc.tool_name}"

        # Must end with FinishEvent
        finish_events = [e for e in events if isinstance(e, FinishEvent)]
        assert len(finish_events) == 1


# ---------------------------------------------------------------------------
# Convenience runner for manual invocation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    """Run all streaming tests and dump results. Usage: python tests/test_litellm_streaming.py"""

    ALL_TOOLS = [WEATHER_TOOL, SEARCH_TOOL, CALCULATOR_TOOL]

    async def _run_all():
        for model, prefix, env_var in MODELS:
            if not _has_api_key(env_var):
                print(f"SKIP {prefix}: {env_var} not set")
                continue

            provider = LiteLLMProvider(model=model)

            # Text streaming (multi-paragraph)
            print(f"\n--- {prefix} text ---")
            events = await _collect_stream(
                provider,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Explain in 3 numbered paragraphs how a CPU executes an instruction. "
                            "Cover fetch, decode, and execute stages. Be concise but thorough."
                        ),
                    }
                ],
                system="You are a computer science teacher. Give clear, structured explanations.",
                max_tokens=512,
            )
            path = _dump_events(events, f"{prefix}_text.json")
            print(f"  {len(events)} events -> {path}")
            for i, e in enumerate(events):
                print(f"  [{i}] {e.type}: {e}")

            # Tool call streaming
            print(f"\n--- {prefix} tool_call ---")
            events = await _collect_stream(
                provider,
                messages=[
                    {
                        "role": "user",
                        "content": "Search the web for 'Python 3.13 release notes'.",
                    }
                ],
                system="You have access to tools. Use the appropriate tool.",
                tools=ALL_TOOLS,
                max_tokens=512,
            )
            path = _dump_events(events, f"{prefix}_tool_call.json")
            print(f"  {len(events)} events -> {path}")
            for i, e in enumerate(events):
                print(f"  [{i}] {e.type}: {e}")

            # Multi-tool call streaming
            print(f"\n--- {prefix} multi_tool ---")
            events = await _collect_stream(
                provider,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "I need three things done in parallel: "
                            "1) Get the weather in London, "
                            "2) Get the weather in New York, "
                            "3) Calculate 1337 * 42. "
                            "Use the tools for all three."
                        ),
                    }
                ],
                system=(
                    "You have access to tools. When the user asks for multiple things, "
                    "call all the needed tools. Always use tools, never guess results."
                ),
                tools=ALL_TOOLS,
                max_tokens=512,
            )
            path = _dump_events(events, f"{prefix}_multi_tool.json")
            print(f"  {len(events)} events -> {path}")
            for i, e in enumerate(events):
                print(f"  [{i}] {e.type}: {e}")

    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(_run_all())
