"""Anthropic Claude LLM provider - backward compatible wrapper around LiteLLM."""

from typing import Any

from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.litellm import LiteLLMProvider


class AnthropicProvider(LLMProvider):
    """
    Anthropic Claude LLM provider.

    This is a backward-compatible wrapper that internally uses LiteLLMProvider.
    Existing code using AnthropicProvider will continue to work unchanged,
    while benefiting from LiteLLM's unified interface and features.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ):
        """
        Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
            model: Model to use (default: claude-haiku-4-5-20251001)
        """
        # Delegate to LiteLLMProvider internally.
        self._provider = LiteLLMProvider(
            model=model,
            api_key=api_key,
        )
        self.model = model
        self.api_key = api_key

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate a completion from Claude (via LiteLLM)."""
        return self._provider.complete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
        )

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: callable,
        max_iterations: int = 10,
    ) -> LLMResponse:
        """Run a tool-use loop until Claude produces a final response."""
        current_messages = list(messages)
        total_input_tokens = 0
        total_output_tokens = 0

        for _ in range(max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system,
                messages=current_messages,
                tools=[self._tool_to_dict(t) for t in tools],
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Check if we're done (no more tool use)
            if response.stop_reason == "end_turn":
                content = ""
                for block in response.content:
                    if block.type == "text":
                        content += block.text

                return LLMResponse(
                    content=content,
                    model=response.model,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    stop_reason=response.stop_reason,
                    raw_response=response,
                )

            # Process tool uses
            tool_uses = []
            assistant_content = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_uses.append(
                        ToolUse(id=block.id, name=block.name, input=block.input)
                    )
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                elif block.type == "text":
                    assistant_content.append({
                        "type": "text",
                        "text": block.text,
                    })

            # Add assistant message with tool uses
            current_messages.append({
                "role": "assistant",
                "content": assistant_content,
            })

            # Execute tools and add results
            tool_results = []
            for tool_use in tool_uses:
                result = tool_executor(tool_use)
                # Ensure content is never empty (Anthropic API requires non-empty content)
                content = result.content if result.content else "(empty result)"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": result.tool_use_id,
                    "content": content,
                    "is_error": result.is_error,
                })

            current_messages.append({
                "role": "user",
                "content": tool_results,
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
