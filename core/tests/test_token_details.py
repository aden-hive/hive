"""Tests for _extract_token_details() and its integration into LiteLLMProvider.

These tests exercise the helper in isolation and verify that every call site
in the provider (complete, complete_with_tools, acomplete, acomplete_with_tools,
stream) passes reasoning / cache_read / cache_creation tokens through to
LLMResponse / FinishEvent.

No real LiteLLM installation is required — all litellm calls are patched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.llm.litellm import LiteLLMProvider, _extract_token_details
from framework.llm.stream_events import FinishEvent

# Integration tests require litellm to be installed.
try:
    import litellm as _litellm_mod  # noqa: F401

    _LITELLM_AVAILABLE = True
except ImportError:
    _LITELLM_AVAILABLE = False

requires_litellm = pytest.mark.skipif(
    not _LITELLM_AVAILABLE, reason="litellm not installed"
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_usage(
    prompt: int = 10,
    completion: int = 5,
    reasoning: int | None = None,
    cache_read: int | None = None,
    cache_creation: int | None = None,
) -> MagicMock:
    """Build a mock LiteLLM Usage object with nested detail objects."""
    usage = MagicMock()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion

    # completion_tokens_details.reasoning_tokens
    completion_details = MagicMock()
    completion_details.reasoning_tokens = reasoning
    usage.completion_tokens_details = completion_details

    # prompt_tokens_details.cached_tokens / cache_creation_tokens
    prompt_details = MagicMock()
    prompt_details.cached_tokens = cache_read
    prompt_details.cache_creation_tokens = cache_creation
    usage.prompt_tokens_details = prompt_details

    return usage


def _make_response(usage: MagicMock | None = None, content: str = "ok") -> MagicMock:
    """Build a mock LiteLLM ModelResponse."""
    resp = MagicMock()
    resp.model = "claude-sonnet-4-6"
    resp.usage = usage
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    resp.choices[0].message.tool_calls = None
    return resp


# ─── _extract_token_details() unit tests ──────────────────────────────────────


class TestExtractTokenDetails:
    def test_none_usage_returns_zeros(self):
        assert _extract_token_details(None) == (0, 0, 0)

    def test_all_fields_present(self):
        usage = _make_usage(reasoning=100, cache_read=200, cache_creation=50)
        assert _extract_token_details(usage) == (100, 200, 50)

    def test_none_fields_become_zero(self):
        """Absent/None nested values default to 0."""
        usage = _make_usage(reasoning=None, cache_read=None, cache_creation=None)
        assert _extract_token_details(usage) == (0, 0, 0)

    def test_partial_fields(self):
        """Only reasoning present, cache fields absent."""
        usage = _make_usage(reasoning=42, cache_read=None, cache_creation=None)
        assert _extract_token_details(usage) == (42, 0, 0)

    def test_zero_values_preserved(self):
        usage = _make_usage(reasoning=0, cache_read=0, cache_creation=0)
        assert _extract_token_details(usage) == (0, 0, 0)

    def test_missing_completion_details_attribute(self):
        """usage.completion_tokens_details is None — no AttributeError."""
        usage = _make_usage()
        usage.completion_tokens_details = None
        r, cr, cc = _extract_token_details(usage)
        assert r == 0

    def test_missing_prompt_details_attribute(self):
        """usage.prompt_tokens_details is None — no AttributeError."""
        usage = _make_usage()
        usage.prompt_tokens_details = None
        r, cr, cc = _extract_token_details(usage)
        assert cr == 0
        assert cc == 0


# ─── complete() integration ───────────────────────────────────────────────────


@requires_litellm
class TestCompleteTokenDetails:
    @patch("litellm.completion")
    def test_reasoning_and_cache_tokens_propagated(self, mock_completion):
        usage = _make_usage(reasoning=150, cache_read=300, cache_creation=80)
        mock_completion.return_value = _make_response(usage=usage)

        provider = LiteLLMProvider(model="claude-sonnet-4-6", api_key="test")
        result = provider.complete(messages=[{"role": "user", "content": "hi"}])

        assert result.reasoning_tokens == 150
        assert result.cache_read_tokens == 300
        assert result.cache_creation_tokens == 80

    @patch("litellm.completion")
    def test_zero_when_no_token_details(self, mock_completion):
        """Standard response without reasoning/cache fields → all zeros."""
        usage = _make_usage(reasoning=None, cache_read=None, cache_creation=None)
        mock_completion.return_value = _make_response(usage=usage)

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test")
        result = provider.complete(messages=[{"role": "user", "content": "hi"}])

        assert result.reasoning_tokens == 0
        assert result.cache_read_tokens == 0
        assert result.cache_creation_tokens == 0


# ─── complete_with_tools() integration ────────────────────────────────────────


@requires_litellm
class TestCompleteWithToolsTokenDetails:
    @patch("litellm.completion")
    def test_single_iteration_tokens(self, mock_completion):
        """No tool calls — tokens extracted from the single response."""
        usage = _make_usage(reasoning=50, cache_read=100, cache_creation=25)
        mock_completion.return_value = _make_response(usage=usage)

        provider = LiteLLMProvider(model="claude-sonnet-4-6", api_key="test")
        result = provider.complete_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            system="",
            tools=[],
            tool_executor=lambda tu: None,
        )

        assert result.reasoning_tokens == 50
        assert result.cache_read_tokens == 100
        assert result.cache_creation_tokens == 25

    @patch("litellm.completion")
    def test_multi_iteration_tokens_accumulated(self, mock_completion):
        """Tokens from each tool-call iteration are summed."""
        # First call: triggers a tool call
        usage1 = _make_usage(
            prompt=10, completion=5, reasoning=30, cache_read=60, cache_creation=10
        )
        resp1 = MagicMock()
        resp1.model = "claude-sonnet-4-6"
        resp1.usage = usage1
        resp1.choices = [MagicMock()]
        resp1.choices[0].finish_reason = "tool_calls"
        tool_call = MagicMock()
        tool_call.id = "tc1"
        tool_call.function.name = "search"
        tool_call.function.arguments = '{"q": "test"}'
        resp1.choices[0].message.tool_calls = [tool_call]
        resp1.choices[0].message.content = None

        # Second call: final answer
        usage2 = _make_usage(
            prompt=20, completion=8, reasoning=70, cache_read=140, cache_creation=0
        )
        resp2 = _make_response(usage=usage2, content="final answer")

        mock_completion.side_effect = [resp1, resp2]

        from framework.llm.provider import ToolResult

        def executor(tu):
            return ToolResult(tool_use_id=tu.id, content="result")

        provider = LiteLLMProvider(model="claude-sonnet-4-6", api_key="test")
        from framework.llm.provider import Tool

        result = provider.complete_with_tools(
            messages=[{"role": "user", "content": "search"}],
            system="",
            tools=[Tool(name="search", description="search", parameters={})],
            tool_executor=executor,
        )

        assert result.reasoning_tokens == 100  # 30 + 70
        assert result.cache_read_tokens == 200  # 60 + 140
        assert result.cache_creation_tokens == 10  # 10 + 0


# ─── acomplete() integration ──────────────────────────────────────────────────


@requires_litellm
class TestACompleteTokenDetails:
    @pytest.mark.asyncio
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_reasoning_and_cache_tokens_propagated(self, mock_acompletion):
        usage = _make_usage(reasoning=200, cache_read=400, cache_creation=0)
        mock_acompletion.return_value = _make_response(usage=usage)

        provider = LiteLLMProvider(model="claude-sonnet-4-6", api_key="test")
        result = await provider.acomplete(messages=[{"role": "user", "content": "hi"}])

        assert result.reasoning_tokens == 200
        assert result.cache_read_tokens == 400
        assert result.cache_creation_tokens == 0


# ─── stream() integration ─────────────────────────────────────────────────────


@requires_litellm
class TestStreamTokenDetails:
    @pytest.mark.asyncio
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_finish_event_carries_token_details(self, mock_acompletion):
        """FinishEvent from stream() includes reasoning/cache token counts."""
        # Build a synthetic async chunk iterator
        finish_chunk = MagicMock()
        finish_chunk.choices = [MagicMock()]
        finish_chunk.choices[0].delta.content = None
        finish_chunk.choices[0].delta.tool_calls = None
        finish_chunk.choices[0].finish_reason = "stop"

        usage = _make_usage(prompt=15, completion=7, reasoning=90, cache_read=180, cache_creation=5)
        finish_chunk.usage = usage

        async def _chunks():
            yield finish_chunk

        mock_acompletion.return_value = _chunks()

        provider = LiteLLMProvider(model="claude-sonnet-4-6", api_key="test")
        events = []
        async for ev in provider.stream(messages=[{"role": "user", "content": "hi"}]):
            events.append(ev)

        finish_events = [e for e in events if isinstance(e, FinishEvent)]
        assert len(finish_events) == 1
        fe = finish_events[0]
        assert fe.input_tokens == 15
        assert fe.output_tokens == 7
        assert fe.reasoning_tokens == 90
        assert fe.cache_read_tokens == 180
        assert fe.cache_creation_tokens == 5

    @pytest.mark.asyncio
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_finish_event_zeros_when_no_details(self, mock_acompletion):
        """FinishEvent defaults to 0 for absent token detail fields."""
        finish_chunk = MagicMock()
        finish_chunk.choices = [MagicMock()]
        finish_chunk.choices[0].delta.content = None
        finish_chunk.choices[0].delta.tool_calls = None
        finish_chunk.choices[0].finish_reason = "stop"

        usage = _make_usage(reasoning=None, cache_read=None, cache_creation=None)
        finish_chunk.usage = usage

        async def _chunks():
            yield finish_chunk

        mock_acompletion.return_value = _chunks()

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test")
        events = []
        async for ev in provider.stream(messages=[{"role": "user", "content": "hi"}]):
            events.append(ev)

        finish_events = [e for e in events if isinstance(e, FinishEvent)]
        assert finish_events[0].reasoning_tokens == 0
        assert finish_events[0].cache_read_tokens == 0
        assert finish_events[0].cache_creation_tokens == 0
