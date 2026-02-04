"""Mock LLM Provider for testing and structural validation without real LLM calls."""

import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamErrorEvent,
    StreamEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
)


class MockLLMProvider(LLMProvider):
    """
    Mock LLM provider for testing agents without making real API calls.

    This provider generates placeholder responses based on the expected output structure,
    allowing structural validation and graph execution testing without incurring costs
    or requiring API keys.

    Example:
        llm = MockLLMProvider()
        response = llm.complete(
            messages=[{"role": "user", "content": "test"}],
            system="Generate JSON with keys: name, age",
            json_mode=True
        )
        # Returns: {"name": "mock_value", "age": "mock_value"}
    """

    def __init__(
        self,
        model: str = "mock-model",
        scenarios: list[list[StreamEvent]] | None = None,
    ):
        """
        Initialize the mock LLM provider.

        Args:
            model: Model name to report in responses (default: "mock-model")
            scenarios: Optional list of pre-programmed StreamEvent sequences.
                Each call to stream() consumes the next scenario, cycling
                back when exhausted. If None, stream() falls back to the
                default word-splitting behavior.
        """
        self.model = model
        self.scenarios = scenarios or []
        self._call_index = 0
        self.stream_calls: list[dict] = []

    def _extract_output_keys(self, system: str) -> list[str]:
        """
        Extract expected output keys from the system prompt.

        Looks for patterns like:
        - "output_keys: [key1, key2]"
        - "keys: key1, key2"
        - "Generate JSON with keys: key1, key2"

        Args:
            system: System prompt text

        Returns:
            List of extracted key names
        """
        keys = []

        # Pattern 1: output_keys: [key1, key2]
        match = re.search(r"output_keys:\s*\[(.*?)\]", system, re.IGNORECASE)
        if match:
            keys_str = match.group(1)
            keys = [k.strip().strip("\"'") for k in keys_str.split(",")]
            return keys

        # Pattern 2: "keys: key1, key2" or "Generate JSON with keys: key1, key2"
        match = re.search(r"(?:keys|with keys):\s*([a-zA-Z0-9_,\s]+)", system, re.IGNORECASE)
        if match:
            keys_str = match.group(1)
            keys = [k.strip() for k in keys_str.split(",") if k.strip()]
            return keys

        # Pattern 3: Look for JSON schema in system prompt
        match = re.search(r'\{[^}]*"([a-zA-Z0-9_]+)":\s*', system)
        if match:
            # Found at least one key in a JSON-like structure
            all_matches = re.findall(r'"([a-zA-Z0-9_]+)":\s*', system)
            if all_matches:
                return list(set(all_matches))

        return keys

    def _generate_mock_response(
        self,
        system: str = "",
        json_mode: bool = False,
    ) -> str:
        """
        Generate a mock response based on the system prompt and mode.

        Args:
            system: System prompt (may contain output key hints)
            json_mode: If True, generate JSON response

        Returns:
            Mock response string
        """
        if json_mode:
            # Try to extract expected keys from system prompt
            keys = self._extract_output_keys(system)

            if keys:
                # Generate JSON with the expected keys
                mock_data = {key: f"mock_{key}_value" for key in keys}
                return json.dumps(mock_data, indent=2)
            else:
                # Fallback: generic mock response
                return json.dumps({"result": "mock_result_value"}, indent=2)
        else:
            # Plain text mock response
            return "This is a mock response for testing purposes."

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """
        Generate a mock completion without calling a real LLM.

        Args:
            messages: Conversation history (ignored in mock mode)
            system: System prompt (used to extract expected output keys)
            tools: Available tools (ignored in mock mode)
            max_tokens: Maximum tokens (ignored in mock mode)
            response_format: Response format (ignored in mock mode)
            json_mode: If True, generate JSON response

        Returns:
            LLMResponse with mock content
        """
        content = self._generate_mock_response(system=system, json_mode=json_mode)

        return LLMResponse(
            content=content,
            model=self.model,
            input_tokens=0,
            output_tokens=0,
            stop_reason="mock_complete",
        )

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: Callable[[ToolUse], ToolResult],
        max_iterations: int = 10,
    ) -> LLMResponse:
        """
        Generate a mock completion without tool use.

        In mock mode, we skip tool execution and return a final response immediately.

        Args:
            messages: Initial conversation (ignored in mock mode)
            system: System prompt (used to extract expected output keys)
            tools: Available tools (ignored in mock mode)
            tool_executor: Tool executor function (ignored in mock mode)
            max_iterations: Max iterations (ignored in mock mode)

        Returns:
            LLMResponse with mock content
        """
        # In mock mode, we don't execute tools - just return a final response
        # Try to generate JSON if the system prompt suggests structured output
        json_mode = "json" in system.lower() or "output_keys" in system.lower()

        content = self._generate_mock_response(system=system, json_mode=json_mode)

        return LLMResponse(
            content=content,
            model=self.model,
            input_tokens=0,
            output_tokens=0,
            stop_reason="mock_complete",
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a mock completion.

        With scenarios: yield events from next scenario, cycling via
        ``_call_index % len(scenarios)``.

        Without scenarios: fall back to word-splitting behavior (backward
        compatible).

        Every call is recorded in ``self.stream_calls`` for test assertions.
        """
        self.stream_calls.append({"messages": messages, "system": system, "tools": tools})

        if self.scenarios:
            events = self.scenarios[self._call_index % len(self.scenarios)]
            self._call_index += 1
            for event in events:
                yield event
        else:
            # Original default behavior preserved
            content = self._generate_mock_response(system=system, json_mode=False)
            words = content.split(" ")
            accumulated = ""
            for i, word in enumerate(words):
                chunk = word if i == 0 else " " + word
                accumulated += chunk
                yield TextDeltaEvent(content=chunk, snapshot=accumulated)
            yield TextEndEvent(full_text=accumulated)
            yield FinishEvent(stop_reason="mock_complete", model=self.model)


# ---------------------------------------------------------------------------
# Scenario helpers — convenience builders for common stream event sequences
# ---------------------------------------------------------------------------


def text_scenario(text: str, input_tokens: int = 10, output_tokens: int = 5) -> list[StreamEvent]:
    """Build a stream scenario that produces text and finishes."""
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(
            stop_reason="stop",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model="mock",
        ),
    ]


def tool_call_scenario(
    tool_name: str,
    tool_input: dict,
    tool_use_id: str = "call_1",
    text: str = "",
) -> list[StreamEvent]:
    """Build a stream scenario that produces a tool call (optionally preceded by text)."""
    events: list[StreamEvent] = []
    if text:
        events.append(TextDeltaEvent(content=text, snapshot=text))
    events.append(
        ToolCallEvent(tool_use_id=tool_use_id, tool_name=tool_name, tool_input=tool_input)
    )
    events.append(
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock")
    )
    return events


def error_scenario(error: str = "Connection lost", recoverable: bool = False) -> list[StreamEvent]:
    """Build a stream scenario that produces a StreamErrorEvent."""
    return [StreamErrorEvent(error=error, recoverable=recoverable)]
