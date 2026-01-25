"""
Production Hardening: Rate Limiting, Circuit Breakers, and Resilience

Enterprise-grade resilience patterns for agent operations:
- Token bucket rate limiting
- Circuit breaker for external services
- Retry with exponential backoff
- Timeout management
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Rate Limiting
# =============================================================================

class RateLimiter:
    """
    Token bucket rate limiter for LLM API calls.
    
    Features:
    - Dual limits: tokens per minute AND requests per minute
    - Async-safe with proper locking
    - Automatic token refill
    - Wait functionality for rate-limited clients
    
    Usage:
        limiter = RateLimiter(
            tokens_per_minute=100000,
            requests_per_minute=100
        )
        
        # Before each API call
        await limiter.acquire(tokens_needed=1500)
        response = await api.call(...)
    """
    
    def __init__(
        self,
        tokens_per_minute: int = 100000,
        requests_per_minute: int = 100,
        burst_allowance: float = 1.2,  # Allow 20% burst
    ):
        self.tokens_per_minute = tokens_per_minute
        self.requests_per_minute = requests_per_minute
        self.burst_allowance = burst_allowance
        
        # Token buckets (with burst capacity)
        self._token_bucket = float(tokens_per_minute * burst_allowance)
        self._request_bucket = float(requests_per_minute * burst_allowance)
        
        self._token_bucket_max = tokens_per_minute * burst_allowance
        self._request_bucket_max = requests_per_minute * burst_allowance
        
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        
        # Statistics
        self.total_requests = 0
        self.total_tokens = 0
        self.total_waits = 0
        self.total_wait_time = 0.0
    
    async def acquire(
        self,
        tokens_needed: int = 0,
        timeout: Optional[float] = 60.0,
    ) -> bool:
        """
        Acquire rate limit tokens.
        
        Args:
            tokens_needed: Estimated tokens for this request
            timeout: Max time to wait for tokens (None = wait forever)
        
        Returns:
            True if acquired, False if timeout
        
        Raises:
            asyncio.TimeoutError if timeout exceeded
        """
        start_time = time.monotonic()
        
        async with self._lock:
            while True:
                self._refill()
                
                # Check if we have capacity
                if self._request_bucket >= 1 and self._token_bucket >= tokens_needed:
                    self._request_bucket -= 1
                    self._token_bucket -= tokens_needed
                    self.total_requests += 1
                    self.total_tokens += tokens_needed
                    return True
                
                # Calculate wait time
                wait_time = self._calculate_wait_time(tokens_needed)
                
                if timeout is not None:
                    elapsed = time.monotonic() - start_time
                    if elapsed + wait_time > timeout:
                        raise asyncio.TimeoutError(
                            f"Rate limit timeout: waited {elapsed:.1f}s, "
                            f"need {wait_time:.1f}s more"
                        )
                
                self.total_waits += 1
                self.total_wait_time += wait_time
                
                logger.debug(f"Rate limited, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
    
    def _refill(self) -> None:
        """Refill token buckets based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        
        if elapsed > 0:
            # Refill proportional to elapsed time
            token_refill = (elapsed / 60.0) * self.tokens_per_minute
            request_refill = (elapsed / 60.0) * self.requests_per_minute
            
            self._token_bucket = min(
                self._token_bucket + token_refill,
                self._token_bucket_max
            )
            self._request_bucket = min(
                self._request_bucket + request_refill,
                self._request_bucket_max
            )
            self._last_refill = now
    
    def _calculate_wait_time(self, tokens_needed: int) -> float:
        """Calculate how long to wait for sufficient capacity."""
        # Time to refill tokens
        token_deficit = max(0, tokens_needed - self._token_bucket)
        token_wait = (token_deficit / self.tokens_per_minute) * 60
        
        # Time to refill requests
        request_deficit = max(0, 1 - self._request_bucket)
        request_wait = (request_deficit / self.requests_per_minute) * 60
        
        return max(token_wait, request_wait, 0.1)  # Minimum 100ms
    
    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        return {
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "total_waits": self.total_waits,
            "total_wait_time": f"{self.total_wait_time:.2f}s",
            "avg_wait_time": f"{self.total_wait_time / max(1, self.total_waits):.2f}s",
            "current_token_bucket": f"{self._token_bucket:.0f}/{self._token_bucket_max:.0f}",
            "current_request_bucket": f"{self._request_bucket:.0f}/{self._request_bucket_max:.0f}",
        }


# =============================================================================
# Circuit Breaker
# =============================================================================

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing fast, not calling service
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitOpenError(Exception):
    """Raised when circuit is open and call is rejected."""
    
    def __init__(self, message: str, time_until_half_open: float = 0):
        super().__init__(message)
        self.time_until_half_open = time_until_half_open


