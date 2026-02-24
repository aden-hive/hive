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
from unittest.mock import MagicMock, patch

import pytest

from framework.llm.anthropic import AnthropicProvider
from framework.llm.litellm import LiteLLMProvider, _compute_retry_delay
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse


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
        provider = LiteLLMProvider(
            model="gpt-4o-mini", api_key="my-key", api_base="https://my-proxy.com/v1"
        )
        assert provider.api_base == "https://my-proxy.com/v1"

    def test_init_ollama_no_key_needed(self):
        """Test that Ollama models don't require API key."""
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise.
            provider = LiteLLMProvider(model="ollama/llama3")
            assert provider.model == "ollama/llama3"


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
        provider.complete(
            messages=[{"role": "user", "content": "Hello"}], system="You are a helpful assistant."
        )

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

        provider.complete(
            messages=[{"role": "user", "content": "What's the weather?"}], tools=tools
        )

        call_kwargs = mock_completion.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["type"] == "function"
        assert call_kwargs["tools"][0]["function"]["name"] == "get_weather"


class TestLiteLLMProviderToolUse:
    """Test LiteLLMProvider.complete_with_tools() method."""

    @patch("litellm.completion")
    def test_complete_with_tools_single_iteration(self, mock_completion):
        """Test tool use with single iteration."""
        # First response: tool call
        tool_call_response = MagicMock()
        tool_call_response.choices = [MagicMock()]
        tool_call_response.choices[0].message.content = None
        tool_call_response.choices[0].message.tool_calls = [MagicMock()]
        tool_call_response.choices[0].message.tool_calls[0].id = "call_123"
        tool_call_response.choices[0].message.tool_calls[0].function.name = "get_weather"
        tool_call_response.choices[0].message.tool_calls[
            0
        ].function.arguments = '{"location": "London"}'
        tool_call_response.choices[0].finish_reason = "tool_calls"
        tool_call_response.model = "gpt-4o-mini"
        tool_call_response.usage.prompt_tokens = 20
        tool_call_response.usage.completion_tokens = 15

        # Second response: final answer
        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].message.content = "The weather in London is sunny."
        final_response.choices[0].message.tool_calls = None
        final_response.choices[0].finish_reason = "stop"
        final_response.model = "gpt-4o-mini"
        final_response.usage.prompt_tokens = 30
        final_response.usage.completion_tokens = 10

        mock_completion.side_effect = [tool_call_response, final_response]

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

        tools = [
            Tool(
                name="get_weather",
                description="Get the weather",
                parameters={
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            )
        ]

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(tool_use_id=tool_use.id, content="Sunny, 22C", is_error=False)

        result = provider.complete_with_tools(
            messages=[{"role": "user", "content": "What's the weather in London?"}],
            system="You are a weather assistant.",
            tools=tools,
            tool_executor=tool_executor,
        )

        assert result.content == "The weather in London is sunny."
        assert result.input_tokens == 50  # 20 + 30
        assert result.output_tokens == 25  # 15 + 10
        assert mock_completion.call_count == 2

    @patch("litellm.completion")
    def test_complete_with_tools_invalid_json_arguments_are_handled(self, mock_completion):
        """Test that invalid JSON tool arguments do not execute the tool."""
        # Mock response with invalid JSON arguments
        tool_call_response = MagicMock()
        tool_call_response.choices = [MagicMock()]
        tool_call_response.choices[0].message.content = None
        tool_call_response.choices[0].message.tool_calls = [MagicMock()]
        tool_call_response.choices[0].message.tool_calls[0].id = "call_123"
        tool_call_response.choices[0].message.tool_calls[0].function.name = "test_tool"
        tool_call_response.choices[0].message.tool_calls[0].function.arguments = "{invalid json"
        tool_call_response.choices[0].finish_reason = "tool_calls"
        tool_call_response.model = "gpt-4o-mini"
        tool_call_response.usage.prompt_tokens = 10
        tool_call_response.usage.completion_tokens = 5

        # Final response (LLM continues after tool error)
        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].message.content = "Handled error"
        final_response.choices[0].message.tool_calls = None
        final_response.choices[0].finish_reason = "stop"
        final_response.model = "gpt-4o-mini"
        final_response.usage.prompt_tokens = 5
        final_response.usage.completion_tokens = 5

        mock_completion.side_effect = [tool_call_response, final_response]

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

        tools = [
            Tool(
                name="test_tool",
                description="Test tool",
                parameters={"properties": {}, "required": []},
            )
        ]

        called = {"value": False}

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            called["value"] = True
            return ToolResult(
                tool_use_id=tool_use.id, content="should not be called", is_error=False
            )

        result = provider.complete_with_tools(
            messages=[{"role": "user", "content": "Run tool"}],
            system="You are a test assistant.",
            tools=tools,
            tool_executor=tool_executor,
        )

        assert called["value"] is False
        assert result.content == "Handled error"


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
    def test_anthropic_provider_complete_with_tools(self, mock_completion):
        """Test AnthropicProvider.complete_with_tools() delegates to LiteLLM."""
        # Mock a simple response (no tool calls)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "The time is 3:00 PM."
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "claude-3-haiku-20240307"
        mock_response.usage.prompt_tokens = 20
        mock_response.usage.completion_tokens = 10
        mock_completion.return_value = mock_response

        provider = AnthropicProvider(api_key="test-key", model="claude-3-haiku-20240307")

        tools = [
            Tool(
                name="get_time",
                description="Get current time",
                parameters={"properties": {}, "required": []},
            )
        ]

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(tool_use_id=tool_use.id, content="3:00 PM", is_error=False)

        result = provider.complete_with_tools(
            messages=[{"role": "user", "content": "What time is it?"}],
            system="You are a time assistant.",
            tools=tools,
            tool_executor=tool_executor,
        )

        assert result.content == "The time is 3:00 PM."
        mock_completion.assert_called_once()

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
        provider.complete(
            messages=[{"role": "user", "content": "Hello"}], system="You are helpful."
        )

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
        assert len(heartbeat_ticks) >= 3, (
            f"Event loop was blocked — only {len(heartbeat_ticks)} heartbeat ticks"
        )

    @pytest.mark.asyncio
    @patch("litellm.acompletion")
    async def test_acomplete_with_tools_uses_acompletion(self, mock_acompletion):
        """acomplete_with_tools() should use litellm.acompletion."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "tool result"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        async def async_return(*args, **kwargs):
            return mock_response

        mock_acompletion.side_effect = async_return

        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")
        tools = [
            Tool(
                name="search",
                description="Search the web",
                parameters={"properties": {"q": {"type": "string"}}, "required": ["q"]},
            )
        ]

        result = await provider.acomplete_with_tools(
            messages=[{"role": "user", "content": "Search for cats"}],
            system="You are helpful.",
            tools=tools,
            tool_executor=lambda tu: ToolResult(tool_use_id=tu.id, content="cats"),
        )

        assert result.content == "tool result"
        mock_acompletion.assert_called_once()

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

            def complete_with_tools(
                self, messages, system, tools, tool_executor, max_iterations=10
            ):
                return LLMResponse(content="sync tools done", model="slow")

        provider = SlowSyncProvider()
        main_thread_id = threading.current_thread().ident

        result = await provider.acomplete(
            messages=[{"role": "user", "content": "hi"}],
        )

        assert result.content == "sync done"
        # The sync complete() should have run on a different thread
        assert call_thread_ids[0] != main_thread_id, (
            "Base acomplete() should offload sync complete() to a thread pool"
        )


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
        from framework.runner.runner import AgentRunner

        assert AgentRunner._is_local_model(model) is True

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
        from framework.runner.runner import AgentRunner

        assert AgentRunner._is_local_model(model) is False
