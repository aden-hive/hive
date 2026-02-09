"""Mock LLM Provider for testing and structural validation without real LLM calls."""

import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamEvent,
    TextDeltaEvent,
    TextEndEvent,
)


class MockLLMProvider(LLMProvider):
    """
    Mock LLM provider for testing agents without making real API calls.

    This provider generates placeholder responses based on the expected output structure,
    allowing structural validation and graph execution testing without incurring costs
    or requiring API keys.
    """

    def __init__(self, model: str = "mock-model"):
        """
        Initialize the mock LLM provider.

        Args:
            model: Model name to report in responses (default: "mock-model")
        """
        self.model = model
        self._call_count = 0

    def _extract_output_keys(self, system: str) -> list[str]:
        """
        Extract expected output keys from the system prompt.
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
            all_matches = re.findall(r'"([a-zA-Z0-9_]+)":\s*', system)
            if all_matches:
                return list(set(all_matches))

        return keys

    def _generate_mock_output(self, system: str) -> dict[str, str]:
        """Generate mock output keys and values based on the system prompt."""
        keys = self._extract_output_keys(system)
        if not keys:
            return {"result": f"mock_result_{self._call_count}"}
        return {key: f"mock_{key}_value_{self._call_count}" for key in keys}

    def _generate_mock_response(
        self,
        system: str = "",
        json_mode: bool = False,
    ) -> str:
        """
        Generate a mock response based on the system prompt and mode.
        """
        if json_mode:
            mock_data = self._generate_mock_output(system)
            return json.dumps(mock_data, indent=2)
        else:
            return f"This is a mock response (call #{self._call_count}) for testing purposes."

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a mock completion without calling a real LLM."""
        self._call_count += 1
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
        """Generate a mock completion without tool use."""
        self._call_count += 1
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
        """Stream a mock completion. If set_output is available, it will call it."""
        self._call_count += 1
        content = self._generate_mock_response(system=system, json_mode=False)
        accumulated = ""

        # Stream text deltas
        words = content.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            accumulated += chunk
            yield TextDeltaEvent(content=chunk, snapshot=accumulated)

        # In EventLoopNode, we need tool calls to progress or complete.
        # If the agent has a 'set_output' tool, simulate using it to fulfill requirements.
        if tools:
            set_output_tool = next((t for t in tools if t.name == "set_output"), None)
            if set_output_tool:
                mock_data = self._generate_mock_output(system)
                for key, value in mock_data.items():
                    yield ToolCallEvent(
                        tool_use_id=f"mock_call_{self._call_count}_{key}",
                        tool_name="set_output",
                        tool_input={"key": key, "value": str(value)},
                    )

        yield TextEndEvent(full_text=accumulated)
        yield FinishEvent(stop_reason="mock_complete", model=self.model)