@dataclass
class CircuitStats:
    """Circuit breaker statistics."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_transitions: list = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.successful_calls / self.total_calls


class CircuitBreaker:
    """
    Circuit breaker for external service calls.
    
    Prevents cascade failures by failing fast when a service is unhealthy.
    
    States:
    - CLOSED: Normal operation, calls go through
    - OPEN: Service failing, reject all calls immediately
    - HALF_OPEN: Testing recovery, allow limited calls
    
    Usage:
        circuit = CircuitBreaker(
            name="openai-api",
            failure_threshold=5,
            recovery_timeout=30
        )
        
        try:
            result = await circuit.call(api.generate, prompt)
        except CircuitOpenError:
            # Service is down, use fallback
            result = get_cached_response()
    """
    
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        success_threshold: int = 2,
        exclude_exceptions: tuple = (),
    ):
        """
        Args:
            name: Circuit name for logging/identification
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before trying recovery
            half_open_max_calls: Max calls in half-open state
            success_threshold: Successes needed to close circuit
            exclude_exceptions: Exceptions that don't count as failures
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        self.exclude_exceptions = exclude_exceptions
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        
        self.stats = CircuitStats()
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state
    
    async def call(
        self,
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> T:
        """
        Execute a function through the circuit breaker.
        
        Args:
            func: Async or sync function to call
            *args, **kwargs: Arguments for the function
        
        Returns:
            Function result
        
        Raises:
            CircuitOpenError: If circuit is open
            Exception: Original exception if call fails
        """
        async with self._lock:
            self._check_state_transition()
            
            if self._state == CircuitState.OPEN:
                self.stats.rejected_calls += 1
                time_until_half_open = max(
                    0,
                    self.recovery_timeout - (time.monotonic() - (self._last_failure_time or 0))
                )
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is OPEN, try again in {time_until_half_open:.1f}s",
                    time_until_half_open=time_until_half_open
                )
            
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    self.stats.rejected_calls += 1
                    raise CircuitOpenError(
                        f"Circuit '{self.name}' is HALF_OPEN, max test calls reached"
                    )
                self._half_open_calls += 1
        
        # Execute the call
        try:
            self.stats.total_calls += 1
            
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            await self._record_success()
            return result
            
        except Exception as e:
            if not isinstance(e, self.exclude_exceptions):
                await self._record_failure()
            raise
    
    def _check_state_transition(self) -> None:
        """Check if state should transition."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._transition_to(CircuitState.HALF_OPEN)
    
    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self.stats.successful_calls += 1
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
    
    async def _record_failure(self) -> None:
        """Record a failed call."""
        async with self._lock:
            self.stats.failed_calls += 1
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open immediately opens circuit
                self._transition_to(CircuitState.OPEN)
            
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        
        # Reset counters on state change
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0
        
        self.stats.state_transitions.append({
            "from": old_state.value,
            "to": new_state.value,
            "time": time.time(),
        })
        
        logger.info(f"Circuit '{self.name}' transitioned: {old_state.value} -> {new_state.value}")
    
    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_calls": self.stats.total_calls,
            "successful_calls": self.stats.successful_calls,
            "failed_calls": self.stats.failed_calls,
            "rejected_calls": self.stats.rejected_calls,
            "success_rate": f"{self.stats.success_rate:.2%}",
            "recent_transitions": self.stats.state_transitions[-5:],
        }


# =============================================================================
# Timeout Wrapper
# =============================================================================

async def with_timeout(
    coro,
    timeout: float,
    error_message: str = "Operation timed out",
) -> Any:
    """
    Execute a coroutine with timeout.
    
    Args:
        coro: Coroutine to execute
        timeout: Timeout in seconds
        error_message: Message for TimeoutError
    
    Returns:
        Coroutine result
    
    Raises:
        asyncio.TimeoutError with custom message
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(error_message)


# =============================================================================
# Retry Decorator
# =============================================================================

def retry_async(
    max_retries: int = 3,
    delay: float = 1.0,
    multiplier: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Decorator for async functions with retry logic.
    
    Usage:
        @retry_async(max_retries=3, delay=1.0)
        async def unstable_api_call():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        if on_retry:
                            on_retry(e, attempt + 1)
                        
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                            f"after {type(e).__name__}: {e}"
                        )
                        
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * multiplier, max_delay)
                    else:
                        raise
            
            raise last_exception or RuntimeError("Unexpected retry failure")
        
        return wrapper
    return decorator


# =============================================================================
# Global Rate Limiter Registry
# =============================================================================

_rate_limiters: dict[str, RateLimiter] = {}
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_rate_limiter(
    name: str = "default",
    **kwargs,
) -> RateLimiter:
    """Get or create a named rate limiter."""
    if name not in _rate_limiters:
        _rate_limiters[name] = RateLimiter(**kwargs)
    return _rate_limiters[name]


def get_circuit_breaker(
    name: str = "default",
    **kwargs,
) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name=name, **kwargs)
    return _circuit_breakers[name]
