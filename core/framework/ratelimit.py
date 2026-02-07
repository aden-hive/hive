"""Rate limiting for LLM calls and API requests.

Provides token bucket based rate limiting with:
- Per-model rate limits
- Per-provider limits
- Automatic backoff and retry
- Request queuing

Usage:
    from framework.ratelimit import RateLimiter, get_limiter

    limiter = get_limiter()

    # Check and acquire rate limit
    async with limiter.acquire("anthropic", "claude-3-5-sonnet"):
        response = await llm.complete(...)

    # Or use decorator
    @limiter.limit("openai", "gpt-4")
    async def my_function():
        ...
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class BackoffStrategy(StrEnum):
    """Backoff strategies for rate limit handling."""

    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    JITTER = "jitter"  # Exponential with random jitter


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""

    # Requests per minute
    requests_per_minute: int = 60

    # Tokens per minute (for LLM rate limiting)
    tokens_per_minute: int = 100_000

    # Burst capacity (allows bursts above the rate)
    burst_multiplier: float = 1.5

    # Backoff settings
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_backoff: float = 1.0
    max_backoff: float = 60.0
    backoff_multiplier: float = 2.0

    # Queue settings
    max_queue_size: int = 100
    queue_timeout: float = 30.0


@dataclass
class TokenBucket:
    """Token bucket for rate limiting.

    Tokens are added at a fixed rate up to a maximum capacity.
    Each request consumes tokens; if insufficient tokens are
    available, the request must wait.
    """

    capacity: float
    tokens: float = field(default=0.0)
    last_update: float = field(default_factory=time.time)
    refill_rate: float = 1.0  # tokens per second

    def __post_init__(self):
        self.tokens = self.capacity

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_update = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens without waiting."""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def time_until_available(self, tokens: float = 1.0) -> float:
        """Calculate wait time until tokens are available."""
        self._refill()
        if self.tokens >= tokens:
            return 0.0
        deficit = tokens - self.tokens
        return deficit / self.refill_rate


@dataclass
class RateLimitState:
    """State for a single rate limit key."""

    request_bucket: TokenBucket
    token_bucket: TokenBucket | None = None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue())
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    consecutive_429s: int = 0
    last_429_time: float = 0.0

    # Stats
    total_requests: int = 0
    total_waits: int = 0
    total_rejections: int = 0


