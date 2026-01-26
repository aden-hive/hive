"""Tests for LiteLLM provider.

Run with:
    cd core
    pip install litellm pytest
    pytest tests/test_litellm_provider.py -v

For live tests (requires API keys):
    OPENAI_API_KEY=sk-... pytest tests/test_litellm_provider.py -v -m live
"""

import os
from unittest.mock import patch, MagicMock

from framework.llm.litellm import LiteLLMProvider
from framework.llm.anthropic import AnthropicProvider
from framework.llm.provider import LLMProvider, Tool, ToolUse, ToolResult


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

    def test_init_with_api_key(self):
        """Test initialization with explicit API key."""
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="my-api-key")
        assert provider.api_key == "my-api-key"

    def test_init_with_api_base(self):
        """Test initialization with custom API base."""
        provider = LiteLLMProvider(
            model="gpt-4o-mini",
            api_key="my-key",
            api_base="https://my-proxy.com/v1"
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
        result = provider.complete(
            messages=[{"role": "user", "content": "Hello"}]
        )

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
            messages=[{"role": "user", "content": "Hello"}],
            system="You are a helpful assistant."
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
                    "properties": {
                        "location": {"type": "string", "description": "City name"}
                    },
                    "required": ["location"]
                }
            )
        ]

        provider.complete(
            messages=[{"role": "user", "content": "What's the weather?"}],
            tools=tools
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
        tool_call_response.choices[0].message.tool_calls[0].function.arguments = '{"location": "London"}'
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
                parameters={"properties": {"location": {"type": "string"}}, "required": ["location"]}
            )
        ]

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="Sunny, 22C",
                is_error=False
            )

        result = provider.complete_with_tools(
            messages=[{"role": "user", "content": "What's the weather in London?"}],
            system="You are a weather assistant.",
            tools=tools,
            tool_executor=tool_executor
        )

        assert result.content == "The weather in London is sunny."
        assert result.input_tokens == 50  # 20 + 30
        assert result.output_tokens == 25  # 15 + 10
        assert mock_completion.call_count == 2


class TestToolConversion:
    """Test tool format conversion."""

    def test_tool_to_openai_format(self):
        """Test converting Tool to OpenAI format."""
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

        tool = Tool(
            name="search",
            description="Search the web",
            parameters={
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
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
            max_tokens=100
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
                parameters={"properties": {}, "required": []}
            )
        ]

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(tool_use_id=tool_use.id, content="3:00 PM", is_error=False)

        result = provider.complete_with_tools(
            messages=[{"role": "user", "content": "What time is it?"}],
            system="You are a time assistant.",
            tools=tools,
            tool_executor=tool_executor
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

        provider.complete(
            messages=[{"role": "user", "content": "hi"}],
            response_format=fmt
        )

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
            json_mode=True
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
        provider.complete(
            messages=[{"role": "user", "content": "Return JSON"}],
            json_mode=True
        )

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
            json_mode=False
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
            messages=[{"role": "user", "content": "Hello"}],
            system="You are helpful."
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
            json_mode=True
        )

        call_kwargs = mock_completion.call_args[1]
        # Should NOT use response_format
        assert "response_format" not in call_kwargs
        # Should have JSON instruction in system prompt
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "Please respond with a valid JSON object" in messages[0]["content"]
