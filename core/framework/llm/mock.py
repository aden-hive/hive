"""Mock LLM Provider for testing and structural validation without real LLM calls."""

import json
import re
from collections.abc import Callable
from typing import Any

from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse


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

    def __init__(self, model: str = "mock-model"):
        """
        Initialize the mock LLM provider.

        Args:
            model: Model name to report in responses (default: "mock-model")
        """
        self.model = model

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
