"""LiteLLM provider for pluggable multi-provider LLM support.

LiteLLM provides a unified, OpenAI-compatible interface that supports
multiple LLM providers including OpenAI, Anthropic, Gemini, Mistral,
Groq, and local models.

See: https://docs.litellm.ai/docs/providers
"""

import json
from typing import Any

import litellm

from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolUse, ToolResult


class LiteLLMProvider(LLMProvider):
    """
    LiteLLM-based LLM provider for multi-provider support.

    Supports any model that LiteLLM supports, including:
    - OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
    - Anthropic: claude-3-opus, claude-3-sonnet, claude-3-haiku
    - Google: gemini-pro, gemini-1.5-pro, gemini-1.5-flash
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

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate a completion using LiteLLM."""
        # Prepare messages with system prompt
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

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

        # Make the call
        response = litellm.completion(**kwargs)

        # Extract content
        content = response.choices[0].message.content or ""

        # Get usage info
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return LLMResponse(
            content=content,
            model=response.model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=response.choices[0].finish_reason or "",
            raw_response=response,
        )

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: callable,
        max_iterations: int = 10,
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
                "max_tokens": 1024,
                "tools": openai_tools,
                **self.extra_kwargs,
            }

            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["api_base"] = self.api_base

            response = litellm.completion(**kwargs)

            # Track tokens
            usage = response.usage
            if usage:
                total_input_tokens += usage.prompt_tokens
                total_output_tokens += usage.completion_tokens

            choice = response.choices[0]
            message = choice.message

            # Check if we're done (no tool calls)
            if choice.finish_reason == "stop" or not message.tool_calls:
                return LLMResponse(
                    content=message.content or "",
                    model=response.model or self.model,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    stop_reason=choice.finish_reason or "stop",
                    raw_response=response,
                )

            # Process tool calls.
            # Add assistant message with tool calls.
            current_messages.append({
                "role": "assistant",
                "content": message.content,
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
            })

            # Execute tools and add results.
            for tool_call in message.tool_calls:
                # Parse arguments
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                tool_use = ToolUse(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=args,
                )

                result = tool_executor(tool_use)

                # Add tool result message
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": result.tool_use_id,
                    "content": result.content,
                })

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
