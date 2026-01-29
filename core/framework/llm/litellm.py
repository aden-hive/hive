"""LiteLLM provider for pluggable multi-provider LLM support.

LiteLLM provides a unified, OpenAI-compatible interface that supports
multiple LLM providers including OpenAI, Anthropic, Gemini, Mistral,
Groq, and local models.

See: https://docs.litellm.ai/docs/providers
"""

import json
import logging
from collections.abc import Callable
from typing import Any

try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse

logger = logging.getLogger(__name__)


class LiteLLMProvider(LLMProvider):
    """
    LiteLLM-based LLM provider for multi-provider support.

    Supports any model that LiteLLM supports, including:
    - OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
    - Anthropic: claude-3-opus, claude-3-sonnet, claude-3-haiku
    - Google: gemini-pro, gemini-1.5-pro, gemini-1.5-flash
    - DeepSeek: deepseek-chat, deepseek-coder, deepseek-reasoner
    - Mistral: mistral-large, mistral-medium, mistral-small
    - Groq: llama3-70b, mixtral-8x7b
    - Local: ollama/llama3, ollama/mistral
    - And many more...

    Usage:
        # OpenAI
        provider = LiteLLMProvider(model="gpt-4o-mini")

        # Anthropic
        provider = LiteLLMProvider(model="claude-3-haiku-20240307")

        # Google Gemini
        provider = LiteLLMProvider(model="gemini/gemini-1.5-flash")

        # DeepSeek
        provider = LiteLLMProvider(model="deepseek/deepseek-chat")

        # Local Ollama
        provider = LiteLLMProvider(model="ollama/llama3")

        # With custom API base
        provider = LiteLLMProvider(
            model="gpt-4o-mini",
            api_base="https://my-proxy.com/v1"
        )
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ):
        """
        Initialize the LiteLLM provider.

        Args:
            model: Model identifier (e.g., "gpt-4o-mini", "claude-3-haiku-20240307")
                   LiteLLM auto-detects the provider from the model name.
            api_key: API key for the provider. If not provided, LiteLLM will
                     look for the appropriate env var (OPENAI_API_KEY,
                     ANTHROPIC_API_KEY, etc.)
            api_base: Custom API base URL (for proxies or local deployments)
            **kwargs: Additional arguments passed to litellm.completion()
        """
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.extra_kwargs = kwargs

        if litellm is None:
            raise ImportError(
                "LiteLLM is not installed. Please install it with: pip install litellm"
            )

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a completion using LiteLLM."""
        # Prepare messages with system prompt
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        # Add JSON mode via prompt engineering (works across all providers)
        if json_mode:
            json_instruction = "\n\nPlease respond with a valid JSON object."
            # Append to system message if present, otherwise add as system message
            if full_messages and full_messages[0]["role"] == "system":
                full_messages[0]["content"] += json_instruction
            else:
                full_messages.insert(0, {"role": "system", "content": json_instruction.strip()})

        # Build kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            **self.extra_kwargs,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Add tools if provided
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]

        # Add response_format for structured output
        # LiteLLM passes this through to the underlying provider
        if response_format:
            kwargs["response_format"] = response_format

        # Make the call with error handling
        try:
            response = litellm.completion(**kwargs)  # type: ignore[union-attr]
        except Exception as e:
            logger.error(f"LiteLLM completion failed: {type(e).__name__}: {e}")
            raise RuntimeError(f"LLM API call failed: {type(e).__name__}: {e}") from e

        # Extract content with safe access
        if not response.choices:
            logger.error("LLM response has no choices")
            raise RuntimeError("LLM response has no choices")

        choice = response.choices[0]
        content = getattr(choice.message, "content", None) or ""

        # Get usage info
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        return LLMResponse(
            content=content,
            model=response.model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=getattr(choice, "finish_reason", "") or "",
            raw_response=response,
        )

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: Callable[[ToolUse], ToolResult],
        max_iterations: int = 10,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Run a tool-use loop until the LLM produces a final response."""
        # Prepare messages with system prompt
        current_messages = []
        if system:
            current_messages.append({"role": "system", "content": system})
        current_messages.extend(messages)

        total_input_tokens = 0
        total_output_tokens = 0

        # Convert tools to OpenAI format
        openai_tools = [self._tool_to_openai_format(t) for t in tools]

        for _ in range(max_iterations):
            # Build kwargs
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": current_messages,
                "max_tokens": max_tokens,
                "tools": openai_tools,
                **self.extra_kwargs,
            }

            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["api_base"] = self.api_base

            try:
                response = litellm.completion(**kwargs)  # type: ignore[union-attr]
            except Exception as e:
                logger.error(f"LiteLLM completion with tools failed: {type(e).__name__}: {e}")
                raise RuntimeError(f"LLM API call failed: {type(e).__name__}: {e}") from e

            # Track tokens with safe access
            usage = response.usage
            if usage:
                total_input_tokens += getattr(usage, "prompt_tokens", 0)
                total_output_tokens += getattr(usage, "completion_tokens", 0)

            # Validate response has choices
            if not response.choices:
                logger.error("LLM response has no choices in tool loop")
                raise RuntimeError("LLM response has no choices")

            choice = response.choices[0]
            message = choice.message

            # Check if we're done (no tool calls)
            if getattr(choice, "finish_reason", "") == "stop" or not getattr(message, "tool_calls", None):
                return LLMResponse(
                    content=getattr(message, "content", "") or "",
                    model=response.model or self.model,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    stop_reason=getattr(choice, "finish_reason", "") or "stop",
                    raw_response=response,
                )

            # Process tool calls.
            # Add assistant message with tool calls.
            current_messages.append(
                {
                    "role": "assistant",
                    "content": getattr(message, "content", None),
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            # Execute tools and add results.
            for tool_call in message.tool_calls:
                # Parse arguments with safe access
                try:
                    arguments = getattr(tool_call.function, "arguments", "{}")
                    if arguments is None:
                        arguments = "{}"
                    args = json.loads(arguments)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Failed to parse tool arguments: {e}")
                    args = {}

                tool_use = ToolUse(
                    id=tool_call.id,
                    name=getattr(tool_call.function, "name", "unknown"),
                    input=args,
                )

                # Execute tool with error handling
                try:
                    result = tool_executor(tool_use)
                except Exception as e:
                    logger.error(f"Tool execution failed for {tool_use.name}: {type(e).__name__}: {e}")
                    result = ToolResult(
                        tool_use_id=tool_use.id,
                        content=f"Error executing tool: {type(e).__name__}: {e}",
                        is_error=True,
                    )

                # Add tool result message
                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.tool_use_id,
                        "content": result.content,
                    }
                )

        # Max iterations reached
        return LLMResponse(
            content="Max tool iterations reached",
            model=self.model,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            stop_reason="max_iterations",
            raw_response=None,
        )

    def _tool_to_openai_format(self, tool: Tool) -> dict[str, Any]:
        """Convert Tool to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.parameters.get("properties", {}),
                    "required": tool.parameters.get("required", []),
                },
            },
        }
