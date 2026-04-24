"""Tests for LiteLLM provider.

Run with:
    cd core
    uv pip install litellm pytest
    pytest tests/test_litellm_provider.py -v

For live tests (requires API keys):
    OPENAI_API_KEY=sk-... pytest tests/test_litellm_provider.py -v -m live
"""

import asyncio
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.config import get_llm_extra_kwargs
from framework.llm.anthropic import AnthropicProvider
from framework.llm.litellm import (
    OPENROUTER_TOOL_COMPAT_MODEL_CACHE,
    LiteLLMProvider,
    _build_system_message,
    _compute_retry_delay,
    _cost_from_tokens,
    _ensure_ollama_chat_prefix,
    _extract_cache_tokens,
    _extract_cost,
    _is_ollama_model,
    _model_supports_cache_control,
    _summarize_request_for_log,
)
from framework.llm.provider import LLMProvider, LLMResponse, Tool


class TestLiteLLMProviderInit:
    """Test LiteLLMProvider initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            provider = LiteLLMProvider()
            assert provider.model == "gpt-4o-mini"
            assert provider.api_key is None
            assert provider.api_base is None

    def test_init_with_custom_model(self):
        """Test initialization with custom model."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            provider = LiteLLMProvider(model="claude-3-haiku-20240307")
            assert provider.model == "claude-3-haiku-20240307"

    def test_init_deepseek_model(self):
        """Test initialization with DeepSeek model."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            provider = LiteLLMProvider(model="deepseek/deepseek-chat")
            assert provider.model == "deepseek/deepseek-chat"

    def test_init_with_api_key(self):
        """Test initialization with explicit API key."""
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="my-api-key")
        assert provider.api_key == "my-api-key"

    def test_init_with_api_base(self):
        """Test initialization with custom API base."""
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="my-key", api_base="https://my-proxy.com/v1")
        assert provider.api_base == "https://my-proxy.com/v1"

    def test_init_minimax_defaults_api_base(self):
        """MiniMax should default to the official OpenAI-compatible endpoint."""
        provider = LiteLLMProvider(model="minimax/MiniMax-M2.1", api_key="my-key")
        assert provider.api_base == "https://api.minimax.io/v1"

    def test_init_minimax_keeps_custom_api_base(self):
        """Explicit api_base should win over MiniMax defaults."""
        provider = LiteLLMProvider(
            model="minimax/MiniMax-M2.1",
            api_key="my-key",
            api_base="https://proxy.example/v1",
        )
        assert provider.api_base == "https://proxy.example/v1"

    def test_init_openrouter_defaults_api_base(self):
        """OpenRouter should default to the official OpenAI-compatible endpoint."""
        provider = LiteLLMProvider(model="openrouter/x-ai/grok-4.20-beta", api_key="my-key")
        assert provider.api_base == "https://openrouter.ai/api/v1"

    def test_init_openrouter_keeps_custom_api_base(self):
        """Explicit api_base should win over OpenRouter defaults."""
        provider = LiteLLMProvider(
            model="openrouter/x-ai/grok-4.20-beta",
            api_key="my-key",
            api_base="https://proxy.example/v1",
        )
        assert provider.api_base == "https://proxy.example/v1"

    def test_init_ollama_no_key_needed(self):
        """Test that Ollama models don't require API key."""
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise; ollama/ is normalised to ollama_chat/ for tool-call support.
            provider = LiteLLMProvider(model="ollama/llama3")
            assert provider.model == "ollama_chat/llama3"

    def test_summarize_request_flags_system_only_payload(self):
        """Request summaries should make system-only payloads obvious in logs."""
        summary = _summarize_request_for_log(
            {
                "model": "openai/glm-5",
                "api_base": "https://api.z.ai/api/coding/paas/v4",
                "messages": [{"role": "system", "content": "You are helpful."}],
                "tools": [{"type": "function", "function": {"name": "read_file"}}],
                "stream": True,
                "max_tokens": 8192,
            }
        )

        assert summary["message_count"] == 1
        assert summary["non_system_message_count"] == 0
        assert summary["first_non_system_role"] is None
        assert summary["last_non_system_role"] is None
        assert summary["system_only"] is True


class TestLiteLLMProviderComplete:
    """Test LiteLLMProvider.complete() method."""

    @patch("litellm.completion")
    def test_complete_basic(self, mock_completion):
        """Test basic completion call."""
        # Mock response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello! I'm an AI assistant."
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_completion.return_value = mock_response

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")
        result = provider.complete(messages=[{"role": "user", "content": "Hello"}])

        assert result.content == "Hello! I'm an AI assistant."
        assert result.model == "gpt-4o-mini"
        assert result.input_tokens == 10
        assert result.output_tokens == 20
        assert result.stop_reason == "stop"

        # Verify litellm.completion was called correctly
        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["api_key"] == "test-key"

    @patch("litellm.completion")
    def test_complete_with_system_prompt(self, mock_completion):
        """Test completion with system prompt."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 15
        mock_response.usage.completion_tokens = 5
        mock_completion.return_value = mock_response

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")
        provider.complete(messages=[{"role": "user", "content": "Hello"}], system="You are a helpful assistant.")

        call_kwargs = mock_completion.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."

    @patch("litellm.completion")
    def test_complete_with_tools(self, mock_completion):
        """Test completion with tools."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 20
        mock_response.usage.completion_tokens = 10
        mock_completion.return_value = mock_response

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

        tools = [
            Tool(
                name="get_weather",
                description="Get the weather for a location",
                parameters={
                    "properties": {"location": {"type": "string", "description": "City name"}},
                    "required": ["location"],
                },
            )
        ]

        provider.complete(messages=[{"role": "user", "content": "What's the weather?"}], tools=tools)

        call_kwargs = mock_completion.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["type"] == "function"
        assert call_kwargs["tools"][0]["function"]["name"] == "get_weather"


