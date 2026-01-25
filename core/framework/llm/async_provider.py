"""
Async LLM Provider

Async wrapper for LLM providers with:
- Full async support for all operations
- Connection pooling integration
- Rate limiting and circuit breaking
- Performance metrics
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolUse, ToolResult
from framework.resilience import RateLimiter, CircuitBreaker, get_rate_limiter, get_circuit_breaker

logger = logging.getLogger(__name__)


@dataclass
class AsyncLLMResponse:
    """Async LLM response with additional metrics."""
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    raw_response: Any = None
    latency_ms: float = 0
    from_cache: bool = False
    
    def to_sync_response(self) -> LLMResponse:
        """Convert to sync LLMResponse for compatibility."""
        return LLMResponse(
            content=self.content,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            stop_reason=self.stop_reason,
            raw_response=self.raw_response,
        )


class AsyncLLMProvider(ABC):
    """
    Abstract async LLM provider.
    
    All async LLM providers should implement this interface.
    """
    
    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: Optional[list[Tool]] = None,
        max_tokens: int = 1024,
        response_format: Optional[dict[str, Any]] = None,
        json_mode: bool = False,
    ) -> AsyncLLMResponse:
        """Generate a completion asynchronously."""
        pass
    
    @abstractmethod
    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: Callable,
        max_iterations: int = 10,
    ) -> AsyncLLMResponse:
        """Run a tool-use loop asynchronously."""
        pass


class AsyncLiteLLMProvider(AsyncLLMProvider):
    """
    Async LiteLLM provider with resilience features.
    
    Features:
    - Full async support using litellm.acompletion
    - Rate limiting (tokens and requests)
    - Circuit breaker for automatic failover
    - Connection pooling
    
    Usage:
        provider = AsyncLiteLLMProvider(
            model="claude-3-5-sonnet-20241022",
            rate_limit_tokens_per_minute=100000,
            rate_limit_requests_per_minute=100,
        )
        
        response = await provider.complete(
            messages=[{"role": "user", "content": "Hello"}],
            system="You are a helpful assistant",
        )
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        rate_limit_tokens_per_minute: int = 100000,
        rate_limit_requests_per_minute: int = 100,
        enable_circuit_breaker: bool = True,
        temperature: float = 0.7,
        **kwargs: Any,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.temperature = temperature
        self.extra_kwargs = kwargs
        
        # Set up rate limiter
        self.rate_limiter = RateLimiter(
            tokens_per_minute=rate_limit_tokens_per_minute,
            requests_per_minute=rate_limit_requests_per_minute,
        )
        
        # Set up circuit breaker
        self.circuit_breaker = CircuitBreaker(
            name=f"llm:{model}",
            failure_threshold=5,
            recovery_timeout=30,
        ) if enable_circuit_breaker else None
    
    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: Optional[list[Tool]] = None,
        max_tokens: int = 1024,
        response_format: Optional[dict[str, Any]] = None,
        json_mode: bool = False,
    ) -> AsyncLLMResponse:
        """Generate a completion using async LiteLLM."""
        import litellm
        
        start_time = time.perf_counter()
        
        # Estimate tokens for rate limiting
        estimated_tokens = sum(len(m.get("content", "")) // 4 for m in messages) + max_tokens
        
        # Wait for rate limit
        await self.rate_limiter.acquire(tokens_needed=estimated_tokens)
        
        # Build messages with system prompt
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)
        
        # Build kwargs
        kwargs = {
            "model": self.model,
            "messages": all_messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            **self.extra_kwargs,
        }
        
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        
        # Add response format for JSON mode
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        elif response_format:
            kwargs["response_format"] = response_format
        
        # Add tools if provided
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]
        
        # Execute with circuit breaker
        async def make_call():
            return await litellm.acompletion(**kwargs)
        
        if self.circuit_breaker:
            response = await self.circuit_breaker.call(make_call)
        else:
            response = await make_call()
        
        end_time = time.perf_counter()
        
        # Parse response
        content = ""
        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content or ""
        
        return AsyncLLMResponse(
            content=content,
            model=response.model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            stop_reason=response.choices[0].finish_reason if response.choices else "",
            raw_response=response,
            latency_ms=(end_time - start_time) * 1000,
        )
    
    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: Callable,
        max_iterations: int = 10,
    ) -> AsyncLLMResponse:
        """Run an async tool-use loop."""
        import litellm
        
        start_time = time.perf_counter()
        total_input_tokens = 0
        total_output_tokens = 0
        
        # Build initial messages
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)
        
        openai_tools = [self._tool_to_openai_format(t) for t in tools]
        
        for iteration in range(max_iterations):
            # Estimate and acquire rate limit
            estimated_tokens = sum(len(str(m)) // 4 for m in all_messages) + 1024
            await self.rate_limiter.acquire(tokens_needed=estimated_tokens)
            
            kwargs = {
                "model": self.model,
                "messages": all_messages,
                "tools": openai_tools,
                "temperature": self.temperature,
                **self.extra_kwargs,
            }
            
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["api_base"] = self.api_base
            
            # Make async call
            async def make_call():
                return await litellm.acompletion(**kwargs)
            
            if self.circuit_breaker:
                response = await self.circuit_breaker.call(make_call)
            else:
                response = await make_call()
            
            # Track tokens
            if response.usage:
                total_input_tokens += response.usage.prompt_tokens
                total_output_tokens += response.usage.completion_tokens
            
            # Check for tool calls
            message = response.choices[0].message
            
            if not message.tool_calls:
                # No tool calls - we're done
                end_time = time.perf_counter()
                return AsyncLLMResponse(
                    content=message.content or "",
                    model=response.model,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    stop_reason=response.choices[0].finish_reason,
                    latency_ms=(end_time - start_time) * 1000,
                )
            
            # Add assistant message with tool calls
            all_messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in message.tool_calls
                ]
            })
            
            # Execute tool calls
            for tool_call in message.tool_calls:
                import json
                
                tool_use = ToolUse(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=json.loads(tool_call.function.arguments),
                )
                
                # Execute tool (may be async)
                if asyncio.iscoroutinefunction(tool_executor):
                    result = await tool_executor(tool_use)
                else:
                    result = tool_executor(tool_use)
                
                # Add tool result
                all_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result.content if hasattr(result, 'content') else str(result),
                })
        
        # Max iterations reached
        end_time = time.perf_counter()
        return AsyncLLMResponse(
            content="Maximum tool iterations reached",
            model=self.model,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            stop_reason="max_iterations",
            latency_ms=(end_time - start_time) * 1000,
        )
    
    def _tool_to_openai_format(self, tool: Tool) -> dict[str, Any]:
        """Convert Tool to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters or {"type": "object", "properties": {}},
            }
        }
    
    def get_stats(self) -> dict[str, Any]:
        """Get provider statistics."""
        stats = {
            "model": self.model,
            "rate_limiter": self.rate_limiter.get_stats(),
        }
        if self.circuit_breaker:
            stats["circuit_breaker"] = self.circuit_breaker.get_stats()
        return stats


class SyncToAsyncWrapper(AsyncLLMProvider):
    """
    Wrapper to use sync LLMProvider as async.
    
    For gradual migration from sync to async.
    """
    
    def __init__(self, sync_provider: LLMProvider):
        self.sync_provider = sync_provider
    
    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: Optional[list[Tool]] = None,
        max_tokens: int = 1024,
        response_format: Optional[dict[str, Any]] = None,
        json_mode: bool = False,
    ) -> AsyncLLMResponse:
        """Wrap sync complete in async."""
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.sync_provider.complete(
                messages, system, tools, max_tokens, response_format, json_mode
            )
        )
        return AsyncLLMResponse(
            content=response.content,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            stop_reason=response.stop_reason,
            raw_response=response.raw_response,
        )
    
    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: Callable,
        max_iterations: int = 10,
    ) -> AsyncLLMResponse:
        """Wrap sync complete_with_tools in async."""
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.sync_provider.complete_with_tools(
                messages, system, tools, tool_executor, max_iterations
            )
        )
        return AsyncLLMResponse(
            content=response.content,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            stop_reason=response.stop_reason,
            raw_response=response.raw_response,
        )