class RateLimiter:
    """Rate limiter with per-provider/model limits.

    Uses token bucket algorithm for smooth rate limiting
    with burst capacity support.
    """

    # Default limits per provider/model
    DEFAULT_LIMITS: dict[str, dict[str, RateLimitConfig]] = {
        "anthropic": {
            "claude-3-5-sonnet-20241022": RateLimitConfig(
                requests_per_minute=50,
                tokens_per_minute=80_000,
            ),
            "claude-3-5-haiku-20241022": RateLimitConfig(
                requests_per_minute=100,
                tokens_per_minute=100_000,
            ),
            "default": RateLimitConfig(
                requests_per_minute=60,
                tokens_per_minute=100_000,
            ),
        },
        "openai": {
            "gpt-4": RateLimitConfig(
                requests_per_minute=200,
                tokens_per_minute=40_000,
            ),
            "gpt-4-turbo": RateLimitConfig(
                requests_per_minute=500,
                tokens_per_minute=150_000,
            ),
            "gpt-3.5-turbo": RateLimitConfig(
                requests_per_minute=3500,
                tokens_per_minute=90_000,
            ),
            "default": RateLimitConfig(
                requests_per_minute=500,
                tokens_per_minute=100_000,
            ),
        },
        "cerebras": {
            "default": RateLimitConfig(
                requests_per_minute=60,
                tokens_per_minute=100_000,
            ),
        },
    }

    def __init__(self, custom_limits: dict[str, dict[str, RateLimitConfig]] | None = None):
        self._limits = dict(self.DEFAULT_LIMITS)
        if custom_limits:
            for provider, models in custom_limits.items():
                self._limits.setdefault(provider, {}).update(models)

        self._states: dict[str, RateLimitState] = {}
        self._lock = asyncio.Lock()
        self._global_stats = defaultdict(int)

    def _get_config(self, provider: str, model: str | None = None) -> RateLimitConfig:
        """Get rate limit config for provider/model."""
        provider_limits = self._limits.get(provider, {})
        if model and model in provider_limits:
            return provider_limits[model]
        return provider_limits.get("default", RateLimitConfig())

    def _get_key(self, provider: str, model: str | None = None) -> str:
        """Generate state key for provider/model."""
        return f"{provider}:{model or 'default'}"

    async def _get_state(self, provider: str, model: str | None = None) -> RateLimitState:
        """Get or create rate limit state."""
        key = self._get_key(provider, model)

        if key not in self._states:
            async with self._lock:
                if key not in self._states:
                    config = self._get_config(provider, model)

                    # Create request rate bucket
                    request_bucket = TokenBucket(
                        capacity=config.requests_per_minute * config.burst_multiplier,
                        refill_rate=config.requests_per_minute / 60.0,
                    )

                    # Create token rate bucket if configured
                    token_bucket = None
                    if config.tokens_per_minute > 0:
                        token_bucket = TokenBucket(
                            capacity=config.tokens_per_minute * config.burst_multiplier,
                            refill_rate=config.tokens_per_minute / 60.0,
                        )

                    self._states[key] = RateLimitState(
                        request_bucket=request_bucket,
                        token_bucket=token_bucket,
                        queue=asyncio.Queue(maxsize=config.max_queue_size),
                    )

        return self._states[key]

    def _calculate_backoff(self, config: RateLimitConfig, attempts: int) -> float:
        """Calculate backoff time based on strategy."""
        import random

        base = config.initial_backoff

        if config.backoff_strategy == BackoffStrategy.FIXED:
            backoff = base
        elif config.backoff_strategy == BackoffStrategy.LINEAR:
            backoff = base * attempts
        elif config.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            backoff = base * (config.backoff_multiplier ** (attempts - 1))
        elif config.backoff_strategy == BackoffStrategy.JITTER:
            exp_backoff = base * (config.backoff_multiplier ** (attempts - 1))
            backoff = exp_backoff * (0.5 + random.random())  # 50-150% of exp
        else:
            backoff = base

        return min(backoff, config.max_backoff)

    async def acquire(
        self,
        provider: str,
        model: str | None = None,
        tokens: int = 0,
        timeout: float | None = None,
    ) -> "RateLimitContext":
        """Acquire rate limit permission.

        Args:
            provider: The API provider
            model: Optional model name for model-specific limits
            tokens: Estimated tokens for this request
            timeout: Maximum time to wait

        Returns:
            Context manager that releases on exit

        Raises:
            TimeoutError: If timeout exceeded waiting for rate limit
        """
        state = await self._get_state(provider, model)
        config = self._get_config(provider, model)
        timeout = timeout or config.queue_timeout

        start_time = time.time()
        attempts = 0

        while True:
            async with state.lock:
                # Check request rate
                if state.request_bucket.try_acquire(1):
                    # Check token rate if applicable
                    if tokens > 0 and state.token_bucket:
                        if not state.token_bucket.try_acquire(tokens):
                            wait_time = state.token_bucket.time_until_available(tokens)
                            if time.time() - start_time + wait_time > timeout:
                                state.total_rejections += 1
                                raise TimeoutError(
                                    f"Rate limit timeout for {provider}/{model}"
                                )
                            state.total_waits += 1
                            await asyncio.sleep(wait_time)
                            continue

                    state.total_requests += 1
                    self._global_stats["acquired"] += 1
                    return RateLimitContext(self, provider, model)

                # Need to wait for request bucket
                wait_time = state.request_bucket.time_until_available(1)

            # Check timeout
            if time.time() - start_time + wait_time > timeout:
                state.total_rejections += 1
                self._global_stats["rejections"] += 1
                raise TimeoutError(f"Rate limit timeout for {provider}/{model}")

            # Wait with backoff
            attempts += 1
            actual_wait = min(wait_time, self._calculate_backoff(config, attempts))
            state.total_waits += 1
            self._global_stats["waits"] += 1

            logger.debug(
                f"Rate limit wait for {provider}/{model}: {actual_wait:.2f}s "
                f"(attempt {attempts})"
            )
            await asyncio.sleep(actual_wait)

    def record_429(self, provider: str, model: str | None = None) -> None:
        """Record a 429 response for adaptive rate limiting."""
        key = self._get_key(provider, model)
        if key in self._states:
            state = self._states[key]
            state.consecutive_429s += 1
            state.last_429_time = time.time()
            self._global_stats["429s"] += 1

            # Reduce bucket capacity on repeated 429s
            if state.consecutive_429s > 3:
                reduction = 0.8  # Reduce to 80%
                state.request_bucket.capacity *= reduction
                if state.token_bucket:
                    state.token_bucket.capacity *= reduction
                logger.warning(
                    f"Reduced rate limit for {provider}/{model} due to 429s"
                )

    def record_success(self, provider: str, model: str | None = None) -> None:
        """Record a successful request."""
        key = self._get_key(provider, model)
        if key in self._states:
            state = self._states[key]
            state.consecutive_429s = 0  # Reset on success
            self._global_stats["successes"] += 1

    def stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        per_key_stats = {}
        for key, state in self._states.items():
            per_key_stats[key] = {
                "total_requests": state.total_requests,
                "total_waits": state.total_waits,
                "total_rejections": state.total_rejections,
                "consecutive_429s": state.consecutive_429s,
                "request_tokens": state.request_bucket.tokens,
                "request_capacity": state.request_bucket.capacity,
            }

        return {
            "global": dict(self._global_stats),
            "per_key": per_key_stats,
        }


class RateLimitContext:
    """Context manager for rate limit acquisition."""

    def __init__(
        self,
        limiter: RateLimiter,
        provider: str,
        model: str | None,
    ):
        self.limiter = limiter
        self.provider = provider
        self.model = model

    async def __aenter__(self) -> "RateLimitContext":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # Record 429 or success based on exception
        if exc_type is not None:
            # Check if it's a rate limit error
            error_str = str(exc_val).lower()
            if "429" in error_str or "rate" in error_str:
                self.limiter.record_429(self.provider, self.model)
        else:
            self.limiter.record_success(self.provider, self.model)


# Global limiter instance
_global_limiter: RateLimiter | None = None
_limiter_lock = asyncio.Lock()


async def get_limiter(
    custom_limits: dict[str, dict[str, RateLimitConfig]] | None = None,
) -> RateLimiter:
    """Get or create the global rate limiter."""
    global _global_limiter

    if _global_limiter is None:
        async with _limiter_lock:
            if _global_limiter is None:
                _global_limiter = RateLimiter(custom_limits)

    return _global_limiter


def limit(
    provider: str,
    model: str | None = None,
    tokens: int = 0,
):
    """Decorator for rate limiting async functions."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            limiter = await get_limiter()
            async with await limiter.acquire(provider, model, tokens):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "RateLimiter",
    "RateLimitConfig",
    "RateLimitContext",
    "BackoffStrategy",
    "TokenBucket",
    "get_limiter",
    "limit",
]