class TestToolConversion:
    """Test tool format conversion."""

    def test_tool_to_openai_format(self):
        """Test converting Tool to OpenAI format."""
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

        tool = Tool(
            name="search",
            description="Search the web",
            parameters={
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        )

        result = provider._tool_to_openai_format(tool)

        assert result["type"] == "function"
        assert result["function"]["name"] == "search"
        assert result["function"]["description"] == "Search the web"
        assert result["function"]["parameters"]["properties"]["query"]["type"] == "string"
        assert result["function"]["parameters"]["required"] == ["query"]

    def test_parse_tool_call_arguments_repairs_truncated_json(self):
        """Truncated JSON fragments should be repaired into valid tool inputs."""
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

        parsed = provider._parse_tool_call_arguments(
            (
                '{"question":"What story structure should the agent use?",'
                '"options":["3-act structure","Beginning-Middle-End","Random paragraph"'
            ),
            "ask_user",
        )

        assert parsed == {
            "question": "What story structure should the agent use?",
            "options": [
                "3-act structure",
                "Beginning-Middle-End",
                "Random paragraph",
            ],
        }

    def test_parse_tool_call_arguments_raises_when_unrepairable(self):
        """Completely invalid JSON should fail fast instead of producing _raw loops."""
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

        with pytest.raises(ValueError, match="Failed to parse tool call arguments"):
            provider._parse_tool_call_arguments('{"question": foo', "ask_user")


class TestAnthropicProviderBackwardCompatibility:
    """Test AnthropicProvider backward compatibility with LiteLLM backend."""

    def test_anthropic_provider_is_llm_provider(self):
        """Test that AnthropicProvider implements LLMProvider interface."""
        provider = AnthropicProvider(api_key="test-key")
        assert isinstance(provider, LLMProvider)

    def test_anthropic_provider_init_defaults(self):
        """Test AnthropicProvider initialization with defaults."""
        provider = AnthropicProvider(api_key="test-key")
        assert provider.model == "claude-haiku-4-5-20251001"
        assert provider.api_key == "test-key"

    def test_anthropic_provider_init_custom_model(self):
        """Test AnthropicProvider initialization with custom model."""
        provider = AnthropicProvider(api_key="test-key", model="claude-3-haiku-20240307")
        assert provider.model == "claude-3-haiku-20240307"

    def test_anthropic_provider_uses_litellm_internally(self):
        """Test that AnthropicProvider delegates to LiteLLMProvider."""
        provider = AnthropicProvider(api_key="test-key", model="claude-3-haiku-20240307")
        assert isinstance(provider._provider, LiteLLMProvider)
        assert provider._provider.model == "claude-3-haiku-20240307"
        assert provider._provider.api_key == "test-key"

    @patch("litellm.completion")
    def test_anthropic_provider_complete(self, mock_completion):
        """Test AnthropicProvider.complete() delegates to LiteLLM."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from Claude!"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "claude-3-haiku-20240307"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_completion.return_value = mock_response

        provider = AnthropicProvider(api_key="test-key", model="claude-3-haiku-20240307")
        result = provider.complete(
            messages=[{"role": "user", "content": "Hello"}],
            system="You are helpful.",
            max_tokens=100,
        )

        assert result.content == "Hello from Claude!"
        assert result.model == "claude-3-haiku-20240307"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["model"] == "claude-3-haiku-20240307"
        assert call_kwargs["api_key"] == "test-key"

    @patch("litellm.completion")
    def test_anthropic_provider_passes_response_format(self, mock_completion):
        """Test that AnthropicProvider accepts and forwards response_format."""
        # Setup mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "{}"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "claude-3-haiku-20240307"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_completion.return_value = mock_response

        provider = AnthropicProvider(api_key="test-key")
        fmt = {"type": "json_object"}

        provider.complete(messages=[{"role": "user", "content": "hi"}], response_format=fmt)

        # Verify it was passed to litellm
        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["response_format"] == fmt


class TestJsonMode:
    """Test json_mode parameter for structured JSON output via prompt engineering."""

    @patch("litellm.completion")
    def test_json_mode_adds_instruction_to_system_prompt(self, mock_completion):
        """Test that json_mode=True adds JSON instruction to system prompt."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"key": "value"}'
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_completion.return_value = mock_response

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")
        provider.complete(
            messages=[{"role": "user", "content": "Return JSON"}],
            system="You are helpful.",
            json_mode=True,
        )

        call_kwargs = mock_completion.call_args[1]
        # Should NOT use response_format (prompt engineering instead)
        assert "response_format" not in call_kwargs
        # Should have JSON instruction appended to system message
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "You are helpful." in messages[0]["content"]
        assert "Please respond with a valid JSON object" in messages[0]["content"]

    @patch("litellm.completion")
    def test_json_mode_creates_system_prompt_if_none(self, mock_completion):
        """Test that json_mode=True creates system prompt if none provided."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"key": "value"}'
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_completion.return_value = mock_response

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")
        provider.complete(messages=[{"role": "user", "content": "Return JSON"}], json_mode=True)

        call_kwargs = mock_completion.call_args[1]
        messages = call_kwargs["messages"]
        # Should insert a system message with JSON instruction
        assert messages[0]["role"] == "system"
        assert "Please respond with a valid JSON object" in messages[0]["content"]

    @patch("litellm.completion")
    def test_json_mode_false_no_instruction(self, mock_completion):
        """Test that json_mode=False does not add JSON instruction."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_completion.return_value = mock_response

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")
        provider.complete(
            messages=[{"role": "user", "content": "Hello"}],
            system="You are helpful.",
            json_mode=False,
        )

        call_kwargs = mock_completion.call_args[1]
        assert "response_format" not in call_kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "Please respond with a valid JSON object" not in messages[0]["content"]

    @patch("litellm.completion")
    def test_json_mode_default_is_false(self, mock_completion):
        """Test that json_mode defaults to False (no JSON instruction)."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_completion.return_value = mock_response

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")
        provider.complete(messages=[{"role": "user", "content": "Hello"}], system="You are helpful.")

        call_kwargs = mock_completion.call_args[1]
        assert "response_format" not in call_kwargs
        messages = call_kwargs["messages"]
        # System prompt should be unchanged
        assert messages[0]["content"] == "You are helpful."

    @patch("litellm.completion")
    def test_anthropic_provider_passes_json_mode(self, mock_completion):
        """Test that AnthropicProvider passes json_mode through (prompt engineering)."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "ok"}'
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "claude-haiku-4-5-20251001"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_completion.return_value = mock_response

        provider = AnthropicProvider(api_key="test-key")
        provider.complete(
            messages=[{"role": "user", "content": "Return JSON"}],
            system="You are helpful.",
            json_mode=True,
        )

        call_kwargs = mock_completion.call_args[1]
        # Should NOT use response_format
        assert "response_format" not in call_kwargs
        # Should have JSON instruction in system prompt
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "Please respond with a valid JSON object" in messages[0]["content"]


class TestComputeRetryDelay:
    """Test _compute_retry_delay() header parsing and fallback logic."""

    def test_fallback_exponential_backoff(self):
        """No exception -> exponential backoff."""
        assert _compute_retry_delay(0) == 2  # 2 * 2^0
        assert _compute_retry_delay(1) == 4  # 2 * 2^1
        assert _compute_retry_delay(2) == 8  # 2 * 2^2
        assert _compute_retry_delay(3) == 16  # 2 * 2^3

    def test_max_delay_cap(self):
        """Backoff should be capped at RATE_LIMIT_MAX_DELAY."""
        # 2 * 2^10 = 2048, should be capped at 120
        assert _compute_retry_delay(10) == 120

    def test_custom_max_delay(self):
        """Custom max_delay should be respected."""
        assert _compute_retry_delay(5, max_delay=10) == 10

    def test_retry_after_ms_header(self):
        """retry-after-ms header should be parsed as milliseconds."""
        exc = _make_exception_with_headers({"retry-after-ms": "5000"})
        assert _compute_retry_delay(0, exception=exc) == 5.0

    def test_retry_after_ms_fractional(self):
        """retry-after-ms should handle fractional values."""
        exc = _make_exception_with_headers({"retry-after-ms": "1500"})
        assert _compute_retry_delay(0, exception=exc) == 1.5

    def test_retry_after_seconds_header(self):
        """retry-after header as seconds should be parsed."""
        exc = _make_exception_with_headers({"retry-after": "3"})
        assert _compute_retry_delay(0, exception=exc) == 3.0

    def test_retry_after_seconds_fractional(self):
        """retry-after header should handle fractional seconds."""
        exc = _make_exception_with_headers({"retry-after": "2.5"})
        assert _compute_retry_delay(0, exception=exc) == 2.5

    def test_retry_after_ms_takes_priority(self):
        """retry-after-ms should take priority over retry-after."""
        exc = _make_exception_with_headers(
            {
                "retry-after-ms": "2000",
                "retry-after": "10",
            }
        )
        assert _compute_retry_delay(0, exception=exc) == 2.0

    def test_retry_after_http_date(self):
        """retry-after as HTTP-date should be parsed."""
        from email.utils import format_datetime

        future = datetime.now(UTC) + timedelta(seconds=5)
        date_str = format_datetime(future, usegmt=True)
        exc = _make_exception_with_headers({"retry-after": date_str})
        delay = _compute_retry_delay(0, exception=exc)
        assert 3.0 <= delay <= 6.0  # within tolerance

    def test_exception_without_response(self):
        """Exception with response=None should fall back to exponential."""
        exc = Exception("test")
        exc.response = None  # type: ignore[attr-defined]
        assert _compute_retry_delay(0, exception=exc) == 2  # exponential fallback

    def test_exception_without_response_attr(self):
        """Exception without .response attr should fall back to exponential."""
        exc = ValueError("no response attr")
        assert _compute_retry_delay(0, exception=exc) == 2

    def test_negative_retry_after_clamped_to_zero(self):
        """Negative retry-after should be clamped to 0."""
        exc = _make_exception_with_headers({"retry-after": "-5"})
        assert _compute_retry_delay(0, exception=exc) == 0

    def test_negative_retry_after_ms_clamped_to_zero(self):
        """Negative retry-after-ms should be clamped to 0."""
        exc = _make_exception_with_headers({"retry-after-ms": "-1000"})
        assert _compute_retry_delay(0, exception=exc) == 0

    def test_invalid_retry_after_falls_back(self):
        """Non-numeric, non-date retry-after should fall back to exponential."""
        exc = _make_exception_with_headers({"retry-after": "not-a-number-or-date"})
        assert _compute_retry_delay(0, exception=exc) == 2  # exponential fallback

    def test_invalid_retry_after_ms_falls_back_to_retry_after(self):
        """Invalid retry-after-ms should fall through to retry-after."""
        exc = _make_exception_with_headers(
            {
                "retry-after-ms": "garbage",
                "retry-after": "7",
            }
        )
        assert _compute_retry_delay(0, exception=exc) == 7.0

    def test_retry_after_capped_at_max_delay(self):
        """Server-provided delay should be capped at max_delay."""
        exc = _make_exception_with_headers({"retry-after": "3600"})
        assert _compute_retry_delay(0, exception=exc) == 120  # capped

    def test_retry_after_ms_capped_at_max_delay(self):
        """Server-provided ms delay should be capped at max_delay."""
        exc = _make_exception_with_headers({"retry-after-ms": "300000"})  # 300s
        assert _compute_retry_delay(0, exception=exc) == 120  # capped


def _make_exception_with_headers(headers: dict[str, str]) -> BaseException:
    """Create a mock exception with response headers for testing."""
    exc = Exception("rate limited")
    response = MagicMock()
    response.headers = headers
    exc.response = response  # type: ignore[attr-defined]
    return exc


# ---------------------------------------------------------------------------
# Async LLM methods — non-blocking event loop tests
# ---------------------------------------------------------------------------


class TestAsyncComplete:
    """Test that acomplete/acomplete_with_tools don't block the event loop."""

    @pytest.mark.asyncio
    @patch("litellm.acompletion")
    async def test_acomplete_uses_acompletion(self, mock_acompletion):
        """acomplete() should call litellm.acompletion (async), not litellm.completion."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "async hello"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        # acompletion is async, so mock must return a coroutine
        async def async_return(*args, **kwargs):
            return mock_response

        mock_acompletion.side_effect = async_return

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")
        result = await provider.acomplete(
            messages=[{"role": "user", "content": "Hello"}],
            system="You are helpful.",
        )

        assert result.content == "async hello"
        assert result.model == "gpt-4o-mini"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        mock_acompletion.assert_called_once()

    @pytest.mark.asyncio
    @patch("litellm.acompletion")
    async def test_acomplete_does_not_block_event_loop(self, mock_acompletion):
        """Verify event loop stays responsive during acomplete()."""
        heartbeat_ticks = []

        async def heartbeat():
            start = time.monotonic()
            for _ in range(10):
                heartbeat_ticks.append(time.monotonic() - start)
                await asyncio.sleep(0.05)

        async def slow_acompletion(*args, **kwargs):
            # Simulate a 300ms LLM call — async, so event loop should stay free
            await asyncio.sleep(0.3)
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "done"
            resp.choices[0].message.tool_calls = None
            resp.choices[0].finish_reason = "stop"
            resp.model = "gpt-4o-mini"
            resp.usage.prompt_tokens = 5
            resp.usage.completion_tokens = 3
            return resp

        mock_acompletion.side_effect = slow_acompletion

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

        # Run heartbeat + acomplete concurrently
        _, result = await asyncio.gather(
            heartbeat(),
            provider.acomplete(
                messages=[{"role": "user", "content": "hi"}],
            ),
        )

        assert result.content == "done"
        # Heartbeat should have ticked multiple times during the 300ms LLM call
        # (if the event loop were blocked, we'd see 0-1 ticks)
        assert len(heartbeat_ticks) >= 3, f"Event loop was blocked — only {len(heartbeat_ticks)} heartbeat ticks"

    @pytest.mark.asyncio
    async def test_mock_provider_acomplete(self):
        """MockLLMProvider.acomplete() should work without blocking."""
        from framework.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        result = await provider.acomplete(
            messages=[{"role": "user", "content": "test"}],
            system="Be helpful.",
        )

        assert result.content  # Should have some mock content
        assert result.model == "mock-model"

    @pytest.mark.asyncio
    async def test_base_provider_acomplete_offloads_to_executor(self):
        """Base LLMProvider.acomplete() should offload sync complete() to thread pool."""
        call_thread_ids = []

        class SlowSyncProvider(LLMProvider):
            model: str = "mock"

            def complete(
                self,
                messages,
                system="",
                tools=None,
                max_tokens=1024,
                response_format=None,
                json_mode=False,
                max_retries=None,
            ):
                call_thread_ids.append(threading.current_thread().ident)
                time.sleep(0.1)  # Sync blocking
                return LLMResponse(content="sync done", model="slow")

        provider = SlowSyncProvider()
        main_thread_id = threading.current_thread().ident

        result = await provider.acomplete(
            messages=[{"role": "user", "content": "hi"}],
        )

        assert result.content == "sync done"
        # The sync complete() should have run on a different thread
        assert call_thread_ids[0] != main_thread_id, "Base acomplete() should offload sync complete() to a thread pool"


class TestMiniMaxStreamFallback:
    """MiniMax models should use non-stream fallback due to parser incompatibility."""

    @pytest.mark.asyncio
    async def test_stream_uses_nonstream_fallback_for_minimax(self):
        """stream() should call acomplete() and synthesize stream events for MiniMax."""
        from framework.llm.stream_events import FinishEvent, TextDeltaEvent

        provider = LiteLLMProvider(model="minimax-text-01", api_key="test-key")

        mock_response = LLMResponse(
            content="hello from minimax",
            model="minimax-text-01",
            input_tokens=7,
            output_tokens=4,
            stop_reason="stop",
            raw_response=None,
        )
        provider.acomplete = AsyncMock(return_value=mock_response)

        events = []
        async for event in provider.stream(messages=[{"role": "user", "content": "hi"}]):
            events.append(event)

        assert provider.acomplete.await_count == 1
        assert any(isinstance(e, TextDeltaEvent) for e in events)
        finish = [e for e in events if isinstance(e, FinishEvent)]
        assert len(finish) == 1
        assert finish[0].model == "minimax-text-01"

    def test_is_minimax_model_variants(self):
        """Recognize both prefixed and plain MiniMax model names."""
        assert LiteLLMProvider(model="minimax-text-01", api_key="x")._is_minimax_model()
        assert LiteLLMProvider(model="minimax/minimax-text-01", api_key="x")._is_minimax_model()
        assert not LiteLLMProvider(model="gpt-4o-mini", api_key="x")._is_minimax_model()


class TestOpenRouterToolCompatFallback:
    """OpenRouter models should fall back when native tool use is unavailable."""

    def teardown_method(self):
        OPENROUTER_TOOL_COMPAT_MODEL_CACHE.clear()

    @pytest.mark.asyncio
    @patch("litellm.acompletion")
    async def test_stream_falls_back_to_json_tool_emulation(self, mock_acompletion):
        """OpenRouter tool-use 404s should emit synthetic ToolCallEvents instead of errors."""
        from framework.llm.stream_events import FinishEvent, ToolCallEvent

        provider = LiteLLMProvider(
            model="openrouter/liquid/lfm-2.5-1.2b-thinking:free",
            api_key="test-key",
        )
        tools = [
            Tool(
                name="web_search",
                description="Search the web",
                parameters={
                    "properties": {
                        "query": {"type": "string"},
                        "num_results": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            )
        ]

        compat_response = MagicMock()
        compat_response.choices = [MagicMock()]
        compat_response.choices[0].message.content = (
            '{"assistant_response":"","tool_calls":['
            '{"name":"web_search","arguments":'
            '{"query":"Python 3.13 release notes","num_results":3}}'
            "]}"
        )
        compat_response.choices[0].finish_reason = "stop"
        compat_response.model = provider.model
        compat_response.usage.prompt_tokens = 18
        compat_response.usage.completion_tokens = 9

        async def side_effect(*args, **kwargs):
            if kwargs.get("stream"):
                raise RuntimeError(
                    'OpenrouterException - {"error":{"message":"No endpoints found '
                    "that support tool use. To learn more about provider routing, "
                    'visit: https://openrouter.ai/docs/guides/routing/provider-selection",'
                    '"code":404}}'
                )
            return compat_response

        mock_acompletion.side_effect = side_effect

        events = []
        async for event in provider.stream(
            messages=[{"role": "user", "content": "Search for the Python 3.13 release notes."}],
            system="Use tools when needed.",
            tools=tools,
            max_tokens=256,
        ):
            events.append(event)

        tool_calls = [event for event in events if isinstance(event, ToolCallEvent)]
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "web_search"
        assert tool_calls[0].tool_input == {
            "query": "Python 3.13 release notes",
            "num_results": 3,
        }
        assert tool_calls[0].tool_use_id.startswith("openrouter_compat_")

        finish_events = [event for event in events if isinstance(event, FinishEvent)]
        assert len(finish_events) == 1
        assert finish_events[0].stop_reason == "tool_calls"
        assert finish_events[0].input_tokens == 18
        assert finish_events[0].output_tokens == 9

        assert mock_acompletion.call_count == 2
        first_call = mock_acompletion.call_args_list[0].kwargs
        assert first_call["stream"] is True
        assert "tools" in first_call

        second_call = mock_acompletion.call_args_list[1].kwargs
        assert "tools" not in second_call
        assert "Tool compatibility mode is active" in second_call["messages"][0]["content"]
        assert provider.model in OPENROUTER_TOOL_COMPAT_MODEL_CACHE

    @pytest.mark.asyncio
    @patch("litellm.acompletion")
    async def test_stream_tool_compat_parses_textual_tool_calls_and_uses_cache(
        self,
        mock_acompletion,
    ):
        """Textual tool-call markers should become ToolCallEvents and skip repeat probing."""
        from framework.llm.stream_events import ToolCallEvent

        provider = LiteLLMProvider(
            model="openrouter/liquid/lfm-2.5-1.2b-thinking:free",
            api_key="test-key",
        )
        tools = [
            Tool(
                name="choose_one",
                description="Ask the user a multiple-choice question",
                parameters={
                    "properties": {
                        "options": {"type": "array"},
                        "question": {"type": "string"},
                        "prompt": {"type": "string"},
                    },
                    "required": ["options", "question", "prompt"],
                },
            )
        ]

        compat_response = MagicMock()
        compat_response.choices = [MagicMock()]
        compat_response.choices[0].message.content = (
            "<|tool_call_start|>"
            "[choose_one(options=['Quartet Collaborator', 'Project Advisor'], "
            "question='Who are you?', prompt='Who are you?')]"
            "<|tool_call_end|>"
        )
        compat_response.choices[0].finish_reason = "stop"
        compat_response.model = provider.model
        compat_response.usage.prompt_tokens = 10
        compat_response.usage.completion_tokens = 5

        call_state = {"count": 0}

        async def side_effect(*args, **kwargs):
            call_state["count"] += 1
            if kwargs.get("stream"):
                raise RuntimeError(
                    'OpenrouterException - {"error":{"message":"No endpoints found that support tool use.","code":404}}'
                )
            return compat_response

        mock_acompletion.side_effect = side_effect

        first_events = []
        async for event in provider.stream(
            messages=[{"role": "user", "content": "Who are you?"}],
            system="Use tools when needed.",
            tools=tools,
            max_tokens=128,
        ):
            first_events.append(event)

        tool_calls = [event for event in first_events if isinstance(event, ToolCallEvent)]
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "choose_one"
        assert tool_calls[0].tool_input == {
            "options": ["Quartet Collaborator", "Project Advisor"],
            "question": "Who are you?",
            "prompt": "Who are you?",
        }

        second_events = []
        async for event in provider.stream(
            messages=[{"role": "user", "content": "Who are you?"}],
            system="Use tools when needed.",
            tools=tools,
            max_tokens=128,
        ):
            second_events.append(event)

        second_tool_calls = [event for event in second_events if isinstance(event, ToolCallEvent)]
        assert len(second_tool_calls) == 1
        assert mock_acompletion.call_count == 3
        assert mock_acompletion.call_args_list[0].kwargs["stream"] is True
        assert "stream" not in mock_acompletion.call_args_list[1].kwargs
        assert "stream" not in mock_acompletion.call_args_list[2].kwargs

    @pytest.mark.asyncio
    @patch("litellm.acompletion")
    async def test_stream_tool_compat_parses_plain_text_tool_call_lines(
        self,
        mock_acompletion,
    ):
        """Plain textual tool-call lines should execute as tools, not user-visible text."""
        from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent

        provider = LiteLLMProvider(
            model="openrouter/liquid/lfm-2.5-1.2b-thinking:free",
            api_key="test-key",
        )
        tools = [
            Tool(
                name="ask_user",
                description="Ask the user a single multiple-choice question",
                parameters={
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array"},
                    },
                    "required": ["question", "options"],
                },
            )
        ]

        compat_response = MagicMock()
        compat_response.choices = [MagicMock()]
        compat_response.choices[0].message.content = (
            "Queen has been loaded. It's ready to assist with your planning needs.\n\n"
            "ask_user('What would you like to do?', ['Define a new agent', "
            "'Diagnose an existing agent', 'Explore tools'])"
        )
        compat_response.choices[0].finish_reason = "stop"
        compat_response.model = provider.model
        compat_response.usage.prompt_tokens = 11
        compat_response.usage.completion_tokens = 7

        async def side_effect(*args, **kwargs):
            if kwargs.get("stream"):
                raise RuntimeError(
                    'OpenrouterException - {"error":{"message":"No endpoints found that support tool use.","code":404}}'
                )
            return compat_response

        mock_acompletion.side_effect = side_effect

        events = []
        async for event in provider.stream(
            messages=[{"role": "user", "content": "hello"}],
            system="Use tools when needed.",
            tools=tools,
            max_tokens=128,
        ):
            events.append(event)

        tool_calls = [event for event in events if isinstance(event, ToolCallEvent)]
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "ask_user"
        assert tool_calls[0].tool_input == {
            "question": "What would you like to do?",
            "options": ["Define a new agent", "Diagnose an existing agent", "Explore tools"],
        }

        text_events = [event for event in events if isinstance(event, TextDeltaEvent)]
        assert len(text_events) == 1
        assert "ask_user(" not in text_events[0].snapshot
        assert text_events[0].snapshot == ("Queen has been loaded. It's ready to assist with your planning needs.")

        finish_events = [event for event in events if isinstance(event, FinishEvent)]
        assert len(finish_events) == 1
        assert finish_events[0].stop_reason == "tool_calls"

    @pytest.mark.asyncio
    @patch("litellm.acompletion")
    async def test_stream_tool_compat_treats_non_json_as_plain_text(self, mock_acompletion):
        """If fallback output is not valid JSON, preserve it as assistant text."""
        from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent

        provider = LiteLLMProvider(
            model="openrouter/liquid/lfm-2.5-1.2b-thinking:free",
            api_key="test-key",
        )
        tools = [
            Tool(
                name="web_search",
                description="Search the web",
                parameters={"properties": {"query": {"type": "string"}}, "required": ["query"]},
            )
        ]

        compat_response = MagicMock()
        compat_response.choices = [MagicMock()]
        compat_response.choices[0].message.content = "I can answer directly without tools."
        compat_response.choices[0].finish_reason = "stop"
        compat_response.model = provider.model
        compat_response.usage.prompt_tokens = 12
        compat_response.usage.completion_tokens = 6

        async def side_effect(*args, **kwargs):
            if kwargs.get("stream"):
                raise RuntimeError(
                    'OpenrouterException - {"error":{"message":"No endpoints found that support tool use.","code":404}}'
                )
            return compat_response

        mock_acompletion.side_effect = side_effect

        events = []
        async for event in provider.stream(
            messages=[{"role": "user", "content": "Say hello."}],
            system="Be concise.",
            tools=tools,
            max_tokens=128,
        ):
            events.append(event)

        text_events = [event for event in events if isinstance(event, TextDeltaEvent)]
        assert len(text_events) == 1
        assert text_events[0].snapshot == "I can answer directly without tools."
        assert not any(isinstance(event, ToolCallEvent) for event in events)

        finish_events = [event for event in events if isinstance(event, FinishEvent)]
        assert len(finish_events) == 1
        assert finish_events[0].stop_reason == "stop"


# ---------------------------------------------------------------------------
# AgentRunner._is_local_model — parameterized tests
# ---------------------------------------------------------------------------


class TestIsLocalModel:
    """Parameterized tests for AgentRunner._is_local_model()."""

    @pytest.mark.parametrize(
        "model",
        [
            "ollama/llama3",
            "ollama/mistral",
            "ollama_chat/llama3",
            "vllm/mistral",
            "lm_studio/phi3",
            "llamacpp/llama-7b",
            "Ollama/Llama3",  # case-insensitive
            "VLLM/Mistral",
        ],
    )
    def test_local_models_return_true(self, model):
        """Local model prefixes should be recognized."""
        from framework.loader.agent_loader import AgentLoader

        assert AgentLoader._is_local_model(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-3-haiku",
            "openai/gpt-4o",
            "gpt-4o-mini",
            "claude-3-haiku-20240307",
            "gemini/gemini-1.5-flash",
            "groq/llama3-70b",
            "mistral/mistral-large",
            "azure/gpt-4",
            "cohere/command-r",
            "together/llama3-70b",
        ],
    )
    def test_cloud_models_return_false(self, model):
        """Cloud model prefixes should not be treated as local."""
        from framework.loader.agent_loader import AgentLoader

        assert AgentLoader._is_local_model(model) is False


# ---------------------------------------------------------------------------
# Ollama helper functions
# ---------------------------------------------------------------------------


class TestIsOllamaModel:
    """Tests for _is_ollama_model()."""

    @pytest.mark.parametrize(
        "model",
        [
            "ollama/llama3",
            "ollama/mistral:7b",
            "ollama_chat/llama3",
            "ollama_chat/qwen2.5:72b",
        ],
    )
    def test_ollama_models_return_true(self, model):
        assert _is_ollama_model(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "openai/gpt-4o",
            "gemini/gemini-1.5-flash",
            "llama3",
            "",
        ],
    )
    def test_non_ollama_models_return_false(self, model):
        assert _is_ollama_model(model) is False


class TestEnsureOllamaChatPrefix:
    """Tests for _ensure_ollama_chat_prefix()."""

    @pytest.mark.parametrize(
        ("input_model", "expected"),
        [
            ("ollama/llama3", "ollama_chat/llama3"),
            ("ollama/mistral:7b", "ollama_chat/mistral:7b"),
            ("ollama/qwen2.5:72b-instruct", "ollama_chat/qwen2.5:72b-instruct"),
        ],
    )
    def test_rewrites_ollama_to_ollama_chat(self, input_model, expected):
        assert _ensure_ollama_chat_prefix(input_model) == expected

    @pytest.mark.parametrize(
        "model",
        [
            "ollama_chat/llama3",
            "gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "gemini/gemini-1.5-flash",
            "",
        ],
    )
    def test_leaves_non_ollama_prefix_unchanged(self, model):
        assert _ensure_ollama_chat_prefix(model) == model


class TestGetLlmExtraKwargsOllama:
    """Tests for num_ctx injection via get_llm_extra_kwargs() for Ollama."""

    def test_ollama_provider_returns_num_ctx(self):
        """Ollama config should inject num_ctx with default 16384."""
        config = {
            "llm": {"provider": "ollama", "model": "ollama/llama3"},
        }
        with patch("framework.config.get_hive_config", return_value=config):
            result = get_llm_extra_kwargs()
        assert result == {"num_ctx": 16384}

    def test_ollama_provider_respects_custom_num_ctx(self):
        """User-specified num_ctx in config should take precedence."""
        config = {
            "llm": {"provider": "ollama", "model": "ollama/llama3", "num_ctx": 32768},
        }
        with patch("framework.config.get_hive_config", return_value=config):
            result = get_llm_extra_kwargs()
        assert result == {"num_ctx": 32768}

    def test_non_ollama_provider_returns_empty(self):
        """Non-Ollama provider without subscriptions should return empty dict."""
        config = {
            "llm": {"provider": "anthropic", "model": "claude-3-haiku"},
        }
        with patch("framework.config.get_hive_config", return_value=config):
            result = get_llm_extra_kwargs()
        assert result == {}

    def test_empty_config_returns_empty(self):
        """Missing config should return empty dict."""
        with patch("framework.config.get_hive_config", return_value={}):
            result = get_llm_extra_kwargs()
        assert result == {}


class TestModelSupportsCacheControl:
    """`cache_control` allowlist covers native providers AND OpenRouter sub-providers
    whose upstream API honors the marker (Anthropic, Gemini, GLM, MiniMax).
    Auto-cache sub-providers (OpenAI, DeepSeek, Grok, Moonshot, Groq) are
    intentionally excluded: sending cache_control is a no-op and a false win."""

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-opus-4-5",
            "claude-3-5-sonnet-20241022",
            "minimax/minimax-text-01",
            "MiniMax-Text-01",
            "zai-glm-4.6",
            "glm-4.6",
            "openrouter/anthropic/claude-opus-4.5",
            "openrouter/anthropic/claude-sonnet-4.5",
            "openrouter/google/gemini-2.5-pro",
            "openrouter/google/gemini-2.5-flash",
            "openrouter/z-ai/glm-5.1",
            "openrouter/z-ai/glm-4.6",
            "openrouter/minimax/minimax-text-01",
        ],
    )
    def test_supported(self, model):
        assert _model_supports_cache_control(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o-mini",
            "gemini/gemini-1.5-flash",
            "ollama_chat/llama3",
            "openrouter/openai/gpt-4o",
            "openrouter/deepseek/deepseek-chat",
            "openrouter/x-ai/grok-2",
            "openrouter/moonshotai/kimi-k2",
            "openrouter/liquid/lfm-2.5-1.2b-thinking:free",
        ],
    )
    def test_unsupported(self, model):
        assert _model_supports_cache_control(model) is False


class TestBuildSystemMessageOpenRouter:
    """`_build_system_message` should split static/dynamic blocks whenever
    the model — native OR OpenRouter-routed — supports cache_control."""

    def test_openrouter_anthropic_splits_into_two_blocks(self):
        msg = _build_system_message(
            system="static prefix",
            system_dynamic_suffix="dynamic tail",
            model="openrouter/anthropic/claude-opus-4.5",
        )
        assert msg == {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "static prefix",
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": "dynamic tail"},
            ],
        }

    def test_openrouter_gemini_splits_into_two_blocks(self):
        msg = _build_system_message(
            system="static prefix",
            system_dynamic_suffix="dynamic tail",
            model="openrouter/google/gemini-2.5-pro",
        )
        assert isinstance(msg["content"], list)
        assert msg["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert msg["content"][1] == {"type": "text", "text": "dynamic tail"}

    def test_openrouter_glm_splits_into_two_blocks(self):
        msg = _build_system_message(
            system="static prefix",
            system_dynamic_suffix="dynamic tail",
            model="openrouter/z-ai/glm-5.1",
        )
        assert isinstance(msg["content"], list)
        assert msg["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_openrouter_openai_stays_concatenated(self):
        """OpenAI via OpenRouter auto-caches; sending cache_control is a no-op."""
        msg = _build_system_message(
            system="static prefix",
            system_dynamic_suffix="dynamic tail",
            model="openrouter/openai/gpt-4o",
        )
        assert msg == {
            "role": "system",
            "content": "static prefix\n\ndynamic tail",
        }

    def test_no_suffix_anthropic_gets_top_level_cache_control(self):
        msg = _build_system_message(
            system="static prefix",
            system_dynamic_suffix=None,
            model="openrouter/anthropic/claude-opus-4.5",
        )
        assert msg == {
            "role": "system",
            "content": "static prefix",
            "cache_control": {"type": "ephemeral"},
        }


class TestOpenRouterToolCompatCacheControl:
    """Tool-compat path must pass cache_control through when the routed
    sub-provider honors it. Before this, the queen persona+tool-list prefix
    was recomputed every turn on Anthropic/GLM via OpenRouter."""

    def test_tool_compat_messages_split_for_cache_capable_model(self):
        provider = LiteLLMProvider(
            model="openrouter/anthropic/claude-opus-4.5",
            api_key="test-key",
        )
        tools = [
            Tool(
                name="web_search",
                description="Search the web",
                parameters={"properties": {"query": {"type": "string"}}, "required": ["query"]},
            )
        ]

        full_messages = provider._build_openrouter_tool_compat_messages(
            messages=[{"role": "user", "content": "hi"}],
            system="You are a queen.",
            tools=tools,
            system_dynamic_suffix="Current time: 2026-04-23T00:00:00Z",
        )

        system_msg = full_messages[0]
        assert system_msg["role"] == "system"
        assert isinstance(system_msg["content"], list)
        assert len(system_msg["content"]) == 2

        static_block = system_msg["content"][0]
        assert static_block["cache_control"] == {"type": "ephemeral"}
        assert "You are a queen." in static_block["text"]
        assert "Tool compatibility mode is active" in static_block["text"]
        assert "web_search" in static_block["text"]
        assert "2026-04-23" not in static_block["text"]

        dynamic_block = system_msg["content"][1]
        assert "cache_control" not in dynamic_block
        assert dynamic_block["text"] == "Current time: 2026-04-23T00:00:00Z"

    def test_tool_compat_messages_stay_concatenated_for_liquid(self):
        """Liquid (and other non-cache-control OR sub-providers) keep legacy behavior."""
        provider = LiteLLMProvider(
            model="openrouter/liquid/lfm-2.5-1.2b-thinking:free",
            api_key="test-key",
        )
        tools = [
            Tool(
                name="web_search",
                description="Search the web",
                parameters={"properties": {"query": {"type": "string"}}, "required": ["query"]},
            )
        ]

        full_messages = provider._build_openrouter_tool_compat_messages(
            messages=[{"role": "user", "content": "hi"}],
            system="You are a queen.",
            tools=tools,
            system_dynamic_suffix="Current time: 2026-04-23T00:00:00Z",
        )

        system_msg = full_messages[0]
        assert isinstance(system_msg["content"], str)
        assert "2026-04-23" in system_msg["content"]
        assert "cache_control" not in system_msg


class TestExtractCacheTokens:
    """`_extract_cache_tokens` reads cache_read + cache_creation from the
    LiteLLM-normalized usage object. Both fields are subsets of
    ``prompt_tokens`` — the helper surfaces them for display, the call sites
    are responsible for never adding them to a total."""

    def test_none_usage_returns_zero(self):
        assert _extract_cache_tokens(None) == (0, 0)

    def test_openai_shape(self):
        """Pure OpenAI responses expose cached reads via
        ``prompt_tokens_details.cached_tokens`` and have no cache write
        field at all (OpenAI's automatic caching is read-only from the
        client's perspective)."""
        usage = MagicMock(spec=["prompt_tokens_details", "cache_creation_input_tokens"])
        usage.prompt_tokens_details = MagicMock(
            spec=["cached_tokens"], cached_tokens=120,
        )
        usage.cache_creation_input_tokens = 0
        cache_read, cache_creation = _extract_cache_tokens(usage)
        assert cache_read == 120
        assert cache_creation == 0

    def test_openrouter_cache_write_tokens_shape(self):
        """OpenRouter normalizes cache writes into
        ``prompt_tokens_details.cache_write_tokens`` (verified empirically
        against openrouter/anthropic and openrouter/z-ai responses). The
        legacy ``usage.cache_creation_input_tokens`` field is NOT set on
        OpenRouter responses, so this is the path that matters in practice."""
        usage = MagicMock()
        usage.prompt_tokens_details = MagicMock(
            cached_tokens=80, cache_write_tokens=50,
        )
        # Explicitly set the Anthropic-native field to 0 to prove we don't
        # depend on it for OpenRouter responses.
        usage.cache_creation_input_tokens = 0
        cache_read, cache_creation = _extract_cache_tokens(usage)
        assert cache_read == 80
        assert cache_creation == 50

    def test_anthropic_native_cache_creation_field_still_works(self):
        """Direct Anthropic API responses (not via OpenRouter) put cache
        writes on the top-level ``cache_creation_input_tokens`` field. Keep
        the fallback so non-OpenRouter Anthropic continues to work."""
        usage = MagicMock(spec=["prompt_tokens_details", "cache_creation_input_tokens"])
        usage.prompt_tokens_details = MagicMock(
            spec=["cached_tokens"], cached_tokens=80,
        )
        usage.cache_creation_input_tokens = 50
        cache_read, cache_creation = _extract_cache_tokens(usage)
        assert cache_read == 80
        assert cache_creation == 50

    def test_raw_anthropic_shape_falls_back(self):
        """Raw Anthropic usage (no prompt_tokens_details) — fall back to
        cache_read_input_tokens."""
        usage = MagicMock(spec=["cache_read_input_tokens", "cache_creation_input_tokens"])
        usage.cache_read_input_tokens = 200
        usage.cache_creation_input_tokens = 75
        # Force prompt_tokens_details to be missing on the spec'd mock.
        cache_read, cache_creation = _extract_cache_tokens(usage)
        assert cache_read == 200
        assert cache_creation == 75

    def test_no_cache_fields_returns_zero(self):
        """A provider that doesn't report cache tokens at all (e.g. Gemini)
        returns (0, 0) — never raises."""
        usage = MagicMock(spec=["prompt_tokens", "completion_tokens"])
        cache_read, cache_creation = _extract_cache_tokens(usage)
        assert cache_read == 0
        assert cache_creation == 0


class TestStreamingChunksFallbackPreservesCacheFields:
    """Regression: when LiteLLM strips usage from yielded streaming chunks,
    we fall back to ``response.chunks`` to recover token totals. LiteLLM's
    own ``calculate_total_usage()`` aggregates ``prompt_tokens`` /
    ``completion_tokens`` correctly but DROPS ``prompt_tokens_details`` —
    which is where OpenRouter places ``cached_tokens`` and
    ``cache_write_tokens``. The fallback path must walk the raw chunks to
    recover those fields, otherwise streaming OpenRouter calls always
    report zero cache tokens. (Verified empirically against
    openrouter/anthropic/* and openrouter/z-ai/*.)"""

    def test_chunks_with_cache_fields_recovered(self):
        """Simulate the chunks-fallback hot path: build raw chunks where the
        last one carries cache_write_tokens, run the same recovery loop the
        streaming code uses, and assert we surface the cache fields."""
        # Three chunks: text deltas, then a final chunk with usage.
        empty_usage_chunk = MagicMock()
        empty_usage_chunk.usage = None
        last_chunk = MagicMock()
        last_chunk.usage = MagicMock()
        last_chunk.usage.prompt_tokens_details = MagicMock(
            cached_tokens=0, cache_write_tokens=5601,
        )
        last_chunk.usage.cache_creation_input_tokens = 0
        chunks = [empty_usage_chunk, empty_usage_chunk, last_chunk]

        # Mirror the production loop in litellm.py's chunks-fallback.
        cached, creation = 0, 0
        for raw in reversed(chunks):
            usage = getattr(raw, "usage", None)
            if usage is None:
                continue
            cr, cc = _extract_cache_tokens(usage)
            if cr or cc:
                cached, creation = cr, cc
                break

        assert cached == 0
        assert creation == 5601, (
            "chunks-fallback must recover cache_write_tokens from the raw "
            "chunk, not from calculate_total_usage which strips details"
        )

    def test_chunks_with_cache_read_recovered(self):
        """Same path, but for a cache HIT (cached_tokens populated)."""
        last_chunk = MagicMock()
        last_chunk.usage = MagicMock()
        last_chunk.usage.prompt_tokens_details = MagicMock(
            cached_tokens=5601, cache_write_tokens=0,
        )
        last_chunk.usage.cache_creation_input_tokens = 0

        cached, creation = 0, 0
        for raw in reversed([last_chunk]):
            usage = getattr(raw, "usage", None)
            if usage is None:
                continue
            cr, cc = _extract_cache_tokens(usage)
            if cr or cc:
                cached, creation = cr, cc
                break

        assert cached == 5601
        assert creation == 0


class TestExtractCost:
    """`_extract_cost` pulls USD cost from three sources in order:
    usage.cost (OpenRouter native / include_cost_in_streaming_usage) →
    response._hidden_params['response_cost'] (LiteLLM logging) →
    litellm.completion_cost() (pricing-table fallback)."""

    def test_none_response_returns_zero(self):
        assert _extract_cost(None, "gpt-4o-mini") == 0.0

    def test_openrouter_usage_cost_is_preferred(self):
        """OpenRouter returns authoritative per-call cost on usage.cost when
        the caller opts in (usage.include=true). That beats LiteLLM's
        pricing-table estimate because it reflects promo pricing and BYOK markup."""
        response = MagicMock()
        response.usage = MagicMock(cost=0.00123)
        response._hidden_params = {"response_cost": 99.99}  # should be ignored
        assert _extract_cost(response, "openrouter/anthropic/claude-opus-4.5") == 0.00123

    def test_hidden_params_response_cost_used_when_no_usage_cost(self):
        """LiteLLM's logging layer attaches response_cost after most
        completions — this is how OpenAI/Anthropic responses get costed
        without going back to the pricing table."""
        response = MagicMock()
        response.usage = MagicMock(spec=[])  # no .cost attribute
        response._hidden_params = {"response_cost": 0.0042}
        assert _extract_cost(response, "gpt-4o-mini") == 0.0042

    def test_falls_back_to_completion_cost_when_nothing_pre_populated(self):
        """For providers where LiteLLM didn't pre-populate cost, call
        litellm.completion_cost() against the pricing table. Mocked here
        because we don't want tests depending on the exact price of
        claude-sonnet-4.5 in LiteLLM's model map."""
        response = MagicMock()
        response.usage = MagicMock(spec=[])
        response._hidden_params = {}
        with patch("litellm.completion_cost", return_value=0.00789):
            assert _extract_cost(response, "anthropic/claude-sonnet-4.5") == 0.00789

    def test_completion_cost_exception_returns_zero(self):
        """Unpriced models (e.g. new OpenRouter routes not yet in LiteLLM's
        catalog) must not crash the hot path."""
        response = MagicMock()
        response.usage = MagicMock(spec=[])
        response._hidden_params = {}
        with patch("litellm.completion_cost", side_effect=Exception("no pricing")):
            assert _extract_cost(response, "openrouter/mystery/model") == 0.0

    def test_zero_cost_falls_through_to_next_source(self):
        """usage.cost == 0 should NOT short-circuit; fall through to
        _hidden_params / completion_cost so we don't cement a false zero."""
        response = MagicMock()
        response.usage = MagicMock(cost=0.0)
        response._hidden_params = {"response_cost": 0.0055}
        assert _extract_cost(response, "gpt-4o-mini") == 0.0055


class TestCostFromTokens:
    """`_cost_from_tokens` is the streaming-path cost helper: stream wrappers
    don't expose the full ModelResponse shape that completion_cost() expects,
    so we go through cost_per_token() with the already-extracted totals."""

    def test_zero_tokens_returns_zero_without_calling_litellm(self):
        with patch("litellm.cost_per_token") as mock:
            assert _cost_from_tokens("claude-opus-4.5", 0, 0) == 0.0
            mock.assert_not_called()

    def test_empty_model_returns_zero(self):
        assert _cost_from_tokens("", 1000, 500) == 0.0

    def test_computes_from_tokens(self):
        with patch("litellm.cost_per_token", return_value=(0.001, 0.002)) as mock:
            cost = _cost_from_tokens(
                "anthropic/claude-opus-4.5",
                input_tokens=1000,
                output_tokens=500,
                cached_tokens=200,
                cache_creation_tokens=100,
            )
        assert cost == pytest.approx(0.003)
        # Verify the cache-aware kwargs are threaded through — Anthropic
        # needs these to apply the 1.25x write / 0.1x read multipliers.
        call_kwargs = mock.call_args.kwargs
        assert call_kwargs["prompt_tokens"] == 1000
        assert call_kwargs["completion_tokens"] == 500
        assert call_kwargs["cache_read_input_tokens"] == 200
        assert call_kwargs["cache_creation_input_tokens"] == 100

    def test_exception_returns_zero(self):
        with patch("litellm.cost_per_token", side_effect=Exception("unpriced")):
            assert _cost_from_tokens("mystery/model", 1000, 500) == 0.0

    def test_negative_or_none_components_coerce_to_zero(self):
        """LiteLLM returns (None, None) for unknown models in some versions;
        treat as 0 rather than crashing on None+None."""
        with patch("litellm.cost_per_token", return_value=(None, None)):
            assert _cost_from_tokens("some/model", 1, 1) == 0.0


class TestLLMResponseAndFinishEventHaveCostUsd:
    """Regression: both LLMResponse and FinishEvent must carry cost_usd so
    the agent loop → event bus → frontend pipeline doesn't lose cost."""

    def test_llm_response_defaults_cost_to_zero(self):
        from framework.llm.provider import LLMResponse

        r = LLMResponse(content="", model="m")
        assert r.cost_usd == 0.0

    def test_finish_event_defaults_cost_to_zero(self):
        from framework.llm.stream_events import FinishEvent

        e = FinishEvent()
        assert e.cost_usd == 0.0

    def test_finish_event_accepts_cost(self):
        from framework.llm.stream_events import FinishEvent

        e = FinishEvent(cost_usd=0.0123)
        assert e.cost_usd == 0.0123
