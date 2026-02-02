"""LiteLLM provider for pluggable multi-provider LLM support.

LiteLLM provides a unified, OpenAI-compatible interface that supports
multiple LLM providers including OpenAI, Anthropic, Gemini, Mistral,
Groq, and local models.

See: https://docs.litellm.ai/docs/providers
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import litellm
    from litellm.exceptions import RateLimitError
except ImportError:
    litellm = None  # type: ignore[assignment]
    RateLimitError = Exception  # type: ignore[assignment, misc]

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

    def _completion_with_rate_limit_retry(self, **kwargs: Any) -> Any:
        """Call litellm.completion with retry on 429 rate limit errors and empty responses."""
        model = kwargs.get("model", self.model)
        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            try:
                response = litellm.completion(**kwargs)  # type: ignore[union-attr]

                # Some providers (e.g. Gemini) return 200 with empty content on
                # rate limit / quota exhaustion instead of a proper 429.  Treat
                # empty responses the same as a rate-limit error and retry.
                content = response.choices[0].message.content if response.choices else None
                has_tool_calls = bool(response.choices and response.choices[0].message.tool_calls)
                if not content and not has_tool_calls:
                    finish_reason = (
                        response.choices[0].finish_reason if response.choices else "unknown"
                    )
                    # Dump full request to file for debugging
                    messages = kwargs.get("messages", [])
                    token_count, token_method = _estimate_tokens(model, messages)
                    dump_path = _dump_failed_request(
                        model=model,
                        kwargs=kwargs,
                        error_type="empty_response",
                        attempt=attempt,
                    )
                    logger.warning(
                        f"[retry] Empty response - {len(messages)} messages, "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )

                    if attempt == RATE_LIMIT_MAX_RETRIES:
                        logger.error(
                            f"[retry] GAVE UP on {model} after {RATE_LIMIT_MAX_RETRIES + 1} "
                            f"attempts — empty response "
                            f"(finish_reason={finish_reason}, "
                            f"choices={len(response.choices) if response.choices else 0})"
                        )
                        return response
                    wait = RATE_LIMIT_BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        f"[retry] {model} returned empty response "
                        f"(finish_reason={finish_reason}, "
                        f"choices={len(response.choices) if response.choices else 0}) — "
                        f"likely rate limited or quota exceeded. "
                        f"Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES})"
                    )
                    time.sleep(wait)
                    continue

                return response
            except RateLimitError as e:
                # Dump full request to file for debugging
                messages = kwargs.get("messages", [])
                token_count, token_method = _estimate_tokens(model, messages)
                dump_path = _dump_failed_request(
                    model=model,
                    kwargs=kwargs,
                    error_type="rate_limit",
                    attempt=attempt,
                )
                if attempt == RATE_LIMIT_MAX_RETRIES:
                    logger.error(
                        f"[retry] GAVE UP on {model} after {RATE_LIMIT_MAX_RETRIES + 1} "
                        f"attempts — rate limit error: {e!s}. "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )
                    raise
                wait = RATE_LIMIT_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    f"[retry] {model} rate limited (429): {e!s}. "
                    f"~{token_count} tokens ({token_method}). "
                    f"Full request dumped to: {dump_path}. "
                    f"Retrying in {wait}s "
                    f"(attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES})"
                )
                time.sleep(wait)
        # unreachable, but satisfies type checker
        raise RuntimeError("Exhausted rate limit retries")

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

    def _safe_completion(self, **kwargs: Any) -> LLMResponse:
        """
        Execute litellm.completion with unified error handling and logging.
        """
        # Set default retries for transient errors if not manually specified
        if "num_retries" not in kwargs:
            kwargs["num_retries"] = 1

        try:
            response = litellm.completion(**kwargs)
            
            # Extract content (handle potentially different response structures if needed, 
            # but standard litellm response has choices[0].message.content)
            content = response.choices[0].message.content or ""
            
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

        except litellm.exceptions.AuthenticationError as e:
            logger.error(f"LiteLLM Authentication Error: {str(e)}. Please check your API key.")
            return LLMResponse(
                content=f"Authentication Error: {str(e)}",
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                stop_reason="error",
                raw_response=None,
            )
        except litellm.exceptions.RateLimitError as e:
            logger.error(f"LiteLLM Rate Limit Error: {str(e)}. Retries exhausted.")
            return LLMResponse(
                content=f"Rate Limit Error: {str(e)}",
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                stop_reason="error",
                raw_response=None,
            )
        except litellm.exceptions.APIConnectionError as e:
            logger.error(f"LiteLLM Connection Error: {str(e)}. Check your network.")
            return LLMResponse(
                content=f"Connection Error: {str(e)}",
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                stop_reason="error",
                raw_response=None,
            )
        except Exception as e:
            # Added exc_info=True to log full traceback for unexpected errors
            logger.error(f"LiteLLM unexpected completion failed: {str(e)}", exc_info=True)
            return LLMResponse(
                content=f"Error: {str(e)}",
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                stop_reason="error",
                raw_response=None,
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

        return self._safe_completion(**kwargs)

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

            # Use safe completion
            response = self._safe_completion(**kwargs)
            
            # Check for error in response
            if response.stop_reason == "error":
                # Propagate tokens used so far + current error tokens (0)
                response.input_tokens += total_input_tokens
                response.output_tokens += total_output_tokens
                return response

            # Track tokens
            total_input_tokens += response.input_tokens
            total_output_tokens += response.output_tokens

            # Check if we're done (no tool calls or explicit stop)
            # Access raw response to check for tool calls
            raw_response = response.raw_response
            choice = raw_response.choices[0]
            message = choice.message
            
            if choice.finish_reason == "stop" or not message.tool_calls:
                return LLMResponse(
                    content=message.content or "",
                    model=response.model,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    stop_reason=choice.finish_reason or "stop",
                    raw_response=raw_response,
                )

            # Process tool calls.
            # Add assistant message with tool calls.
            current_messages.append(
                {
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
                }
            )

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
