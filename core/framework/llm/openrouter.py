"""Minimal OpenRouter LLM provider for development/testing.

This provider is intentionally small and intended for development use only.
If `OPENROUTER_API_KEY` is set the starter agent example will use this provider;
otherwise the framework will fall back to `MockLLMProvider`.

Uses OpenAI client for OpenRouter API compatibility, including automatic retry
logic for transient errors (429 rate limits, etc.).
"""

import json
from typing import Any

from framework.llm.provider import LLMProvider, LLMResponse, Tool

from openai import OpenAI



class OpenRouterProvider(LLMProvider):
    """OpenRouter provider using OpenAI client for automatic retry logic.

    Uses the OpenAI Python client pointed at OpenRouter's API base.
    This provides:
    - Automatic retries on 429 (rate limit) and 5xx errors
    - Exponential backoff
    - Cleaner API handling

    Usage:
        provider = OpenRouterProvider(
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            model="meta-llama/llama-3.2-3b-instruct:free"
        )
    """

    def __init__(self, model: str, api_key: str, api_base: str | None = None):
        if OpenAI is None:
            raise ImportError(
                "OpenAI client is required for OpenRouterProvider. Install with: pip install openai"
            )

        self.model = model
        self.api_key = api_key
        self.api_base = api_base or "https://openrouter.ai/api/v1"

        # Initialize OpenAI client pointed at OpenRouter
        self.client = OpenAI(
            base_url=self.api_base,
            api_key=self.api_key,
            # OpenAI client has built-in retry logic: retries on 429, 5xx, and connection errors
            # Default: 2 max retries with exponential backoff
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a completion using OpenAI client (routed to OpenRouter)."""
        # Prepare messages with system prompt
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        # Debug output
        print(f"[OpenRouter Debug] Model: {self.model}")
        print(f"[OpenRouter Debug] API Base: {self.api_base}")
        print(f"[OpenRouter Debug] API Key present: {bool(self.api_key)}")

        # Make request via OpenAI client (with automatic retry logic)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=0.2,
            )
        except Exception as e:
            print("[OpenRouter Debug] Request failed before completion.")
            print(f"[OpenRouter Debug] Error type: {type(e).__name__}")
            print(f"[OpenRouter Debug] Error: {e}")
            raise

        # Extract response data
        try:
            content = response.choices[0].message.content or ""
        except Exception as e:
            print("[OpenRouter Debug] Malformed response (no choices).")
            try:
                print(f"[OpenRouter Debug] Raw response: {response}")
            except Exception:
                print("[OpenRouter Debug] Raw response could not be printed.")
            print(f"[OpenRouter Debug] Error type: {type(e).__name__}")
            print(f"[OpenRouter Debug] Error: {e}")
            raise

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        return LLMResponse(
            content=content,
            model=self.model,
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
        tool_executor,
        max_iterations: int = 10,
    ) -> LLMResponse:
        """Tool-call loop not implemented for OpenRouter (lightweight provider)."""
        # Lightweight: single call only. Tool loops require more complex state management.
        # Tool-call can be implemented for testing and development
        return self.complete(messages=messages, system=system, tools=None)
