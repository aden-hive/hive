"""Anthropic Claude LLM provider."""

import os
from typing import Any

import anthropic

from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolUse, ToolResult


class AnthropicProvider(LLMProvider):
    """
    Anthropic Claude LLM provider.

    Uses the Anthropic API to interact with Claude models.
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
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key."
            )

        self.model = model
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate a completion from Claude."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        if system:
            kwargs["system"] = system

        if tools:
            kwargs["tools"] = [self._tool_to_dict(t) for t in tools]

        response = self.client.messages.create(**kwargs)

        # Extract text content
        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
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

    def _tool_to_dict(self, tool: Tool) -> dict[str, Any]:
        """Convert Tool to Anthropic API format."""
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                "type": "object",
                "properties": tool.parameters.get("properties", {}),
                "required": tool.parameters.get("required", []),
            },
        }
